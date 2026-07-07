#!/usr/bin/env python
"""
Carga masiva SQLite -> Azure Database for PostgreSQL (Flexible Server).

Vuelca la tabla `fact_ejecucion_presupuestaria` de `data_lake/catalog.db`
(17,264,536 filas) a la base de datos PostgreSQL de Azure usando COPY FROM STDIN
por streaming (sin cargar todo en memoria), que es la vía más rápida de ingesta.

Requisitos:
  - pip install "psycopg[binary]"
  - La IP del cliente debe estar autorizada en el firewall del servidor Azure
    (Portal Azure -> el servidor -> Networking -> Firewall rules).
  - Azure exige SSL: se usa sslmode=require.

Uso:
    python scripts/load_to_azure.py                 # carga incremental (append)
    python scripts/load_to_azure.py --truncate      # vacía la tabla antes de cargar
    python scripts/load_to_azure.py --truncate --post-index  # carga + PK e índices
    python scripts/load_to_azure.py --index-only     # solo crea PK e índices (idempotente)
    python scripts/load_to_azure.py --test           # solo prueba conexión y esquema
    python scripts/load_to_azure.py --limit 100000   # carga parcial (pruebas)


"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
SQLITE_PATH = ROOT / "data_lake" / "catalog.db"
TABLE = "fact_ejecucion_presupuestaria"

# Columnas en el MISMO orden en origen y destino.
COLUMNS = [
    "fact_id", "ccaa_slug", "entidad_id", "anio", "trimestre",
    "capitulo_id", "grupo_funcional_id", "fase", "importe_eur",
    "dataset_uri", "loaded_at",
]


def _require_password() -> str:
    pwd = os.getenv("PGPASSWORD")
    if not pwd:
        print("[ERROR] Falta la variable de entorno PGPASSWORD con la contraseña de Azure.")
        print("  PowerShell:  $env:PGPASSWORD = 'tu_password'")
        print("  Bash:        export PGPASSWORD='tu_password'")
        sys.exit(4)
    return pwd


PG = dict(
    host=os.getenv("PGHOST", "postgres-tfm.postgres.database.azure.com"),
    port=int(os.getenv("PGPORT", "5432")),
    dbname=os.getenv("PGDATABASE", "postgres"),
    user=os.getenv("PGUSER", "adminuser"),
    sslmode=os.getenv("PGSSLMODE", "require"),
    connect_timeout=30,
)

BATCH = 50_000  # filas leídas de SQLite por lote


def connect_pg() -> psycopg.Connection:
    try:
        return psycopg.connect(password=_require_password(), **PG)
    except psycopg.OperationalError as exc:
        print("\n[ERROR] No se pudo conectar a Azure PostgreSQL.")
        print(f"        {exc}")
        print("\nCausas habituales:")
        print("  1) La IP de este equipo no está en el firewall del servidor Azure.")
        print("     Portal -> postgres-tfm -> Networking -> '+ Add current client IP'.")
        print("  2) SSL: Azure exige sslmode=require (ya está configurado).")
        print("  3) Usuario: en Flexible Server es 'adminuser'; en Single Server sería")
        print("     'adminuser@postgres-tfm'. Prueba PGUSER='adminuser@postgres-tfm'.")
        sys.exit(2)


def verify_schema(pg: psycopg.Connection) -> None:
    """Comprueba que la tabla destino existe y tiene las 11 columnas esperadas."""
    with pg.cursor() as cur:
        cur.execute(
            "SELECT column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_name = %s ORDER BY ordinal_position",
            (TABLE,),
        )
        cols = cur.fetchall()
    if not cols:
        print(f"[ERROR] La tabla '{TABLE}' no existe en la base de datos destino.")
        sys.exit(3)
    dest = [c[0] for c in cols]
    print(f"[schema] Columnas en destino ({len(dest)}): {dest}")
    faltan = [c for c in COLUMNS if c not in dest]
    sobran = [c for c in dest if c not in COLUMNS]
    if faltan:
        print(f"[ERROR] Faltan columnas en destino: {faltan}")
        sys.exit(3)
    if sobran:
        print(f"[aviso] Columnas extra en destino (se ignoran): {sobran}")
    print("[schema] OK: todas las columnas esperadas están presentes.")


# Índices recomendados (se crean DESPUÉS del COPY: es más rápido que mantenerlos
# durante la inserción). Las consultas típicas del TFM filtran por CCAA/año/capítulo/fase.
POST_INDEX_STMTS = [
    # Clave primaria en fact_id (único en origen), sólo si no existe ya.
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conrelid = 'fact_ejecucion_presupuestaria'::regclass AND contype = 'p'
        ) THEN
            ALTER TABLE fact_ejecucion_presupuestaria ADD PRIMARY KEY (fact_id);
        END IF;
    END $$;
    """,
    "CREATE INDEX IF NOT EXISTS ix_fact_ccaa_anio "
    "ON fact_ejecucion_presupuestaria (ccaa_slug, anio);",
    "CREATE INDEX IF NOT EXISTS ix_fact_cap_fase "
    "ON fact_ejecucion_presupuestaria (capitulo_id, fase);",
]


def create_indexes(pg: psycopg.Connection) -> None:
    """Crea PK e índices recomendados (idempotente)."""
    print("\n[índices] Creando PK e índices (puede tardar unos minutos en 17M filas)...")
    for stmt in POST_INDEX_STMTS:
        label = " ".join(stmt.split())[:70]
        t0 = time.time()
        with pg.cursor() as cur:
            cur.execute(stmt)
        pg.commit()
        print(f"  [ok] {label}...  ({time.time()-t0:.1f}s)")
    print("[índices] Completado.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Carga SQLite -> Azure PostgreSQL")
    ap.add_argument("--truncate", action="store_true", help="Vacía la tabla destino antes de cargar")
    ap.add_argument("--test", action="store_true", help="Solo prueba conexión y esquema")
    ap.add_argument("--limit", type=int, default=0, help="Cargar solo N filas (pruebas)")
    ap.add_argument("--post-index", action="store_true", help="Tras la carga, crea PK e índices")
    ap.add_argument("--index-only", action="store_true", help="Solo crea PK e índices (sin cargar datos)")
    args = ap.parse_args()

    if not SQLITE_PATH.exists():
        print(f"[ERROR] No existe SQLite: {SQLITE_PATH}")
        sys.exit(1)

    print(f"[origen] {SQLITE_PATH}")
    print(f"[destino] {PG['user']}@{PG['host']}:{PG['port']}/{PG['dbname']} (sslmode={PG['sslmode']})\n")

    pg = connect_pg()
    print("[conexión] OK")
    verify_schema(pg)

    if args.index_only:
        create_indexes(pg)
        with pg.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {TABLE}")
            print(f"[destino] Filas en destino: {cur.fetchone()[0]:,}")
        pg.close()
        return

    # Total de filas de origen (para progreso / ETA)
    scon = sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True)
    scon.text_factory = str
    total = scon.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
    if args.limit:
        total = min(total, args.limit)
    print(f"[origen] Filas a cargar: {total:,}")

    if args.test:
        print("\n[test] Conexión y esquema verificados. Sin cargar datos (--test).")
        with pg.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {TABLE}")
            print(f"[destino] Filas actuales en destino: {cur.fetchone()[0]:,}")
        pg.close(); scon.close()
        return

    if args.truncate:
        print("[destino] TRUNCATE de la tabla...")
        with pg.cursor() as cur:
            cur.execute(f"TRUNCATE TABLE {TABLE}")
        pg.commit()

    col_list = ", ".join(COLUMNS)
    select_sql = f"SELECT {col_list} FROM {TABLE}"
    if args.limit:
        select_sql += f" LIMIT {args.limit}"

    scur = scon.execute(select_sql)

    copy_sql = f"COPY {TABLE} ({col_list}) FROM STDIN"
    t0 = time.time()
    done = 0
    print("\n[carga] Iniciando COPY por streaming...\n")
    with pg.cursor() as cur:
        with cur.copy(copy_sql) as copy:
            while True:
                rows = scur.fetchmany(BATCH)
                if not rows:
                    break
                for r in rows:
                    copy.write_row(r)
                done += len(rows)
                el = time.time() - t0
                rate = done / el if el else 0
                eta = (total - done) / rate if rate else 0
                pct = 100 * done / total if total else 0
                print(f"  {done:>12,}/{total:,} ({pct:5.1f}%)  "
                      f"{rate:,.0f} filas/s  ETA {eta/60:5.1f} min", end="\r", flush=True)
    pg.commit()
    el = time.time() - t0
    print(f"\n\n[carga] COMPLETADA: {done:,} filas en {el/60:.1f} min "
          f"({done/el:,.0f} filas/s)")

    # Verificación final
    with pg.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {TABLE}")
        dest_count = cur.fetchone()[0]
        cur.execute(f"ANALYZE {TABLE}")
    pg.commit()
    print(f"[verif] Filas en destino tras la carga: {dest_count:,}")
    if dest_count == total and not args.limit:
        print("[verif] OK: el recuento coincide con el origen.")

    if args.post_index:
        create_indexes(pg)

    pg.close(); scon.close()


if __name__ == "__main__":
    main()
