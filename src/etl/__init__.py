"""
Capa ETL: RAW -> STAGING -> CURATED.

Submódulos:
  - parsers/  : parseo por formato (CSV, XLSX, JSON, XML, PC-AXIS).
  - normalizer: normalización de importes, fechas, códigos de capítulo.
  - validator : validación de esquema (pandera).
  - curator   : carga a Parquet curado y SQLite.
"""
from src.etl.normalizer import BudgetNormalizer  # noqa: F401
from src.etl.validator import validate_fact_ejecucion  # noqa: F401
from src.etl.curator import Curator  # noqa: F401
