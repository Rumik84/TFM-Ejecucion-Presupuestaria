#!/usr/bin/env python
"""
Paso 3 — Modelo predictivo INDEPENDIENTE por CCAA.

Entrena un modelo separado para cada CCAA (la predicción es por comunidad,
no agrupada), sobre el dataset homogéneo CCAA-capítulo-año del Paso 2
(`data_lake/04_models/dataset/model_dataset.parquet`).

Para cada CCAA:
  - Split temporal ya marcado en la columna `split` (train ≤2022, test 2023-24).
  - Baselines de referencia: OBR ≈ obr_lag_1 (persistencia) y OBR ≈ CRE (crédito).
  - Modelos: Ridge (lineal), Random Forest y XGBoost, con preprocesado
    (imputación + one-hot del capítulo). Se justifica el uso de árboles por la
    no-normalidad y heterocedasticidad (notebook 02).
  - Métricas en test: MAE (principal), MAPE, RMSE, R².
  - Serializa el mejor modelo por CCAA y guarda un CSV de métricas.

Uso:
    python scripts/train_models_per_ccaa.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.modeling.evaluate import Evaluator
from src.modeling.models import get_model
from src.modeling.preprocessing import build_preprocessor

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "data_lake" / "04_models" / "dataset" / "model_dataset.parquet"
MODELS_DIR = ROOT / "data_lake" / "04_models"

TARGET = "OBR"
NUM_COLS = ["PRE", "CRE", "ratio_cre_pre",
            "obr_lag_1", "obr_lag_2", "obr_lag_3", "obr_roll3_mean", "anio"]
CAT_COLS = ["capitulo_id"]

# Modelos y su hiperparámetros (moderados, ajustados a muestras pequeñas)
MODEL_SPECS = {
    "ridge": {},
    "random_forest": {"n_estimators": 300, "max_depth": 5},
    "xgboost": {"n_estimators": 200, "max_depth": 3, "learning_rate": 0.05},
}


def make_pipeline(name: str):
    prep = build_preprocessor(NUM_COLS, CAT_COLS)
    est = get_model(name, **MODEL_SPECS.get(name, {}))
    return Pipeline([("prep", prep), ("est", est)])


def baseline_metrics(test: pd.DataFrame) -> dict[str, dict]:
    y = test[TARGET].to_numpy(float)
    pred_lag = test["obr_lag_1"].fillna(test["CRE"]).fillna(test["PRE"]).to_numpy(float)
    pred_cre = test["CRE"].fillna(test["PRE"]).to_numpy(float)
    return {
        "baseline_lag1": Evaluator.compute_metrics(y, pred_lag),
        "baseline_cre": Evaluator.compute_metrics(y, pred_cre),
    }


def train_ccaa(slug: str, df: pd.DataFrame) -> list[dict]:
    d = df[df["ccaa_slug"] == slug]
    d = d[d[TARGET].notna() & (d[TARGET] > 0)]
    train = d[d["split"] == "train"]
    test = d[d["split"] == "test"]
    nombre = d["ccaa_nombre"].iloc[0] if len(d) else slug

    rows: list[dict] = []
    base = {"ccaa": nombre, "n_train": len(train), "n_test": len(test)}

    if len(train) < 15 or len(test) < 5:
        rows.append({**base, "modelo": "—", "nota": "datos insuficientes (train<15 o test<5)"})
        return rows

    # Baselines
    for name, met in baseline_metrics(test).items():
        rows.append({**base, "modelo": name, **met})

    # Modelos ML
    X_tr, y_tr = train[NUM_COLS + CAT_COLS], train[TARGET]
    X_te, y_te = test[NUM_COLS + CAT_COLS], test[TARGET]
    best = (None, np.inf, None)
    for name in MODEL_SPECS:
        try:
            pipe = make_pipeline(name)
            pipe.fit(X_tr, y_tr)
            preds = pipe.predict(X_te)
            met = Evaluator.compute_metrics(y_te, preds)
            rows.append({**base, "modelo": name, **met})
            if met["mae"] < best[1]:
                best = (name, met["mae"], pipe)
        except Exception as exc:  # noqa: BLE001
            rows.append({**base, "modelo": name, "nota": f"error: {type(exc).__name__}"})

    # Serializar el mejor modelo ML de esta CCAA (para despliegue)
    if best[2] is not None:
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        path = MODELS_DIR / f"{slug}__best_{best[0]}.joblib"
        joblib.dump(best[2], path)

    # Marcar el GANADOR GLOBAL de la CCAA (incluye baselines) por menor MAE
    cand = [r for r in rows if isinstance(r.get("mae"), (int, float)) and not np.isnan(r["mae"])]
    if cand:
        win = min(cand, key=lambda r: r["mae"])
        win["ganador"] = "★"
        win["bate_baseline"] = (
            "sí" if win["modelo"] not in ("baseline_lag1", "baseline_cre") else "no (gana baseline)"
        )
    return rows


def main() -> None:
    if not DATASET.exists():
        raise SystemExit(f"No existe {DATASET}. Ejecuta antes scripts/build_model_dataset.py")
    df = pd.read_parquet(DATASET)
    ccaa_slugs = [c for c in df["ccaa_slug"].unique()]

    print("[Paso 3] Entrenando un modelo INDEPENDIENTE por CCAA...\n")
    all_rows: list[dict] = []
    for slug in ccaa_slugs:
        all_rows.extend(train_ccaa(slug, df))

    res = pd.DataFrame(all_rows)
    # MAE legible en millones de euros
    if "mae" in res.columns:
        res["MAE_M€"] = (res["mae"].astype(float) / 1e6).round(1)
    for c in ["mape", "r2"]:
        if c in res.columns:
            res[c] = res[c].astype(float).round(3)
    cols = [c for c in ["ccaa", "n_train", "n_test", "modelo", "MAE_M€", "mape", "r2",
                        "ganador", "bate_baseline", "nota"] if c in res.columns]
    res = res[cols]

    out = MODELS_DIR / "metrics_per_ccaa.csv"
    res.to_csv(out, index=False, encoding="utf-8-sig")

    pd.set_option("display.width", 220, "display.max_rows", 100)
    print(res.fillna("").to_string(index=False))

    # Resumen: ganador por CCAA
    print("\n=== GANADOR POR CCAA (menor MAE, incluye baselines) ===")
    win = res[res.get("ganador") == "★"] if "ganador" in res.columns else res.iloc[0:0]
    for _, r in win.iterrows():
        print(f"  {r['ccaa']:<16} -> {r['modelo']:<15} (MAE={r['MAE_M€']} M€, MAPE={r['mape']}) | ML bate baseline: {r['bate_baseline']}")

    n_ml = (win["bate_baseline"] == "sí").sum() if len(win) else 0
    print(f"\nEn {n_ml}/{len(win)} CCAA el modelo ML supera al mejor baseline.")
    print(f"\n[OK] Métricas -> {out}")
    print(f"[OK] Mejor modelo ML por CCAA -> {MODELS_DIR}/<ccaa>__best_<modelo>.joblib")


if __name__ == "__main__":
    main()
