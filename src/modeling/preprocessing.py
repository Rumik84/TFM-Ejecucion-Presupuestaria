"""
Preprocesamiento específico para modelado.

Divide features/target, maneja one-hot de variables categóricas, split temporal
(rolling origin) para evitar data leakage en series presupuestarias.
"""
from __future__ import annotations

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


def build_preprocessor(numeric_cols: list[str], categorical_cols: list[str]) -> ColumnTransformer:
    """Preprocesador estándar: imputación + one-hot/estandarización."""
    num_pipe = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ]
    )
    cat_pipe = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("ohe", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]
    )
    return ColumnTransformer(
        transformers=[
            ("num", num_pipe, numeric_cols),
            ("cat", cat_pipe, categorical_cols),
        ],
        remainder="drop",
    )


def temporal_split(
    df: pd.DataFrame,
    anio_col: str = "anio",
    train_until_year: int = 2023,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split temporal train/test. Por defecto entrena hasta 2023 y testea en 2024-2025."""
    train = df[df[anio_col] <= train_until_year].copy()
    test = df[df[anio_col] > train_until_year].copy()
    return train, test
