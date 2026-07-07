"""
Script de bootstrap: crea la base SQLite y precarga dim_ccaa.

Uso:
    $ python scripts/init_db.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Añadir raíz del proyecto al PYTHONPATH si se ejecuta directamente
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from config import settings  # noqa: E402
from src.storage import SQLiteRepository  # noqa: E402
from src.utils import get_logger  # noqa: E402

logger = get_logger(__name__)


def main() -> None:
    logger.info("Bootstrapping data lake en %s", settings.paths.data_lake_root)
    settings.paths.data_lake_root.mkdir(parents=True, exist_ok=True)

    repo = SQLiteRepository()
    repo.init_schema()

    # Precargar dim_ccaa desde ccaa_catalog.yaml
    rows = [
        {
            "slug": c["slug"],
            "nombre": c["nombre"],
            "uri_nti": c["uri_nti"],
            "cobertura": c.get("cobertura"),
        }
        for c in settings.ccaa
    ]
    df = pd.DataFrame(rows)
    with repo.engine.begin() as conn:
        conn.execute(
            __import__("sqlalchemy").text("DELETE FROM dim_ccaa")
        )
    repo.upsert_dataframe(df, "dim_ccaa")
    logger.info("dim_ccaa cargada con %d filas", len(df))

    # Precargar dim_capitulo_economico (clasificación estándar)
    capitulos = pd.DataFrame(
        [
            (1, "Gastos de personal", "corriente"),
            (2, "Gastos corrientes en bienes y servicios", "corriente"),
            (3, "Gastos financieros", "corriente"),
            (4, "Transferencias corrientes", "corriente"),
            (5, "Fondo de contingencia", "corriente"),
            (6, "Inversiones reales", "capital"),
            (7, "Transferencias de capital", "capital"),
            (8, "Activos financieros", "financiero"),
            (9, "Pasivos financieros", "financiero"),
        ],
        columns=["capitulo_id", "nombre", "tipo"],
    )
    with repo.engine.begin() as conn:
        conn.execute(
            __import__("sqlalchemy").text("DELETE FROM dim_capitulo_economico")
        )
    repo.upsert_dataframe(capitulos, "dim_capitulo_economico")
    logger.info("dim_capitulo_economico cargada con %d capítulos", len(capitulos))

    logger.info("Bootstrap completado. SQLite listo en %s", settings.paths.sqlite_path)


if __name__ == "__main__":
    main()
