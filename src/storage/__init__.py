"""Abstracción de persistencia: SQLite (curado) + Parquet (staging/curado/features)."""
from __future__ import annotations

import os

from src.storage.sqlite_repository import SQLiteRepository  # noqa: F401
from src.storage.parquet_repository import ParquetRepository  # noqa: F401


def get_repository():
    """Devuelve el repositorio de lectura según el backend configurado.

    - `DATA_BACKEND=azure`  -> PostgresRepository (base de datos de Azure).
    - cualquier otro valor  -> SQLiteRepository (data lake local, por defecto).

    El dashboard usa esta factoría para ser agnóstico del backend. Ambos
    repositorios exponen los mismos métodos de lectura
    (`load_ccaa_catalog`, `load_ejecucion`, `load_feature_store`, `load_predictions`).
    """
    backend = os.getenv("DATA_BACKEND", "sqlite").strip().lower()
    if backend in ("azure", "postgres", "postgresql", "pg"):
        # Import diferido: evita exigir psycopg/SQLAlchemy-Azure en modo local.
        from src.storage.postgres_repository import PostgresRepository

        return PostgresRepository()
    return SQLiteRepository()
