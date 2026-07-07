"""
Genera la evidencia cuantitativa sobre la capa curada y el catalogo.

Produce cuatro tablas que respaldan las afirmaciones de la memoria:
  1. Volumen por CCAA (filas, rango temporal, anios cubiertos).
  2. Fases presupuestarias presentes por CCAA (PRE/CRE/OBR/PAG/ARN...).
  3. Nulos en entidad_id y trimestre por CCAA.
  4. Formatos en catalog_distribution (heterogeneidad de las fuentes).

Uso:
    python scripts/evidencia_datos.py
    python scripts/evidencia_datos.py --out docs/evidencia_datos.txt
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CURATED_GLOB = str(ROOT / "data_lake" / "02_curated" / "*" / "fact_ejecucion" / "**" / "*.parquet")
CATALOG_DB = ROOT / "data_lake" / "catalog.db"


def banner(text: str, stream) -> None:
    print("", file=stream)
    print("=" * 72, file=stream)
    print(f" {text}", file=stream)
    print("=" * 72, file=stream)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, help="Fichero donde guardar la salida")
    args = ap.parse_args()

    streams = [sys.stdout]
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        streams.append(open(args.out, "w", encoding="utf-8"))

    def echo(text: str = "") -> None:
        for s in streams:
            print(text, file=s)

    def echo_banner(text: str) -> None:
        for s in streams:
            banner(text, s)

    con = duckdb.connect()
    glob_param = CURATED_GLOB.replace("\\", "/")

    # --- 1. Volumen por CCAA ------------------------------------------------
    echo_banner("1. VOLUMEN POR CCAA")
    df = con.execute(f"""
        SELECT ccaa_slug,
               COUNT(*)              AS filas,
               MIN(anio)             AS anio_min,
               MAX(anio)             AS anio_max,
               COUNT(DISTINCT anio)  AS anios_con_dato
        FROM read_parquet('{glob_param}', hive_partitioning=true)
        GROUP BY ccaa_slug
        ORDER BY filas DESC
    """).df()
    echo(df.to_string(index=False))
    echo()
    echo(f"TOTAL filas curadas: {int(df['filas'].sum()):,}")

    # --- 2. Fases por CCAA --------------------------------------------------
    echo_banner("2. FASES PRESUPUESTARIAS POR CCAA (pivote)")
    df2 = con.execute(f"""
        SELECT ccaa_slug, fase, COUNT(*) AS filas
        FROM read_parquet('{glob_param}', hive_partitioning=true)
        GROUP BY ccaa_slug, fase
    """).df()
    piv = df2.pivot(index="ccaa_slug", columns="fase", values="filas").fillna(0).astype(int)
    echo(piv.to_string())
    echo()
    echo("Leyenda: PRE=Presupuesto inicial, CRE=Credito definitivo,")
    echo("         ARN=Autorizacion, OBR=Obligacion reconocida, PAG=Pago.")

    # --- 3. Nulos en entidad_id y trimestre --------------------------------
    echo_banner("3. NULOS EN entidad_id Y trimestre (por CCAA)")
    df3 = con.execute(f"""
        SELECT ccaa_slug,
               COUNT(*)                                            AS filas,
               ROUND(100.0 * SUM(CASE WHEN entidad_id IS NULL THEN 1 ELSE 0 END)/COUNT(*), 1)
                    AS pct_null_entidad,
               ROUND(100.0 * SUM(CASE WHEN trimestre  IS NULL THEN 1 ELSE 0 END)/COUNT(*), 1)
                    AS pct_null_trimestre
        FROM read_parquet('{glob_param}', hive_partitioning=true)
        GROUP BY ccaa_slug
        ORDER BY ccaa_slug
    """).df()
    echo(df3.to_string(index=False))

    # --- 4. Formatos en catalog_distribution -------------------------------
    echo_banner("4. HETEROGENEIDAD DE FORMATOS (catalog_distribution)")
    if CATALOG_DB.exists():
        sql = sqlite3.connect(CATALOG_DB)
        df4 = pd.read_sql_query(
            """
            SELECT formato,
                   COUNT(*) AS n_distribuciones,
                   SUM(CASE WHEN downloaded_at IS NOT NULL THEN 1 ELSE 0 END) AS descargadas
            FROM catalog_distribution
            GROUP BY formato
            ORDER BY n_distribuciones DESC
            """, sql)
        echo(df4.to_string(index=False))
        echo()
        echo(f"TOTAL distribuciones en catalogo: {int(df4['n_distribuciones'].sum()):,}")
    else:
        echo(f"[AVISO] No existe {CATALOG_DB}")

    # Cerrar ficheros extra
    for s in streams[1:]:
        s.close()
    if args.out:
        print(f"\n[OK] Evidencia guardada en {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
