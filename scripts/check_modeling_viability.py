"""
Demuestra la viabilidad tecnica del stack de modelado y del dashboard.

Comprueba cuatro cosas y emite un informe:
  1. XGBoost, LightGBM y Streamlit estan instalados y son importables.
  2. El feature store de Aragon se carga correctamente.
  3. Se entrena un XGBoost y un LightGBM minimos sobre datos reales y se
     reporta MAE y R2 sobre un hold-out temporal.
  4. `src/dashboard/app.py` se importa sin errores (sin lanzar el servidor).

Uso:
    python scripts/check_modeling_viability.py
"""
from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FEATURES_DIR = ROOT / "data_lake" / "03_features" / "aragon" / "features"
TARGET = "OBR"
FEATURES_NUM = [
    "PRE", "CRE",
    "obr_lag_1", "obr_lag_2", "obr_lag_3", "obr_lag_4",
    "obr_rolling4_mean", "obr_rolling4_std",
    "q_sin", "q_cos",
]


def banner(text: str) -> None:
    print()
    print("-" * 70)
    print(f" {text}")
    print("-" * 70)


def step_1_imports() -> dict:
    banner("1. Librerias de modelado y dashboard")
    libs = ["xgboost", "lightgbm", "streamlit", "sklearn", "joblib"]
    result = {}
    for lib in libs:
        try:
            m = importlib.import_module(lib)
            ver = getattr(m, "__version__", "n/a")
            print(f"  [OK]  {lib:12s} {ver}")
            result[lib] = ver
        except Exception as e:
            print(f"  [ERR] {lib:12s} {e}")
            result[lib] = f"ERROR: {e}"
    return result


def step_2_load_features() -> pd.DataFrame:
    banner("2. Carga del feature store de Aragon")
    if not FEATURES_DIR.exists():
        print("  [ERR] No existe", FEATURES_DIR)
        return pd.DataFrame()
    d = ds.dataset(FEATURES_DIR, format="parquet", partitioning="hive")
    df = d.to_table().to_pandas()
    print(f"  [OK]  Filas: {len(df):,} | Columnas: {df.shape[1]}")
    print(f"  [OK]  Rango anios: {int(df['anio'].min())}-{int(df['anio'].max())}")
    return df


def step_3_train(df: pd.DataFrame) -> dict:
    banner("3. Entrenamiento minimo XGBoost y LightGBM")
    if df.empty:
        print("  [SKIP] No hay datos.")
        return {}

    # Dataset: eliminar filas sin target y sin lags (arranque frio)
    cols_needed = [*FEATURES_NUM, TARGET, "anio"]
    have = [c for c in cols_needed if c in df.columns]
    ds_df = df[have].dropna(subset=[TARGET]).copy()
    for c in FEATURES_NUM:
        if c in ds_df.columns:
            ds_df[c] = ds_df[c].fillna(0.0)

    # Split temporal: ultimo anio disponible = test
    years = sorted(ds_df["anio"].dropna().unique())
    if len(years) < 3:
        print(f"  [SKIP] Solo hay {len(years)} anios, muy poco para split.")
        return {}
    test_year = years[-1]
    train = ds_df[ds_df["anio"] < test_year]
    test = ds_df[ds_df["anio"] == test_year]
    x_cols = [c for c in FEATURES_NUM if c in ds_df.columns]
    X_tr, y_tr = train[x_cols], train[TARGET]
    X_te, y_te = test[x_cols], test[TARGET]

    print(f"  Train: {len(X_tr):,} filas (anios < {test_year})")
    print(f"  Test : {len(X_te):,} filas (anio  = {test_year})")
    print(f"  Features: {len(x_cols)} numericas")

    results = {}
    from sklearn.metrics import mean_absolute_error, r2_score

    # XGBoost
    try:
        from xgboost import XGBRegressor
        t0 = time.time()
        m = XGBRegressor(n_estimators=200, max_depth=5, learning_rate=0.1,
                         random_state=42, n_jobs=-1, verbosity=0)
        m.fit(X_tr, y_tr)
        yhat = m.predict(X_te)
        mae = mean_absolute_error(y_te, yhat)
        r2 = r2_score(y_te, yhat)
        dt = time.time() - t0
        print(f"  [OK]  XGBoost  MAE={mae:>14,.0f} EUR  R2={r2:>6.3f}  ({dt:.1f}s)")
        results["xgboost"] = {"mae": mae, "r2": r2, "train_time_s": dt}
    except Exception as e:
        print(f"  [ERR] XGBoost: {e}")
        results["xgboost"] = {"error": str(e)}

    # LightGBM
    try:
        from lightgbm import LGBMRegressor
        t0 = time.time()
        m = LGBMRegressor(n_estimators=200, max_depth=-1, learning_rate=0.1,
                          random_state=42, n_jobs=-1, verbose=-1)
        m.fit(X_tr, y_tr)
        yhat = m.predict(X_te)
        mae = mean_absolute_error(y_te, yhat)
        r2 = r2_score(y_te, yhat)
        dt = time.time() - t0
        print(f"  [OK]  LightGBM MAE={mae:>14,.0f} EUR  R2={r2:>6.3f}  ({dt:.1f}s)")
        results["lightgbm"] = {"mae": mae, "r2": r2, "train_time_s": dt}
    except Exception as e:
        print(f"  [ERR] LightGBM: {e}")
        results["lightgbm"] = {"error": str(e)}

    return results


def step_4_dashboard() -> dict:
    banner("4. Dashboard Streamlit (import sin lanzar servidor)")
    try:
        # Importar el modulo del dashboard; si compila, la arquitectura es valida
        import src.dashboard.app as app  # noqa: F401
        import src.dashboard.components.kpi_cards  # noqa: F401
        import src.dashboard.components.charts      # noqa: F401
        pages_dir = ROOT / "src" / "dashboard" / "pages"
        pages = list(pages_dir.glob("*.py")) if pages_dir.exists() else []
        print(f"  [OK]  src/dashboard/app.py importa correctamente.")
        print(f"  [OK]  Paginas encontradas: {len(pages)}")
        for p in pages:
            print(f"         - {p.name}")
        return {"ok": True, "n_pages": len(pages)}
    except Exception as e:
        print(f"  [ERR] {type(e).__name__}: {e}")
        return {"ok": False, "error": str(e)}


def main() -> int:
    print()
    print("=" * 70)
    print(" Viabilidad tecnica: Modelado (XGBoost/LightGBM) + Dashboard Streamlit")
    print("=" * 70)

    libs = step_1_imports()
    df = step_2_load_features()
    models = step_3_train(df)
    dash = step_4_dashboard()

    # Resumen
    banner("Resumen")
    ok_libs = all("ERROR" not in str(v) for v in libs.values())
    ok_models = any("mae" in v for v in models.values()) if models else False
    ok_dash = dash.get("ok", False)
    print(f"  Imports           : {'OK' if ok_libs else 'FAIL'}")
    print(f"  Entrenamiento ML  : {'OK' if ok_models else 'FAIL'}")
    print(f"  Import dashboard  : {'OK' if ok_dash else 'FAIL'}")
    all_ok = ok_libs and ok_models and ok_dash
    print()
    print("  [{status}] Viabilidad tecnica {label}".format(
        status="OK" if all_ok else "FAIL",
        label="demostrada" if all_ok else "con fallos, revisar arriba",
    ))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
