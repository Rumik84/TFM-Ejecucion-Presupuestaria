"""
Prefect Flow 2 — Descarga de distribuciones.

Para cada dataset registrado en `catalog_dataset` descarga sus distribuciones
(CSV/XLSX/JSON/XML/PC-AXIS) a data_lake/00_raw/{ccaa}/distributions.

Se paraleliza por CCAA usando `map`.
"""
from __future__ import annotations

import sqlite3

import pandas as pd
from prefect import flow, task

from src.ingestion import DistributionDownloader
from src.storage import SQLiteRepository
from src.utils import get_logger

logger = get_logger(__name__)


@task
def load_datasets_by_ccaa(ccaa_slug: str) -> pd.DataFrame:
    repo = SQLiteRepository()
    sql = """
        SELECT uri, id, publisher_id, ccaa_slug
        FROM catalog_dataset
        WHERE ccaa_slug = ? AND score_relevancia >= 4
    """
    with sqlite3.connect(str(repo.db_path)) as conn:
        return pd.read_sql(sql, conn, params=(ccaa_slug,))


@task(retries=1, retry_delay_seconds=60)
def download_for(row: dict) -> int:
    downloader = DistributionDownloader()
    records = downloader.download_for_dataset(
        dataset_uri=row["uri"],
        dataset_id=row["id"],
        ccaa_slug=row["ccaa_slug"],
        publisher_id=row.get("publisher_id"),
    )
    return len(records)


@flow(name="download_distributions", log_prints=True)
def download_distributions_flow(ccaa_slugs: list[str] | None = None) -> dict:
    from config import settings

    slugs = ccaa_slugs or settings.ccaa_codes()
    total_per_ccaa: dict[str, int] = {}

    for slug in slugs:
        datasets = load_datasets_by_ccaa.submit(slug).result()
        if datasets.empty:
            logger.info("Sin datasets para %s", slug)
            total_per_ccaa[slug] = 0
            continue

        counts = []
        for rec in datasets.to_dict(orient="records"):
            counts.append(download_for.submit(rec))
        total_per_ccaa[slug] = sum(c.result() for c in counts)

    logger.info("Descarga completa: %s", total_per_ccaa)
    return total_per_ccaa


if __name__ == "__main__":
    download_distributions_flow()
