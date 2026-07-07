"""
Prefect Flow 1 — Ingesta del catálogo de datasets desde datos.gob.es.

Ejecuta `CatalogCrawler.crawl()` con las queries del TFM y persiste
catálogo en SQLite. Idempotente gracias al drop_duplicates(subset='uri').

Uso:
    $ python -m flows.flow_ingest_catalog
    $ prefect deployment build flows/flow_ingest_catalog.py:ingest_catalog_flow --name daily
"""
from __future__ import annotations

from prefect import flow, task

from src.ingestion import CatalogCrawler
from src.utils import get_logger

logger = get_logger(__name__)


@task(retries=2, retry_delay_seconds=30)
def crawl_task(min_score: int = 4):
    crawler = CatalogCrawler()
    return crawler.crawl(min_score=min_score)


@flow(name="ingest_catalog", log_prints=True)
def ingest_catalog_flow(min_score: int = 4):
    """Flow de ingesta del catálogo: descubre datasets y los registra en SQLite."""
    df = crawl_task.submit(min_score).result()
    logger.info("Catálogo ingresado: %d datasets relevantes", len(df))
    return len(df)


if __name__ == "__main__":
    ingest_catalog_flow()
