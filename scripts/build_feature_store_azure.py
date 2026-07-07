#!/usr/bin/env python
"""
Construye el FEATURE STORE de modelado como una TABLA materializada en
Azure Database for PostgreSQL, a partir de la tabla de hechos
`fact_ejecucion_presupuestaria` que ya está cargada en Azure.

Es el equivalente relacional del feature store en parquet
(`data_lake/03_features`): calcula UNA vez el pivot fase->columnas y los lags,
y persiste el resultado en la tabla `feature_store_modelado`, de modo que el
notebook `04_modelado_predictivo_azure.ipynb` solo tenga que hacer un SELECT.

La transformación replica EXACTAMENTE `src/features/builder.py` (misma lógica
de pivot, ratios y lags por serie con dropna=False) para que los resultados del
modelado coincidan con los del notebook 03 / el Entregable 3.

Requisitos:
  - pip install "psycopg[binary]" sqlalchemy
  - La IP del cliente autorizada en el firewall del servidor Azure.
  - La tabla `fact_ejecucion_presupuestaria` ya cargada en Azure
    (ver scripts/load_to_azure.py).

Uso:
    python scripts/build_feature_store_azure.py            # todas las CCAA con datos
    python scripts/build_feature_store_azure.py --ccaa aragon --ccaa canarias
    python scripts/build_feature_store_azure.py --test     # solo conexión + recuentos
    python scripts/build_feature_store_azure.py --table mi_tabla

Credenciales: la contraseña se lee SIEMPRE de la variable de entorno PGPASSWORD.
    PowerShell:  $env:PGPASSWORD = 'tu_password'
    Bash:        export PGPASSWORD='tu_password'
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.storage.azure import make_azure_engine  # noqa: E402
from src.storage.feature_store import read_feature_store_parquet  # noqa: E402

FACT_TABLE = "fact_ejecucion_presupuestaria"
DEFAULT_OUT_TABLE = "feature_store_modelado"

# Columnas de granularidad que identifican la serie temporal (idéntico a builder.py).
SERIES_KEYS = ["entidad_id", "capitulo_id", "grupo_funcional_id"]


# --------------------------------------------------------------------------- #
# Conexión
# --------------------------------------------------------------------------- #
def make_engine():
    """Engine SQLAlchemy contra Azure (delegado al helper compartido)."""
    try:
        return make_azure_engine()
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        sys.exit(4)


# --------------------------------------------------------------------------- #
# Ingeniería de features (réplica exacta de src/features/builder.py)
# --------------------------------------------------------------------------- #
def build_features_df(facts: pd.DataFrame, ccaa_slug: str) -> pd.DataFrame:
    """Convierte los hechos crudos de una CCAA en el dataset wide de modelado.

    Misma lógica que FeatureBuilder.build(), pero SIN persistir en parquet.
    """
    if facts.empty:
        return facts

    # 1. Pivot a formato wide por fase
    wide = (
        facts.groupby(
            ["ccaa_slug", "entidad_id", "anio", "trimestre",
             "capitulo_id", "grupo_funcional_id", "fase"],
            dropna=False,
        )["importe_eur"]
        .sum()
        .unstack("fase")
        .reset_index()
    )

    # 2. Ratios y derivados
    if "PRE" in wide.columns and "OBR" in wide.columns:
        wide["brecha_eur"] = wide["PRE"] - wide["OBR"]
        wide["brecha_pct"] = wide["brecha_eur"] / wide["PRE"].replace(0, np.nan)
    if "PRE" in wide.columns and "CRE" in wide.columns:
        wide["ratio_cre_pre"] = wide["CRE"] / wide["PRE"].replace(0, np.nan)
    if "OBR" in wide.columns and "CRE" in wide.columns:
        wide["ejecutado_pct"] = wide["OBR"] / wide["CRE"].replace(0, np.nan)
    if "OBR" in wide.columns and "PAG" in wide.columns:
        wide["pago_pct"] = wide["PAG"] / wide["OBR"].replace(0, np.nan)

    # 3. Features temporales (lags por serie; dropna=False para NO perder las
    #    columnas de granularidad que estén a NULL en cada CCAA).
    wide = wide.sort_values(SERIES_KEYS + ["anio", "trimestre"])
    if "OBR" in wide.columns:
        grp = wide.groupby(SERIES_KEYS, dropna=False, group_keys=False)["OBR"]
        for lag in (1, 2, 3, 4):
            wide[f"obr_lag_{lag}"] = grp.shift(lag)
        wide["obr_rolling4_mean"] = grp.transform(lambda s: s.rolling(4, min_periods=1).mean())
        wide["obr_rolling4_std"] = grp.transform(lambda s: s.rolling(4, min_periods=1).std())
    else:
        for lag in (1, 2, 3, 4):
            wide[f"obr_lag_{lag}"] = np.nan
        wide["obr_rolling4_mean"] = np.nan
        wide["obr_rolling4_std"] = np.nan

    # 4. Estacionalidad del trimestre
    q = wide["trimestre"].fillna(0).astype(int)
    wide["q_sin"] = np.sin(2 * np.pi * q / 4)
    wide["q_cos"] = np.cos(2 * np.pi * q / 4)

    return wide


# --------------------------------------------------------------------------- #
# Carga de hechos desde Azure
# --------------------------------------------------------------------------- #
def read_facts(engine, ccaa_slug: str) -> pd.DataFrame:
    sql = text(
        f"""
        SELECT ccaa_slug, entidad_id, anio, trimestre,
               capitulo_id, grupo_funcional_id, fase, importe_eur
        FROM {FACT_TABLE}
        WHERE ccaa_slug = :slug
        """
    )
    with engine.connect() as conn:
        return pd.read_sql(sql, conn, params={"slug": ccaa_slug})


def list_ccaa(engine) -> list[str]:
    sql = text(f"SELECT DISTINCT ccaa_slug FROM {FACT_TABLE} ORDER BY ccaa_slug")
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(sql)]


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def build_from_parquet(targets: list[str] | None) -> pd.DataFrame:
    """Lee el feature store del parquet (FUENTE DE VERDAD). Rápido y fiel."""
    if not targets:
        fs = read_feature_store_parquet()
    else:
        parts = [read_feature_store_parquet(ccaa_slug=s) for s in targets]
        parts = [p for p in parts if not p.empty]
        fs = pd.concat(parts, ignore_index=True, sort=False) if parts else pd.DataFrame()
    return fs


def build_from_facts(engine, targets: list[str] | None) -> pd.DataFrame:
    """Recalcula el feature store desde los hechos de Azure (equivalente al parquet)."""
    ccaa_all = list_ccaa(engine)
    print(f"[conexión] OK. CCAA con hechos en Azure ({len(ccaa_all)}): {ccaa_all}")
    tgt = targets or ccaa_all
    faltan = [c for c in tgt if c not in ccaa_all]
    if faltan:
        print(f"[aviso] CCAA solicitadas sin datos en Azure (se omiten): {faltan}")
    tgt = [c for c in tgt if c in ccaa_all]
    frames = []
    for slug in tgt:
        facts = read_facts(engine, slug)
        wide = build_features_df(facts, slug)
        if wide.empty:
            print(f"  [{slug:>18}] 0 filas de hechos -> se omite")
            continue
        frames.append(wide)
        print(f"  [{slug:>18}] hechos={len(facts):>8,}  ->  features={len(wide):>7,} filas x {wide.shape[1]} cols")
    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()


def _pg_type(dtype) -> str:
    """Mapea un dtype de pandas al tipo PostgreSQL para el CREATE TABLE."""
    import pandas.api.types as pt
    if pt.is_bool_dtype(dtype):
        return "boolean"
    if pt.is_integer_dtype(dtype):
        return "bigint"
    if pt.is_float_dtype(dtype):
        return "double precision"
    if pt.is_datetime64_any_dtype(dtype):
        return "timestamp"
    return "text"


def _write_df_via_copy(df: pd.DataFrame, table: str, engine) -> None:
    """Crea `table` desde los dtypes del df y vuelca las filas con psycopg COPY.

    Sustituye a `DataFrame.to_sql` (roto con pandas 3.0 + SQLAlchemy 2.0). Usa la
    conexión DBAPI cruda (psycopg) del engine para el COPY por streaming.
    """
    import math

    cols = list(df.columns)
    coldefs = ", ".join(f'"{c}" {_pg_type(df[c].dtype)}' for c in cols)
    collist = ", ".join(f'"{c}"' for c in cols)

    raw = engine.raw_connection()
    try:
        pgconn = raw.driver_connection  # psycopg.Connection subyacente
        with pgconn.cursor() as cur:
            cur.execute(f'DROP TABLE IF EXISTS "{table}"')
            cur.execute(f'CREATE TABLE "{table}" ({coldefs})')
            with cur.copy(f'COPY "{table}" ({collist}) FROM STDIN') as copy:
                for row in df.itertuples(index=False, name=None):
                    # NaN/NaT -> None (NULL) para COPY.
                    clean = tuple(
                        None if (v is None or (isinstance(v, float) and math.isnan(v)))
                        else v
                        for v in row
                    )
                    copy.write_row(clean)
        pgconn.commit()
    finally:
        raw.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Feature store de modelado -> tabla en Azure PostgreSQL")
    ap.add_argument("--ccaa", action="append", default=[],
                    help="Procesar solo estas CCAA (repetible). Por defecto: todas.")
    ap.add_argument("--table", default=DEFAULT_OUT_TABLE, help=f"Nombre de la tabla destino (def: {DEFAULT_OUT_TABLE})")
    ap.add_argument("--from-facts", action="store_true",
                    help="Recalcular desde los hechos de Azure en vez de leer el parquet (fuente de verdad).")
    ap.add_argument("--test", action="store_true", help="Solo prueba conexión / lectura, sin escribir.")
    args = ap.parse_args()

    engine = make_engine()
    targets = args.ccaa or None
    t0 = time.time()

    if args.from_facts:
        print("[origen] Recálculo desde los hechos de Azure (--from-facts).")
        fs = build_from_facts(engine, targets)
    else:
        print("[origen] Feature store en parquet (fuente de verdad).")
        fs = build_from_parquet(targets)

    if fs.empty:
        print("[ERROR] No se generó ninguna fila de features (¿parquet/hechos vacíos?).")
        sys.exit(3)

    print(f"\n[feature store] Total: {len(fs):,} filas x {fs.shape[1]} columnas.")
    print(f"[feature store] Columnas: {list(fs.columns)}")

    if args.test:
        print(f"[test] {len(fs):,} filas listas. Sin escribir (--test).")
        return

    # Escritura en Azure (replace: recrea la tabla desde cero, idempotente).
    # NOTA: no se usa pandas `to_sql` porque pandas 3.0 dejó de aceptar el Engine
    # de SQLAlchemy 2.0 como conectable (cae al path DBAPI2 y llama `.cursor()` sobre
    # el Engine -> AttributeError). Se escribe con psycopg COPY (mismo mecanismo
    # probado que el loader de hechos), creando la tabla desde los dtypes del df.
    print(f"[destino] Escribiendo tabla '{args.table}' en Azure vía COPY...")
    _write_df_via_copy(fs, args.table, engine)

    # Índice para el filtro típico del notebook (por CCAA y año).
    with engine.begin() as conn:
        conn.execute(text(
            f'CREATE INDEX IF NOT EXISTS ix_{args.table}_ccaa_anio '
            f'ON {args.table} (ccaa_slug, anio)'
        ))
        n = conn.execute(text(f"SELECT COUNT(*) FROM {args.table}")).scalar()

    print(f"[verif] Filas en destino: {n:,}  ({time.time()-t0:.1f}s)")
    print(f"[OK] Feature store materializado en Azure como tabla '{args.table}'.")


if __name__ == "__main__":
    main()
