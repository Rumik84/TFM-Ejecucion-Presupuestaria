"""
Conexión a Azure Database for PostgreSQL (Flexible Server).

Punto único para construir el `Engine` de SQLAlchemy contra Azure, reutilizado
por el repositorio del dashboard (`PostgresRepository`) y por los scripts de
sincronización (`scripts/sync_azure.py`, `scripts/build_feature_store_azure.py`,
`scripts/generate_predictions.py`).

La contraseña se lee SIEMPRE de la variable de entorno `PGPASSWORD` (no se embebe).
El resto de parámetros tienen valores por defecto y pueden sobreescribirse por
entorno (PGHOST, PGPORT, PGDATABASE, PGUSER, PGSSLMODE).

    PowerShell:  $env:PGPASSWORD = 'tu_password'
    Bash:        export PGPASSWORD='tu_password'
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL


def azure_params() -> dict:
    """Parámetros de conexión (sin la contraseña)."""
    return dict(
        username=os.getenv("PGUSER", "adminuser"),
        host=os.getenv("PGHOST", "postgres-tfm.postgres.database.azure.com"),
        port=int(os.getenv("PGPORT", "5432")),
        database=os.getenv("PGDATABASE", "postgres"),
        sslmode=os.getenv("PGSSLMODE", "require"),
    )


def require_password() -> str:
    pwd = os.getenv("PGPASSWORD")
    if not pwd:
        raise RuntimeError(
            "Falta la variable de entorno PGPASSWORD con la contraseña de Azure.\n"
            "  PowerShell:  $env:PGPASSWORD = 'tu_password'\n"
            "  Bash:        export PGPASSWORD='tu_password'"
        )
    return pwd


def make_azure_engine() -> Engine:
    """Crea un Engine SQLAlchemy (dialecto psycopg v3) contra Azure PostgreSQL."""
    p = azure_params()
    url = URL.create(
        "postgresql+psycopg",
        username=p["username"],
        password=require_password(),
        host=p["host"],
        port=p["port"],
        database=p["database"],
        query={"sslmode": p["sslmode"]},
    )
    # pool_pre_ping evita conexiones muertas por el corte de inactividad de Azure.
    return create_engine(url, pool_pre_ping=True)
