#!/usr/bin/env python
"""
Paso 3c — Modelo predictivo INDEPENDIENTE por CCAA con TARGET en log1p.

Idéntico al Paso 3b (grano nativo, un modelo por CCAA, mismos features seguros
contra fuga y mismo split temporal) salvo que el objetivo OBR se transforma con
log1p y se invierte con expm1 vía TransformedTargetRegressor. El objetivo es
estabilizar la escala de euros (que abarca muchos órdenes de magnitud) y, sobre
todo, evitar que la regresión lineal (Ridge) se desestabilice.

Los baselines (obr_lag_1 y CRE) NO se transforman: se evalúan sobre la escala
original para que la comparación sea honesta.

Regenera además las 4 figuras del notebook 03 en reports/modelado/ y guarda las
métricas en data_lake/04_models/metrics_native_log_per_ccaa.csv.

Uso:
    python scripts/train_models_native_log.py
"""
from __future__ import annotations

import re
import sys
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import sklearn.base as skb
from sklearn.compose import ColumnTransformer, TransformedTargetRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from xgboost import XGBRegressor

warnings.filterwarnings("ignore")
sns.set_theme(style="whitegrid", palette="muted", font_scale=0.95)
plt.rcParams["figure.dpi"] = 110

ROOT = Path(__file__).resolve().parent.parent
FEATURES_DIR = ROOT / "data_lake" / "03_features"
MODELS_DIR = ROOT / "data_lake" / "04_models"
REPORTS_DIR = ROOT / "reports" / "modelado"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
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
    "ridge": Ridge(alpha=1.0),
    "random_forest": RandomForestRegressor(n_estimators=300, max_depth=6,
                                           random_state=42, n_jobs=-1),
    "xgboost": XGBRegressor(n_estimators=300, max_depth=4, learning_rate=0.05,
                            random_state=42, tree_method="hist"),
}
TEST_N_YEARS = 2


def load_ccaa(slug):
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


def metrics(y_true, y_pred):
    y_true = np.asarray(y_true, float)
    y_pred = np.asarray(y_pred, float)
    denom = np.where(np.abs(y_true) < 1e-6, np.nan, np.abs(y_true))
    return dict(
        mae=float(mean_absolute_error(y_true, y_pred)),
        rmse=float(np.sqrt(mean_squared_error(y_true, y_pred))),
        mape=float(np.nanmean(np.abs(y_true - y_pred) / denom)),
        r2=float(r2_score(y_true, y_pred)) if len(y_true) >= 2 else np.nan,
    )


def make_pipeline(model, cat_cols):
    """Pipeline (prep + est) envuelto para predecir en log1p e invertir con expm1."""
    num_pipe = Pipeline([("imp", SimpleImputer(strategy="median")),
                         ("sc", StandardScaler())])
    cat_pipe = Pipeline([("imp", SimpleImputer(strategy="most_frequent")),
                         ("ohe", OneHotEncoder(handle_unknown="ignore", sparse_output=False))])
    prep = ColumnTransformer([("num", num_pipe, NUM_COLS),
                              ("cat", cat_pipe, cat_cols)], remainder="drop")
    inner = Pipeline([("prep", prep), ("est", model)])
    return TransformedTargetRegressor(regressor=inner, func=np.log1p, inverse_func=np.expm1)


def main():
    print("[Paso 3c] Modelo independiente por CCAA — target log1p (grano nativo)\n")
    rows = []
    PRED = {}    # ccaa -> dict(y, preds, best, grano)
    IMPORT = {}  # ccaa -> {modelo: (feat_names, importances)}

    for slug in CCAA_OBR:
        d = load_ccaa(slug)
        nombre = CCAA_NAMES.get(slug, slug)
        if d.empty or TARGET not in d.columns:
            continue
        for c in ["PRE", "OBR", "CRE", "PAG"]:
            if c in d.columns:
                d = d[~(d[c].abs() > MAX_IMPORTE)]
        d = d[d[TARGET].notna() & (d[TARGET] > 0)].copy()
        if "ratio_cre_pre" not in d.columns and {"CRE", "PRE"} <= set(d.columns):
            d["ratio_cre_pre"] = d["CRE"] / d["PRE"].replace(0, np.nan)
        cat_cols = ["capitulo_id"] if ("capitulo_id" in d.columns and d["capitulo_id"].notna().any()) else []
        grano = "capítulo" if cat_cols else "entidad/CCAA"

        years = sorted(d["anio"].unique())
        test_years = set(years[-TEST_N_YEARS:])
        train = d[~d["anio"].isin(test_years)]
        test = d[d["anio"].isin(test_years)]
        base = dict(ccaa=nombre, grano=grano, n_train=len(train), n_test=len(test))
        if len(train) < 20 or len(test) < 5:
            rows.append({**base, "modelo": "—", "nota": "datos insuficientes"})
            continue

        y_te = test[TARGET].to_numpy(float)
        fb = float(train[TARGET].median())
        preds = {}
        preds["baseline_lag1"] = test["obr_lag_1"].fillna(test["CRE"]).fillna(test["PRE"]).fillna(fb).to_numpy(float)
        preds["baseline_cre"] = test["CRE"].fillna(test["PRE"]).fillna(fb).to_numpy(float)
        for name in ("baseline_lag1", "baseline_cre"):
            rows.append({**base, "modelo": name, **metrics(y_te, preds[name])})

        feat = NUM_COLS + cat_cols
        Xtr, ytr, Xte = train[feat], train[TARGET], test[feat]
        best = (None, np.inf)
        for name, model in MODEL_SPECS.items():
            ttr = make_pipeline(skb.clone(model), cat_cols)
            ttr.fit(Xtr, ytr)
            p = ttr.predict(Xte)
            preds[name] = p
            m = metrics(y_te, p)
            rows.append({**base, "modelo": name, **m})
            if m["mae"] < best[1]:
                best = (name, m["mae"])
            if name in ("random_forest", "xgboost"):
                try:
                    inner = ttr.regressor_
                    fn = inner.named_steps["prep"].get_feature_names_out()
                    IMPORT.setdefault(nombre, {})[name] = (fn, inner.named_steps["est"].feature_importances_)
                except Exception:
                    pass
        cand = {k: metrics(y_te, v)["mae"] for k, v in preds.items()}
        winner = min(cand, key=cand.get)
        PRED[nombre] = dict(y=y_te, preds=preds, best=winner, grano=grano)

    res = pd.DataFrame(rows)
    res["MAE_M€"] = (res["mae"] / 1e6).round(1)
    res["mape"] = res["mape"].round(3)
    res["r2"] = res["r2"].round(3)
    res["ganador"] = ""
    res["bate_baseline"] = ""
    for cc in res["ccaa"].unique():
        sub = res[(res["ccaa"] == cc) & res["mae"].notna()]
        if len(sub):
            idx = sub["mae"].idxmin()
            res.loc[idx, "ganador"] = "★"
            res.loc[idx, "bate_baseline"] = "sí" if res.loc[idx, "modelo"] not in ("baseline_lag1", "baseline_cre") else "no"

    out = MODELS_DIR / "metrics_native_log_per_ccaa.csv"
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    disp_cols = ["ccaa", "grano", "n_train", "n_test", "modelo", "MAE_M€", "mape", "r2", "ganador", "bate_baseline"]
    res[disp_cols].to_csv(out, index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 230, "display.max_rows", 120)
    print(res[disp_cols].fillna("").to_string(index=False))

    win = res[res["ganador"] == "★"][["ccaa", "grano", "n_train", "n_test", "modelo", "MAE_M€", "bate_baseline"]]
    n_ml = (win["bate_baseline"] == "sí").sum()
    print(f"\n=== GANADOR POR CCAA (target log1p) ===")
    print(win.reset_index(drop=True).to_string(index=False))
    print(f"\nEl ML supera al baseline en {n_ml}/{len(win)} CCAA evaluables.")

    # ── Figuras (mismas 4 del notebook 03, ahora con resultados log1p) ──
    # 4.1 heatmap
    piv = res[res["mae"].notna()].pivot_table(index="ccaa", columns="modelo", values="MAE_M€")
    order_m = ["baseline_lag1", "baseline_cre", "ridge", "random_forest", "xgboost"]
    piv = piv[[c for c in order_m if c in piv.columns]]
    fig, ax = plt.subplots(figsize=(13, 6))
    sns.heatmap(piv, annot=True, fmt=".0f", cmap="RdYlGn_r",
                cbar_kws={"label": "MAE (M€)"}, linewidths=.4, annot_kws={"size": 8})
    ax.set_title("MAE por CCAA y modelo (M€) — target log1p — verde = mejor", weight="bold")
    ax.set_xlabel(""); ax.set_ylabel("")
    fig.tight_layout(); fig.savefig(REPORTS_DIR / "mae_heatmap.png", bbox_inches="tight", dpi=110); plt.close(fig)

    # 4.2 baseline vs ML
    comp = []
    for cc in res["ccaa"].unique():
        sub = res[(res["ccaa"] == cc) & res["mae"].notna()]
        if sub.empty:
            continue
        bl = sub[sub["modelo"].str.startswith("baseline")]["MAE_M€"].min()
        ml = sub[~sub["modelo"].str.startswith("baseline")]["MAE_M€"].min()
        comp.append((cc, bl, ml))
    c = pd.DataFrame(comp, columns=["ccaa", "MejorBaseline", "MejorML"]).sort_values("MejorBaseline")
    x = np.arange(len(c)); w = 0.38
    fig, ax = plt.subplots(figsize=(13, 6))
    ax.bar(x - w / 2, c["MejorBaseline"], w, label="Mejor baseline", color="#8c8c8c")
    ax.bar(x + w / 2, c["MejorML"], w, label="Mejor ML (log1p)", color="#1f77b4")
    ax.set_yscale("log"); ax.set_ylabel("MAE (M€, escala log)")
    ax.set_xticks(x); ax.set_xticklabels(c["ccaa"], rotation=30, ha="right")
    ax.set_title("Mejor baseline vs mejor modelo ML por CCAA (target log1p)", weight="bold")
    for cc_i, (_, r_) in enumerate(c.iterrows()):
        if r_["MejorML"] < r_["MejorBaseline"]:
            ax.text(cc_i, max(r_["MejorML"], r_["MejorBaseline"]) * 1.15, "✓ML",
                    ha="center", color="#1f77b4", fontsize=9, weight="bold")
    ax.legend(); fig.tight_layout()
    fig.savefig(REPORTS_DIR / "baseline_vs_ml.png", bbox_inches="tight", dpi=110); plt.close(fig)

    # 4.3 predicho vs real
    ccaas = [cc for cc in PRED]
    n = len(ccaas); ncols = 3; nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(15, 4.3 * nrows))
    axes = np.atleast_1d(axes).ravel()
    for ax, cc in zip(axes, ccaas):
        info = PRED[cc]; y = info["y"]; p = info["preds"][info["best"]]
        ax.scatter(y / 1e6, p / 1e6, s=18, alpha=0.5, color="#1f77b4")
        lim = [min(y.min(), p.min()) / 1e6, max(y.max(), p.max()) / 1e6]
        ax.plot(lim, lim, "--", color="#c44e52", lw=1.2)
        ax.set_title(f"{cc}  (mejor: {info['best']})", fontsize=10)
        ax.set_xlabel("OBR real (M€)"); ax.set_ylabel("OBR predicho (M€)")
        try:
            ax.set_xscale("log"); ax.set_yscale("log")
        except Exception:
            pass
    for ax in axes[n:]:
        ax.set_visible(False)
    fig.suptitle("Predicho vs. real por CCAA (target log1p) — línea roja = predicción perfecta",
                 y=1.005, weight="bold")
    fig.tight_layout(); fig.savefig(REPORTS_DIR / "pred_vs_real.png", bbox_inches="tight", dpi=110); plt.close(fig)

    # 4.4 importancias
    tree_winners = {cc: res[(res.ccaa == cc) & (res.ganador == '★')]['modelo'].iloc[0]
                    for cc in res.ccaa.unique()
                    if len(res[(res.ccaa == cc) & (res.ganador == '★')]) and
                    res[(res.ccaa == cc) & (res.ganador == '★')]['modelo'].iloc[0] in ('random_forest', 'xgboost')}
    if tree_winners:
        fig, axes = plt.subplots(1, len(tree_winners), figsize=(6 * len(tree_winners), 4.5), squeeze=False)
        axes = axes.ravel()
        for ax, (cc, mdl) in zip(axes, tree_winners.items()):
            fn, imp = IMPORT[cc][mdl]
            s = pd.Series(imp, index=[f.replace('num__', '').replace('cat__', '') for f in fn]).sort_values().tail(10)
            ax.barh(s.index, s.values, color="#2ca02c", alpha=0.85)
            ax.set_title(f"{cc} — {mdl}", fontsize=11); ax.set_xlabel("Importancia")
        fig.suptitle("Importancia de variables (árboles ganadores, target log1p)", y=1.02, weight="bold")
        fig.tight_layout(); fig.savefig(REPORTS_DIR / "importancias.png", bbox_inches="tight", dpi=110); plt.close(fig)
        print(f"\n[figuras] árboles ganadores: {tree_winners}")
    else:
        print("\n[figuras] Ninguna CCAA tiene un árbol como ganador global; importancias.png no se regenera.")

    print(f"\n[OK] Métricas -> {out}")
    print(f"[OK] Figuras   -> {REPORTS_DIR}")


if __name__ == "__main__":
    main()
