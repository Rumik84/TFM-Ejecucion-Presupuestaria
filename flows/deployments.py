"""
Definiciones de deployments de Prefect.

Despliega los flows con schedules adecuados:
  - ingest_catalog_flow       : diario a las 06:00 UTC
  - download_distributions    : diario a las 07:00 UTC (tras el catálogo)
  - etl_by_ccaa_flow          : diario a las 08:00 UTC
  - build_features_flow       : diario a las 09:00 UTC
  - train_models_flow         : semanal (lunes a las 10:00 UTC)
  - main_pipeline             : on-demand (ejecución manual)

Uso:
    $ python flows/deployments.py
    $ prefect deployment apply *-deployment.yaml
"""
from __future__ import annotations

from prefect.client.schemas.schedules import CronSchedule
from prefect.deployments import Deployment

from flows.flow_build_features import build_features_flow
from flows.flow_download_distributions import download_distributions_flow
from flows.flow_etl_by_ccaa import etl_by_ccaa_flow
from flows.flow_ingest_catalog import ingest_catalog_flow
from flows.flow_main import main_pipeline
from flows.flow_train_models import train_models_flow


def build_deployments() -> list[Deployment]:
    return [
        Deployment.build_from_flow(
            flow=ingest_catalog_flow,
            name="ingest-catalog-daily",
            schedule=CronSchedule(cron="0 6 * * *", timezone="UTC"),
            work_queue_name="default",
        ),
        Deployment.build_from_flow(
            flow=download_distributions_flow,
            name="download-distributions-daily",
            schedule=CronSchedule(cron="0 7 * * *", timezone="UTC"),
            work_queue_name="default",
        ),
        Deployment.build_from_flow(
            flow=etl_by_ccaa_flow,
            name="etl-by-ccaa-daily",
            schedule=CronSchedule(cron="0 8 * * *", timezone="UTC"),
            work_queue_name="default",
        ),
        Deployment.build_from_flow(
            flow=build_features_flow,
            name="build-features-daily",
            schedule=CronSchedule(cron="0 9 * * *", timezone="UTC"),
            work_queue_name="default",
        ),
        Deployment.build_from_flow(
            flow=train_models_flow,
            name="train-models-weekly",
            schedule=CronSchedule(cron="0 10 * * 1", timezone="UTC"),  # lunes
            work_queue_name="default",
        ),
        Deployment.build_from_flow(
            flow=main_pipeline,
            name="main-on-demand",
            work_queue_name="default",
        ),
    ]


if __name__ == "__main__":
    for dep in build_deployments():
        dep.apply()
        print(f"Deployment applied: {dep.name}")
