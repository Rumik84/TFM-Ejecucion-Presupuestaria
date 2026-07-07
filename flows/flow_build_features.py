"""
Prefect Flow 4 — Construcción del feature store por CCAA.

Lee `fact_ejecucion_presupuestaria` filtrado por CCAA desde SQLite, construye
las features (lags, rolling, estacionalidad, ratios) y las guarda como Parquet.
"""
from __future__ import annotations

from prefect import flow, task

from config import settings
from src.features import FeatureBuilder
from src.storage import SQLiteRepository
from src.utils import get_logger

logger = get_logger(__name__)


@task
def build_for(ccaa_slug: str) -> int:
    repo = SQLiteRepository()
    facts = repo.load_ejecucion(ccaa_slug=ccaa_slug)
    if facts.empty:
        return 0
    fb = FeatureBuilder()
    df = fb.build(facts, ccaa_slug=ccaa_slug)
    return len(df)


@flow(name="build_features", log_prints=True)
def build_features_flow(ccaa_slugs: list[str] | None = None) -> dict[str, int]:
    slugs = ccaa_slugs or settings.ccaa_codes()
    results = {s: build_for.submit(s).result() for s in slugs}
    logger.info("Feature store: %s", results)
    return results


if __name__ == "__main__":
    build_features_flow()
