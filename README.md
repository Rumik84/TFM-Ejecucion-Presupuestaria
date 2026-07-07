# Análisis Predictivo y Visualización Dinámica de la Ejecución Presupuestaria de las Entidades Locales en España (2018-2025)

Trabajo Fin de Máster — Máster Universitario en Análisis y Visualización de Datos Masivos (UNIR).

Autores: Eliesel Gómez Sánchez, Carlos A. Herrera Díaz
Director: Abel Alejandro Coronado Iruegas

---

## 1. Descripción

Sistema end-to-end que construye un **data lake local** a partir de los datasets públicos publicados en [datos.gob.es](https://datos.gob.es/es/apidata), normaliza la información presupuestaria de las entidades locales y autonómicas españolas, entrena modelos de aprendizaje supervisado para predecir la ejecución presupuestaria y expone los resultados en un **dashboard interactivo** desarrollado con Streamlit.

Objetivo: detectar tempranamente la brecha entre el presupuesto aprobado y el gasto real devengado (obligaciones reconocidas netas) en las entidades locales de España durante el periodo 2018-2025, separando el análisis por Comunidad Autónoma.

## 2. Arquitectura

```
API datos.gob.es ──► INGESTA ──► 00_raw ──► ETL ──► 01_staging ──► CURADO ──► 02_curated (Parquet + SQLite)
                                                                         │
                                                                         ├──► 03_features ──► MODELING ──► 04_models
                                                                         │
                                                                         └──► DASHBOARD (Streamlit)
```

- **Lenguaje:** Python 3.11+
- **Orquestación:** Prefect 2.x (flows programables y observables)
- **Almacenamiento:**
  - `00_raw`: JSON crudo de la API + archivos originales (CSV/XLSX/XML/PC-AXIS) **separados por CCAA**
  - `01_staging`: Parquet normalizado por CCAA
  - `02_curated`: Parquet curado + base **SQLite** (`catalog.db`) con hechos y dimensiones
  - `03_features`: Feature store en Parquet
  - `04_models`: Modelos serializados (joblib) y métricas
- **Modelado:** scikit-learn, XGBoost, LightGBM
- **Visualización:** Streamlit + Plotly

## 3. Separación por Comunidad Autónoma

El data lake está físicamente particionado por CCAA (más un nodo `nacional` para agregados MINHAP). Las 17 Comunidades + Ceuta y Melilla están declaradas en `config/ccaa_catalog.yaml` con su URI NTI oficial, de modo que cada flow de Prefect procesa las CCAA de forma independiente y paralelizable.

## 4. Cómo empezar

```bash
# 1. Clonar y entrar al proyecto
cd Ejecucion_presupuestaria

# 2. Crear entorno virtual e instalar dependencias

# Ruta de referencia del intérprete dentro del proyecto (ajústala a tu ubicación real):
# PYEXE="C:/Users/usuario/Documents/Master/Projects/Ejecucion_presupuestaria/.venv/Scripts/python.exe"
#
# Si mueves o renombras la carpeta del proyecto debes recrear el .venv:
#   - Windows:  scripts\reset_venv.ps1
#   - macOS/Linux:  rm -rf .venv && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Inicializar el data lake (SQLite + carpetas)
python scripts/init_db.py

# 4. Ejecutar el pipeline completo (ingesta + ETL + modelado)
python scripts/run_pipeline.py --ccaa all

# 5. Lanzar dashboard
streamlit run src/dashboard/app.py
```

## 5. Estructura del repositorio

```
Ejecucion_presupuestaria/
├── config/                      # Configuración declarativa (YAML + .py)
├── data_lake/                   # Almacenamiento del data lake (gitignored)
│   ├── 00_raw/{ccaa}/           # Respuestas API + distribuciones originales
│   ├── 01_staging/{ccaa}/       # Parquet normalizado
│   ├── 02_curated/{ccaa}/       # Parquet curado + SQLite unificada
│   ├── 03_features/{ccaa}/      # Feature store
│   └── 04_models/               # Modelos entrenados
├── src/
│   ├── ingestion/               # Cliente API y crawler del catálogo
│   ├── etl/                     # Parsers, normalizador, validador, curador
│   ├── features/                # Ingeniería de características
│   ├── modeling/                # Entrenamiento y evaluación
│   ├── dashboard/               # Streamlit app + páginas
│   ├── storage/                 # Capa de persistencia SQLite + Parquet
│   └── utils/                   # Logging, paths, helpers
├── flows/                       # Flows de Prefect
├── notebooks/                   # EDA y experimentos
├── tests/                       # Unit tests
└── scripts/                     # Entry-points (init_db, run_pipeline)
```

## 6. Datasets de entrada (inventario base)

Consultar los archivos `Inventario_datasets_datos_gob_es.xlsx` y `Resumen_datasets_datos_gob_es.md`, que documentan los 522 datasets relevantes identificados en la API del portal.

## 7. Resúmen del proyecto:

Resumen del Proyecto — Ejecución Presupuestaria
________________________________________
1. Origen de los datos (API)
Fuente principal: datos.gob.es — el catálogo nacional de datos abiertos del Gobierno de España.
•	Endpoint base: https://datos.gob.es/apidata/catalog/
•	Se consulta por palabras clave (presupuesto, ejecucion, liquidacion, obligaciones-reconocidas), por tema (hacienda) y por título
•	La API devuelve metadatos de datasets + URLs de descarga de distribuciones (CSV, XLSX, PC-AXIS, JSON, XML)
•	Limitación importante: datasets de portales autonómicos propios (Euskadi → opendata.euskadi.eus, Navarra, etc.) aparecen indexados en datos.gob.es pero sus distribuciones NO son accesibles vía la API nacional → hay que descargarlos directamente del portal regional
________________________________________
2. CCAA con datos similares disponibles
Del catálogo ya ingestado (889 datasets con score ≥ 4):
CCAA	Datasets	Calidad estimada
Nacional (MINHAP + Universidades)	209	✅ Confirmada (83k filas, 2015–2023)
Andalucía	112	✅ Alta (CSVs estructurados, descargables)
País Vasco	96	⚠️ Federated (opendata.euskadi.eus, acceso directo necesario)
Aragón	74	Por validar
Castilla-La Mancha	67	Por validar
Asturias	58	Por validar
Madrid	57	Por validar
Navarra	56	Por validar
Cantabria	35	Por validar
Murcia	31	Por validar
Las CCAA con portales propios (Euskadi, Navarra, Cataluña) requieren conectores adicionales. El resto son accesibles vía datos.gob.es directamente.
________________________________________
3. Datos para analizar la brecha presupuesto ↔ gasto real
El esquema captura exactamente las fases del ciclo presupuestario:
PRE  → Presupuesto inicial aprobado
CRE  → Crédito definitivo (tras modificaciones)
ARN  → Autorización de gasto
DIS  → Disposición / compromiso
OBR  → Obligaciones reconocidas netas  ← gasto real devengado
PAG  → Pagos líquidos realizados
La brecha se calcula como:
Brecha absoluta  = OBR − PRE  (o OBR − CRE para brecha sobre crédito definitivo)
Tasa ejecución   = OBR / CRE × 100
Desviación rel.  = (OBR − PRE) / PRE × 100
Dimensiones de análisis disponibles:
•	anio + trimestre → evolución temporal e infraanual
•	capitulo_id (1–9) → clasificación económica (personal, bienes, transferencias, inversión…)
•	grupo_funcional_id → clasificación funcional (sanidad, educación, seguridad…)
•	ccaa_slug + entidad_id → comparativa territorial entre CCAA y entidades
•	dataset_uri → trazabilidad hasta la fuente original
Con los datos actuales (83,521 filas, 2015–2023, 9 capítulos) ya se puede calcular la brecha por capítulo económico y año para el nivel nacional/Andalucía.
________________________________________
4. Viabilidad para ML y Dashboard
Para modelos de Machine Learning: ✅ SÍ
Los datos son explotables para:
•	Predicción de ejecución (OBR dado PRE/CRE): regresión con XGBoost/LightGBM/RF usando año, capítulo, CCAA, histórico
•	Detección de anomalías: brechas atípicas respecto al histórico (alerta roja/amarilla/verde)
•	Series temporales: predicción de cierre anual con datos trimestrales parciales (2015–2023 da 8 años de histórico, suficiente para modelos básicos)
•	Features disponibles: año, trimestre, capítulo, CCAA, importe PRE/CRE/OBR, tasa histórica por entidad
Para Dashboard Streamlit: ✅ SÍ
La arquitectura ya incluye:
•	Parquet curado en 02_curated/ → lectura rápida por año/CCAA
•	SQLite con fact_ejecucion_presupuestaria → consultas SQL directas
•	Dimensiones listas: capítulos económicos, CCAA, entidades
•	El dashboard Streamlit está esqueletizado y puede conectar directamente al SQLiteRepository
Limitación actual: solo fase PRE en los datos de Andalucía (el dataset no indica la fase explícitamente). Para calcular la brecha real se necesitan datasets que incluyan columna de fase o datos OBR separados — esto existe en los datasets de "liquidación" y "obligaciones reconocidas" que el crawler ya identifica con score alto.

All CCAAregions in catalog:
  nacional: 209 datasets
  andalucia: 112 datasets
  pais-vasco: 96 datasets
  aragon: 74 datasets
  castilla-la-mancha: 67 datasets
  asturias: 58 datasets
  madrid: 57 datasets
  navarra: 56 datasets
  cantabria: 35 datasets
  murcia: 31 datasets
  la-rioja: 25 datasets
  canarias: 20 datasets
  cataluna: 20 datasets
  comunidad-valenciana: 13 datasets
  castilla-y-leon: 10 datasets
  illes-balears: 6 datasets


Both download batches running in background. Feature store results so far:
CCAA	Facts	Feature rows	Cols	brecha_eur non-null
aragon	4.15M	8,157	23	5,952
madrid	299K	94	23	78
castilla-la-mancha	375K	41	21	22
asturias	891K	12	23	7
All 4 CCAAregions have feature Parquet files written to data_lake/03_features/. The 23 features include brecha_eur, brecha_pct, ejecutado_pct, pago_pct, 4 OBR lags, rolling mean/std, and seasonal sin/cos.
Aragón dominates with 8K rows — the others collapse to few rows because entidad_id/grupo_funcional_id are mostly null, making pivot keys merge. Two download batches are now running in parallel for the remaining 11 CCAAregions. Once complete, we'll run ETL + feature build on them too.


## 8. Estado del proyecto

**Versión actual: v0.1 — Estructura y esqueletos de código.**

Los módulos contienen docstrings y TODOs detallados para guiar la implementación en las iteraciones siguientes. Ver `docs/ROADMAP.md` (pendiente) para el plan de sprints.
