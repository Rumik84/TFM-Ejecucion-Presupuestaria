"""
Entrenamiento de modelos por CCAA.

Entrena un modelo por combinación (CCAA, modelo) sobre el feature store
correspondiente. Serializa el modelo a `data_lake/04_models/{ccaa}/{modelo}.joblib`
y registra métricas en SQLite.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import joblib
import pandas as pd

from config import settings
from src.modeling.evaluate import Evaluator
from src.modeling.models import get_model
from src.modeling.preprocessing import temporal_split
from src.storage import ParquetRepository, SQLiteRepository
from src.utils import features_path_for, get_logger, models_path

logger = get_logger(__name__)

TARGET_COL = "OBR"     # obligaciones reconocidas netas
DEFAULT_FEATURES_NUMERIC = [
    "PRE", "CRE", "ratio_cre_pre",
    "obr_lag_1", "obr_lag_2", "obr_lag_3", "obr_lag_4",
    "obr_rolling4_mean", "obr_rolling4_std",
    "q_sin", "q_cos",
]
DEFAULT_FEATURES_CATEGORICAL = ["capitulo_id", "grupo_funcional_id"]


class Trainer:
    def __init__(self, repo: SQLiteRepository | None = None):
        self.repo = repo or SQLiteRepository()

    # ------------------------------------------------------------------
    def train_for_ccaa(
        self,
        ccaa_slug: str,
        model_names: list[str] | None = None,
        train_until_year: int = 2023,
    ) -> dict[str, dict]:
        """Entrena varios modelos y devuelve un dict {modelo: métricas}."""
        features = self._load_features(ccaa_slug)
        if features.empty or TARGET_COL not in features.columns:
            logger.warning("Sin features para %s (o falta columna %s)", ccaa_slug, TARGET_COL)
            return {}

        train, test = temporal_split(features, train_until_year=train_until_year)
        if train.empty or test.empty:
            logger.warning("Split temporal vacío para %s", ccaa_slug)
            return {}

        num_cols = [c for c in DEFAULT_FEATURES_NUMERIC if c in features.columns]
        cat_cols = [c for c in DEFAULT_FEATURES_CATEGORICAL if c in features.columns]

        X_train = train[num_cols + cat_cols]
        y_train = train[TARGET_COL]
        X_test = test[num_cols + cat_cols]
        y_test = test[TARGET_COL]

        results: dict[str, dict] = {}
        model_names = model_names or ["linear", "random_forest", "xgboost"]

        for name in model_names:
            logger.info("[%s] Entrenando %s", ccaa_slug, name)
            try:
                model = get_model(name)
                # TODO: envolver con preprocesador (ColumnTransformer) + modelo
                model.fit(X_train.fillna(0), y_train)
                preds = model.predict(X_test.fillna(0))
                metrics = Evaluator.compute_metrics(y_test, preds)

                # Serializar
                out_path = models_path() / f"{ccaa_slug}__{name}.joblib"
                joblib.dump(model, out_path)

                results[name] = {**metrics, "path": str(out_path)}
                logger.info("[%s] %s -> MAE=%.2f  MAPE=%.2f%%", ccaa_slug, name, metrics["mae"], metrics["mape"] * 100)
            except Exception as exc:  # noqa: BLE001
                logger.error("Modelo %s falló en %s: %s", name, ccaa_slug, exc)

        self._persist_metrics(ccaa_slug, results)
        return results

    # ------------------------------------------------------------------
    def _load_features(self, ccaa_slug: str) -> pd.DataFrame:
        try:
            repo = ParquetRepository(features_path_for(ccaa_slug))
            return repo.read("features")
        except FileNotFoundError:
            return pd.DataFrame()

    # ------------------------------------------------------------------
    def _persist_metrics(self, ccaa_slug: str, results: dict[str, dict]) -> None:
        rows = []
        for modelo, met in results.items():
            rows.append(
                {
                    "ccaa_slug": ccaa_slug,
                    "modelo": modelo,
                    "modelo_version": "0.1",
                    "mae": met.get("mae"),
                    "mape": met.get("mape"),
                    "rmse": met.get("rmse"),
                    "generated_at": datetime.utcnow().isoformat(),
                }
            )
        if rows:
            df = pd.DataFrame(rows)
            # TODO: crear tabla model_metrics en schema.sql (fuera del MVP)
            logger.debug("Métricas: %s", df.to_dict(orient="records"))
