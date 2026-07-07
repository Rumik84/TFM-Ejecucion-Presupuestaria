-- =====================================================================
--  Schema de la base SQLite `catalog.db`
--  Diseño: snowflake con dimensiones (CCAA, capítulos, publishers) y
--  tablas de hechos (ejecución presupuestaria, predicciones).
-- =====================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- 1. METADATOS DEL DATA LAKE (catálogo de datasets ingestados)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dim_publisher (
    publisher_id   TEXT PRIMARY KEY,       -- DIR3 (p. ej. 'E05250001')
    nombre         TEXT NOT NULL,
    ambito         TEXT,                   -- 'estado' | 'ccaa' | 'provincia' | 'municipio'
    ccaa_slug      TEXT REFERENCES dim_ccaa(slug)
);

CREATE TABLE IF NOT EXISTS dim_ccaa (
    slug           TEXT PRIMARY KEY,       -- 'pais-vasco'
    nombre         TEXT NOT NULL,          -- 'País Vasco'
    uri_nti        TEXT NOT NULL,          -- 'Pais-Vasco'
    cobertura      TEXT                    -- 'muy_alta' | 'alta' | 'media' | 'baja' | 'sin_datos'
);

CREATE TABLE IF NOT EXISTS catalog_dataset (
    uri            TEXT PRIMARY KEY,       -- URI canónico del dataset en datos.gob.es
    id             TEXT,                   -- identificador corto (puede ser NULL en algunos publishers)
    titulo         TEXT NOT NULL,
    descripcion    TEXT,
    publisher_id   TEXT REFERENCES dim_publisher(publisher_id),
    ccaa_slug      TEXT REFERENCES dim_ccaa(slug),
    issued         TEXT,                   -- ISO-8601
    modified       TEXT,                   -- ISO-8601
    score_relevancia INTEGER,              -- heredado del inventario (score ≥ 4 => relevante)
    raw_json_path  TEXT,                   -- ruta al JSON crudo de la API
    query_kind     TEXT,                   -- tipo de query que lo descubrió: keyword|theme|title|publisher
    query_value    TEXT,                   -- valor de la query (p.ej. 'presupuesto')
    ingested_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_catalog_ccaa    ON catalog_dataset(ccaa_slug);
CREATE INDEX IF NOT EXISTS idx_catalog_publ    ON catalog_dataset(publisher_id);
CREATE INDEX IF NOT EXISTS idx_catalog_modif   ON catalog_dataset(modified);

CREATE TABLE IF NOT EXISTS catalog_distribution (
    distribution_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_uri         TEXT NOT NULL REFERENCES catalog_dataset(uri),
    formato             TEXT NOT NULL,      -- CSV | XLSX | JSON | XML | PC-AXIS | PDF
    access_url          TEXT NOT NULL,
    download_url        TEXT,
    byte_size           INTEGER,
    local_path          TEXT,               -- ruta local en data_lake/00_raw/{ccaa}/distributions/
    downloaded_at       TEXT,
    checksum_md5        TEXT,
    UNIQUE(dataset_uri, formato, access_url)
);

CREATE INDEX IF NOT EXISTS idx_dist_dataset ON catalog_distribution(dataset_uri);
CREATE INDEX IF NOT EXISTS idx_dist_formato ON catalog_distribution(formato);

-- ---------------------------------------------------------------------
-- 2. DIMENSIONES PRESUPUESTARIAS
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dim_capitulo_economico (
    capitulo_id   INTEGER PRIMARY KEY,     -- 1..9 (clasificación económica)
    nombre        TEXT NOT NULL,
    tipo          TEXT NOT NULL            -- 'corriente' | 'capital' | 'financiero'
);

CREATE TABLE IF NOT EXISTS dim_capitulo_funcional (
    grupo_funcional_id  TEXT PRIMARY KEY,  -- p. ej. '1', '2', '3.1', '4.6'
    nombre              TEXT NOT NULL,
    nivel               INTEGER NOT NULL   -- 1=área, 2=política, 3=grupo, 4=programa
);

CREATE TABLE IF NOT EXISTS dim_entidad (
    entidad_id    TEXT PRIMARY KEY,        -- p. ej. código INE del municipio
    nombre        TEXT NOT NULL,
    tipo          TEXT NOT NULL,           -- 'municipio' | 'diputacion' | 'ccaa' | 'estado'
    ccaa_slug     TEXT REFERENCES dim_ccaa(slug),
    provincia_ine TEXT,
    poblacion     INTEGER
);

CREATE INDEX IF NOT EXISTS idx_entidad_ccaa ON dim_entidad(ccaa_slug);

-- ---------------------------------------------------------------------
-- 3. HECHOS: EJECUCIÓN PRESUPUESTARIA
-- ---------------------------------------------------------------------
-- fase_presupuestaria: 'PRE' presupuesto inicial,
--                     'CRE' crédito definitivo,
--                     'ARN' autorización,
--                     'DIS' disposición/compromiso,
--                     'OBR' obligación reconocida neta (=gasto real devengado),
--                     'PAG' pago líquido
CREATE TABLE IF NOT EXISTS fact_ejecucion_presupuestaria (
    fact_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ccaa_slug           TEXT NOT NULL REFERENCES dim_ccaa(slug),
    entidad_id          TEXT REFERENCES dim_entidad(entidad_id),
    anio                INTEGER NOT NULL,
    trimestre           INTEGER,            -- NULL si es anual
    capitulo_id         INTEGER REFERENCES dim_capitulo_economico(capitulo_id),
    grupo_funcional_id  TEXT REFERENCES dim_capitulo_funcional(grupo_funcional_id),
    fase                TEXT NOT NULL,      -- PRE | CRE | ARN | DIS | OBR | PAG
    importe_eur         REAL NOT NULL,
    dataset_uri         TEXT REFERENCES catalog_dataset(uri),
    loaded_at           TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(ccaa_slug, entidad_id, anio, trimestre, capitulo_id, grupo_funcional_id, fase, dataset_uri)
);

CREATE INDEX IF NOT EXISTS idx_fact_ccaa_anio ON fact_ejecucion_presupuestaria(ccaa_slug, anio);
CREATE INDEX IF NOT EXISTS idx_fact_entidad   ON fact_ejecucion_presupuestaria(entidad_id, anio);
CREATE INDEX IF NOT EXISTS idx_fact_fase      ON fact_ejecucion_presupuestaria(fase);

-- ---------------------------------------------------------------------
-- 4. PREDICCIONES Y DESVIACIONES
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fact_prediccion (
    pred_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ccaa_slug           TEXT NOT NULL REFERENCES dim_ccaa(slug),
    entidad_id          TEXT REFERENCES dim_entidad(entidad_id),
    anio                INTEGER NOT NULL,
    capitulo_id         INTEGER REFERENCES dim_capitulo_economico(capitulo_id),
    modelo              TEXT NOT NULL,     -- 'linear' | 'xgb' | 'lgbm' | 'rf' | ...
    modelo_version      TEXT NOT NULL,
    importe_predicho    REAL NOT NULL,
    importe_real        REAL,              -- se rellena cuando el dato cierra
    mae                 REAL,
    mape                REAL,
    desviacion_rel      REAL,              -- (real - predicho) / predicho
    alerta              TEXT,              -- 'verde' | 'amarillo' | 'rojo'
    generated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_pred_ccaa_anio ON fact_prediccion(ccaa_slug, anio);

-- ---------------------------------------------------------------------
-- 5. REGISTRO DE EJECUCIÓN DE FLOWS (auditoría)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pipeline_run (
    run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    flow_name     TEXT NOT NULL,
    ccaa_slug     TEXT,
    started_at    TEXT NOT NULL,
    ended_at      TEXT,
    status        TEXT NOT NULL,           -- 'running' | 'success' | 'failed'
    records_in    INTEGER,
    records_out   INTEGER,
    error_message TEXT
);
