"""
Prefect Flow 5 — Entrenamiento de modelos por CCAA.

Entrena los modelos seleccionados (linear / rf / xgboost / lightgbm) sobre el
feature store de cada CCAA y persiste los artefactos en data_lake/04_models/.
"""
from __future__ import annotations

from prefect import flow, task

from config import settings
from src.modeling import Trainer
from src.utils import get_logger

logger = get_logger(__name__)


@task
def train_for(ccaa_slug: str, models: list[str]) -> dict:
    trainer = Trainer()
    return trainer.train_for_ccaa(ccaa_slug, model_names=models)


@flow(name="train_models", log_prints=True)
def train_models_flow(
    ccaa_slugs: list[str] | None = None,
    models: list[str] | None = None,
) -> dict[str, dict]:
    slugs = ccaa_slugs or settings.ccaa_codes()
    models = models or ["linear", "random_forest", "xgboost"]
    results = {s: train_for.submit(s, models).result() for s in slugs}
    return results


if __name__ == "__main__":
    train_models_flow()
