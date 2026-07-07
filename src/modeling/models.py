"""
Registry de modelos de regresión.

Todos los modelos exponen la misma API (fit, predict) de scikit-learn para que
el entrenador pueda tratarlos homogéneamente.
"""
from __future__ import annotations

from typing import Any

from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


class ModelRegistry:
    """Registro de modelos disponibles para el entrenamiento."""

    @staticmethod
    def available() -> list[str]:
        return ["linear", "ridge", "random_forest", "gbm", "xgboost", "lightgbm"]


def get_model(name: str, **kwargs: Any):
    """Factory. Devuelve un estimador sklearn-compatible.

    Nota: xgboost y lightgbm se importan bajo demanda para no obligar a instalarlos.
    """
    name = name.lower()
    if name == "linear":
        return Pipeline([("scaler", StandardScaler()), ("est", LinearRegression(**kwargs))])
    if name == "ridge":
        return Pipeline([("scaler", StandardScaler()), ("est", Ridge(alpha=kwargs.pop("alpha", 1.0), **kwargs))])
    if name in ("random_forest", "rf"):
        return RandomForestRegressor(
            n_estimators=kwargs.pop("n_estimators", 300),
            max_depth=kwargs.pop("max_depth", None),
            random_state=42,
            n_jobs=-1,
            **kwargs,
        )
    if name == "gbm":
        return GradientBoostingRegressor(random_state=42, **kwargs)
    if name == "xgboost":
        from xgboost import XGBRegressor

        return XGBRegressor(
            n_estimators=kwargs.pop("n_estimators", 500),
            learning_rate=kwargs.pop("learning_rate", 0.05),
            max_depth=kwargs.pop("max_depth", 6),
            random_state=42,
            tree_method="hist",
            **kwargs,
        )
    if name == "lightgbm":
        from lightgbm import LGBMRegressor

        return LGBMRegressor(
            n_estimators=kwargs.pop("n_estimators", 500),
            learning_rate=kwargs.pop("learning_rate", 0.05),
            num_leaves=kwargs.pop("num_leaves", 63),
            random_state=42,
            **kwargs,
        )

    raise ValueError(f"Modelo desconocido: {name}. Disponibles: {ModelRegistry.available()}")
