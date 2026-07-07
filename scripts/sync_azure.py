#!/usr/bin/env python
"""
Orquestador de sincronización LOCAL -> Azure PostgreSQL (full refresh).

Fuente de verdad = SQLite (`data_lake/catalog.db`, hechos crudos + dims +
predicciones) y parquet (`data_lake/03_features`, feature store). Este script deja
Azure como una réplica servible por el dashboard, en un solo comando. Cuando se
añaden datos nuevos al data lake local, basta con re-ejecutarlo.

Pasos (full refresh):
  1. hechos       fact_ejecucion_presupuestaria   (SQLite -> Azure, TRUNCATE+COPY)
  2. dims         dim_ccaa (+ dims del modelo)     (SQLite -> Azure, UPSERT)
  3. features     feature_store_modelado           (parquet -> Azure, DROP+CREATE)
  4. predicciones fact_prediccion                  (entrena -> SQLite -> Azure, TRUNCATE+COPY)

Los pasos 1 y 3 delegan en los scripts probados (`load_to_azure.py`,
`build_feature_store_azure.py`); 2 y 4 se hacen aquí (tablas pequeñas).

Credenciales: PGPASSWORD por variable de entorno (ver load_to_azure.py).

Uso:
    python scripts/sync_azure.py                     # todo (full refresh)
    python scripts/sync_azure.py --only features     # solo un paso
    python scripts/sync_azure.py --only predicciones --skip-train  # sube predicciones ya generadas
    python scripts/sync_azure.py --skip-hechos       # todo menos recargar los 17M hechos
"""
from __future__ import annotations

import argparse
import subprocess
import sqlite3
import sys
import time
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.load_to_azure import SQLITE_PATH, connect_pg  # noqa: E402

PY = sys.executable
STEPS = ["hechos", "dims", "features", "predicciones"]


def run_script(args: list[str], label: str) -> None:
    """Ejecuta otro script del proyecto como subproceso, heredando el entorno."""
    print(f"\n{'='*70}\n[{label}] $ {' '.join([Path(args[0]).name] + args[1:])}\n{'='*70}")
    res = subprocess.run([PY, str(ROOT / "scripts" / args[0]), *args[1:]], cwd=str(ROOT))
    if res.returncode != 0:
        print(f"[ERROR] El paso '{label}' terminó con código {res.returncode}.")
        sys.exit(res.returncode)


# --------------------------------------------------------------------------- #
# Paso 2: dims (UPSERT — no se puede TRUNCATE por las FK que las referencian)
# --------------------------------------------------------------------------- #
DIM_TABLES = {
    # tabla: (columnas, clave de conflicto)
    "dim_ccaa": (["slug", "nombre", "uri_nti", "cobertura"], "slug"),
    "dim_capitulo_economico": (["capitulo_id", "nombre", "tipo"], "capitulo_id"),
}


def _sqlite_cols(scon: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in scon.execute(f"PRAGMA table_info({table})")]


def sync_dims(pg: psycopg.Connection, scon: sqlite3.Connection) -> None:
    print("\n[dims] UPSERT de dimensiones (SQLite -> Azure)...")
    for table, (cols, key) in DIM_TABLES.items():
        # Solo columnas que existan realmente en el origen SQLite.
        src_cols = _sqlite_cols(scon, table)
        if not src_cols:
            print(f"   [skip] {table}: no existe en SQLite")
            continue
        use = [c for c in cols if c in src_cols]
        rows = scon.execute(f"SELECT {', '.join(use)} FROM {table}").fetchall()
        if not rows:
            print(f"   [skip] {table}: 0 filas en origen")
            continue
        set_clause = ", ".join(f"{c}=EXCLUDED.{c}" for c in use if c != key)
        placeholders = ", ".join(["%s"] * len(use))
        sql = (
            f"INSERT INTO {table} ({', '.join(use)}) VALUES ({placeholders}) "
            f"ON CONFLICT ({key}) DO UPDATE SET {set_clause}"
        )
        with pg.cursor() as cur:
            cur.executemany(sql, rows)
        pg.commit()
        print(f"   [ok] {table}: {len(rows):,} filas upserted")


# --------------------------------------------------------------------------- #
# Pre-paso: dims referenciales id-only (dim_entidad, dim_capitulo_funcional)
# --------------------------------------------------------------------------- #
# Estas dims están VACÍAS en el origen (no hay metadatos de entidad/grupo
# funcional), pero sus FKs desde el fact (fk_fact_entidad, fk_fact_gfunc) SÍ se
# validan en cada INSERT del COPY. Sin poblarlas, un TRUNCATE+COPY del fact falla
# (p.ej. entidad_id=35003 ausente). Se insertan los ids DISTINTOS presentes en los
# hechos con placeholders en las columnas NOT NULL, de forma idempotente. Así el
# full refresh es reproducible sin desactivar la integridad referencial.
REF_DIMS = {
    # tabla: (col_id_en_fact, col_id_en_dim, columnas_extra_not_null {col: valor})
    "dim_entidad": ("entidad_id", "entidad_id",
                    {"nombre": "(sin catalogar)", "tipo": "desconocido"}),
    "dim_capitulo_funcional": ("grupo_funcional_id", "grupo_funcional_id",
                               {"nombre": "(sin catalogar)", "nivel": 0}),
}


_CATALOG_COLS = ["uri", "id", "titulo", "descripcion", "publisher_id", "ccaa_slug",
                 "issued", "modified", "score_relevancia", "raw_json_path",
                 "query_kind", "query_value", "ingested_at"]


def sync_ref_datasets(pg: psycopg.Connection, scon: sqlite3.Connection) -> None:
    """UPSERT de `catalog_dataset` (SQLite -> Azure) antes de cargar hechos.

    La FK `fk_fact_dataset` (validada) exige que cada `dataset_uri` del fact exista
    en `catalog_dataset`. Al añadir fuentes nuevas (p.ej. GVA/dadesobertes, Generalitat)
    hay datasets en el catálogo local que aún no están en Azure -> el COPY fallaría.
    """
    print("\n[ref-datasets] UPSERT de catalog_dataset (SQLite -> Azure)...")
    cols = ", ".join(_CATALOG_COLS)
    rows = [list(r) for r in scon.execute(f"SELECT {cols} FROM catalog_dataset").fetchall()]
    if not rows:
        return
    # La FK fk_dataset_publisher -> dim_publisher se valida: publisher_id que no exista
    # en Azure (p.ej. 'GVA-DADESOBERTES', fuente de portal regional) se pone a NULL
    # (columna nullable) para no violarla.
    with pg.cursor() as cur:
        cur.execute("SELECT publisher_id FROM dim_publisher")
        valid_pub = {r[0] for r in cur.fetchall()}
    pub_idx = _CATALOG_COLS.index("publisher_id")
    for r in rows:
        if r[pub_idx] is not None and r[pub_idx] not in valid_pub:
            r[pub_idx] = None
    set_clause = ", ".join(f"{c}=EXCLUDED.{c}" for c in _CATALOG_COLS if c != "uri")
    placeholders = ", ".join(["%s"] * len(_CATALOG_COLS))
    sql = (f"INSERT INTO catalog_dataset ({cols}) VALUES ({placeholders}) "
           f"ON CONFLICT (uri) DO UPDATE SET {set_clause}")
    with pg.cursor() as cur:
        cur.executemany(sql, rows)
    pg.commit()
    print(f"   [ok] catalog_dataset: {len(rows):,} filas upserted")


def sync_ref_dims(pg: psycopg.Connection, scon: sqlite3.Connection) -> None:
    print("\n[ref-dims] Poblando dims referenciales id-only desde los hechos...")
    for table, (fact_col, dim_col, extra) in REF_DIMS.items():
        ids = [r[0] for r in scon.execute(
            f"SELECT DISTINCT {fact_col} FROM fact_ejecucion_presupuestaria "
            f"WHERE {fact_col} IS NOT NULL").fetchall()]
        if not ids:
            print(f"   [skip] {table}: 0 ids en hechos")
            continue
        extra_cols = list(extra.keys())
        cols = [dim_col] + extra_cols
        placeholders = ", ".join(["%s"] * len(cols))
        sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
               f"ON CONFLICT ({dim_col}) DO NOTHING")
        rows = [(str(i), *extra.values()) for i in ids]
        with pg.cursor() as cur:
            cur.executemany(sql, rows)
        pg.commit()
        print(f"   [ok] {table}: {len(ids):,} ids garantizados")


# --------------------------------------------------------------------------- #
# Paso 4: predicciones (TRUNCATE + COPY — fact_prediccion no tiene hijos)
# --------------------------------------------------------------------------- #
PRED_COLS = [
    "pred_id", "ccaa_slug", "entidad_id", "anio", "capitulo_id", "modelo",
    "modelo_version", "importe_predicho", "importe_real", "mae", "mape",
    "desviacion_rel", "alerta", "generated_at",
]


def sync_predicciones(pg: psycopg.Connection, scon: sqlite3.Connection) -> None:
    print("\n[predicciones] TRUNCATE + COPY de fact_prediccion (SQLite -> Azure)...")
    total = scon.execute("SELECT COUNT(*) FROM fact_prediccion").fetchone()[0]
    if total == 0:
        print("   [aviso] fact_prediccion está vacía en SQLite. "
              "Ejecuta antes: python scripts/generate_predictions.py")
        return
    with pg.cursor() as cur:
        cur.execute("TRUNCATE TABLE fact_prediccion")
        scur = scon.execute(f"SELECT {', '.join(PRED_COLS)} FROM fact_prediccion")
        with cur.copy(f"COPY fact_prediccion ({', '.join(PRED_COLS)}) FROM STDIN") as copy:
            n = 0
            while True:
                batch = scur.fetchmany(10000)
                if not batch:
                    break
                for r in batch:
                    copy.write_row(r)
                n += len(batch)
    pg.commit()
    print(f"   [ok] fact_prediccion: {n:,} filas copiadas")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="Sincroniza el data lake local -> Azure (full refresh)")
    ap.add_argument("--only", choices=STEPS, help="Ejecutar solo este paso")
    ap.add_argument("--skip-hechos", action="store_true", help="No recargar los 17M hechos (rápido)")
    ap.add_argument("--skip-train", action="store_true",
                    help="En 'predicciones', no re-entrenar: sube la fact_prediccion ya existente en SQLite")
    args = ap.parse_args()

    if not SQLITE_PATH.exists():
        print(f"[ERROR] No existe SQLite: {SQLITE_PATH}")
        sys.exit(1)

    steps = [args.only] if args.only else list(STEPS)
    if args.skip_hechos and "hechos" in steps:
        steps.remove("hechos")

    print(f"[sync] Full refresh a Azure. Pasos: {steps}")
    t0 = time.time()

    # 0. Pre-paso: garantizar dims referenciales id-only ANTES de cargar hechos,
    #    para que las FKs fk_fact_entidad / fk_fact_gfunc no bloqueen el COPY.
    if "hechos" in steps:
        pg = connect_pg()
        scon = sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True)
        scon.text_factory = str
        try:
            sync_ref_datasets(pg, scon)
            sync_ref_dims(pg, scon)
        finally:
            scon.close()
            pg.close()

    # 1. hechos (subproceso: streaming COPY probado)
    if "hechos" in steps:
        run_script(["load_to_azure.py", "--truncate", "--post-index"], "hechos")

    # 3. features (subproceso: lee parquet, fuente de verdad)
    if "features" in steps:
        run_script(["build_feature_store_azure.py"], "features")

    # 4a. entrenar predicciones -> SQLite (subproceso), salvo --skip-train
    if "predicciones" in steps and not args.skip_train:
        run_script(["generate_predictions.py"], "predicciones (entrenamiento)")

    # 2 + 4b. subidas pequeñas directas (dims, predicciones)
    if "dims" in steps or "predicciones" in steps:
        pg = connect_pg()
        scon = sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True)
        scon.text_factory = str
        try:
            if "dims" in steps:
                sync_dims(pg, scon)
            if "predicciones" in steps:
                sync_predicciones(pg, scon)
        finally:
            scon.close()
            pg.close()

    print(f"\n[OK] Sincronización completada en {(time.time()-t0)/60:.1f} min. "
          f"Azure listo para el dashboard (DATA_BACKEND=azure).")


if __name__ == "__main__":
    main()
