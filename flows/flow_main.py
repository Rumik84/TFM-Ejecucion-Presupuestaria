"""
Prefect Flow MAESTRO — Orquesta el pipeline end-to-end.

    ingest_catalog  ──►  download_distributions  ──►  etl_by_ccaa
                                                         │
                                                         ▼
                                                   build_features
                                                         │
                                                         ▼
                                                   train_models

Cada sub-flow se ejecuta como una task y puede dispararse por CCAA o global.
"""
from __future__ import annotations

from prefect import flow

from flows.flow_build_features import build_features_flow
from flows.flow_download_distributions import download_distributions_flow
from flows.flow_etl_by_ccaa import etl_by_ccaa_flow
from flows.flow_ingest_catalog import ingest_catalog_flow
from flows.flow_train_models import train_models_flow
from src.utils import get_logger

logger = get_logger(__name__)


@flow(name="main_pipeline", log_prints=True)
def main_pipeline(ccaa_slugs: list[str] | None = None, min_score: int = 4):
    logger.info("=== Paso 1: Ingesta de catálogo ===")
    ingest_catalog_flow(min_score=min_score)

    logger.info("=== Paso 2: Descarga de distribuciones ===")
    download_distributions_flow(ccaa_slugs=ccaa_slugs)

    logger.info("=== Paso 3: ETL por CCAA ===")
    etl_by_ccaa_flow(ccaa_slugs=ccaa_slugs)

    logger.info("=== Paso 4: Feature engineering ===")
    build_features_flow(ccaa_slugs=ccaa_slugs)

    logger.info("=== Paso 5: Entrenamiento de modelos ===")
    train_models_flow(ccaa_slugs=ccaa_slugs)

    logger.info("Pipeline completado.")


if __name__ == "__main__":
    main_pipeline()
