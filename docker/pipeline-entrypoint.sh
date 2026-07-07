#!/bin/bash
# Entrypoint del contenedor pipeline.
# Inicializa la BD SQLite si no existe y luego corre el pipeline.
set -e

DB_PATH="${SQLITE_PATH:-/data/data_lake/catalog.db}"

# Crear directorios del data lake si no existen (primera ejecución o volumen vacío)
mkdir -p \
    "${DATA_LAKE_ROOT:-/data/data_lake}/00_raw" \
    "${DATA_LAKE_ROOT:-/data/data_lake}/01_staging" \
    "${DATA_LAKE_ROOT:-/data/data_lake}/02_curated" \
    "${DATA_LAKE_ROOT:-/data/data_lake}/03_features" \
    "${DATA_LAKE_ROOT:-/data/data_lake}/04_models" \
    "${LOG_DIR:-/data/logs}"

if [ ! -f "$DB_PATH" ]; then
    echo "[entrypoint] Base de datos no encontrada. Ejecutando init_db..."
    python scripts/init_db.py
    echo "[entrypoint] init_db completado."
else
    echo "[entrypoint] Base de datos existente en $DB_PATH. Saltando init_db."
fi

echo "[entrypoint] Iniciando pipeline con args: $*"
exec python scripts/run_pipeline.py "$@"
