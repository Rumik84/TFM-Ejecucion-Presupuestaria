"""
Diagnóstico completo del estado de recolección por CCAA.

Cruza las tres capas del pipeline para cada CCAA del catálogo:
  1. catalog_dataset   → ¿se ha crawleado?
  2. catalog_distribution → ¿se han descargado las distribuciones?
  3. data_lake/02_curated → ¿hay datos transformados?

Uso:
    python scripts/diagnostico_cobertura.py
    python scripts/diagnostico_cobertura.py --out docs/diagnostico.txt
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data_lake" / "catalog.db"
CURATED_ROOT = ROOT / "data_lake" / "02_curated"
CCAA_YAML = ROOT / "config" / "ccaa_catalog.yaml"


def load_ccaa_catalog() -> list[dict]:
    import yaml
    with CCAA_YAML.open(encoding="utf-8") as f:
        return yaml.safe_load(f)["ccaa"]


def curated_filas(slug: str) -> int:
    """Cuenta filas Parquet en la capa curada para una CCAA (sin depender de duckdb)."""
    base = CURATED_ROOT / slug / "fact_ejecucion"
    if not base.exists():
        return 0
    try:
        import pyarrow.parquet as pq
        total = 0
        for pf in base.rglob("*.parquet"):
            total += pq.read_metadata(pf).num_rows
        return total
    except Exception:
        return -1  # no se pudo leer


def curated_anio_range(slug: str) -> tuple[int | None, int | None]:
    """Devuelve (min_anio, max_anio) extrayendo desde las subcarpetas hive anio=YYYY."""
    base = CURATED_ROOT / slug / "fact_ejecucion"
    if not base.exists():
        return None, None
    years = []
    for p in base.iterdir():
        if p.is_dir() and p.name.startswith("anio="):
            try:
                years.append(int(p.name.split("=")[1]))
            except ValueError:
                pass
    if not years:
        return None, None
    return min(years), max(years)


def raw_distributions_count(slug: str) -> int:
    """Cuenta archivos descargados en 00_raw/{slug}/distributions (excluye .gitkeep)."""
    raw = ROOT / "data_lake" / "00_raw" / slug / "distributions"
    if not raw.exists():
        return 0
    return sum(1 for f in raw.rglob("*") if f.is_file() and f.name != ".gitkeep")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, help="Guardar salida en este fichero")
    args = ap.parse_args()

    streams = [sys.stdout]
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        streams.append(open(args.out, "w", encoding="utf-8"))

    def echo(text: str = "") -> None:
        for s in streams:
            print(text, file=s)

    def banner(text: str) -> None:
        echo()
        echo("=" * 72)
        echo(f" {text}")
        echo("=" * 72)

    ccaa_list = load_ccaa_catalog()

    # ── Datos de SQLite ──────────────────────────────────────────────────────
    if not DB.exists():
        echo(f"[ERROR] No existe {DB}. Ejecuta primero: python scripts/init_db.py")
        return 1

    con = sqlite3.connect(DB)

    datasets_por_ccaa = pd.read_sql_query(
        "SELECT ccaa_slug, COUNT(*) AS n_datasets FROM catalog_dataset GROUP BY ccaa_slug",
        con,
    ).set_index("ccaa_slug")["n_datasets"].to_dict()

    dist_por_ccaa = pd.read_sql_query(
        """
        SELECT c.ccaa_slug,
               COUNT(*) AS n_dist,
               SUM(CASE WHEN d.downloaded_at IS NOT NULL THEN 1 ELSE 0 END) AS n_desc
        FROM catalog_distribution d
        JOIN catalog_dataset c ON c.uri = d.dataset_uri
        GROUP BY c.ccaa_slug
        """,
        con,
    ).set_index("ccaa_slug").to_dict(orient="index")

    # ── Construir tabla de diagnóstico ───────────────────────────────────────
    rows = []
    for entry in ccaa_list:
        slug = entry["slug"]
        cob = entry.get("cobertura", "?")
        n_ds = datasets_por_ccaa.get(slug, 0)
        d_info = dist_por_ccaa.get(slug, {})
        n_dist = d_info.get("n_dist", 0)
        n_desc = d_info.get("n_desc", 0)
        n_raw = raw_distributions_count(slug)
        n_curado = curated_filas(slug)
        anio_min, anio_max = curated_anio_range(slug)

        # Estado del pipeline
        if n_curado > 0:
            estado = "CURADO"
        elif n_desc > 0 or n_raw > 0:
            estado = "DESCARGADO"
        elif n_ds > 0:
            estado = "CATALOGADO"
        else:
            estado = "PENDIENTE"

        rows.append({
            "CCAA": entry["nombre"],
            "Cobertura": cob,
            "Estado": estado,
            "Datasets": n_ds,
            "Dist.catálogo": n_dist,
            "Dist.descarg.": n_desc,
            "Archivos raw": n_raw,
            "Filas curadas": n_curado if n_curado > 0 else 0,
            "Años": f"{anio_min}–{anio_max}" if anio_min else "—",
        })

    df = pd.DataFrame(rows)
    order = {"CURADO": 0, "DESCARGADO": 1, "CATALOGADO": 2, "PENDIENTE": 3}
    df = df.sort_values(["Estado", "Cobertura"], key=lambda s: s.map(order) if s.name == "Estado" else s)

    # ── Salida ───────────────────────────────────────────────────────────────
    banner("DIAGNÓSTICO DE COBERTURA POR CCAA")
    echo(df.to_string(index=False))

    banner("RESUMEN")
    for estado, grp in df.groupby("Estado"):
        nombres = ", ".join(grp["CCAA"].tolist())
        echo(f"  {estado:12s} ({len(grp):2d}): {nombres}")

    banner("ACCIONES RECOMENDADAS")

    pendientes = df[df["Estado"] == "PENDIENTE"]["CCAA"].tolist()
    catalogados = df[df["Estado"] == "CATALOGADO"]["CCAA"].tolist()
    descargados = df[df["Estado"] == "DESCARGADO"]["CCAA"].tolist()

    pendientes_slugs = [
        e["slug"] for e in ccaa_list if e["nombre"] in pendientes
    ]
    catalogados_slugs = [
        e["slug"] for e in ccaa_list if e["nombre"] in catalogados
    ]
    descargados_slugs = [
        e["slug"] for e in ccaa_list if e["nombre"] in descargados
    ]

    if pendientes_slugs:
        echo()
        echo("  [PENDIENTES] Sin catalogo ni datos -> ejecutar pipeline completo:")
        echo(f"    python scripts/run_pipeline.py --ccaa {' '.join(pendientes_slugs)}")

    if catalogados_slugs:
        echo()
        echo("  [CATALOGADOS] Datasets en catalogo pero sin descargar -> retomar desde paso 2:")
        echo(f"    python scripts/run_pipeline.py --only download --ccaa {' '.join(catalogados_slugs)}")

    if descargados_slugs:
        echo()
        echo("  [DESCARGADOS] Archivos descargados pero sin ETL -> retomar desde paso 3:")
        echo(f"    python scripts/run_pipeline.py --only etl --ccaa {' '.join(descargados_slugs)}")

    # ── Completitud de las CCAA ya curadas ──────────────────────────────────
    curadas = df[df["Estado"] == "CURADO"].copy()
    if not curadas.empty:
        banner("COMPLETITUD DE LAS CCAA YA CURADAS")
        echo()
        echo("  CCAA con todas las fases (PRE+CRE+OBR+PAG):")

        con2 = sqlite3.connect(DB)
        for _, row in curadas.iterrows():
            slug = next(e["slug"] for e in ccaa_list if e["nombre"] == row["CCAA"])
            fases = pd.read_sql_query(
                "SELECT DISTINCT fase FROM fact_ejecucion_presupuestaria WHERE ccaa_slug = ?",
                con2, params=(slug,),
            )["fase"].tolist()
            fases_str = ", ".join(sorted(fases)) if fases else "—"
            completa = all(f in fases for f in ["PRE", "OBR"])
            flag = "OK" if completa else "!!"
            echo(f"    {flag} {row['CCAA']:35s} fases={fases_str}  filas={row['Filas curadas']:>10,}")

    echo()
    for s in streams[1:]:
        s.close()
    if args.out:
        print(f"\n[OK] Diagnóstico guardado en {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
