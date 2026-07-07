"""
Predicción / inferencia.

Carga el modelo serializado para una CCAA y genera predicciones de cierre de
ejercicio. Persiste los resultados en `fact_prediccion` con las alertas.
"""
from __future__ import annotations

from datetime import datetime

import joblib
import pandas as pd

from src.modeling.evaluate import Evaluator
from src.storage import ParquetRepository, SQLiteRepository
from src.utils import features_path_for, get_logger, models_path

logger = get_logger(__name__)


class Predictor:
    def __init__(self, repo: SQLiteRepository | None = None):
        self.repo = repo or SQLiteRepository()

    # ------------------------------------------------------------------
    def predict_for_ccaa(self, ccaa_slug: str, modelo: str = "xgboost", anio_objetivo: int = 2025) -> pd.DataFrame:
        model_path = models_path() / f"{ccaa_slug}__{modelo}.joblib"
        if not model_path.exists():
            logger.warning("Modelo no encontrado: %s", model_path)
            return pd.DataFrame()

        model = joblib.load(model_path)

        repo = ParquetRepository(features_path_for(ccaa_slug))
        features = repo.read("features")
        sub = features[features["anio"] == anio_objetivo].copy()
        if sub.empty:
            logger.warning("No hay features para %s año %s", ccaa_slug, anio_objetivo)
            return sub

        # TODO: mantener mismas columnas que en train
        X = sub.select_dtypes(include=["number"]).drop(columns=["OBR", "anio"], errors="ignore").fillna(0)
        sub["importe_predicho"] = model.predict(X)
        sub["importe_real"] = sub.get("OBR")
        sub["desviacion_rel"] = (
            (sub["importe_real"] - sub["importe_predicho"]) / sub["importe_predicho"].replace(0, pd.NA)
        )
        sub["alerta"] = Evaluator.desviacion_alertas(sub)
        sub["modelo"] = modelo
        sub["modelo_version"] = "0.1"
        sub["generated_at"] = datetime.utcnow().isoformat()
        sub["ccaa_slug"] = ccaa_slug

        # Persistir en SQLite
        cols = [
            "ccaa_slug", "entidad_id", "anio", "capitulo_id", "modelo", "modelo_version",
            "importe_predicho", "importe_real", "desviacion_rel", "alerta", "generated_at",
        ]
        cols = [c for c in cols if c in sub.columns]
        self.repo.upsert_dataframe(sub[cols], "fact_prediccion")
        return sub
