"""
Valida el feature store `data_lake/03_features/<ccaa>/features/`.

Comprueba:
  1. Que las columnas de features obligatorias existen en cada CCAA.
  2. El numero de combinaciones (entidad_id, capitulo_id, anio).
  3. El rango temporal y las filas totales.

Uso:
    python scripts/check_features.py
    python scripts/check_features.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pyarrow.dataset as ds

# Columnas de features que deben estar presentes en el dataset
REQUIRED_FEATURES = [
    "brecha_eur",
    "brecha_pct",
    "ejecutado_pct",
    "obr_lag_1",
    "obr_lag_2",
    "obr_lag_3",
    "obr_lag_4",
    "q_sin",
    "q_cos",
]

ROOT = Path(__file__).resolve().parent.parent
FEATURES = ROOT / "data_lake" / "03_features"


def inspect_ccaa(ccaa_dir: Path) -> dict | None:
    feat_dir = ccaa_dir / "features"
    if not feat_dir.exists() or not any(feat_dir.rglob("*.parquet")):
        return None

    d = ds.dataset(feat_dir, format="parquet", partitioning="hive")
    cols = list(d.schema.names)
    rows = d.count_rows()

    # Combinaciones unicas (entidad, capitulo, anio) via pyarrow
    tbl = d.to_table(columns=["entidad_id", "capitulo_id", "anio"])
    import pandas as pd
    df = tbl.to_pandas()
    combos = df.drop_duplicates().shape[0]
    anios = sorted(df["anio"].dropna().unique().tolist())

    missing = [c for c in REQUIRED_FEATURES if c not in cols]
    return {
        "ccaa": ccaa_dir.name,
        "rows": rows,
        "combos": combos,
        "anios": f"{anios[0]}-{anios[-1]}" if anios else "n/a",
        "n_cols": len(cols),
        "missing_features": missing,
        "ok": not missing,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="Salida en JSON")
    args = ap.parse_args()

    results = []
    for ccaa_dir in sorted(FEATURES.iterdir()):
        if not ccaa_dir.is_dir():
            continue
        r = inspect_ccaa(ccaa_dir)
        if r:
            results.append(r)

    if args.json:
        print(json.dumps({"required": REQUIRED_FEATURES, "results": results}, indent=2))
        return 0 if all(r["ok"] for r in results) else 1

    print()
    print("Features obligatorias que debe contener el dataset:")
    for c in REQUIRED_FEATURES:
        print(f"  - {c}")

    print()
    print(f"{'CCAA':<22} {'Filas':>10} {'Combos':>10} {'Años':>12} {'Cols':>5}  Estado")
    print("-" * 80)
    total_rows = 0
    total_combos = 0
    all_ok = True
    for r in results:
        status = "OK" if r["ok"] else f"FALTAN: {r['missing_features']}"
        if not r["ok"]:
            all_ok = False
        total_rows += r["rows"]
        total_combos += r["combos"]
        print(
            f"{r['ccaa']:<22} {r['rows']:>10,} {r['combos']:>10,} "
            f"{r['anios']:>12} {r['n_cols']:>5}  {status}"
        )

    print("-" * 80)
    print(f"{'TOTAL':<22} {total_rows:>10,} {total_combos:>10,}")
    print()
    if all_ok:
        print("[OK] Todas las CCAA tienen las features obligatorias.")
        return 0
    else:
        print("[FAIL] Alguna CCAA no tiene todas las features.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
