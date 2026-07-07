#!/usr/bin/env python
"""
Paso 2 — Dataset de modelado homogéneo (CCAA-capítulo-año).

Homogeneiza la granularidad heterogénea del feature store a un grano común
**CCAA-capítulo-año** y define el split temporal train/test/holdout.

Decisiones de diseño (ver notebook 02 y análisis de granularidad):
  - Solo entran las 7 CCAA con clasificación por CAPÍTULO económico:
    aragon, asturias, cataluna, madrid, pais-vasco, castilla-y-leon, nacional.
    (Aragón y AGE se agregan sobre grupo_funcional; el resto ya está a capítulo.)
  - Se EXCLUYEN del modelo predictivo (grano incompatible / solo descriptivo):
    canarias (grano entidad, sin capítulo), illes-balears y castilla-la-mancha
    (sin clasificación), y las de solo-PRE (murcia, galicia, c.valenciana...).
  - Objetivo (target): OBR (obligaciones reconocidas de cierre del ejercicio).
  - Features SEGURAS contra fuga (leakage): PRE y CRE (conocidas antes del cierre),
    ratio_cre_pre, lags de OBR (t-1..t-3) y media móvil de OBR desplazada.
    Se EXCLUYEN ejecutado_pct y brecha_pct porque derivan de OBR (fuga).

Uso:
    python scripts/build_model_dataset.py
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
FEATURES_DIR = ROOT / "data_lake" / "03_features"
OUT_DIR = ROOT / "data_lake" / "04_models" / "dataset"
MAX_IMPORTE = 1e11

# CCAA con clasificación por capítulo económico → aptas para el grano común.
CAP_CCAA = [
    "aragon", "asturias", "cataluna", "madrid",
    "pais-vasco", "castilla-y-leon", "nacional",
]
CCAA_NAMES = {
    "aragon": "Aragón", "asturias": "Asturias", "cataluna": "Cataluña",
    "madrid": "Madrid", "pais-vasco": "País Vasco",
    "castilla-y-leon": "Castilla y León", "nacional": "AGE (nacional)",
}

# Split temporal (predicción del cierre anual).
TRAIN_MAX_YEAR = 2022          # train: anio <= 2022
TEST_YEARS = (2023, 2024)      # test: últimos años completos
# holdout: anio >= 2025 (ejercicios en curso / incompletos)


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
    df = pd.concat(parts, ignore_index=True)
    df["ccaa_slug"] = slug
    return df


def build() -> pd.DataFrame:
    frames = []
    for slug in CAP_CCAA:
        d = load_ccaa(slug)
        if d.empty:
            print(f"  [SKIP] sin feature store: {slug}")
            continue
        for c in ["PRE", "OBR", "CRE", "PAG"]:
            if c in d.columns:
                d = d[~(d[c].abs() > MAX_IMPORTE)]
        d = d[d["capitulo_id"].notna()]
        frames.append(d)
    raw = pd.concat(frames, ignore_index=True)

    # 1. Agregar al grano común CCAA-capítulo-año
    g = raw.groupby(["ccaa_slug", "capitulo_id", "anio"], as_index=False).agg(
        OBR=("OBR", "sum"), PRE=("PRE", "sum"),
        CRE=("CRE", "sum"), PAG=("PAG", "sum"),
    )
    g["capitulo_id"] = g["capitulo_id"].astype(int)

    # 2. Ratios seguros como features (no derivan de OBR)
    g["ratio_cre_pre"] = g["CRE"] / g["PRE"].replace(0, np.nan)

    # 3. Ratios derivados de OBR (solo descriptivos / diagnóstico, NO features)
    g["brecha_pct"] = (g["PRE"] - g["OBR"]) / g["PRE"].replace(0, np.nan)
    g["ejecutado_pct"] = g["OBR"] / g["CRE"].replace(0, np.nan)

    # 4. Lags y media móvil de OBR, recalculados al grano CCAA-capítulo.
    #    shift(1) antes del rolling → no incluye el año objetivo (sin leakage).
    g = g.sort_values(["ccaa_slug", "capitulo_id", "anio"])
    grp = g.groupby(["ccaa_slug", "capitulo_id"], group_keys=False)["OBR"]
    for lag in (1, 2, 3):
        g[f"obr_lag_{lag}"] = grp.shift(lag)
    g["obr_roll3_mean"] = grp.transform(
        lambda s: s.shift(1).rolling(3, min_periods=1).mean()
    )

    # 5. Split temporal
    def split_of(y: int) -> str:
        if y <= TRAIN_MAX_YEAR:
            return "train"
        if y in TEST_YEARS:
            return "test"
        return "holdout"

    g["split"] = g["anio"].apply(split_of)
    g["ccaa_nombre"] = g["ccaa_slug"].map(CCAA_NAMES)
    return g


FEATURES = [
    "PRE", "CRE", "ratio_cre_pre",
    "obr_lag_1", "obr_lag_2", "obr_lag_3", "obr_roll3_mean",
    "capitulo_id", "ccaa_slug", "anio",
]
TARGET = "OBR"


def main() -> None:
    print("[Paso 2] Construyendo dataset de modelado CCAA-capítulo-año...")
    g = build()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "model_dataset.parquet"
    g.to_parquet(out, index=False)

    # ── Diagnóstico ──
    print(f"\n[OK] Dataset -> {out}")
    print(f"     Filas: {len(g):,} | columnas: {g.shape[1]}")
    print(f"     Con target OBR>0: {(g['OBR'] > 0).sum():,} | con obr_lag_1: {g['obr_lag_1'].notna().sum():,}")

    print("\nReparto por split (solo filas con target OBR válido):")
    valid = g[g["OBR"].notna() & (g["OBR"] > 0)]
    print(valid.groupby("split").size().reindex(["train", "test", "holdout"]).to_string())

    print("\nFilas por CCAA y split:")
    piv = valid.pivot_table(index="ccaa_nombre", columns="split",
                            values="OBR", aggfunc="size", fill_value=0)
    piv = piv.reindex(columns=["train", "test", "holdout"], fill_value=0)
    print(piv.to_string())

    print(f"\nFeatures ({len(FEATURES)}): {FEATURES}")
    print(f"Target: {TARGET}")
    print("\nExcluidas del modelo predictivo (grano incompatible / solo descriptivo):")
    print("  canarias (entidad), illes-balears, castilla-la-mancha (sin clasificación),")
    print("  murcia, galicia, comunidad-valenciana, andalucia (solo PRE).")


if __name__ == "__main__":
    main()
