"""
Normalizador de datos presupuestarios.

Transforma un DataFrame heterogéneo procedente de cualquier parser en el
esquema canónico utilizado por el data lake curado, estructurado alrededor
de la tabla de hechos `fact_ejecucion_presupuestaria` (ver schema.sql).

El esquema canónico tiene las siguientes columnas:

    ccaa_slug, entidad_id, anio, trimestre,
    capitulo_id, grupo_funcional_id, fase, importe_eur, dataset_uri
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

import pandas as pd

from src.utils import get_logger
from src.utils.text import parse_euro_amount

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
#  Diccionarios de mapeo (extender según los datasets que se vayan integrando)
# ---------------------------------------------------------------------------
FASE_MAP = {
    # Presupuesto inicial
    r"presupuesto\s*inicial": "PRE",
    r"credito\s*inicial": "PRE",
    # Crédito definitivo
    r"credito\s*definitivo": "CRE",
    r"presupuesto\s*definitivo": "CRE",
    # Autorizaciones
    r"autorizacion(es)?\s*de\s*gasto": "ARN",
    r"\ba\b": "ARN",
    # Disposición / compromiso
    r"disposicion(es)?": "DIS",
    r"compromiso(s)?": "DIS",
    # Obligaciones reconocidas netas (gasto real devengado)
    r"obligaciones\s*reconocidas(\s*netas)?": "OBR",
    r"\bobl\.?\s*reconocidas": "OBR",
    # Pagos líquidos
    r"pagos?\s*l[ií]quido(s)?": "PAG",
    r"pagos?\s*realizados?": "PAG",
    # Canarias SDMX: PRESUPUESTO_ESTADO values
    r"presupuesto_inicial": "PRE",
    r"presupuesto_definitivo": "CRE",
    r"presupuesto_ejecutado": "OBR",
    # Solo el total de líquidos (PAG). El `$` evita que las variantes
    # `_CORRIENTE` y `_CERRADOS` (que son sus componentes) también mapeen a PAG
    # y tripliquen el importe pagado.
    r"ingresos_gastos_liquidos$": "PAG",
}


COLUMN_ALIASES = {
    # Alias comunes en CCAA / ayuntamientos -> columna canónica
    "aprobado": "importe_pre",
    "inicial": "importe_pre",
    "definitivo": "importe_cre",
    "ejecutado": "importe_obr",
    "obligado": "importe_obr",
    "obligaciones": "importe_obr",
    "reconocido": "importe_obr",
    "pagado": "importe_pag",
    "año": "anio",
    "ano": "anio",
    "ejercicio": "anio",
    "capitulo": "capitulo_id",
    "cap.": "capitulo_id",
    "economica": "capitulo_id",
    "economic": "capitulo_id",
    "grupo funcional": "grupo_funcional_id",
    "funcional": "grupo_funcional_id",
    # CLM / portales con formato "concepto + valor"
    "valor": "importe",
    "concepto": "fase",
    "importe en miles de euros": "importe",
    "importe (miles eur)": "importe",
    "importe miles euros": "importe",
    # Madrid Ayuntamiento (formato wide con nombres abreviados)
    "prev.inicial": "importe_pre",
    "prev.definitiv": "importe_cre",
    "d. recon.netos": "importe_obr",
    "recaudado": "importe_pag",
    "oblig. reconocidas": "importe_obr",
    "credito definitivo": "importe_cre",
    "credito inicial": "importe_pre",
    "obligaciones reconocidas netas": "importe_obr",
    "pagos liquidos": "importe_pag",
    "remanentes de credito": "importe_cre",
    # Canarias — formato SDMX estadístico (TIME_PERIOD / OBS_VALUE)
    "time_period": "anio",
    "obs_value": "importe",
    "presupuesto_estado": "fase",
    "territorio": "entidad_id",
    # Cataluña / Barcelona Ayuntamiento (cabeceras en catalán)
    "capitol": "capitulo_id",
    "prev. inicial": "importe_pre",
    "prev.definitiva": "importe_cre",
    "drets reconeguts": "importe_obr",
    "obligacions reconegudes": "importe_obr",
    "pagaments": "importe_pag",
    "recaptat liquidat": "importe_pag",
    "pagaments reconeguts": "importe_pag",
    "credits inicials": "importe_pre",
    "credits definitius": "importe_cre",
    "obligacions netes": "importe_obr",
    # Bizkaia / Diputaciones Forales del País Vasco
    # Cabeceras bilingües euskera/español, lowercased → "basque/spanish"
    # "ejercicio" y "capitulo" ya están cubiertos por aliases genéricos.
    "credito final": "importe_cre",          # azken kreditua/credito final
    "autorizacion": "importe_arn",           # baimena/autorizacion
    "disposicion": "importe_dis",            # xedapena/disposicion
    "obligacion": "importe_obr",             # betebeharra/obligacion (singular)
    "pago de ejercicio": "importe_pag",      # .../pago de ejercicio corriente|cerrados
    # Illes Balears / Cataluña — columnes en Català
    "exercici": "anio",                      # Catalan exercici = ejercicio
    "any": "anio",                           # Catalan any = año
    "capítol": "capitulo_id",               # Catalan capítol = capítulo (with accent)
    "crèdit definitiu": "importe_cre",       # IB liquidats: crèdit definitiu
    "crèdit ordenat": "importe_obr",         # IB liquidats despeses: ordenat = obligación reconocida (fase O)
    "crèdit pagat": "importe_pag",           # IB liquidats despeses: crèdit pagat = pagos
    "drets reconeguts nets": "importe_obr",  # IB liquidats ingressos
    "recaptació líquida": "importe_pag",     # IB liquidats ingressos
    "recaptació íntegra": "importe_pag",     # IB liquidats ingressos (alternate)
    "autoritzat": "importe_arn",             # BCN gastos: autoritzat
    "disposat": "importe_dis",               # BCN gastos: disposat
    "obligat": "importe_obr",                # BCN gastos: obligat (obligaciones reconocidas)
    "pagament efectuat": "importe_pag",      # BCN gastos: pagament efectuat
    # Generalitat de Catalunya (Socrata ajns-4mi7) — ejecución mensual de gastos
    "pressupost definitiu": "importe_cre",   # crédito definitivo
    "obligacions pagades": "importe_pag",    # pagos (obligaciones pagadas)
    # Galicia — columnas en gallego
    "capítulo": "capitulo_id",              # gallego/español con tilde en u
    "orzamento": "importe_pre",             # gallego: orzamento = presupuesto
}


class BudgetNormalizer:
    """Normaliza un DataFrame crudo al esquema canónico de hechos."""

    def __init__(self, ccaa_slug: str, dataset_uri: str):
        self.ccaa_slug = ccaa_slug
        self.dataset_uri = dataset_uri

    # ------------------------------------------------------------------
    def normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df

        df = df.copy()
        df.columns = [self._clean_col(c) for c in df.columns]
        df = df.rename(columns=self._build_rename_map(df.columns))

        # Canarias SDMX: keep only absolute amount rows (drop % and per-hab)
        if "medidas" in df.columns:
            df = df[df["medidas"].astype(str).str.upper() == "IMPORTE_PRESUPUESTARIO"]
            df = df.drop(columns=["medidas"], errors="ignore")

        # Canarias SDMX: PRESUPUESTO_PARTIDA trae TODA la jerarquía económica a la
        # vez (total `GASTOS`, grupos de operaciones, capítulos `G_1..G_9`,
        # artículos `G_10..`, conceptos `G_100..`, subconceptos `G_100_00`) y ambos
        # lados (GASTOS/INGRESOS). Sumarla entera multiplica el gasto por doble
        # conteo jerárquico (×5-13 según la profundidad). Nos quedamos SOLO con los
        # capítulos de GASTO `G_1..G_9`: suman exactamente el total `GASTOS` y
        # permiten poblar `capitulo_id`.
        if "presupuesto_partida" in df.columns:
            # El fichero *funcional* añade `presupuesto_programa_gasto` y reclasifica
            # los MISMOS capítulos económicos por programa: incluirlo duplicaría todo
            # el gasto frente al fichero económico. Se descarta (el económico ya
            # aporta el importe por capítulo).
            if "presupuesto_programa_gasto" in df.columns or "presupuesto_programa" in df.columns:
                return df.iloc[0:0].reindex(columns=[
                    "ccaa_slug", "entidad_id", "anio", "trimestre",
                    "capitulo_id", "grupo_funcional_id", "fase",
                    "importe_eur", "dataset_uri",
                ])
            part = df["presupuesto_partida"].astype(str).str.strip().str.upper()
            is_chapter = part.str.fullmatch(r"G_[1-9]")
            df = df[is_chapter].copy()
            df["capitulo_id"] = part[is_chapter].str[2]
            df = df.drop(columns=["presupuesto_partida"], errors="ignore")

        # Drop duplicate canonical columns — keep first occurrence
        df = df.loc[:, ~df.columns.duplicated(keep="first")]

        # Año — si no hay columna explícita, intentar extraer del nombre del sheet
        if "anio" not in df.columns and "__sheet__" in df.columns:
            year_from_sheet = df["__sheet__"].astype(str).str.extract(r"((?:19|20)\d{2})")[0]
            df["anio"] = pd.to_numeric(year_from_sheet, errors="coerce")
        if "anio" in df.columns:
            df["anio"] = df["anio"].apply(_parse_year)

        # Capítulo económico (1..9)
        if "capitulo_id" in df.columns:
            df["capitulo_id"] = df["capitulo_id"].apply(_parse_int)

        # Caso especial: parser ya devuelve importe_eur + fase canónico (p.ej. PCAxisParser).
        # En ese caso, importe_eur NO es una "columna de fase wide" → no hacer melt.
        _already_processed = (
            "importe_eur" in df.columns
            and "fase" in df.columns
            and "importe" not in df.columns
        )

        if _already_processed:
            # Garantizar que los códigos de fase son canónicos
            valid_fases = {"PRE", "CRE", "ARN", "DIS", "OBR", "PAG"}
            df["fase"] = df["fase"].apply(
                lambda x: x if x in valid_fases else _normalize_fase(x)
            )
        else:
            # Si llegan en formato wide (importe_pre, importe_cre, importe_obr), hacer melt
            fase_cols = [c for c in df.columns if c.startswith("importe_")]
            if fase_cols:
                df = self._melt_fases(df, fase_cols)
            elif "fase" in df.columns and "importe" in df.columns:
                df["fase"] = df["fase"].apply(_normalize_fase)
                # If no rows got a valid phase code, the mapped column is a
                # description field (e.g. economic code label), not a phase column.
                # Fall through to treat the amount as PRE.
                if df["fase"].isna().all():
                    df["fase"] = "PRE"
                df["importe_eur"] = df["importe"].apply(parse_euro_amount)
            elif "importe" in df.columns:
                # Columna importe sin fase explícita: tratar como presupuesto inicial
                df["fase"] = "PRE"
                df["importe_eur"] = df["importe"].apply(parse_euro_amount)

        # Columnas obligatorias
        df["ccaa_slug"] = self.ccaa_slug
        df["dataset_uri"] = self.dataset_uri
        required = [
            "ccaa_slug", "entidad_id", "anio", "trimestre",
            "capitulo_id", "grupo_funcional_id", "fase",
            "importe_eur", "dataset_uri",
        ]
        for col in required:
            if col not in df.columns:
                df[col] = None

        df = df[required]
        df = df.dropna(subset=["anio", "fase", "importe_eur"])
        df["importe_eur"] = df["importe_eur"].astype(float)
        return df

    # ------------------------------------------------------------------
    def _clean_col(self, c: Any) -> str:
        s = str(c).strip()
        # Remove soft hyphens (U+00AD) that some portals embed in column names
        s = s.replace("­", "")
        # NFKD decomposition strips accents: é→e, í→i, ó→o, etc.
        s = unicodedata.normalize("NFKD", s)
        s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
        s = s.lower()
        s = re.sub(r"\s+", " ", s)
        return s

    def _build_rename_map(self, cols: list[str]) -> dict[str, str]:
        # Sort by alias length descending so longer (more specific) patterns win
        # over shorter ones (e.g. "pago de ejercicio" before "ejercicio").
        sorted_aliases = sorted(COLUMN_ALIASES.items(), key=lambda kv: len(kv[0]), reverse=True)
        # Normalize alias keys the same way _clean_col normalizes column names
        # so that accented aliases match accentless column names and vice versa.
        normalized_aliases = [(self._clean_col(alias), canonical) for alias, canonical in sorted_aliases]
        m: dict[str, str] = {}
        for c in cols:
            for alias_norm, canonical in normalized_aliases:
                if alias_norm in c:
                    m[c] = canonical
                    break
        return m

    def _melt_fases(self, df: pd.DataFrame, fase_cols: list[str]) -> pd.DataFrame:
        # Drop any "fase" column that came from COLUMN_ALIASES to avoid a name
        # collision with the melt var_name="fase" (would create two "fase" cols).
        df = df.drop(columns=["fase"], errors="ignore")
        id_vars = [c for c in df.columns if c not in fase_cols]
        long = df.melt(id_vars=id_vars, value_vars=fase_cols, var_name="fase", value_name="importe")
        long["fase"] = long["fase"].str.replace("importe_", "", regex=False).str.upper()
        long["importe_eur"] = long["importe"].apply(parse_euro_amount)
        return long.drop(columns=["importe"])


# ---------------------------------------------------------------------------
def _normalize_fase(value: Any) -> str | None:
    if pd.isna(value):
        return None
    s = str(value).lower()
    for pattern, code in FASE_MAP.items():
        if re.search(pattern, s):
            return code
    return None


def _parse_year(value: Any) -> int | None:
    if pd.isna(value):
        return None
    try:
        y = int(str(value)[:4])
        if 1980 <= y <= 2100:
            return y
    except (TypeError, ValueError):
        pass
    return None


def _parse_int(value: Any) -> int | None:
    if pd.isna(value):
        return None
    try:
        s = str(value).strip()
        result = int(float(s))
        # Economic codes like 10000 → capitulo 1; keep only 1-9
        if result > 9:
            result = int(s[0])
        return result if 1 <= result <= 9 else None
    except (TypeError, ValueError):
        # Handle "1 GASTOS DE PERSOAL", "2 Obligaciones reconocidas", etc.
        m = re.match(r"^(\d+)", str(value).strip())
        if m:
            result = int(m.group(1))
            if result > 9:
                result = int(str(result)[0])
            return result if 1 <= result <= 9 else None
        return None
