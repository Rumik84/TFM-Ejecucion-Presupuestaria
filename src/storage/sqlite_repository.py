"""
Repositorio SQLite del data lake curado.

Responsabilidades:
  - Crear/migrar el esquema (schema.sql).
  - Persistir catálogo de datasets ingestados.
  - Persistir hechos curados (fact_ejecucion_presupuestaria, fact_prediccion).
  - Consultas de lectura utilizadas por el dashboard.

Notas:
  - Se usa `sqlalchemy` con el dialecto sqlite para compatibilidad.
  - Las operaciones de inserción masiva usan `pd.DataFrame.to_sql(..., method='multi')`.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from config import settings
from src.utils import get_logger

logger = get_logger(__name__)


class SQLiteRepository:
    """Acceso único a la base SQLite del data lake curado."""

    def __init__(self, db_path: Path | None = None):
        self.db_path: Path = db_path or settings.paths.sqlite_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(
            f"sqlite:///{self.db_path}",
            echo=False,
            future=True,
        )

    # --------------------------------------------------------------
    #  Schema / bootstrapping
    # --------------------------------------------------------------
    def init_schema(self, schema_path: Path | None = None) -> None:
        """Ejecuta schema.sql. Idempotente (usa CREATE IF NOT EXISTS)."""
        schema_path = schema_path or Path(__file__).parent / "schema.sql"
        ddl = schema_path.read_text(encoding="utf-8")

        with self.engine.begin() as conn:
            # sqlite3 admite múltiples sentencias por executescript:
            conn.connection.executescript(ddl)
        logger.info("Esquema SQLite inicializado en %s", self.db_path)

    # --------------------------------------------------------------
    #  Sesiones
    # --------------------------------------------------------------
    @contextmanager
    def connection(self) -> Iterator:
        """Context manager para obtener una conexión raw con transacción."""
        with self.engine.begin() as conn:
            yield conn

    # --------------------------------------------------------------
    #  Escritura masiva genérica
    # --------------------------------------------------------------
    def upsert_dataframe(
        self,
        df: pd.DataFrame,
        table: str,
        if_exists: str = "append",
        index: bool = False,
    ) -> int:
        """Inserta un DataFrame en la tabla dada con INSERT OR IGNORE para idempotencia."""
        if df.empty:
            return 0
        # Convert pandas nullable dtypes (pd.NA) to Python None for sqlite3
        df = df.astype(object).where(df.notna(), None)
        cols = list(df.columns)
        placeholders = ", ".join("?" * len(cols))
        col_names = ", ".join(f'"{c}"' for c in cols)
        sql = f'INSERT OR IGNORE INTO "{table}" ({col_names}) VALUES ({placeholders})'
        rows = [tuple(row) for row in df.itertuples(index=False, name=None)]
        with sqlite3.connect(str(self.db_path)) as raw_conn:
            # Ensure table exists for first-time inserts (fall back to to_sql)
            existing = raw_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not existing:
                df.to_sql(table, raw_conn, if_exists="replace", index=index, method="multi")
                inserted = len(df)
            else:
                cursor = raw_conn.executemany(sql, rows)
                inserted = cursor.rowcount
        logger.info("%d filas escritas en %s", inserted, table)
        return inserted

    # --------------------------------------------------------------
    #  Helpers del dominio (lectura)
    # --------------------------------------------------------------
    def load_ccaa_catalog(self) -> pd.DataFrame:
        """Devuelve dim_ccaa como DataFrame."""
        with sqlite3.connect(str(self.db_path)) as conn:
            return pd.read_sql("SELECT * FROM dim_ccaa", conn)

    def load_ejecucion(self, ccaa_slug: str | None = None, anio: int | None = None) -> pd.DataFrame:
        """Devuelve hechos de ejecución filtrados."""
        sql = "SELECT * FROM fact_ejecucion_presupuestaria WHERE 1=1"
        params: list = []
        if ccaa_slug:
            sql += " AND ccaa_slug = ?"
            params.append(ccaa_slug)
        if anio:
            sql += " AND anio = ?"
            params.append(anio)
        with sqlite3.connect(str(self.db_path)) as conn:
            return pd.read_sql(sql, conn, params=params)

    def load_predictions(self, ccaa_slug: str | None = None) -> pd.DataFrame:
        """Devuelve predicciones y alertas."""
        sql = "SELECT * FROM fact_prediccion"
        params: list = []
        if ccaa_slug:
            sql += " WHERE ccaa_slug = ?"
            params.append(ccaa_slug)
        with sqlite3.connect(str(self.db_path)) as conn:
            return pd.read_sql(sql, conn, params=params)

    def load_feature_store(self, ccaa_slug: str | None = None) -> pd.DataFrame:
        """Devuelve el feature store de modelado (leído del parquet, fuente de verdad).

        Espejo de `PostgresRepository.load_feature_store`, que lo lee de la tabla
        `feature_store_modelado` en Azure. Aquí se lee del parquet local.
        """
        # Import diferido para no acoplar la carga del módulo a features/config.
        from src.storage.feature_store import read_feature_store_parquet

        return read_feature_store_parquet(ccaa_slug=ccaa_slug)
