#!/usr/bin/env python
"""
Migra el MODELO COMPLETO (esquema estrella) de SQLite a Azure PostgreSQL.

La tabla de hechos `fact_ejecucion_presupuestaria` ya está cargada (17,26M filas)
por scripts/load_to_azure.py. Este script añade el resto del modelo para que Azure
quede idéntico al SQLite de origen:

  Dimensiones y catálogo:
    dim_ccaa, dim_capitulo_economico, dim_capitulo_funcional, dim_publisher,
    dim_entidad, catalog_dataset, catalog_distribution, fact_prediccion, pipeline_run

  Claves foráneas (mismas relaciones que SQLite). Se validan si no hay filas
  huérfanas; si las hay (porque la dimensión está vacía en el origen), se crean
  como NOT VALID: la restricción queda declarada y visible, y se aplica a filas
  NUEVAS, pero no se valida sobre las ya cargadas. Esto reproduce fielmente el
  comportamiento de SQLite (que declara las FK pero no las fuerza).

Credenciales: se reutiliza la configuración de load_to_azure (PGPASSWORD por entorno).

Uso:
    python scripts/migrate_model_to_azure.py            # crea tablas, carga y FKs
    python scripts/migrate_model_to_azure.py --summary  # solo muestra estado actual
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.load_to_azure import PG, SQLITE_PATH, connect_pg  # noqa: E402

# ---------------------------------------------------------------------------
# 1. DDL de las tablas (solo PK/UNIQUE; las FK se añaden al final para poder
#    cargar datos aunque haya huérfanos respecto a dimensiones vacías).
#    Tipos alineados con la tabla de hechos ya existente (SMALLINT en capitulo_id,
#    TEXT en claves de texto) para que las FK sean compatibles.
# ---------------------------------------------------------------------------
DDL = {
    "dim_ccaa": """
        CREATE TABLE IF NOT EXISTS dim_ccaa (
            slug       TEXT PRIMARY KEY,
            nombre     TEXT NOT NULL,
            uri_nti    TEXT NOT NULL,
            cobertura  TEXT
        );""",
    "dim_capitulo_economico": """
        CREATE TABLE IF NOT EXISTS dim_capitulo_economico (
            capitulo_id  SMALLINT PRIMARY KEY,
            nombre       TEXT NOT NULL,
            tipo         TEXT NOT NULL
        );""",
    "dim_capitulo_funcional": """
        CREATE TABLE IF NOT EXISTS dim_capitulo_funcional (
            grupo_funcional_id  TEXT PRIMARY KEY,
            nombre              TEXT NOT NULL,
            nivel               INTEGER NOT NULL
        );""",
    "dim_publisher": """
        CREATE TABLE IF NOT EXISTS dim_publisher (
            publisher_id  TEXT PRIMARY KEY,
            nombre        TEXT NOT NULL,
            ambito        TEXT,
            ccaa_slug     TEXT
        );""",
    "dim_entidad": """
        CREATE TABLE IF NOT EXISTS dim_entidad (
            entidad_id     TEXT PRIMARY KEY,
            nombre         TEXT NOT NULL,
            tipo           TEXT NOT NULL,
            ccaa_slug      TEXT,
            provincia_ine  TEXT,
            poblacion      INTEGER
        );""",
    "catalog_dataset": """
        CREATE TABLE IF NOT EXISTS catalog_dataset (
            uri               TEXT PRIMARY KEY,
            id                TEXT,
            titulo            TEXT NOT NULL,
            descripcion       TEXT,
            publisher_id      TEXT,
            ccaa_slug         TEXT,
            issued            TEXT,
            modified          TEXT,
            score_relevancia  INTEGER,
            raw_json_path     TEXT,
            query_kind        TEXT,
            query_value       TEXT,
            ingested_at       TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
        );""",
    "catalog_distribution": """
        CREATE TABLE IF NOT EXISTS catalog_distribution (
            distribution_id  INTEGER PRIMARY KEY,
            dataset_uri      TEXT NOT NULL,
            formato          TEXT NOT NULL,
            access_url       TEXT NOT NULL,
            download_url     TEXT,
            byte_size        BIGINT,
            local_path       TEXT,
            downloaded_at    TEXT,
            checksum_md5     TEXT,
            CONSTRAINT uq_distribution UNIQUE (dataset_uri, formato, access_url)
        );""",
    "fact_prediccion": """
        CREATE TABLE IF NOT EXISTS fact_prediccion (
            pred_id           INTEGER PRIMARY KEY,
            ccaa_slug         TEXT NOT NULL,
            entidad_id        TEXT,
            anio              SMALLINT NOT NULL,
            capitulo_id       SMALLINT,
            modelo            TEXT NOT NULL,
            modelo_version    TEXT NOT NULL,
            importe_predicho  DOUBLE PRECISION NOT NULL,
            importe_real      DOUBLE PRECISION,
            mae               DOUBLE PRECISION,
            mape              DOUBLE PRECISION,
            desviacion_rel    DOUBLE PRECISION,
            alerta            TEXT,
            generated_at      TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
        );""",
    "pipeline_run": """
        CREATE TABLE IF NOT EXISTS pipeline_run (
            run_id         INTEGER PRIMARY KEY,
            flow_name      TEXT NOT NULL,
            ccaa_slug      TEXT,
            started_at     TEXT NOT NULL,
            ended_at       TEXT,
            status         TEXT NOT NULL,
            records_in     INTEGER,
            records_out    INTEGER,
            error_message  TEXT
        );""",
}

# Orden de creación/carga (respeta dependencias lógicas)
TABLE_ORDER = [
    "dim_ccaa", "dim_capitulo_economico", "dim_capitulo_funcional",
    "dim_publisher", "dim_entidad", "catalog_dataset",
    "catalog_distribution", "fact_prediccion", "pipeline_run",
]

# ---------------------------------------------------------------------------
# 2. Claves foráneas del modelo (nombre, tabla hija, col hija, tabla padre, col padre)
# ---------------------------------------------------------------------------
FACT = "fact_ejecucion_presupuestaria"
FOREIGN_KEYS = [
    # entre dimensiones / catálogo
    ("fk_publisher_ccaa", "dim_publisher", "ccaa_slug", "dim_ccaa", "slug"),
    ("fk_entidad_ccaa", "dim_entidad", "ccaa_slug", "dim_ccaa", "slug"),
    ("fk_dataset_publisher", "catalog_dataset", "publisher_id", "dim_publisher", "publisher_id"),
    ("fk_dataset_ccaa", "catalog_dataset", "ccaa_slug", "dim_ccaa", "slug"),
    ("fk_distribution_dataset", "catalog_distribution", "dataset_uri", "catalog_dataset", "uri"),
    ("fk_pred_ccaa", "fact_prediccion", "ccaa_slug", "dim_ccaa", "slug"),
    ("fk_pred_entidad", "fact_prediccion", "entidad_id", "dim_entidad", "entidad_id"),
    ("fk_pred_capitulo", "fact_prediccion", "capitulo_id", "dim_capitulo_economico", "capitulo_id"),
    # tabla de hechos principal
    ("fk_fact_ccaa", FACT, "ccaa_slug", "dim_ccaa", "slug"),
    ("fk_fact_entidad", FACT, "entidad_id", "dim_entidad", "entidad_id"),
    ("fk_fact_capitulo", FACT, "capitulo_id", "dim_capitulo_economico", "capitulo_id"),
    ("fk_fact_gfunc", FACT, "grupo_funcional_id", "dim_capitulo_funcional", "grupo_funcional_id"),
    ("fk_fact_dataset", FACT, "dataset_uri", "catalog_dataset", "uri"),
]


def sqlite_columns(scon: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in scon.execute(f"PRAGMA table_info({table})")]


def create_tables(pg: psycopg.Connection) -> None:
    print("[1/3] Creando tablas (IF NOT EXISTS)...")
    for t in TABLE_ORDER:
        with pg.cursor() as cur:
            cur.execute(DDL[t])
        pg.commit()
        print(f"   [ok] {t}")


def load_data(pg: psycopg.Connection, scon: sqlite3.Connection) -> None:
    print("\n[2/3] Cargando datos (solo tablas vacías en destino)...")
    for t in TABLE_ORDER:
        src_n = scon.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        with pg.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            dst_n = cur.fetchone()[0]
        if src_n == 0:
            print(f"   [skip] {t}: origen vacío (0 filas)")
            continue
        if dst_n > 0:
            print(f"   [skip] {t}: destino ya tiene {dst_n:,} filas")
            continue
        cols = sqlite_columns(scon, t)
        col_list = ", ".join(cols)
        scur = scon.execute(f"SELECT {col_list} FROM {t}")
        t0 = time.time()
        n = 0
        with pg.cursor() as cur:
            with cur.copy(f"COPY {t} ({col_list}) FROM STDIN") as copy:
                while True:
                    rows = scur.fetchmany(10000)
                    if not rows:
                        break
                    for r in rows:
                        copy.write_row(r)
                    n += len(rows)
        pg.commit()
        print(f"   [ok] {t}: {n:,} filas ({time.time()-t0:.1f}s)")


def add_foreign_keys(pg: psycopg.Connection) -> None:
    print("\n[3/3] Añadiendo claves foráneas (validadas o NOT VALID según huérfanos)...")
    for name, child, ccol, parent, pcol in FOREIGN_KEYS:
        with pg.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_constraint WHERE conname = %s", (name,))
            if cur.fetchone():
                print(f"   [skip] {name}: ya existe")
                continue
            cur.execute(
                f"SELECT COUNT(*) FROM {child} c "
                f"LEFT JOIN {parent} p ON c.{ccol} = p.{pcol} "
                f"WHERE c.{ccol} IS NOT NULL AND p.{pcol} IS NULL"
            )
            orphans = cur.fetchone()[0]
            not_valid = " NOT VALID" if orphans > 0 else ""
            cur.execute(
                f"ALTER TABLE {child} ADD CONSTRAINT {name} "
                f"FOREIGN KEY ({ccol}) REFERENCES {parent}({pcol}){not_valid}"
            )
        pg.commit()
        estado = f"NOT VALID ({orphans:,} huérfanos)" if orphans else "validada"
        print(f"   [ok] {name}: {child}.{ccol} -> {parent}.{pcol}  [{estado}]")


def summary(pg: psycopg.Connection) -> None:
    print("\n=== RESUMEN DEL MODELO EN AZURE ===")
    with pg.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' ORDER BY table_name"
        )
        tables = [r[0] for r in cur.fetchall()]
        print("Tablas:")
        for t in tables:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            print(f"   {t:<32} {cur.fetchone()[0]:>12,} filas")
        cur.execute(
            "SELECT conname, contype, convalidated FROM pg_constraint c "
            "JOIN pg_class r ON r.oid = c.conrelid "
            "WHERE r.relnamespace = 'public'::regnamespace AND contype IN ('f','p') "
            "ORDER BY contype DESC, conname"
        )
        print("\nRestricciones (p=PK, f=FK; validada=t/f):")
        for n, tp, val in cur.fetchall():
            print(f"   [{tp}] {n:<28} validada={val}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Migra el modelo completo a Azure PostgreSQL")
    ap.add_argument("--summary", action="store_true", help="Solo muestra el estado actual")
    args = ap.parse_args()

    if not SQLITE_PATH.exists():
        print(f"[ERROR] No existe SQLite: {SQLITE_PATH}")
        sys.exit(1)

    print(f"[destino] {PG['user']}@{PG['host']}:{PG['port']}/{PG['dbname']}\n")
    pg = connect_pg()
    print("[conexión] OK")

    if args.summary:
        summary(pg)
        pg.close()
        return

    scon = sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True)
    scon.text_factory = str

    create_tables(pg)
    load_data(pg, scon)
    add_foreign_keys(pg)
    summary(pg)

    scon.close()
    pg.close()
    print("\n[OK] Modelo migrado. Azure ahora replica el esquema estrella de SQLite.")


if __name__ == "__main__":
    main()
