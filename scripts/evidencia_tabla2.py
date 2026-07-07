"""
Reconstruye la Tabla 2 de la memoria (Fuentes de datos por CCAA y cobertura)
a partir del catalog.db actual.

Uso:
    python scripts/evidencia_tabla2.py
    python scripts/evidencia_tabla2.py --out docs/evidencia_tabla2.txt
    python scripts/evidencia_tabla2.py --md docs/evidencia_tabla2.md
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data_lake" / "catalog.db"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, help="Texto plano de salida")
    ap.add_argument("--md", type=Path, help="Tabla en formato Markdown")
    ap.add_argument(
        "--ccaa",
        nargs="*",
        default=["aragon", "asturias", "canarias", "castilla-la-mancha",
                 "madrid", "nacional"],
        help="Slugs de CCAA a incluir (orden alfabetico)",
    )
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    placeholders = ",".join(["?"] * len(args.ccaa))

    # Cobertura desde dim_ccaa
    cov = pd.read_sql_query(
        f"SELECT slug AS ccaa_slug, nombre, cobertura "
        f"FROM dim_ccaa WHERE slug IN ({placeholders})",
        con, params=args.ccaa,
    )

    # Conteo de datasets por CCAA
    n_ds = pd.read_sql_query(
        f"SELECT ccaa_slug, COUNT(*) AS n_datasets "
        f"FROM catalog_dataset WHERE ccaa_slug IN ({placeholders}) "
        f"GROUP BY ccaa_slug",
        con, params=args.ccaa,
    )

    # Top publisher por CCAA (con su recuento)
    top = pd.read_sql_query(
        f"""
        SELECT ccaa_slug, publisher_id, COUNT(*) AS n
        FROM catalog_dataset
        WHERE ccaa_slug IN ({placeholders})
        GROUP BY ccaa_slug, publisher_id
        """, con, params=args.ccaa,
    )
    top_pub = (
        top.sort_values(["ccaa_slug", "n"], ascending=[True, False])
           .groupby("ccaa_slug")
           .head(1)[["ccaa_slug", "publisher_id"]]
           .rename(columns={"publisher_id": "publicador_principal"})
    )

    df = (cov.merge(n_ds, on="ccaa_slug", how="left")
              .merge(top_pub, on="ccaa_slug", how="left")
              .sort_values("ccaa_slug")
              .reset_index(drop=True))
    df["tipo_acceso"] = "API datos.gob.es"

    final = df[["nombre", "cobertura", "publicador_principal",
                "tipo_acceso", "n_datasets"]].rename(columns={
        "nombre": "CCAA",
        "cobertura": "Cobertura",
        "publicador_principal": "Publicador principal",
        "tipo_acceso": "Tipo de acceso",
        "n_datasets": "Nº datasets",
    })

    txt = final.to_string(index=False)
    print(txt)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(txt + "\n", encoding="utf-8")
        print(f"\n[OK] Texto guardado en {args.out}")

    if args.md:
        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text(final.to_markdown(index=False) + "\n", encoding="utf-8")
        print(f"[OK] Markdown guardado en {args.md}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
