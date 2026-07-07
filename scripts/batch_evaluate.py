"""
Evaluacion batch de todas las CCAA pendientes.

Ejecuta download + ETL para cada CCAA en la lista, recoge resultados
y produce una tabla resumen comparativa.

Uso:
    python scripts/batch_evaluate.py
    python scripts/batch_evaluate.py --ccaa aragon castilla-la-mancha
    python scripts/batch_evaluate.py --only download
    python scripts/batch_evaluate.py --only etl
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import sqlalchemy as sa

from config import settings
from src.etl import Curator
from src.ingestion import DatosGobClient, DistributionDownloader
from src.storage import SQLiteRepository
from src.utils import get_logger

logger = get_logger(__name__)

DEFAULT_CCAA = [
    "aragon",
    "castilla-la-mancha",
    "asturias",
    "madrid",
    "navarra",
    "cantabria",
    "murcia",
    "la-rioja",
    "canarias",
    "cataluna",
    "comunidad-valenciana",
    "castilla-y-leon",
    "illes-balears",
    "andalucia",
    "pais-vasco",
]

SEP = "-" * 70


def download_ccaa(ccaa_slug: str, max_datasets: int, max_distrib: int) -> dict:
    """Descarga distribuciones para una CCAA. Devuelve stats."""
    repo = SQLiteRepository()
    client = DatosGobClient()
    downloader = DistributionDownloader(client=client, repo=repo)

    with repo.connection() as conn:
        rows = conn.execute(
            sa.text(
                """
                SELECT uri, id, publisher_id
                FROM catalog_dataset
                WHERE ccaa_slug = :slug AND score_relevancia >= 4
                ORDER BY score_relevancia DESC
                LIMIT :lim
                """
            ),
            {"slug": ccaa_slug, "lim": max_datasets},
        ).fetchall()

    if not rows:
        return {"files": 0, "formats": {}, "bytes": 0, "errors": 0}

    stats: dict[str, int] = {}
    total_bytes = 0
    n_errors = 0

    for row in rows:
        dataset_uri, dataset_id, publisher_id = row[0], row[1], row[2]
        try:
            records = downloader.download_for_dataset(
                dataset_uri=dataset_uri,
                dataset_id=dataset_id,
                ccaa_slug=ccaa_slug,
                publisher_id=publisher_id or "unknown",
            )
            records = records[:max_distrib]
            for rec in records:
                fmt = rec.get("formato", "UNKNOWN")
                stats[fmt] = stats.get(fmt, 0) + 1
                total_bytes += 0
        except Exception as exc:
            logger.warning("[%s] Error dataset %s: %s", ccaa_slug, dataset_id, exc)
            n_errors += 1

    return {"files": sum(stats.values()), "formats": stats, "bytes": total_bytes, "errors": n_errors}


def etl_ccaa(ccaa_slug: str) -> dict:
    """Ejecuta ETL para una CCAA. Devuelve stats."""
    curator = Curator()
    try:
        df = curator.run_for_ccaa(ccaa_slug)
    except Exception as exc:
        logger.error("[%s] ETL fallo: %s", ccaa_slug, exc)
        return {"rows": 0, "years": [], "fases": [], "error": str(exc)}

    if df is None or df.empty:
        return {"rows": 0, "years": [], "fases": [], "error": "sin datos"}

    years = sorted(df["anio"].dropna().unique().tolist()) if "anio" in df.columns else []
    fases = sorted(df["fase"].dropna().unique().tolist()) if "fase" in df.columns else []
    total_eur = df["importe_eur"].sum() if "importe_eur" in df.columns else 0.0
    return {
        "rows": len(df),
        "years": years,
        "fases": fases,
        "total_eur": total_eur,
        "error": None,
    }


def print_summary(results: list[dict]) -> None:
    print("\n" + "=" * 70)
    print("  RESUMEN BATCH EVALUACION")
    print("=" * 70)
    fmt = "{:<22} {:>8} {:>9} {:>14} {:>12} {}"
    print(fmt.format("CCAA", "ARCHIVOS", "FILAS", "EUR (M)", "ANIOS", "FASES"))
    print(SEP)
    for r in results:
        eur_m = r.get("total_eur", 0) / 1e6
        years = r.get("years", [])
        year_str = f"{years[0]}-{years[-1]}" if len(years) >= 2 else (str(years[0]) if years else "-")
        fases_str = ",".join(r.get("fases", [])) or "-"
        err = r.get("etl_error") or ""
        err_tag = f" [ERR: {err[:25]}]" if err else ""
        print(fmt.format(
            r["ccaa"][:22],
            r.get("files_downloaded", 0),
            f"{r.get('rows', 0):,}",
            f"{eur_m:,.0f}" if eur_m > 0 else "-",
            year_str,
            fases_str + err_tag,
        ))
    print(SEP)
    total_rows = sum(r.get("rows", 0) for r in results)
    total_files = sum(r.get("files_downloaded", 0) for r in results)
    print(fmt.format("TOTAL", total_files, f"{total_rows:,}", "", "", ""))
    print("=" * 70 + "\n")


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Evaluacion batch de CCAA")
    ap.add_argument("--ccaa", nargs="+", default=None,
                    help="CCAAregions a procesar (default: todas)")
    ap.add_argument("--max-datasets", type=int, default=100,
                    help="Max datasets por CCAA (default: 100 = todos)")
    ap.add_argument("--max-distrib", type=int, default=10,
                    help="Distribuciones maximas por dataset (default: 10)")
    ap.add_argument("--only", choices=["all", "download", "etl"], default="all")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    ccaa_list = args.ccaa or DEFAULT_CCAA

    print("\n" + "=" * 70)
    print(f"  BATCH EVALUACION -- {len(ccaa_list)} CCAAregions")
    print(f"  max_datasets={args.max_datasets}  max_distrib={args.max_distrib}  only={args.only}")
    print("=" * 70 + "\n")

    summary: list[dict] = []

    for ccaa in ccaa_list:
        print(f"\n{SEP}")
        print(f"  [{ccaa.upper()}]")
        print(SEP)

        entry: dict = {"ccaa": ccaa}
        t0 = time.time()

        if args.only in ("all", "download"):
            print("  -> Descargando distribuciones...")
            dl_stats = download_ccaa(ccaa, args.max_datasets, args.max_distrib)
            entry["files_downloaded"] = dl_stats["files"]
            entry["download_errors"] = dl_stats["errors"]
            entry["formats"] = dl_stats["formats"]
            print(f"     {dl_stats['files']} archivos  |  {dl_stats['errors']} errores  |  {dl_stats['formats']}")

        if args.only in ("all", "etl"):
            print("  -> Ejecutando ETL...")
            etl_stats = etl_ccaa(ccaa)
            entry["rows"] = etl_stats["rows"]
            entry["years"] = etl_stats["years"]
            entry["fases"] = etl_stats["fases"]
            entry["total_eur"] = etl_stats.get("total_eur", 0)
            entry["etl_error"] = etl_stats.get("error")
            print(f"     {etl_stats['rows']:,} filas  |  anios={etl_stats['years']}  |  fases={etl_stats['fases']}")
            if etl_stats.get("error"):
                print(f"     ERROR: {etl_stats['error']}")

        elapsed = time.time() - t0
        print(f"  [{ccaa}] completado en {elapsed:.1f}s")
        summary.append(entry)

    print_summary(summary)


if __name__ == "__main__":
    main()
