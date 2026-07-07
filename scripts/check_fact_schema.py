"""
Valida que el modelo de hechos `fact_ejecucion` tiene el mismo esquema
en todas las CCAA curadas (9 columnas canónicas).

Uso:
    python scripts/check_fact_schema.py
    python scripts/check_fact_schema.py --json

Imprime una tabla con CCAA, num_filas, columnas, diffs vs canonical. Sale con
código 0 si todas las CCAA presentes pasan el contrato, 1 si hay discrepancias.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pyarrow.dataset as ds

EXPECTED = [
    "ccaa_slug",
    "entidad_id",
    "trimestre",
    "capitulo_id",
    "grupo_funcional_id",
    "fase",
    "importe_eur",
    "dataset_uri",
    "anio",
]

ROOT = Path(__file__).resolve().parent.parent
CURATED = ROOT / "data_lake" / "02_curated"


def inspect_ccaa(ccaa_dir: Path) -> dict | None:
    fact_dir = ccaa_dir / "fact_ejecucion"
    if not fact_dir.exists() or not any(fact_dir.rglob("*.parquet")):
        return None
    d = ds.dataset(fact_dir, format="parquet", partitioning="hive")
    cols = list(d.schema.names)
    rows = d.count_rows()
    missing = [c for c in EXPECTED if c not in cols]
    extra = [c for c in cols if c not in EXPECTED]
    return {
        "ccaa": ccaa_dir.name,
        "rows": rows,
        "n_cols": len(cols),
        "cols": cols,
        "missing": missing,
        "extra": extra,
        "ok": not missing and not extra,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="Salida en JSON")
    args = ap.parse_args()

    results = []
    for ccaa_dir in sorted(CURATED.iterdir()):
        if not ccaa_dir.is_dir():
            continue
        r = inspect_ccaa(ccaa_dir)
        if r:
            results.append(r)

    if args.json:
        print(json.dumps({"expected": EXPECTED, "results": results}, indent=2))
        return 0 if all(r["ok"] for r in results) else 1

    print()
    print("Esquema canonico fact_ejecucion (9 columnas):")
    for c in EXPECTED:
        print(f"  - {c}")

    print()
    print(f"{'CCAA':<22} {'Filas':>12} {'Cols':>5}  Estado")
    print("-" * 70)
    all_ok = True
    for r in results:
        status = "OK" if r["ok"] else f"DIFF (missing={r['missing']} extra={r['extra']})"
        if not r["ok"]:
            all_ok = False
        print(f"{r['ccaa']:<22} {r['rows']:>12,} {r['n_cols']:>5}  {status}")

    print()
    if all_ok:
        print("[OK] Todas las CCAA comparten el esquema canonico de 9 columnas.")
        return 0
    else:
        print("[FAIL] Hay CCAA con esquemas divergentes.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
