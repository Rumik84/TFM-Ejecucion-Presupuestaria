"""
Feature Builder.

Convierte la tabla de hechos `fact_ejecucion_presupuestaria` en un dataset
tabular apto para aprendizaje supervisado. El objetivo de predicción
habitual es el `importe_OBR` (obligaciones reconocidas netas) del siguiente
trimestre o del cierre del ejercicio.

Features construidas (no exhaustivas):
  - % ejecutado acumulado a cierre de trimestre previo
  - lags de OBR y CRE por capítulo económico (t-1, t-2, t-3 trimestres)
  - rolling mean/std últimos 4 trimestres
  - estacionalidad (sin/cos del trimestre)
  - dummies de CCAA y capítulo
  - ratio CRE/PRE (reformulaciones presupuestarias)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.storage import ParquetRepository
from src.utils import features_path_for, get_logger

logger = get_logger(__name__)


class FeatureBuilder:
    def __init__(self, target_fase: str = "OBR"):
        self.target_fase = target_fase

    # ------------------------------------------------------------------
    def build(self, facts: pd.DataFrame, ccaa_slug: str) -> pd.DataFrame:
        """Genera el dataset de entrenamiento para una CCAA."""
        if facts.empty:
            return facts

        # 1. Pivot a formato wide por fase
        wide = (
            facts.groupby(
                ["ccaa_slug", "entidad_id", "anio", "trimestre", "capitulo_id", "grupo_funcional_id", "fase"],
                dropna=False,
            )["importe_eur"]
            .sum()
            .unstack("fase")
            .reset_index()
        )

        # 2. Ratios y derivados
        if "PRE" in wide.columns and "OBR" in wide.columns:
            wide["brecha_eur"] = wide["PRE"] - wide["OBR"]
            wide["brecha_pct"] = wide["brecha_eur"] / wide["PRE"].replace(0, np.nan)
        if "PRE" in wide.columns and "CRE" in wide.columns:
            wide["ratio_cre_pre"] = wide["CRE"] / wide["PRE"].replace(0, np.nan)
        if "OBR" in wide.columns and "CRE" in wide.columns:
            wide["ejecutado_pct"] = wide["OBR"] / wide["CRE"].replace(0, np.nan)
        if "OBR" in wide.columns and "PAG" in wide.columns:
            wide["pago_pct"] = wide["PAG"] / wide["OBR"].replace(0, np.nan)

        # 3. Features temporales
        # La serie temporal se identifica por las columnas de granularidad que
        # cada CCAA tenga pobladas: la granularidad es HETEROGÉNEA entre CCAA
        # (Aragón: capítulo + grupo funcional, entidad NULL; Canarias: entidad,
        # capítulo NULL; etc.). Se agrupa con dropna=False para NO descartar las
        # columnas que estén a NULL. El bug previo agrupaba por ["entidad_id",
        # "capitulo_id"] con dropna=True: como entidad_id es 100% nulo, pandas
        # descartaba TODAS las filas y los lags salían vacíos.
        SERIES_KEYS = ["entidad_id", "capitulo_id", "grupo_funcional_id"]
        wide = wide.sort_values(SERIES_KEYS + ["anio", "trimestre"])
        if "OBR" in wide.columns:
            grp = wide.groupby(SERIES_KEYS, dropna=False, group_keys=False)["OBR"]
            for lag in (1, 2, 3, 4):
                wide[f"obr_lag_{lag}"] = grp.shift(lag)
            wide["obr_rolling4_mean"] = grp.transform(
                lambda s: s.rolling(4, min_periods=1).mean()
            )
            wide["obr_rolling4_std"] = grp.transform(
                lambda s: s.rolling(4, min_periods=1).std()
            )
        else:
            for lag in (1, 2, 3, 4):
                wide[f"obr_lag_{lag}"] = np.nan
            wide["obr_rolling4_mean"] = np.nan
            wide["obr_rolling4_std"] = np.nan

        # 4. Estacionalidad del trimestre
        q = wide["trimestre"].fillna(0).astype(int)
        wide["q_sin"] = np.sin(2 * np.pi * q / 4)
        wide["q_cos"] = np.cos(2 * np.pi * q / 4)

        # 5. Persistir feature store
        repo = ParquetRepository(features_path_for(ccaa_slug))
        repo.write(wide, "features", partition_cols=["anio"])

        logger.info("[%s] Feature store: %d filas x %d cols", ccaa_slug, *wide.shape)
        return wide
