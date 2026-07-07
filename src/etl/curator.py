"""
Curator: orquesta el ETL por CCAA.

Para cada CCAA:
  1. Lee los metadatos de `catalog_distribution` en SQLite.
  2. Para cada distribución soportada, llama al parser adecuado.
  3. Aplica BudgetNormalizer y validador pandera.
  4. Persiste el resultado:
      - Parquet en data_lake/02_curated/{ccaa}/fact_ejecucion.parquet
        (particionado por año).
      - Tabla fact_ejecucion_presupuestaria en SQLite.
"""
from __future__ import annotations

import json
import re
import sqlite3
import traceback as _tb  # noqa: F401 – used in _process_one error handler
from pathlib import Path

import pandas as pd

from config import settings
from src.etl.normalizer import BudgetNormalizer
from src.etl.parsers import get_parser
from src.etl.parsers.csv_parser import CSVParser
from src.etl.parsers.xlsx_parser import XLSXParser
from src.etl.parsers.pcaxis_parser import PCAxisParser
from src.etl.validator import validate_fact_ejecucion
from src.storage import ParquetRepository, SQLiteRepository
from src.utils import curated_path_for, get_logger, staging_path_for

logger = get_logger(__name__)


class Curator:
    def __init__(self, repo: SQLiteRepository | None = None):
        self.repo = repo or SQLiteRepository()

    # ------------------------------------------------------------------
    def run_for_ccaa(self, ccaa_slug: str) -> pd.DataFrame:
        """Ejecuta el ETL completo para una CCAA. Devuelve el DataFrame de hechos curados."""
        logger.info("=== Curator para CCAA '%s' ===", ccaa_slug)

        distributions = self._load_distributions(ccaa_slug)
        if distributions.empty:
            logger.warning("Sin distribuciones para CCAA %s", ccaa_slug)
            return pd.DataFrame()

        distributions = self._apply_exclusions(distributions, ccaa_slug)
        distributions = self._select_distributions(distributions)

        year_overrides = self._load_year_overrides(ccaa_slug)
        staging_repo = ParquetRepository(staging_path_for(ccaa_slug))
        curated_repo = ParquetRepository(curated_path_for(ccaa_slug))
        all_facts: list[pd.DataFrame] = []

        for _, row in distributions.iterrows():
            fact_df = self._process_one(row, year_overrides)
            if fact_df is None or fact_df.empty:
                continue

            # Staging: Parquet por distribución (para trazabilidad)
            staging_repo.write(fact_df, f"dist_{row['distribution_id']}")

            # Validación
            try:
                fact_df = validate_fact_ejecucion(fact_df)
            except Exception as exc:  # noqa: BLE001
                logger.error("Validación falló en dist %s: %s", row["distribution_id"], exc)
                continue

            all_facts.append(fact_df)

        if not all_facts:
            return pd.DataFrame()

        consolidated = pd.concat(all_facts, ignore_index=True)
        consolidated = self._drop_duplicate_year_blocks(consolidated)

        # Curated: Parquet particionado + SQLite
        curated_repo.write(consolidated, "fact_ejecucion", partition_cols=["anio"])

        # DELETE existing rows for this CCAA before re-inserting.
        # INSERT OR IGNORE cannot deduplicate when nullable columns are part of
        # the UNIQUE constraint (NULL != NULL in SQL), causing duplicates on re-runs.
        with sqlite3.connect(str(self.repo.db_path)) as raw:
            raw.execute("DELETE FROM fact_ejecucion_presupuestaria WHERE ccaa_slug = ?", (ccaa_slug,))
        self.repo.upsert_dataframe(consolidated, "fact_ejecucion_presupuestaria")
        logger.info("[%s] %d hechos curados", ccaa_slug, len(consolidated))
        return consolidated

    # ------------------------------------------------------------------
    # Selección de distribuciones: evita procesar el MISMO contenido varias veces.
    #   1) Dedup de FORMATO: cada recurso se publica en varios formatos
    #      (CSV/TSV/XLSX/JSON/XML) y todos se descargan → procesar solo uno.
    #   2) Dedup TEMPORAL: fuentes con snapshots periódicos acumulados
    #      (p.ej. Bizkaia: `ejecucion-...-gastos-2023-<mes>`, un fichero por mes,
    #      cada uno año-a-fecha) → quedarse SOLO el último mes de cada serie/año.
    # Sin esto, País Vasco se multiplica por (nº formatos ×5) × (nº meses ×~12).
    # ------------------------------------------------------------------
    _FORMAT_PREF = {"CSV": 0, "TSV": 1, "PC-AXIS": 1, "PX": 1, "XLSX": 2, "XLS": 2,
                    "JSON": 3, "XML": 4, "RDF": 5}
    _MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
              "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
              "noviembre": 11, "diciembre": 12}

    @staticmethod
    def _resource_key(local_path: object) -> str:
        """Nombre lógico del recurso (sin el prefijo hash de distribución ni extensión)."""
        base = Path(str(local_path)).name
        res = base.rsplit("__", 1)[-1]  # lo que va tras el último '__' = nombre del recurso
        for ext in (".csv", ".tsv", ".xlsx", ".xls", ".json", ".xml", ".px", ".rdf"):
            if res.lower().endswith(ext):
                res = res[: -len(ext)]
                break
        return res.lower()

    # ------------------------------------------------------------------
    # Exclusiones por CCAA: datasets estructuralmente inservibles (mis-adscritos
    # y/o snapshots mensuales SIN fecha en el nombre ni en el dato, que no se
    # pueden deduplicar y se cuentan N veces).
    #   madrid: `l01280796-presupuestos-ejecucion-mensual*` = Ayuntamiento de Madrid
    #   (municipio 28079, NO la Comunidad), 480 ficheros de inversiones opacos
    #   (`300624-*-...-curso/histori`) acumulados → ×7. Se conserva el resto
    #   (p.ej. `ejecucion-anual-h`), más limpio.
    _EXCLUDE_DATASET_SUBSTR: dict[str, tuple[str, ...]] = {
        # madrid (= Ayuntamiento de Madrid, l01280796): además del mensual municipal,
        # se excluyen el ANTEPROYECTO (`proyectos-de-presupuesto`, borrador que infla el
        # PRE 2017-2018 ~5.600 M€, análogo a aragón) y los `generales-ejercicios-anteriores`
        # (ppto general de años previos que solapa la ejecución y mete un pico de 5.484 M€
        # en 2011). Queda solo `ejecucion-anual-historico` (serie autoritativa; completa 2019+).
        "madrid": ("l01280796-presupuestos-ejecucion-mensual",
                   "presupuestos-proyectos-de-presupuesto",
                   "presupuestos-generales-ejercicios-anteriores"),
        # galicia: `...-sobre-el-plan-estrategico` = re-desglose del MISMO gasto por
        # plan estratégico (duplica el total). Se queda `gastos-del-presupuesto-YYYY`.
        "galicia": ("plan-estrategico",),
        # aragon: el dataset autoritativo es `ejecucion-presupuestaria-YYYY` (PRE+CRE+
        # OBR+PAG). `presupuesto-del-gobierno` y `proyecto-de-presupuesto` son copias
        # redundantes del PRE inicial del MISMO año -> triplican el PRE. Se excluyen.
        "aragon": ("proyecto-de-presupuesto-del-gobierno", "presupuesto-del-gobierno-de-aragon"),
        # comunidad-valenciana: la fuente autonómica correcta es la GVA (dadesobertes.gva.es,
        # `gva_generalitat_gastos...`). Se excluye la CIUDAD de Valencia y sus organismos
        # (`l01462508`, `l01462444`), que no son la comunidad autónoma.
        "comunidad-valenciana": ("l01462508", "l01462444"),
        # cataluna: la fuente autonómica correcta es la Generalitat (A09002970,
        # `generalitat_catalunya_gastos...`). Se excluye la base municipal de la
        # CIUDAD de Barcelona (`l01080193`), que no es la comunidad autónoma.
        "cataluna": ("l01080193",),
        # pais-vasco: `a16003011-presupuestos-generales`/`-proyecto` (Gobierno Vasco)
        # son ficheros SIN cabecera, multi-nivel y jerárquicos (×8), solo 2015-2021
        # (fuera de ventana). La serie foral limpia y consistente 2016-2025 la aporta
        # `l02000048` (Bizkaia). Se excluye el dataset malformado.
        "pais-vasco": ("a16003011-presupuestos-generales", "a16003011-proyecto-de-presupuesto"),
        # illes-balears: el XLSX `partidas-presupuestos-liquidados-gastos` es la serie
        # COMPLETA (2002-2024, todas las fases PRE/CRE/ARN/DIS/OBR/PAG). Los datasets
        # `presupuesto-inicial-gastos-YYYY` solo aportan el PRE de 2022-2024, que el XLSX
        # ya incluye -> se contarían dos veces (doble conteo del PRE). Se excluyen.
        "illes-balears": ("presupuesto-inicial-gastos",),
    }

    def _apply_exclusions(self, dists: pd.DataFrame, ccaa_slug: str) -> pd.DataFrame:
        if dists.empty or "dataset_uri" not in dists.columns:
            return dists
        uri = dists["dataset_uri"].astype(str)
        low = uri.str.lower()
        mask = pd.Series(False, index=dists.index)

        # (a) General: la tabla es de ejecución de GASTO. Los INGRESOS no deben
        # contarse como hechos de gasto. Se filtra tanto por el nombre del DATASET
        # como por el nombre del RECURSO/fichero (algunos datasets de 'ejecución'
        # traen ficheros de ingresos sueltos, p.ej. aragón `ejecucion_ingresos.csv`).
        # No toca combinados tipo `ingresos_gastos_liquidos` (contienen 'gasto').
        def _ingresos_only(series):
            s = series.astype(str).str.lower()
            return s.str.contains("ingreso", na=False) & ~s.str.contains("gasto", na=False)

        ingresos_only = _ingresos_only(uri)
        if "local_path" in dists.columns:
            ingresos_only = ingresos_only | _ingresos_only(dists["local_path"].map(self._resource_key))
        mask |= ingresos_only

        # (b) Específico por CCAA.
        pats = self._EXCLUDE_DATASET_SUBSTR.get(ccaa_slug, ())
        for p in pats:
            mask |= uri.str.contains(p, regex=False, na=False)

        if mask.any():
            logger.info("[dist] Exclusión %s: descarta %d distribuciones "
                        "(ingresos_only=%d, específicas=%d)", ccaa_slug, int(mask.sum()),
                        int(ingresos_only.sum()), int((mask & ~ingresos_only).sum()))
        return dists[~mask]

    def _select_distributions(self, dists: pd.DataFrame) -> pd.DataFrame:
        if dists.empty or "local_path" not in dists.columns:
            return dists
        d = dists.copy()
        d["__resource__"] = d["local_path"].map(self._resource_key)

        # 1) Dedup de formato: un único formato por (dataset_uri, recurso lógico).
        d["__fmtrank__"] = d["formato"].astype(str).str.upper().map(self._FORMAT_PREF).fillna(9)
        n0 = len(d)
        d = (d.sort_values("__fmtrank__")
               .drop_duplicates(subset=["dataset_uri", "__resource__"], keep="first"))
        if len(d) < n0:
            logger.info("[dist] Dedup de formato: %d -> %d distribuciones", n0, len(d))

        # 1b) Dedup de recursos con nombre-UUID: algunas fuentes (opendata.aragon.es)
        # publican CADA recurso DOS veces: con nombre descriptivo (`ejecucion_gastos`)
        # y con nombre-UUID (`6026409b-...`), contenido idéntico -> se cuenta ×2. Si en
        # un dataset coexisten recursos con nombre y recursos con nombre-UUID, se
        # descartan los UUID (se conserva la copia con nombre). CONDICIONAL: si el
        # dataset SOLO tiene recursos UUID, no se toca (no hay copia alternativa).
        _UUID_RE = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        d["__isuuid__"] = d["__resource__"].str.match(_UUID_RE, na=False)
        has_named = d.groupby("dataset_uri")["__isuuid__"].transform(lambda s: (~s).any())
        drop_uuid = d["__isuuid__"] & has_named
        if drop_uuid.any():
            logger.info("[dist] Dedup nombre-UUID: descarta %d recursos duplicados", int(drop_uuid.sum()))
            d = d[~drop_uuid]

        # 2) Dedup temporal: snapshots mensuales acumulados -> último mes por (serie, año).
        #    Cubre dos codificaciones de mes:
        #      a) mes-palabra al final  `...-YYYY-diciembre`     (Bizkaia/País Vasco)
        #      b) mes numérico junto al año `ejecucion_YYYY_MM_...`
        #         o `eliminaciones_..._MM_YYYY`                  (Ayto. Madrid, 300618)
        #    En (b) la serie se forma sustituyendo el par año+mes por un marcador, de
        #    modo que enero..diciembre de la MISMA serie/año colapsen; se conserva el
        #    mes máximo (los importes de ejecución son acumulados año-a-fecha).
        _MNUM = r"(0?[1-9]|1[0-2])"
        _YM = re.compile(r"(?:^|[_-])(20\d{2})[_-]" + _MNUM + r"(?=[_-]|$)")
        _MY = re.compile(r"(?:^|[_-])" + _MNUM + r"[_-](20\d{2})(?=[_-]|$)")

        def _period(res: str):
            m = re.match(r"^(.*)-(\d{4})-([a-záéíóúñ]+)$", res)
            if m:
                mes = self._MESES.get(m.group(3))
                if mes:
                    return (m.group(1), int(m.group(2)), mes)
            m = _YM.search(res)
            if m:
                serie = res[: m.start()] + "|ym|" + res[m.end() :]
                return (serie, int(m.group(1)), int(m.group(2)))
            m = _MY.search(res)
            if m:
                serie = res[: m.start()] + "|my|" + res[m.end() :]
                return (serie, int(m.group(2)), int(m.group(1)))
            return (None, None, None)

        per = d["__resource__"].map(_period)
        d["__serie__"] = per.map(lambda t: t[0])
        d["__anio__"] = per.map(lambda t: t[1])
        d["__mes__"] = per.map(lambda t: t[2])
        periodic = d[d["__serie__"].notna()]
        if not periodic.empty:
            keep = periodic.loc[periodic.groupby(["__serie__", "__anio__"])["__mes__"].idxmax()]
            n_before = len(periodic)
            d = pd.concat([d[d["__serie__"].isna()], keep], ignore_index=True)
            logger.info("[dist] Dedup temporal (último mes/año): %d -> %d snapshots periódicos",
                        n_before, len(keep))

        return d.drop(columns=["__resource__", "__fmtrank__", "__isuuid__",
                               "__serie__", "__anio__", "__mes__"],
                      errors="ignore")

    # ------------------------------------------------------------------
    @staticmethod
    def _drop_duplicate_year_blocks(df: pd.DataFrame) -> pd.DataFrame:
        """Elimina bloques (año × dataset) que son RÉPLICA EXACTA de otro ya visto.

        Algunas fuentes publican ficheros con rangos de años solapados (p.ej. Illes
        Balears: `despeses-2022-2023` y `despeses-2023-2024` contienen ambos el 2023
        con datos idénticos), de modo que el año compartido se contaría 2-4 veces.

        Es un dedup SEGURO a nivel de bloque: solo descarta el aporte de un dataset a
        un año cuando el conjunto completo de sus filas de hecho es idéntico al de
        otro dataset ya conservado para ese mismo año. NO deduplica filas sueltas
        (dentro de un fichero puede haber partidas distintas con el mismo importe, que
        colapsarían por error, ya que el grano de hecho no guarda la partida). Si dos
        datasets aportan datos DISTINTOS al mismo año (p.ej. gastos vs ingresos, o
        entidades distintas), ambos se conservan.
        """
        if df.empty or "dataset_uri" not in df.columns or "anio" not in df.columns:
            return df
        key = ["entidad_id", "capitulo_id", "grupo_funcional_id", "fase", "importe_eur"]
        key = [c for c in key if c in df.columns]
        keep_idx: list = []
        seen: dict = {}  # anio -> set de firmas de bloque ya conservadas
        dropped = 0

        def _row_str(r):
            # A str para poder ordenar/hashear con tipos mixtos (capitulo_id str/float/None).
            return tuple("" if (v is None or (isinstance(v, float) and pd.isna(v))) else str(v) for v in r)

        for (anio, _uri), block in df.groupby(["anio", "dataset_uri"], dropna=False, sort=False):
            rows = sorted(_row_str(r) for r in block[key].values.tolist())
            sig = hash(tuple(rows))
            sigs = seen.setdefault(anio, set())
            if sig in sigs:
                dropped += len(block)
                continue
            sigs.add(sig)
            keep_idx.extend(block.index.tolist())
        if dropped:
            logger.info("[dedup] %d filas de bloques (año×dataset) duplicados eliminadas", dropped)
            return df.loc[keep_idx].reset_index(drop=True)
        return df

    # ------------------------------------------------------------------
    def _load_year_overrides(self, ccaa_slug: str) -> dict[str, int]:
        """Carga overrides de año para distribuciones sin columna temporal.

        El fichero JSON tiene formato {dist_id: year} y se genera por fuentes
        externas (e.g. consulta API CKAN de Barcelona) para datasets donde el año
        no está en el CSV pero sí en el nombre del recurso.
        """
        override_file = (
            settings.paths.data_lake_root / "00_raw" / ccaa_slug / "dist_year_overrides.json"
        )
        if not override_file.exists():
            return {}
        try:
            with open(override_file) as fh:
                raw = json.load(fh)
            return {str(k): int(v) for k, v in raw.items() if v is not None}
        except Exception as exc:
            logger.warning("No se pudo cargar year_overrides para %s: %s", ccaa_slug, exc)
            return {}

    # ------------------------------------------------------------------
    def _load_distributions(self, ccaa_slug: str) -> pd.DataFrame:
        sql = """
            SELECT d.*, c.ccaa_slug
            FROM catalog_distribution d
            JOIN catalog_dataset c ON c.uri = d.dataset_uri
            WHERE c.ccaa_slug = :ccaa AND d.local_path IS NOT NULL
        """
        with sqlite3.connect(str(self.repo.db_path)) as conn:
            return pd.read_sql(sql.replace(":ccaa", "?"), conn, params=(ccaa_slug,))

    # ------------------------------------------------------------------
    def _process_one(self, row: pd.Series, year_overrides: dict | None = None) -> pd.DataFrame | None:
        local_path = settings.paths.data_lake_root / Path(row["local_path"])
        if not local_path.exists():
            logger.warning("Archivo no encontrado: %s", local_path)
            return None

        fmt = row["formato"]
        try:
            parser = get_parser(fmt)
            raw_df = parser.parse(local_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Parser falló para %s (%s): %s", local_path.name, fmt, exc)
            # Fallback: try parser inferred from file extension when catalog format is wrong
            ext_parser = _extension_parser(local_path)
            if ext_parser is not None and type(ext_parser) != type(parser):
                try:
                    logger.info(
                        "Fallback por extensión %s para %s",
                        local_path.suffix,
                        local_path.name,
                    )
                    raw_df = ext_parser.parse(local_path)
                except Exception as exc2:
                    logger.warning("Fallback por extensión falló para %s: %s", local_path.name, exc2)
                    return None
            else:
                return None

        if raw_df.empty:
            return None

        # Inject year when dataset has no temporal column but override is known
        if year_overrides:
            dist_id = str(row["distribution_id"])
            override_year = year_overrides.get(dist_id)
            if override_year and "anio" not in raw_df.columns:
                cols_lower = [str(c).strip().lower() for c in raw_df.columns]
                has_time = any(c in {"año", "ano", "año", "exercici", "any", "ejercicio"} for c in cols_lower)
                if not has_time:
                    raw_df = raw_df.copy()
                    raw_df["anio"] = override_year

        normalizer = BudgetNormalizer(
            ccaa_slug=row["ccaa_slug"],
            dataset_uri=row["dataset_uri"],
        )
        try:
            return normalizer.normalize(raw_df)
        except Exception:
            logger.error("Normalize FALLO para %s:\n%s", local_path.name, _tb.format_exc())
            return None


def _extension_parser(path: Path):
    """Infiere el parser apropiado por extensión de archivo."""
    _ext_map = {
        ".csv": CSVParser,
        ".tsv": CSVParser,
        ".xlsx": XLSXParser,
        ".xls": XLSXParser,
        ".px": PCAxisParser,
    }
    cls = _ext_map.get(path.suffix.lower())
    return cls() if cls else None
