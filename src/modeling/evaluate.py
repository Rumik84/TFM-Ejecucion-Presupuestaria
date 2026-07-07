"""
Métricas de evaluación.

MAE (objetivo principal del TFM), RMSE, MAPE y R².
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


class Evaluator:
    @staticmethod
    def compute_metrics(y_true, y_pred) -> dict[str, float]:
        y_true = np.asarray(y_true, dtype=float)
        y_pred = np.asarray(y_pred, dtype=float)

        mae = mean_absolute_error(y_true, y_pred)
        rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
        r2 = r2_score(y_true, y_pred) if len(y_true) >= 2 else float("nan")

        # MAPE robusto (evita división por 0)
        denom = np.where(np.abs(y_true) < 1e-6, np.nan, np.abs(y_true))
        mape = float(np.nanmean(np.abs(y_true - y_pred) / denom))

        return {"mae": float(mae), "rmse": rmse, "mape": mape, "r2": float(r2)}

    @staticmethod
    def desviacion_alertas(df: pd.DataFrame, umbral_amarillo: float = 0.05, umbral_rojo: float = 0.15) -> pd.Series:
        """Clasifica desviaciones relativas en alertas semáforo."""
        abs_desv = df["desviacion_rel"].abs()
        return pd.cut(
            abs_desv,
            bins=[-0.01, umbral_amarillo, umbral_rojo, float("inf")],
            labels=["verde", "amarillo", "rojo"],
        )
