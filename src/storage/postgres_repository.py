"""
Repositorio PostgreSQL (Azure) — espejo de lectura de `SQLiteRepository`.

Sirve al dashboard cuando la fuente es la base de datos de Azure (capa de
servicio). Expone los mismos métodos de lectura que el repositorio SQLite, para
que el dashboard sea agnóstico del backend (ver `get_repository()` en
`src/storage/__init__.py`).

Diferencias frente a SQLite:
  - `load_feature_store()` lee la tabla materializada `feature_store_modelado`
    (en SQLite se lee del parquet).
  - `load_ejecucion()` aplica un LIMIT por defecto: la tabla de hechos tiene ~17M
    filas y traerlas por red sería inviable. El dashboard usa el feature store
    (agregado y diminuto) para KPIs y gráficos; los hechos crudos solo se ojean.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.storage.azure import make_azure_engine

FEATURE_STORE_TABLE = "feature_store_modelado"
FACT_TABLE = "fact_ejecucion_presupuestaria"
DEFAULT_FACT_LIMIT = 100_000


class PostgresRepository:
    """Acceso de lectura a la base de datos de Azure para el dashboard."""

    def __init__(self, engine: Engine | None = None):
        self.engine: Engine = engine or make_azure_engine()

    # --------------------------------------------------------------
    #  Lectura robusta. NOTA: no se usa `pd.read_sql` porque pandas 3.0 dejó de
    #  reconocer el Engine/Connection de SQLAlchemy 2.0 como conectable (falla con
    #  "Query must be a string unless using sqlalchemy" / `.cursor()`). Se ejecuta
    #  vía SQLAlchemy y se construye el DataFrame desde el resultado.
    def _read(self, sql: str, params: dict | None = None) -> pd.DataFrame:
        with self.engine.connect() as conn:
            result = conn.execute(text(sql), params or {})
            df = pd.DataFrame(result.fetchall(), columns=list(result.keys()))
        # Coerción numérica: una columna NUMÉRICA enteramente NULL (o con NULLs)
        # llega como object con `None` (no float NaN), lo que rompe `.abs()`/agregados
        # (a diferencia del parquet, que preserva el dtype). Se convierte a numérico
        # cada columna object cuya conversión NO pierde valores no nulos (así el texto
        # como ccaa_slug se mantiene intacto).
        for col in df.columns:
            if df[col].dtype == object:
                conv = pd.to_numeric(df[col], errors="coerce")
                if conv.notna().sum() >= df[col].notna().sum():
                    df[col] = conv
        return df

    # --------------------------------------------------------------
    #  Lectura del dominio (misma firma que SQLiteRepository)
    # --------------------------------------------------------------
    def load_ccaa_catalog(self) -> pd.DataFrame:
        return self._read("SELECT * FROM dim_ccaa")

    def load_ejecucion(
        self,
        ccaa_slug: str | None = None,
        anio: int | None = None,
        limit: int | None = DEFAULT_FACT_LIMIT,
    ) -> pd.DataFrame:
        sql = f"SELECT * FROM {FACT_TABLE} WHERE 1=1"
        params: dict = {}
        if ccaa_slug:
            sql += " AND ccaa_slug = :ccaa"
            params["ccaa"] = ccaa_slug
        if anio:
            sql += " AND anio = :anio"
            params["anio"] = anio
        if limit:
            sql += f" LIMIT {int(limit)}"
        return self._read(sql, params)

    def load_feature_store(self, ccaa_slug: str | None = None) -> pd.DataFrame:
        sql = f"SELECT * FROM {FEATURE_STORE_TABLE}"
        params: dict = {}
        if ccaa_slug:
            sql += " WHERE ccaa_slug = :ccaa"
            params["ccaa"] = ccaa_slug
        return self._read(sql, params)

    def load_predictions(self, ccaa_slug: str | None = None) -> pd.DataFrame:
        sql = "SELECT * FROM fact_prediccion"
        params: dict = {}
        if ccaa_slug:
            sql += " WHERE ccaa_slug = :ccaa"
            params["ccaa"] = ccaa_slug
        return self._read(sql, params)
