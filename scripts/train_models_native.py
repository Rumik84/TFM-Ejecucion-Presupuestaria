#!/usr/bin/env python
"""
Paso 3b — Modelo predictivo INDEPENDIENTE por CCAA en su GRANO NATIVO.

A diferencia del Paso 3 (grano común CCAA-capítulo-año, para comparar), aquí
cada CCAA usa su máxima granularidad disponible en el feature store, lo que
maximiza el nº de filas:
  - Aragón / AGE: capítulo + grupo funcional (~miles de filas)
  - Canarias: entidad (~770 filas)
  - resto: capítulo

Split temporal adaptado a cada CCAA (sus rangos de años difieren): las últimas
2 años con datos = test; el resto = train.

Features SEGURAS contra fuga: PRE, CRE, ratio_cre_pre, obr_lag_1..4, anio y el
capítulo (one-hot) cuando existe. Se EXCLUYEN obr_rolling4_* (incluyen el año
objetivo → fuga) y ejecutado_pct / brecha_pct (derivan de OBR).

Uso:
    python scripts/train_models_native.py
"""
from __future__ import annotations

import re
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
FEATURES_DIR = ROOT / "data_lake" / "03_features"
MODELS_DIR = ROOT / "data_lake" / "04_models"
MAX_IMPORTE = 1e11

CCAA_OBR = ["aragon", "asturias", "canarias", "cataluna", "madrid",
            "pais-vasco", "castilla-y-leon", "nacional", "illes-balears",
            "castilla-la-mancha"]
CCAA_NAMES = {
    "aragon": "Aragón", "asturias": "Asturias", "canarias": "Canarias",
    "cataluna": "Cataluña", "madrid": "Madrid", "pais-vasco": "País Vasco",
    "castilla-y-leon": "Castilla y León", "nacional": "AGE (nacional)",
    "illes-balears": "Illes Balears", "castilla-la-mancha": "C.-La Mancha",
}

TARGET = "OBR"
NUM_COLS = ["PRE", "CRE", "ratio_cre_pre", "obr_lag_1", "obr_lag_2",
            "obr_lag_3", "obr_lag_4", "anio"]
MODEL_SPECS = {
    "ridge": {},
    "random_forest": {"n_estimators": 300, "max_depth": 6},
    "xgboost": {"n_estimators": 300, "max_depth": 4, "learning_rate": 0.05},
}
TEST_N_YEARS = 2      # últimos N años como test


def load_ccaa(slug: str) -> pd.DataFrame:
    fs = sorted((FEATURES_DIR / slug / "features").rglob("*.parquet"))
    if not fs:
        return pd.DataFrame()
    parts = []
    for f in fs:
        d = pd.read_parquet(f)
        if "anio" not in d.columns:
            m = re.search(r"anio=(\d+)", str(f))
            if m:
                d["anio"] = int(m.group(1))
        parts.append(d)
    return pd.concat(parts, ignore_index=True)


def make_pipeline(name: str, cat_cols: list[str]):
    prep = build_preprocessor([c for c in NUM_COLS], cat_cols)
    est = get_model(name, **MODEL_SPECS.get(name, {}))
    return Pipeline([("prep", prep), ("est", est)])


def temporal_split_last(d: pd.DataFrame, n_years: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    years = sorted(d["anio"].unique())
    test_years = set(years[-n_years:])
    train = d[~d["anio"].isin(test_years)]
    test = d[d["anio"].isin(test_years)]
    return train, test


def train_ccaa(slug: str) -> list[dict]:
    d = load_ccaa(slug)
    nombre = CCAA_NAMES.get(slug, slug)
    if d.empty or TARGET not in d.columns:
        return [{"ccaa": nombre, "modelo": "—", "nota": "sin feature store / sin OBR"}]

    for c in ["PRE", "OBR", "CRE", "PAG"]:
        if c in d.columns:
            d = d[~(d[c].abs() > MAX_IMPORTE)]
    d = d[d[TARGET].notna() & (d[TARGET] > 0)].copy()
    if "ratio_cre_pre" not in d.columns and {"CRE", "PRE"} <= set(d.columns):
        d["ratio_cre_pre"] = d["CRE"] / d["PRE"].replace(0, np.nan)

    # capítulo como categórica solo si está poblado
    cat_cols = ["capitulo_id"] if d.get("capitulo_id") is not None and d["capitulo_id"].notna().any() else []
    grano = "capítulo" if cat_cols else "entidad/CCAA"

    train, test = temporal_split_last(d, TEST_N_YEARS)
    base = {"ccaa": nombre, "grano": grano, "n_train": len(train), "n_test": len(test)}
    if len(train) < 20 or len(test) < 5:
        return [{**base, "modelo": "—", "nota": "datos insuficientes"}]

    rows: list[dict] = []
    y_te = test[TARGET].to_numpy(float)
    # Baselines (fallback a la mediana de OBR de train si faltan CRE y PRE)
    fb = float(train[TARGET].median())
    pred_lag = test["obr_lag_1"].fillna(test["CRE"]).fillna(test["PRE"]).fillna(fb).to_numpy(float)
    pred_cre = test["CRE"].fillna(test["PRE"]).fillna(fb).to_numpy(float)
    rows.append({**base, "modelo": "baseline_lag1", **Evaluator.compute_metrics(y_te, pred_lag)})
    rows.append({**base, "modelo": "baseline_cre", **Evaluator.compute_metrics(y_te, pred_cre)})

    # Modelos ML
    feat = NUM_COLS + cat_cols
    X_tr, y_tr = train[feat], train[TARGET]
    X_te = test[feat]
    best = (None, np.inf, None)
    for name in MODEL_SPECS:
        try:
            pipe = make_pipeline(name, cat_cols)
            pipe.fit(X_tr, y_tr)
            preds = pipe.predict(X_te)
            met = Evaluator.compute_metrics(y_te, preds)
            rows.append({**base, "modelo": name, **met})
            if met["mae"] < best[1]:
                best = (name, met["mae"], pipe)
        except Exception as exc:  # noqa: BLE001
            rows.append({**base, "modelo": name, "nota": f"error: {type(exc).__name__}"})

    if best[2] is not None:
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump(best[2], MODELS_DIR / f"{slug}__native_best_{best[0]}.joblib")

    cand = [r for r in rows if isinstance(r.get("mae"), (int, float)) and not np.isnan(r["mae"])]
    if cand:
        win = min(cand, key=lambda r: r["mae"])
        win["ganador"] = "★"
        win["bate_baseline"] = "sí" if win["modelo"] not in ("baseline_lag1", "baseline_cre") else "no"
    return rows


def main() -> None:
    print("[Paso 3b] Modelo independiente por CCAA en GRANO NATIVO...\n")
    all_rows: list[dict] = []
    for slug in CCAA_OBR:
        all_rows.extend(train_ccaa(slug))

    res = pd.DataFrame(all_rows)
    if "mae" in res.columns:
        res["MAE_M€"] = (res["mae"].astype(float) / 1e6).round(1)
    for c in ["mape", "r2"]:
        if c in res.columns:
            res[c] = res[c].astype(float).round(3)
    cols = [c for c in ["ccaa", "grano", "n_train", "n_test", "modelo", "MAE_M€",
                        "mape", "r2", "ganador", "bate_baseline", "nota"] if c in res.columns]
    res = res[cols]

    out = MODELS_DIR / "metrics_native_per_ccaa.csv"
    res.to_csv(out, index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 230, "display.max_rows", 120)
    print(res.fillna("").to_string(index=False))

    print("\n=== GANADOR POR CCAA (menor MAE, incluye baselines) ===")
    win = res[res.get("ganador") == "★"] if "ganador" in res.columns else res.iloc[0:0]
    for _, r in win.iterrows():
        print(f"  {r['ccaa']:<16} [{r['grano']:<12}] -> {r['modelo']:<14} MAE={r['MAE_M€']} M€ | ML bate baseline: {r['bate_baseline']}")
    n_ml = (win["bate_baseline"] == "sí").sum() if len(win) else 0
    print(f"\nEn {n_ml}/{len(win)} CCAA evaluables el ML supera al baseline.")
    print(f"\n[OK] Métricas -> {out}")


if __name__ == "__main__":
    main()
