"""Carga cacheada compartida por el dashboard (repo + tablas de dominio).

Centraliza el acceso al repositorio (SQLite o Azure según DATA_BACKEND) y cachea
las tablas pequeñas (catálogo, feature store, predicciones) para que todas las
páginas compartan la misma caché.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.storage import get_repository


@st.cache_resource
def repo():
    return get_repository()


@st.cache_data(ttl=3600)
def ccaa_catalog() -> pd.DataFrame:
    return repo().load_ccaa_catalog()


@st.cache_data(ttl=3600)
def features() -> pd.DataFrame:
    return repo().load_feature_store()


@st.cache_data(ttl=3600)
def predictions() -> pd.DataFrame:
    return repo().load_predictions()
