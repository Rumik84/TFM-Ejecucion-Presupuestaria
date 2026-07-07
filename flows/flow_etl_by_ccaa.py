"""
Prefect Flow 3 — ETL por CCAA (RAW → STAGING → CURATED).

Recorre todas las CCAA (o un subconjunto) y ejecuta `Curator.run_for_ccaa`.
Cada CCAA se procesa como task independiente, de modo que un fallo en una no
bloquea al resto.
"""
from __future__ import annotations

from prefect import flow, task

from config import settings
from src.etl import Curator
from src.utils import get_logger

logger = get_logger(__name__)


@task(retries=1, retry_delay_seconds=30)
def curate_ccaa(ccaa_slug: str) -> int:
    curator = Curator()
    df = curator.run_for_ccaa(ccaa_slug)
    return len(df)


@flow(name="etl_by_ccaa", log_prints=True)
def etl_by_ccaa_flow(ccaa_slugs: list[str] | None = None) -> dict[str, int]:
    slugs = ccaa_slugs or settings.ccaa_codes()
    futures = {s: curate_ccaa.submit(s) for s in slugs}
    results = {s: f.result() for s, f in futures.items()}
    logger.info("ETL completado: %s", results)
    return results


if __name__ == "__main__":
    etl_by_ccaa_flow()
