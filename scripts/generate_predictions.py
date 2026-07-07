#!/usr/bin/env python
"""
Genera la tabla `fact_prediccion` en SQLite (fuente de verdad) a partir de los
modelos predictivos por CCAA (Paso 3c: target OBR en log1p).

Para cada CCAA entrena el modelo independiente en grano nativo (mismos features
seguros contra fuga y mismo split temporal que `train_models_native_log.py` /
notebook 03) y, sobre los años de test, produce una fila por observación con:

  importe_real     = OBR real de cierre
  importe_predicho = OBR predicho por el mejor modelo de la CCAA
  desviacion_rel   = (real - predicho) / predicho
  alerta           = verde (|dev|<5%) | amarillo (<15%) | rojo (>=15%)
  mae, mape        = métricas de test del modelo ganador (a nivel CCAA)
  modelo           = modelo ganador (menor MAE, incl. baselines honestos)

El resultado se persiste en `fact_prediccion` de la BD SQLite. Desde ahí,
`scripts/sync_azure.py` lo replica a Azure para alimentar el dashboard.

Uso:
    python scripts/generate_predictions.py
    python scripts/generate_predictions.py --ccaa aragon --ccaa canarias
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn.base as skb
from sklearn.compose import ColumnTransformer, TransformedTargetRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from xgboost import XGBRegressor

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import settings  # noqa: E402
from src.storage.feature_store import read_feature_store_parquet  # noqa: E402

warnings.filterwarnings("ignore")

MODELO_VERSION = "3c-log1p"
MAX_IMPORTE = 1e11
TARGET = "OBR"
NUM_COLS = ["PRE", "CRE", "ratio_cre_pre", "obr_lag_1", "obr_lag_2",
            "obr_lag_3", "obr_lag_4", "anio"]
MODEL_SPECS = {
    "ridge": Ridge(alpha=1.0),
    "random_forest": RandomForestRegressor(n_estimators=300, max_depth=6,
                                           random_state=42, n_jobs=-1),
    "xgboost": XGBRegressor(n_estimators=300, max_depth=4, learning_rate=0.05,
                            random_state=42, tree_method="hist"),
}
TEST_N_YEARS = 2
CCAA_OBR = ["aragon", "asturias", "canarias", "cataluna", "madrid",
            "pais-vasco", "castilla-y-leon", "nacional", "illes-balears",
            "castilla-la-mancha", "comunidad-valenciana"]


def metrics(y_true, y_pred):
    y_true = np.asarray(y_true, float)
    y_pred = np.asarray(y_pred, float)
    denom = np.where(np.abs(y_true) < 1e-6, np.nan, np.abs(y_true))
    return dict(
        mae=float(mean_absolute_error(y_true, y_pred)),
        mape=float(np.nanmean(np.abs(y_true - y_pred) / denom)),
        r2=float(r2_score(y_true, y_pred)) if len(y_true) >= 2 else np.nan,
    )


def make_pipeline(model, cat_cols):
    num_pipe = Pipeline([("imp", SimpleImputer(strategy="median")),
                         ("sc", StandardScaler())])
    cat_pipe = Pipeline([("imp", SimpleImputer(strategy="most_frequent")),
                         ("ohe", OneHotEncoder(handle_unknown="ignore", sparse_output=False))])
    prep = ColumnTransformer([("num", num_pipe, NUM_COLS),
                              ("cat", cat_pipe, cat_cols)], remainder="drop")
    inner = Pipeline([("prep", prep), ("est", model)])
    return TransformedTargetRegressor(regressor=inner, func=np.log1p, inverse_func=np.expm1)


def _alerta(dev_rel: float) -> str:
    if dev_rel is None or np.isnan(dev_rel):
        return "gris"
    a = abs(dev_rel)
    if a < 0.05:
        return "verde"
    if a < 0.15:
        return "amarillo"
    return "rojo"


def _as_smallint(v):
    """Convierte capitulo_id a int (o None) — la columna es SMALLINT en Azure."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def predict_ccaa(slug: str) -> list[dict]:
    """Entrena y devuelve las filas de fact_prediccion para una CCAA (test years)."""
    d = read_feature_store_parquet(ccaa_slug=slug)
    if d.empty or TARGET not in d.columns:
        return []
    for c in ["PRE", "OBR", "CRE", "PAG"]:
        if c in d.columns:
            d = d[~(d[c].abs() > MAX_IMPORTE)]
    d = d[d[TARGET].notna() & (d[TARGET] > 0)].copy()
    if "ratio_cre_pre" not in d.columns and {"CRE", "PRE"} <= set(d.columns):
        d["ratio_cre_pre"] = d["CRE"] / d["PRE"].replace(0, np.nan)
    cat_cols = ["capitulo_id"] if ("capitulo_id" in d.columns and d["capitulo_id"].notna().any()) else []

    years = sorted(d["anio"].unique())
    test_years = set(years[-TEST_N_YEARS:])
    train = d[~d["anio"].isin(test_years)]
    test = d[d["anio"].isin(test_years)].copy()
    if len(train) < 20 or len(test) < 5:
        return []

    y_te = test[TARGET].to_numpy(float)
    fb = float(train[TARGET].median())
    preds = {
        "baseline_lag1": test["obr_lag_1"].fillna(test["CRE"]).fillna(test["PRE"]).fillna(fb).to_numpy(float),
        "baseline_cre": test["CRE"].fillna(test["PRE"]).fillna(fb).to_numpy(float),
    }
    feat = NUM_COLS + cat_cols
    Xtr, ytr, Xte = train[feat], train[TARGET], test[feat]
    for name, model in MODEL_SPECS.items():
        ttr = make_pipeline(skb.clone(model), cat_cols)
        ttr.fit(Xtr, ytr)
        preds[name] = ttr.predict(Xte)

    # Modelo ganador: menor MAE de test (comparación honesta, incluye baselines)
    scored = {k: metrics(y_te, v) for k, v in preds.items()}
    winner = min(scored, key=lambda k: scored[k]["mae"])
    p = np.asarray(preds[winner], float)
    m = scored[winner]

    # entidad_id / capitulo_id según grano
    ent = test["entidad_id"] if "entidad_id" in test.columns else pd.Series([None] * len(test))
    cap = test["capitulo_id"] if "capitulo_id" in test.columns else pd.Series([None] * len(test))

    rows = []
    for i in range(len(test)):
        real = float(y_te[i])
        pred = float(p[i])
        dev = (real - pred) / pred if abs(pred) > 1e-6 else np.nan
        rows.append(dict(
            ccaa_slug=slug,
            entidad_id=(None if pd.isna(ent.iloc[i]) else str(ent.iloc[i])),
            anio=int(test["anio"].iloc[i]),
            capitulo_id=_as_smallint(cap.iloc[i]),
            modelo=winner,
            modelo_version=MODELO_VERSION,
            importe_predicho=pred,
            importe_real=real,
            mae=m["mae"],
            mape=(None if np.isnan(m["mape"]) else m["mape"]),
            desviacion_rel=(None if np.isnan(dev) else dev),
            alerta=_alerta(dev),
        ))
    print(f"  [{slug:>18}] modelo={winner:<14} filas={len(rows):>5}  MAE={m['mae']/1e6:.1f}M€")
    return rows


def write_sqlite(rows: list[dict]) -> int:
    """Reemplaza el contenido de fact_prediccion en SQLite (full refresh)."""
    df = pd.DataFrame(rows)
    df.insert(0, "pred_id", range(1, len(df) + 1))
    df["generated_at"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    cols = ["pred_id", "ccaa_slug", "entidad_id", "anio", "capitulo_id", "modelo",
            "modelo_version", "importe_predicho", "importe_real", "mae", "mape",
            "desviacion_rel", "alerta", "generated_at"]
    df = df[cols].astype(object).where(pd.notna(df[cols]), None)

    db = settings.paths.sqlite_path
    placeholders = ", ".join("?" * len(cols))
    with sqlite3.connect(str(db)) as conn:
        conn.execute("DELETE FROM fact_prediccion")
        conn.executemany(
            f'INSERT INTO fact_prediccion ({", ".join(cols)}) VALUES ({placeholders})',
            [tuple(r) for r in df.itertuples(index=False, name=None)],
        )
        conn.commit()
    return len(df)


def main() -> None:
    ap = argparse.ArgumentParser(description="Genera fact_prediccion en SQLite")
    ap.add_argument("--ccaa", action="append", default=[],
                    help="Solo estas CCAA (repetible). Por defecto: todas las modelables.")
    args = ap.parse_args()

    targets = args.ccaa or CCAA_OBR
    print(f"[predicciones] Entrenando y prediciendo {len(targets)} CCAA (target log1p)...\n")
    all_rows: list[dict] = []
    for slug in targets:
        all_rows.extend(predict_ccaa(slug))

    if not all_rows:
        print("[ERROR] No se generó ninguna predicción (¿feature store vacío?).")
        sys.exit(1)

    n = write_sqlite(all_rows)
    dist = pd.Series([r["alerta"] for r in all_rows]).value_counts().to_dict()
    print(f"\n[OK] {n:,} predicciones escritas en fact_prediccion (SQLite).")
    print(f"[alertas] {dist}")
    print("[siguiente] Sube a Azure con:  python scripts/sync_azure.py --only predicciones")


if __name__ == "__main__":
    main()
