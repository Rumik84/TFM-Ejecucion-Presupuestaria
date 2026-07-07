# Data Lake — separado por CCAA

Convención de capas (medallion):

- `00_raw/{ccaa}/`       → Respuestas JSON de la API + archivos originales descargados.
- `01_staging/{ccaa}/`   → Parquet normalizado (una copia por distribución).
- `02_curated/{ccaa}/`   → Parquet curado particionado por año (fact_ejecucion).
- `03_features/{ccaa}/`  → Feature store para ML.
- `04_models/`           → Modelos serializados (*.joblib).

**La base de datos SQLite unificada** está en `catalog.db` (catálogo + hechos + predicciones).

CCAA disponibles (20 nodos):
andalucia, aragon, asturias, illes-balears, canarias, cantabria, castilla-la-mancha,
castilla-y-leon, cataluna, comunidad-valenciana, extremadura, galicia, madrid, murcia,
navarra, pais-vasco, la-rioja, ceuta, melilla, nacional.
