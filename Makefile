# ============================================================================
#  Makefile — Ejecución Presupuestaria TFM
# ============================================================================

.PHONY: help install init ingest etl features train dashboard pipeline test lint clean

help:
	@echo "Targets disponibles:"
	@echo "  install    - Instala dependencias del proyecto"
	@echo "  init       - Inicializa el data lake (SQLite + carpetas)"
	@echo "  ingest     - Ejecuta la ingesta del catálogo datos.gob.es"
	@echo "  etl        - Ejecuta el ETL (raw -> staging -> curated)"
	@echo "  features   - Genera el feature store"
	@echo "  train      - Entrena los modelos predictivos"
	@echo "  dashboard  - Lanza el dashboard Streamlit"
	@echo "  pipeline   - Ejecuta el pipeline end-to-end"
	@echo "  test       - Ejecuta los tests"
	@echo "  lint       - Ejecuta ruff + black + mypy"
	@echo "  clean      - Limpia caches y logs"

install:
	python -m pip install -U pip
	pip install -r requirements.txt

init:
	python scripts/init_db.py

ingest:
	python -m flows.flow_ingest_catalog

etl:
	python -m flows.flow_etl_by_ccaa

features:
	python -m flows.flow_build_features

train:
	python -m flows.flow_train_models

dashboard:
	streamlit run src/dashboard/app.py

pipeline:
	python scripts/run_pipeline.py --ccaa all

test:
	pytest

lint:
	ruff check src flows tests scripts
	black --check src flows tests scripts
	mypy src flows

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
