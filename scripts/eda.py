#!/usr/bin/env python
"""
Análisis Exploratorio de Datos (EDA) — Ejecución Presupuestaria Entidades Locales España
==========================================================================================
Genera un informe HTML autocontenido con gráficas embebidas + Excel de estadísticas.

Grupos analizados:
  Núcleo (PRE+OBR): aragon, asturias, cataluna, madrid, pais-vasco,
                    illes-balears, castilla-la-mancha, castilla-y-leon, nacional
  Descriptivo (PRE): murcia, galicia, comunidad-valenciana

Uso:
    python scripts/eda.py
    python scripts/eda.py --output reports/eda_v2
    python scripts/eda.py --desde 2015
"""
from __future__ import annotations

import argparse
import base64
import io
import sqlite3
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns
from scipy import stats

# ─────────────────────────────── CONFIG ──────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data_lake" / "catalog.db"
FEATURES_DIR = ROOT / "data_lake" / "03_features"

CCAA_NUCLEO = [
    "aragon", "asturias", "cataluna", "madrid", "pais-vasco",
    "illes-balears", "castilla-la-mancha", "castilla-y-leon", "nacional",
]
CCAA_DESCRIPTIVO = ["murcia", "galicia", "comunidad-valenciana"]
ALL_CCAA = CCAA_NUCLEO + CCAA_DESCRIPTIVO

CCAA_NAMES: dict[str, str] = {
    "aragon": "Aragón",
    "asturias": "Asturias",
    "cataluna": "Cataluña",
    "madrid": "Madrid",
    "pais-vasco": "País Vasco",
    "illes-balears": "Illes Balears",
    "castilla-la-mancha": "C.-La Mancha",
    "castilla-y-leon": "Castilla y León",
    "nacional": "AGE",
    "murcia": "Murcia",
    "galicia": "Galicia",
    "comunidad-valenciana": "C. Valenciana",
    "cantabria": "Cantabria",
    "andalucia": "Andalucía",
}

CAPITULO_NAMES: dict[int, str] = {
    1: "1-Personal",
    2: "2-Bienes/Servicios",
    3: "3-G.Financieros",
    4: "4-Transf.corrientes",
    5: "5-Contingencia",
    6: "6-Inversiones",
    7: "7-Transf.capital",
    8: "8-Act.financieros",
    9: "9-Pas.financieros",
}

FASE_COLORS = {
    "PRE": "#1f77b4",
    "CRE": "#2ca02c",
    "ARN": "#98df8a",
    "DIS": "#ffbb78",
    "OBR": "#d62728",
    "PAG": "#9467bd",
}

sns.set_theme(style="whitegrid", palette="muted", font_scale=0.9)
plt.rcParams["figure.dpi"] = 100

# ─────────────────────────────── HELPERS ─────────────────────────────────────


def ccaa_label(slug: str) -> str:
    return CCAA_NAMES.get(slug, slug)


def cap_label(cid) -> str:
    try:
        return CAPITULO_NAMES.get(int(cid), f"Cap.{int(cid)}")
    except (TypeError, ValueError):
        return "?"


def fmt_meur(x, _=None) -> str:
    if abs(x) >= 1_000:
        return f"{x/1_000:.0f}MM€"
    return f"{x:.0f}M€"


def fig_to_b64(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=100)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


# ─────────────────────────────── DATA LOADING ────────────────────────────────


_MAX_IMPORTE_ROW = 1e11  # 100,000M EUR — umbral para filtrar filas con valores imposibles


def load_fact_agg(conn: sqlite3.Connection, slugs: list[str]) -> pd.DataFrame:
    """Suma de importes por ccaa_slug, anio, fase.
    Filtra filas con importe_eur fuera de un rango plausible (outliers de parseo).
    """
    ph = ",".join("?" * len(slugs))
    sql = f"""
        SELECT ccaa_slug, anio, fase,
               COUNT(*) AS n_hechos,
               SUM(importe_eur) AS importe_total
        FROM fact_ejecucion_presupuestaria
        WHERE ccaa_slug IN ({ph})
          AND importe_eur BETWEEN -{_MAX_IMPORTE_ROW} AND {_MAX_IMPORTE_ROW}
        GROUP BY ccaa_slug, anio, fase
    """
    df = pd.read_sql(sql, conn, params=slugs)
    df["anio"] = df["anio"].astype(int)
    return df


def load_cap_agg(conn: sqlite3.Connection, slugs: list[str]) -> pd.DataFrame:
    """Suma por ccaa_slug, capitulo_id, anio, fase."""
    ph = ",".join("?" * len(slugs))
    sql = f"""
        SELECT ccaa_slug, capitulo_id, anio, fase,
               SUM(importe_eur) AS importe_total,
               COUNT(*) AS n_hechos
        FROM fact_ejecucion_presupuestaria
        WHERE ccaa_slug IN ({ph}) AND capitulo_id IS NOT NULL
          AND importe_eur BETWEEN -{_MAX_IMPORTE_ROW} AND {_MAX_IMPORTE_ROW}
        GROUP BY ccaa_slug, capitulo_id, anio, fase
    """
    df = pd.read_sql(sql, conn, params=slugs)
    df["anio"] = df["anio"].astype(int)
    df["capitulo_id"] = pd.to_numeric(df["capitulo_id"], errors="coerce")
    return df.dropna(subset=["capitulo_id"])


def load_cobertura(conn: sqlite3.Connection, slugs: list[str]) -> pd.DataFrame:
    ph = ",".join("?" * len(slugs))
    sql = f"""
        SELECT ccaa_slug,
               COUNT(*) AS hechos_total,
               MIN(anio) AS anio_min,
               MAX(anio) AS anio_max,
               COUNT(DISTINCT anio) AS n_anios,
               COUNT(DISTINCT entidad_id) AS n_entidades,
               ROUND(SUM(importe_eur) / 1e6, 1) AS importe_meur
        FROM fact_ejecucion_presupuestaria
        WHERE ccaa_slug IN ({ph})
        GROUP BY ccaa_slug
        ORDER BY hechos_total DESC
    """
    df = pd.read_sql(sql, conn, params=slugs)
    # Fases por separado (GROUP_CONCAT sin ORDER BY es portable)
    sql_fases = f"""
        SELECT ccaa_slug, GROUP_CONCAT(DISTINCT fase) AS fases
        FROM fact_ejecucion_presupuestaria
        WHERE ccaa_slug IN ({ph})
        GROUP BY ccaa_slug
    """
    fases_df = pd.read_sql(sql_fases, conn, params=slugs)
    df = df.merge(fases_df, on="ccaa_slug", how="left")
    df["nombre"] = df["ccaa_slug"].map(ccaa_label)
    df["grupo"] = df["ccaa_slug"].apply(
        lambda s: "Núcleo (PRE+OBR)" if s in CCAA_NUCLEO else "Descriptivo (solo PRE)"
    )
    return df


def load_features(slugs: list[str]) -> pd.DataFrame:
    import pyarrow.dataset as ds

    frames: list[pd.DataFrame] = []
    for slug in slugs:
        feat_dir = FEATURES_DIR / slug / "features"
        if not feat_dir.exists() or not any(feat_dir.rglob("*.parquet")):
            print(f"  [SKIP] Sin feature store: {slug}")
            continue
        try:
            d = ds.dataset(feat_dir, format="parquet", partitioning="hive")
            df = d.to_table().to_pandas()
            df["ccaa_slug"] = slug
            frames.append(df)
        except Exception as exc:
            print(f"  [WARN] Error cargando features de {slug}: {exc}")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ─────────────────────────────── CHARTS ──────────────────────────────────────


def chart_hechos_ccaa(cov_df: pd.DataFrame) -> str:
    df = cov_df.sort_values("hechos_total")
    colors = [
        "#c62828" if g == "Núcleo (PRE+OBR)" else "#1565c0"
        for g in df["grupo"]
    ]
    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.barh(df["nombre"], df["hechos_total"] / 1e6, color=colors)
    ax.set_xlabel("Millones de hechos")
    ax.set_title("Total hechos curados por CCAA (02_curated)")
    for bar, val in zip(bars, df["hechos_total"]):
        ax.text(
            bar.get_width() + 0.02, bar.get_y() + bar.get_height() / 2,
            f"{val:,.0f}", va="center", fontsize=8,
        )
    from matplotlib.patches import Patch
    ax.legend(
        handles=[
            Patch(color="#c62828", label="Núcleo (PRE+OBR)"),
            Patch(color="#1565c0", label="Descriptivo (solo PRE)"),
        ],
        loc="lower right",
    )
    fig.tight_layout()
    return fig_to_b64(fig)


def chart_cobertura_heatmap(fact_agg: pd.DataFrame) -> str:
    pivot = (
        fact_agg.groupby(["ccaa_slug", "anio"])["n_hechos"]
        .sum()
        .unstack(fill_value=0)
    )
    pivot = pivot.loc[:, (pivot > 0).any()]
    pivot.index = [ccaa_label(s) for s in pivot.index]

    fig, ax = plt.subplots(figsize=(18, 5))
    sns.heatmap(
        np.log1p(pivot),
        ax=ax,
        cmap="YlOrRd",
        linewidths=0.3,
        annot=False,
        cbar_kws={"label": "log(1 + hechos)"},
    )
    ax.set_title("Cobertura temporal por CCAA (intensidad = volumen de hechos)")
    ax.set_xlabel("Año")
    ax.set_ylabel("")
    fig.tight_layout()
    return fig_to_b64(fig)


def chart_evolucion_pre_obr(fact_agg: pd.DataFrame, desde: int) -> str:
    df = fact_agg[
        fact_agg["ccaa_slug"].isin(CCAA_NUCLEO)
        & fact_agg["fase"].isin(["PRE", "OBR"])
        & (fact_agg["anio"] >= desde)
    ]
    agg = (
        df.groupby(["anio", "fase"])["importe_total"]
        .sum()
        .unstack(fill_value=0)
        .reset_index()
    )

    fig, ax = plt.subplots(figsize=(12, 5))
    if "PRE" in agg.columns:
        ax.plot(
            agg["anio"], agg["PRE"] / 1e9, "o-",
            color=FASE_COLORS["PRE"], label="Presupuesto (PRE)", linewidth=2,
        )
    if "OBR" in agg.columns:
        ax.fill_between(
            agg["anio"], agg["OBR"] / 1e9,
            alpha=0.25, color=FASE_COLORS["OBR"],
        )
        ax.plot(
            agg["anio"], agg["OBR"] / 1e9, "s-",
            color=FASE_COLORS["OBR"], label="Obligaciones (OBR)", linewidth=2,
        )
    ax.set_xlabel("Año")
    ax.set_ylabel("Importe total (miles de M€)")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}MM€"))
    ax.set_title(f"Evolución PRE vs OBR — 9 CCAAs núcleo ({desde}–2025)")
    ax.legend()
    ax.set_xticks(sorted(agg["anio"].unique()))
    fig.tight_layout()
    return fig_to_b64(fig)


def chart_brecha_ccaa(fact_agg: pd.DataFrame, desde: int) -> str:
    df = (
        fact_agg[
            fact_agg["ccaa_slug"].isin(CCAA_NUCLEO)
            & fact_agg["fase"].isin(["PRE", "OBR"])
            & (fact_agg["anio"] >= desde)
        ]
        .groupby(["ccaa_slug", "fase"])["importe_total"]
        .sum()
        .unstack(fill_value=0)
    )
    if "PRE" not in df.columns or "OBR" not in df.columns:
        return ""

    df["brecha"] = df["PRE"] - df["OBR"]
    df["brecha_pct"] = df["brecha"] / df["PRE"].replace(0, np.nan) * 100
    df = df.sort_values("brecha_pct")
    df.index = [ccaa_label(s) for s in df.index]

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    colors = ["#c62828" if v > 0 else "#1b5e20" for v in df["brecha"]]

    axes[0].barh(df.index, df["brecha"] / 1e9, color=colors)
    axes[0].axvline(0, color="black", lw=0.8)
    axes[0].set_xlabel("Brecha PRE−OBR (miles de M€)")
    axes[0].set_title(f"Brecha absoluta acumulada ({desde}–2025)")
    axes[0].xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}MM€"))

    axes[1].barh(df.index, df["brecha_pct"], color=colors)
    axes[1].axvline(0, color="black", lw=0.8)
    axes[1].set_xlabel("Brecha (% sobre PRE)")
    axes[1].set_title(f"Brecha relativa ({desde}–2025)")
    axes[1].xaxis.set_major_formatter(mticker.PercentFormatter())

    fig.tight_layout()
    return fig_to_b64(fig)


def chart_tasa_ejecucion(fact_agg: pd.DataFrame, desde: int) -> str:
    df = fact_agg[
        fact_agg["ccaa_slug"].isin(CCAA_NUCLEO)
        & fact_agg["fase"].isin(["PRE", "OBR", "CRE", "ARN"])
        & (fact_agg["anio"] >= desde)
    ].copy()
    df["fase"] = df["fase"].replace({"ARN": "CRE"})

    agg = (
        df.groupby(["ccaa_slug", "anio", "fase"])["importe_total"]
        .sum()
        .unstack(fill_value=np.nan)
        .reset_index()
    )
    if "OBR" not in agg.columns or "PRE" not in agg.columns:
        return ""
    agg["tasa"] = (agg["OBR"] / agg["PRE"].replace(0, np.nan)) * 100

    fig, ax = plt.subplots(figsize=(12, 5))
    colors = plt.cm.tab10.colors
    for i, slug in enumerate(CCAA_NUCLEO):
        sub = agg[agg["ccaa_slug"] == slug].sort_values("anio")
        if sub.empty or sub["tasa"].isna().all():
            continue
        ax.plot(
            sub["anio"], sub["tasa"], "o-",
            label=ccaa_label(slug), color=colors[i % len(colors)],
            linewidth=1.5, markersize=4,
        )
    ax.axhline(100, color="black", lw=0.8, ls="--", alpha=0.5, label="100%")
    ax.yaxis.set_major_formatter(mticker.PercentFormatter())
    ax.set_xlabel("Año")
    ax.set_ylabel("OBR / PRE (%)")
    ax.set_title(f"Tasa de ejecución (OBR/PRE) por CCAA ({desde}–2025)")
    ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left", fontsize=8)
    ax.set_xticks(sorted(agg["anio"].unique()))
    fig.tight_layout()
    return fig_to_b64(fig)


def chart_por_capitulo(cap_agg: pd.DataFrame, desde: int) -> str:
    df = cap_agg[
        cap_agg["ccaa_slug"].isin(CCAA_NUCLEO)
        & cap_agg["fase"].isin(["PRE", "OBR"])
        & (cap_agg["anio"] >= desde)
    ].copy()
    df["cap_label"] = df["capitulo_id"].map(cap_label)

    agg = (
        df.groupby(["cap_label", "fase"])["importe_total"]
        .sum()
        .unstack(fill_value=0)
    )
    orden = [cap_label(i) for i in range(1, 10) if cap_label(i) in agg.index]
    agg = agg.reindex([r for r in orden if r in agg.index])

    x = np.arange(len(agg))
    w = 0.35
    fig, ax = plt.subplots(figsize=(14, 6))
    if "PRE" in agg.columns:
        ax.bar(x - w / 2, agg["PRE"] / 1e9, w, label="PRE", color=FASE_COLORS["PRE"], alpha=0.85)
    if "OBR" in agg.columns:
        ax.bar(x + w / 2, agg["OBR"] / 1e9, w, label="OBR", color=FASE_COLORS["OBR"], alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(agg.index, rotation=30, ha="right")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}MM€"))
    ax.set_ylabel("Importe (miles de M€)")
    ax.set_title(f"PRE vs OBR por capítulo económico — núcleo ({desde}–2025)")
    ax.legend()
    fig.tight_layout()
    return fig_to_b64(fig)


def chart_heatmap_capitulo_anio(cap_agg: pd.DataFrame, desde: int) -> str:
    df = cap_agg[
        cap_agg["ccaa_slug"].isin(CCAA_NUCLEO)
        & cap_agg["fase"].isin(["PRE", "OBR"])
        & (cap_agg["anio"] >= desde)
    ].copy()
    df["cap_label"] = df["capitulo_id"].map(cap_label)

    pre = df[df["fase"] == "PRE"].groupby(["cap_label", "anio"])["importe_total"].sum()
    obr = df[df["fase"] == "OBR"].groupby(["cap_label", "anio"])["importe_total"].sum()
    ratio = (obr / pre * 100).unstack(fill_value=np.nan)

    orden = [cap_label(i) for i in range(1, 10)]
    ratio = ratio.reindex([r for r in orden if r in ratio.index])

    fig, ax = plt.subplots(figsize=(14, 6))
    sns.heatmap(
        ratio,
        ax=ax,
        cmap="RdYlGn",
        center=100,
        vmin=50,
        vmax=150,
        annot=True,
        fmt=".0f",
        linewidths=0.3,
        cbar_kws={"label": "OBR/PRE (%)"},
    )
    ax.set_title(f"Tasa de ejecución OBR/PRE por capítulo y año — núcleo ({desde}–2025)")
    ax.set_xlabel("Año")
    ax.set_ylabel("")
    fig.tight_layout()
    return fig_to_b64(fig)


def chart_distribucion_brecha(feat_df: pd.DataFrame) -> str:
    if "brecha_pct" not in feat_df.columns:
        return ""

    df = feat_df[
        feat_df["ccaa_slug"].isin(CCAA_NUCLEO) & feat_df["brecha_pct"].notna()
    ].copy()
    df["nombre"] = df["ccaa_slug"].map(ccaa_label)
    df["bp_clip"] = df["brecha_pct"].clip(-2, 2)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    axes[0].hist(df["bp_clip"], bins=80, color=FASE_COLORS["OBR"], alpha=0.7, edgecolor="white")
    axes[0].axvline(0, color="black", lw=1.2, ls="--")
    axes[0].xaxis.set_major_formatter(mticker.PercentFormatter(xmax=1))
    axes[0].set_xlabel("brecha_pct [(PRE−OBR)/PRE], recortado ±200%")
    axes[0].set_ylabel("Frecuencia")
    axes[0].set_title("Distribución global de brecha presupuestaria")

    order = df.groupby("nombre")["bp_clip"].median().sort_values().index.tolist()
    data_by_ccaa = [df.loc[df["nombre"] == n, "bp_clip"].dropna().values for n in order]
    axes[1].boxplot(
        data_by_ccaa, vert=False, tick_labels=order,
        flierprops=dict(marker=".", markersize=2, alpha=0.3),
    )
    axes[1].axvline(0, color="black", lw=1.2, ls="--")
    axes[1].xaxis.set_major_formatter(mticker.PercentFormatter(xmax=1))
    axes[1].set_xlabel("brecha_pct [recortado ±200%]")
    axes[1].set_title("Brecha por CCAA (mediana + IQR)")

    fig.suptitle("Brecha presupuestaria (PRE−OBR)/PRE — CCAAs núcleo", y=1.01)
    fig.tight_layout()
    return fig_to_b64(fig)


def chart_ejecutado_por_capitulo(feat_df: pd.DataFrame) -> str:
    if "ejecutado_pct" not in feat_df.columns:
        return ""

    df = feat_df[
        feat_df["ccaa_slug"].isin(CCAA_NUCLEO)
        & feat_df["ejecutado_pct"].notna()
        & feat_df["capitulo_id"].notna()
    ].copy()
    df["cap_label"] = df["capitulo_id"].map(cap_label)
    df["ep_clip"] = df["ejecutado_pct"].clip(0, 2)

    order = [cap_label(i) for i in range(1, 10) if cap_label(i) in df["cap_label"].unique()]
    data_by_cap = [df.loc[df["cap_label"] == c, "ep_clip"].dropna().values for c in order]

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.boxplot(
        data_by_cap, vert=False, tick_labels=order,
        flierprops=dict(marker=".", markersize=2, alpha=0.3),
    )
    ax.axvline(1.0, color="red", lw=1.2, ls="--", label="100% ejecución")
    ax.xaxis.set_major_formatter(mticker.PercentFormatter(xmax=1))
    ax.set_xlabel("OBR / CRE [recortado 0–200%]")
    ax.set_title("Tasa de ejecución (OBR/CRE) por capítulo económico — núcleo")
    ax.legend(loc="lower right")
    fig.tight_layout()
    return fig_to_b64(fig)


def chart_correlacion(feat_df: pd.DataFrame) -> str:
    cols = [
        c for c in [
            "PRE", "OBR", "CRE", "brecha_eur", "brecha_pct",
            "ejecutado_pct", "pago_pct", "ratio_cre_pre",
            "obr_lag_1", "obr_lag_2", "obr_lag_3", "obr_lag_4",
            "obr_rolling4_mean", "obr_rolling4_std",
        ]
        if c in feat_df.columns
    ]
    if len(cols) < 3:
        return ""

    # Clip extremos para que la correlación no esté dominada por outliers
    sample = feat_df[cols].dropna(how="all")
    for c in ["PRE", "OBR", "CRE", "brecha_eur", "obr_lag_1", "obr_rolling4_mean"]:
        if c in sample.columns:
            q1, q99 = sample[c].quantile([0.01, 0.99])
            sample[c] = sample[c].clip(q1, q99)

    corr = sample.corr()
    mask = np.triu(np.ones_like(corr, dtype=bool))

    fig, ax = plt.subplots(figsize=(12, 10))
    sns.heatmap(
        corr,
        ax=ax,
        mask=mask,
        cmap="coolwarm",
        center=0,
        vmin=-1,
        vmax=1,
        annot=True,
        fmt=".2f",
        linewidths=0.3,
        square=True,
        cbar_kws={"label": "Pearson r"},
    )
    ax.set_title("Matriz de correlación — features ML (núcleo, valores extremos recortados)")
    fig.tight_layout()
    return fig_to_b64(fig)


def chart_descriptivo_evolucion(fact_agg: pd.DataFrame, desde: int) -> str:
    df = fact_agg[
        fact_agg["ccaa_slug"].isin(CCAA_DESCRIPTIVO)
        & (fact_agg["fase"] == "PRE")
        & (fact_agg["anio"] >= desde)
    ].copy()

    fig, ax = plt.subplots(figsize=(10, 4))
    palette = ["#e65100", "#006064", "#558b2f"]
    for i, slug in enumerate(CCAA_DESCRIPTIVO):
        sub = df[df["ccaa_slug"] == slug].sort_values("anio")
        if sub.empty:
            continue
        ax.plot(
            sub["anio"], sub["importe_total"] / 1e6, "o-",
            label=ccaa_label(slug), color=palette[i], linewidth=2,
        )
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}M€"))
    ax.set_xlabel("Año")
    ax.set_ylabel("Presupuesto PRE (M€)")
    ax.set_title(f"Evolución presupuesto inicial (PRE) — CCAAs descriptivas ({desde}–2025)")
    ax.legend()
    ax.set_xticks(sorted(df["anio"].unique()))
    fig.tight_layout()
    return fig_to_b64(fig)


def chart_descriptivo_capitulo(cap_agg: pd.DataFrame, desde: int) -> str:
    df = cap_agg[
        cap_agg["ccaa_slug"].isin(CCAA_DESCRIPTIVO)
        & (cap_agg["fase"] == "PRE")
        & (cap_agg["anio"] >= desde)
    ].copy()
    if df.empty:
        return ""
    df["nombre"] = df["ccaa_slug"].map(ccaa_label)
    df["cap_label"] = df["capitulo_id"].map(cap_label)

    pivot = df.groupby(["nombre", "cap_label"])["importe_total"].sum().unstack(fill_value=0)

    fig, ax = plt.subplots(figsize=(12, 5))
    pivot.T.plot(kind="bar", ax=ax, alpha=0.85)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1e6:.0f}M€"))
    ax.set_xlabel("Capítulo económico")
    ax.set_ylabel("Importe PRE (M€)")
    ax.set_title(f"Distribución PRE por capítulo — CCAAs descriptivas ({desde}–2025)")
    ax.set_xticklabels(ax.get_xticklabels(), rotation=30, ha="right")
    ax.legend(title="CCAA")
    fig.tight_layout()
    return fig_to_b64(fig)


# ──────────────── SANEO Y CALIDAD DE DATOS (R1) ──────────────────────────────

_FEAT_IMPORTE_COLS = ["PRE", "OBR", "CRE", "PAG"]


def sanitize_features(feat_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Elimina filas con importes físicamente imposibles (|x| > 1e11 €).

    Mismo umbral que el filtro SQL de la tabla de hechos. Devuelve el DataFrame
    saneado y un informe por CCAA con el recuento de filas corruptas (evidencia
    de limpieza). El origen conocido es Asturias (Ayto. de Avilés, OBR ~1e19).
    """
    if feat_df.empty:
        return feat_df, pd.DataFrame()

    present = [c for c in _FEAT_IMPORTE_COLS if c in feat_df.columns]
    mask_bad = pd.Series(False, index=feat_df.index)
    for c in present:
        mask_bad |= feat_df[c].abs() > _MAX_IMPORTE_ROW

    report = (
        feat_df.assign(_bad=mask_bad)
        .groupby("ccaa_slug")
        .agg(n_filas=("_bad", "size"), n_corruptas=("_bad", "sum"))
        .reset_index()
    )
    report["pct_corruptas"] = (report["n_corruptas"] / report["n_filas"] * 100).round(3)
    report["nombre"] = report["ccaa_slug"].map(ccaa_label)
    report = report.sort_values("n_corruptas", ascending=False)

    clean = feat_df.loc[~mask_bad].copy()
    return clean, report


def _fmt_p(p: float) -> str:
    """Formatea p-valores muy pequeños en notación legible."""
    if p is None or np.isnan(p):
        return "—"
    if p < 1e-4:
        return f"{p:.2e}"
    return f"{p:.4f}"


def tabla_calidad(report: pd.DataFrame, n_antes: int, n_despues: int) -> str:
    if report.empty:
        return "<p><em>Feature store no disponible.</em></p>"
    show = report[report["n_corruptas"] > 0][
        ["nombre", "n_filas", "n_corruptas", "pct_corruptas"]
    ].copy()
    resumen = (
        f"<div class='callout'><strong>Saneo aplicado:</strong> "
        f"{n_antes:,} filas → <strong>{n_despues:,}</strong> tras eliminar "
        f"<strong>{n_antes - n_despues:,}</strong> filas con importes imposibles "
        f"(|importe| &gt; 1×10¹¹ €). Umbral idéntico al de la tabla de hechos.</div>"
    )
    if show.empty:
        return resumen + "<p>No quedan filas corruptas tras el saneo. ✔</p>"
    show.columns = ["CCAA", "Filas (antes)", "Filas corruptas", "% corruptas"]
    show["Filas (antes)"] = show["Filas (antes)"].map("{:,}".format)
    return resumen + _df_to_html(show)


# ──────────────── ESTADÍSTICOS DESCRIPTIVOS (R2) ─────────────────────────────

_DESC_COLS = [
    "PRE", "OBR", "CRE", "brecha_eur", "brecha_pct",
    "ejecutado_pct", "pago_pct", "ratio_cre_pre",
]


def tabla_descriptivos(feat_df: pd.DataFrame) -> str:
    cols = [c for c in _DESC_COLS if c in feat_df.columns]
    if not cols:
        return "<p><em>Sin columnas para describir.</em></p>"
    desc = (
        feat_df[cols]
        .describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9])
        .T.reset_index()
        .rename(columns={
            "index": "Variable", "mean": "media", "std": "desv_típica",
            "50%": "mediana", "min": "mín", "max": "máx",
        })
    )
    desc["count"] = desc["count"].map("{:,.0f}".format)
    return _df_to_html(desc.round(4))


def tabla_descriptivos_por_capitulo(feat_df: pd.DataFrame) -> str:
    if "ejecutado_pct" not in feat_df.columns or "capitulo_id" not in feat_df.columns:
        return ""
    df = feat_df[feat_df["capitulo_id"].notna() & feat_df["ejecutado_pct"].notna()].copy()
    if df.empty:
        return ""
    df["cap"] = df["capitulo_id"].astype(int)
    g = (
        df.groupby("cap")["ejecutado_pct"]
        .agg(n="count", media="mean", mediana="median", desv_típica="std",
             p25=lambda s: s.quantile(0.25), p75=lambda s: s.quantile(0.75))
        .reset_index()
    )
    g["Capítulo"] = g["cap"].map(cap_label)
    g = g[["Capítulo", "n", "media", "mediana", "desv_típica", "p25", "p75"]]
    g["n"] = g["n"].map("{:,}".format)
    return _df_to_html(g.round(4))


# ──────────────── DISTRIBUCIONES Y Q-Q (R3) ──────────────────────────────────


def chart_histogramas(feat_df: pd.DataFrame) -> str:
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.5))

    if "OBR" in feat_df.columns:
        obr = feat_df["OBR"].dropna()
        obr = obr[(obr > 0) & np.isfinite(obr)]
        axes[0].hist(np.log1p(obr), bins=60, color=FASE_COLORS["OBR"], alpha=0.75, edgecolor="white")
        axes[0].set_title("OBR (escala log)")
        axes[0].set_xlabel("log(1 + OBR €)")
        axes[0].set_ylabel("Frecuencia")

    if "ejecutado_pct" in feat_df.columns:
        ep = feat_df["ejecutado_pct"].dropna().clip(0, 2)
        axes[1].hist(ep, bins=60, color="#2ca02c", alpha=0.75, edgecolor="white")
        axes[1].axvline(1.0, color="black", ls="--", lw=1.2, label="100%")
        axes[1].xaxis.set_major_formatter(mticker.PercentFormatter(xmax=1))
        axes[1].set_title("Tasa de ejecución (OBR/CRE)")
        axes[1].set_xlabel("ejecutado_pct [0–200%]")
        axes[1].set_ylabel("Frecuencia")
        axes[1].legend()

    if "brecha_pct" in feat_df.columns:
        bp = feat_df["brecha_pct"].dropna().clip(-2, 2)
        axes[2].hist(bp, bins=60, color="#1565c0", alpha=0.75, edgecolor="white")
        axes[2].axvline(0, color="black", ls="--", lw=1.2)
        axes[2].xaxis.set_major_formatter(mticker.PercentFormatter(xmax=1))
        axes[2].set_title("Brecha (PRE−OBR)/PRE")
        axes[2].set_xlabel("brecha_pct [±200%]")
        axes[2].set_ylabel("Frecuencia")

    fig.suptitle("Distribución de variables clave del feature store (saneado)", y=1.02)
    fig.tight_layout()
    return fig_to_b64(fig)


def chart_qqplot(feat_df: pd.DataFrame) -> str:
    if "OBR" not in feat_df.columns:
        return ""
    obr = feat_df["OBR"].dropna()
    obr = obr[np.isfinite(obr)]
    if obr.empty:
        return ""
    logobr = np.log1p(obr[obr > 0])

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    s1 = obr.sample(min(5000, len(obr)), random_state=42)
    stats.probplot(s1, dist="norm", plot=axes[0])
    axes[0].set_title("Q-Q plot — OBR (escala original)")
    if len(logobr) > 20:
        s2 = logobr.sample(min(5000, len(logobr)), random_state=42)
        stats.probplot(s2, dist="norm", plot=axes[1])
    axes[1].set_title("Q-Q plot — log(1 + OBR)")
    fig.suptitle("Contraste de normalidad de OBR frente a la distribución normal", y=1.02)
    fig.tight_layout()
    return fig_to_b64(fig)


# ──────────────── SUPUESTOS ESTADÍSTICOS (R4) ────────────────────────────────


def tabla_normalidad(feat_df: pd.DataFrame) -> str:
    specs = [
        ("OBR", "raw", "OBR"),
        ("OBR", "log", "log(1+OBR)"),
        ("ejecutado_pct", "raw", "ejecutado_pct"),
        ("brecha_pct", "raw", "brecha_pct"),
    ]
    rows = []
    for col, transform, label in specs:
        if col not in feat_df.columns:
            continue
        s = feat_df[col].dropna()
        if transform == "log":
            s = np.log1p(s[s > 0])
        s = s[np.isfinite(s)]
        if transform == "raw" and col != "OBR":
            s = s.clip(-5, 5)  # ratios extremos no aportan al contraste
        if len(s) < 20:
            continue
        samp = s.sample(min(5000, len(s)), random_state=42)
        try:
            W, pW = stats.shapiro(samp)
        except Exception:
            W, pW = np.nan, np.nan
        try:
            K2, pK2 = stats.normaltest(s)
        except Exception:
            K2, pK2 = np.nan, np.nan
        sd = s.std(ddof=0)
        if sd > 0:
            ks, pks = stats.kstest((s - s.mean()) / sd, "norm")
        else:
            ks, pks = np.nan, np.nan
        normal = "No" if (not np.isnan(pK2) and pK2 < 0.05) else "Sí"
        rows.append({
            "Variable": label,
            "n": f"{len(s):,}",
            "Shapiro W": round(W, 4) if not np.isnan(W) else "—",
            "p(Shapiro)": _fmt_p(pW),
            "D'Agostino K²": round(K2, 1) if not np.isnan(K2) else "—",
            "p(K²)": _fmt_p(pK2),
            "KS": round(ks, 4) if not np.isnan(ks) else "—",
            "p(KS)": _fmt_p(pks),
            "Asimetría": round(float(stats.skew(s)), 3),
            "Curtosis": round(float(stats.kurtosis(s)), 3),
            "¿Normal? (α=.05)": normal,
        })
    if not rows:
        return "<p><em>Sin datos suficientes para el contraste de normalidad.</em></p>"
    return _df_to_html(pd.DataFrame(rows))


def tabla_homocedasticidad(feat_df: pd.DataFrame) -> str:
    rows = []

    # Levene (varianzas iguales entre capítulos) sobre ejecutado_pct
    if {"capitulo_id", "ejecutado_pct"} <= set(feat_df.columns):
        df = feat_df[feat_df["capitulo_id"].notna() & feat_df["ejecutado_pct"].notna()].copy()
        df["cap"] = df["capitulo_id"].astype(int)
        groups = [
            g["ejecutado_pct"].clip(-5, 5).values
            for _, g in df.groupby("cap") if len(g) >= 20
        ]
        if len(groups) >= 2:
            try:
                W, p = stats.levene(*groups, center="median")
                rows.append({
                    "Test": "Levene — ejecutado_pct entre capítulos",
                    "Estadístico": round(W, 3),
                    "p-valor": _fmt_p(p),
                    "Conclusión (α=.05)": "Heterocedástico" if p < 0.05 else "Homocedástico",
                })
            except Exception:
                pass

    # Breusch-Pagan sobre regresión OLS OBR ~ PRE (+CRE)
    if {"OBR", "PRE"} <= set(feat_df.columns):
        try:
            import statsmodels.api as sm
            from statsmodels.stats.diagnostic import het_breuschpagan

            pred = ["PRE"] + (["CRE"] if "CRE" in feat_df.columns else [])
            d = feat_df.dropna(subset=["OBR"] + pred)
            if len(d) > 50:
                X = sm.add_constant(d[pred])
                model = sm.OLS(d["OBR"], X).fit()
                lm, lmp, F, Fp = het_breuschpagan(model.resid, model.model.exog)
                rows.append({
                    "Test": f"Breusch-Pagan — OBR ~ {' + '.join(pred)}",
                    "Estadístico": round(lm, 3),
                    "p-valor": _fmt_p(lmp),
                    "Conclusión (α=.05)": "Heterocedástico" if lmp < 0.05 else "Homocedástico",
                })
        except Exception as exc:
            print(f"  [WARN] Breusch-Pagan no disponible: {exc}")

    if not rows:
        return "<p><em>Sin datos suficientes para el contraste de homocedasticidad.</em></p>"
    return _df_to_html(pd.DataFrame(rows))


# ─────────────────────────────── HTML TEMPLATE ───────────────────────────────

_HTML = """\
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>EDA — Ejecución Presupuestaria Entidades Locales España</title>
<style>
body{{font-family:Arial,sans-serif;margin:2rem;color:#222;background:#fafafa;max-width:1400px;margin:auto;padding:1rem 2rem}}
h1{{color:#1a237e;border-bottom:3px solid #1a237e;padding-bottom:.5rem}}
h2{{color:#283593;margin-top:2.5rem;border-left:4px solid #283593;padding-left:.75rem}}
h3{{color:#3949ab;margin-top:1.5rem}}
.meta{{color:#555;font-size:.9rem;margin-bottom:2rem}}
.chart{{margin:1.5rem 0;text-align:center}}
.chart img{{max-width:100%;border:1px solid #ddd;border-radius:4px;box-shadow:2px 2px 8px rgba(0,0,0,.1)}}
.caption{{font-size:.82rem;color:#555;font-style:italic;margin-top:.4rem}}
table{{border-collapse:collapse;width:100%;margin:1rem 0;font-size:.88rem}}
th{{background:#283593;color:white;padding:7px 12px;text-align:left}}
td{{padding:5px 12px;border-bottom:1px solid #ddd}}
tr:nth-child(even){{background:#f0f4ff}}
.tag-n{{background:#c62828;color:white;padding:2px 8px;border-radius:10px;font-size:.8rem}}
.tag-d{{background:#1565c0;color:white;padding:2px 8px;border-radius:10px;font-size:.8rem}}
.callout{{background:#e8eaf6;border-left:4px solid #283593;padding:.9rem 1rem;margin:1rem 0;border-radius:0 4px 4px 0}}
.toc{{background:#f5f5f5;padding:1rem 2rem;border-radius:4px;margin-bottom:2rem}}
.toc a{{color:#283593;text-decoration:none}}
.toc li{{margin:.3rem 0}}
.footer{{margin-top:3rem;color:#aaa;font-size:.8rem;border-top:1px solid #ddd;padding-top:1rem}}
</style>
</head>
<body>
<h1>Análisis Exploratorio de Datos<br>
<small>Ejecución Presupuestaria — Entidades Locales España (2018-2025)</small></h1>
<div class="meta">
  Generado: {fecha}&nbsp;|&nbsp;
  Total hechos curados: <strong>{total_hechos:,}</strong>&nbsp;|&nbsp;
  Período análisis principal: <strong>{desde}–2025</strong>&nbsp;|&nbsp;
  Fuente: datos.gob.es → Arquitectura Medallion (00_raw→01_staging→02_curated→03_features)
</div>

<div class="toc"><strong>Contenido</strong>
<ol>
<li><a href="#s1">Cobertura del data lake</a></li>
<li><a href="#s2">Cobertura temporal (heatmap)</a></li>
<li><a href="#s3">Evolución PRE vs OBR — núcleo</a></li>
<li><a href="#s4">Brecha presupuestaria (PRE−OBR)</a></li>
<li><a href="#s5">Tasa de ejecución por CCAA y año</a></li>
<li><a href="#s6">Análisis por capítulo económico</a></li>
<li><a href="#s7">Features ML — correlaciones y distribuciones</a></li>
<li><a href="#s8">Análisis descriptivo — CCAAs solo PRE</a></li>
<li><a href="#s9">Calidad de datos — evidencia de limpieza</a></li>
<li><a href="#s10">Estadísticos descriptivos</a></li>
<li><a href="#s11">Validación de supuestos estadísticos</a></li>
</ol></div>

<h2 id="s1">1. Cobertura del data lake</h2>
<div class="callout">
<strong>Grupos de análisis:</strong><br>
<span class="tag-n">Núcleo (PRE+OBR)</span>&nbsp;
Aragón · Asturias · Cataluña · Madrid · País Vasco · Illes Balears · C.-La Mancha · Castilla y León · AGE<br>
<span class="tag-d">Descriptivo (solo PRE)</span>&nbsp;
Murcia · Galicia · Comunitat Valenciana
</div>
{tabla_cobertura}
<div class="chart"><img src="data:image/png;base64,{ch_hechos}">
<div class="caption">Total de registros en <code>fact_ejecucion_presupuestaria</code> por CCAA. Rojo=núcleo modelo, azul=solo descriptivo.</div></div>

<h2 id="s2">2. Cobertura temporal</h2>
<div class="chart"><img src="data:image/png;base64,{ch_cob}">
<div class="caption">Cada celda indica el volumen de hechos (escala logarítmica) disponibles para ese par CCAA-año.</div></div>

<h2 id="s3">3. Evolución PRE vs OBR — CCAAs núcleo</h2>
<div class="callout">
Suma de <strong>PRE</strong> (crédito inicial aprobado) y <strong>OBR</strong> (obligaciones reconocidas netas)
para las 9 CCAAs del núcleo. La diferencia entre ambas curvas representa la brecha de ejecución agregada.
</div>
<div class="chart"><img src="data:image/png;base64,{ch_evol}">
<div class="caption">El área sombreada bajo OBR resalta la infraejecución respecto al presupuesto aprobado.</div></div>

<h2 id="s4">4. Brecha presupuestaria (PRE − OBR)</h2>
<div class="callout">
La <strong>brecha presupuestaria</strong> mide cuánto del presupuesto aprobado no llegó a convertirse en obligaciones.
Una brecha positiva indica infraejecución; negativa indica uso de créditos suplementarios (sobreeje cución).
</div>
<div class="chart"><img src="data:image/png;base64,{ch_brecha}">
<div class="caption">Brecha acumulada por CCAA ({desde}–2025). Izquierda: valor absoluto. Derecha: porcentaje sobre PRE.</div></div>

<h3>Distribución de brecha_pct (feature store)</h3>
<div class="chart"><img src="data:image/png;base64,{ch_bdist}">
<div class="caption">brecha_pct = (PRE−OBR)/PRE. Valores recortados en ±200% para visualización. Mediana y dispersión por CCAA.</div></div>

<h2 id="s5">5. Tasa de ejecución por CCAA y año</h2>
<div class="chart"><img src="data:image/png;base64,{ch_tasa}">
<div class="caption">OBR/PRE×100. La línea discontinua marca el 100% (ejecución exacta del presupuesto aprobado).</div></div>

<h2 id="s6">6. Análisis por capítulo económico</h2>
<div class="chart"><img src="data:image/png;base64,{ch_cap}">
<div class="caption">Suma total de PRE y OBR por capítulo económico ({desde}–2025, núcleo). Cap.1 y Cap.6 concentran el mayor volumen.</div></div>

<h3>Heatmap tasa ejecución OBR/PRE por capítulo × año</h3>
<div class="chart"><img src="data:image/png;base64,{ch_heat}">
<div class="caption">Verde intenso = alta ejecución (≥150%); rojo = baja ejecución (≤50%). Valores >100% por créditos adicionales (ARN/suplementos).</div></div>

<h3>Distribución tasa OBR/CRE por capítulo (feature store)</h3>
<div class="chart"><img src="data:image/png;base64,{ch_ejec}">
<div class="caption">La línea roja marca el 100% de ejecución del crédito disponible. Invertido=Cap.9 (pasivos financieros) por su naturaleza.</div></div>

<h2 id="s7">7. Features ML — correlaciones y distribuciones (núcleo)</h2>
<h3>Estadísticas descriptivas del feature store</h3>
{tabla_features}
<h3>Matriz de correlación de Pearson</h3>
<div class="chart"><img src="data:image/png;base64,{ch_corr}">
<div class="caption">Correlación entre las principales variables del feature store. OBR y sus lags muestran alta autocorrelación, confirmando la estructura temporal de la serie.</div></div>

<h2 id="s8">8. Análisis descriptivo — CCAAs solo PRE</h2>
<div class="callout">
Murcia, Galicia y Comunitat Valenciana solo disponen de datos de presupuesto inicial (PRE).
No son aptas para el modelo predictivo (sin OBR) pero permiten análisis descriptivo del gasto planificado.
</div>
<div class="chart"><img src="data:image/png;base64,{ch_desc_ev}">
<div class="caption">Evolución del presupuesto inicial anual para las CCAAs descriptivas.</div></div>

<div class="chart"><img src="data:image/png;base64,{ch_desc_cap}">
<div class="caption">Distribución del presupuesto inicial (PRE) por capítulo económico ({desde}–2025).</div></div>

<h2 id="s9">9. Calidad de datos — evidencia de limpieza</h2>
<div class="callout">
Antes de calcular cualquier estadístico se aplica un <strong>saneo</strong> sobre el feature store:
se descartan las filas con importes físicamente imposibles (|importe| &gt; 1×10¹¹ €), originadas
por errores de parseo en una entidad concreta (Ayuntamiento de Avilés, Asturias). Esto garantiza
que las métricas y los contrastes posteriores se calculan sobre <strong>datos limpios</strong>.
</div>
{tabla_calidad}

<h2 id="s10">10. Estadísticos descriptivos</h2>
<div class="callout">
Medidas de tendencia central (media, mediana), dispersión (desviación típica) y percentiles
(10/25/50/75/90) de las variables clave, calculadas sobre el feature store saneado.
</div>
<h3>Resumen global por variable</h3>
{tabla_descriptivos}
<h3>Tasa de ejecución (OBR/CRE) por capítulo económico</h3>
{tabla_desc_cap}

<h2 id="s11">11. Validación de supuestos estadísticos</h2>
<div class="callout">
Contrastes que <strong>justifican la selección de algoritmos</strong>. La hipótesis nula de
normalidad/homocedasticidad se rechaza con p&lt;0.05. El rechazo esperado de ambas sustenta el
uso de modelos basados en árboles (Random Forest, XGBoost, LightGBM) frente a la regresión
lineal ordinaria (OLS), que asume residuos normales y varianza constante.
</div>
<h3>Normalidad</h3>
{tabla_normalidad}
<div class="chart"><img src="data:image/png;base64,{ch_qq}">
<div class="caption">Q-Q plot: los puntos se desvían de la recta → no normalidad. La transformación log(1+OBR) aproxima mejor pero no normaliza por completo.</div></div>
<div class="chart"><img src="data:image/png;base64,{ch_hist}">
<div class="caption">Distribuciones de OBR (log), tasa de ejecución y brecha. Asimetría y colas pesadas evidentes en OBR.</div></div>
<h3>Homocedasticidad</h3>
{tabla_homocedasticidad}

<div class="footer">
TFM — Análisis Predictivo y Visualización Dinámica de la Ejecución Presupuestaria de las Entidades Locales en España (2018-2025)<br>
UNIR · Máster en Data Science · {fecha}
</div>
</body></html>
"""


def _df_to_html(df: pd.DataFrame) -> str:
    return df.to_html(
        classes="",
        index=False,
        border=0,
        float_format=lambda x: f"{x:,.2f}" if isinstance(x, float) else x,
        na_rep="—",
    )


# ─────────────────────────────── MAIN ────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser(description="EDA de ejecución presupuestaria")
    ap.add_argument("--output", default="reports/eda", help="Directorio de salida")
    ap.add_argument("--desde", type=int, default=2018, help="Año inicial (análisis principal)")
    args = ap.parse_args()

    out_dir = ROOT / args.output
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[EDA] DB:     {DB_PATH}")
    print(f"[EDA] Salida: {out_dir}")
    print(f"[EDA] Desde:  {args.desde}")

    conn = sqlite3.connect(str(DB_PATH))

    print("\n[1/4] Cargando agregados de hechos...")
    fact_agg = load_fact_agg(conn, ALL_CCAA + ["cantabria", "andalucia"])
    cap_agg = load_cap_agg(conn, ALL_CCAA + ["cantabria"])
    cov_df = load_cobertura(conn, ALL_CCAA)
    conn.close()

    total_hechos = int(cov_df["hechos_total"].sum())

    print("[2/4] Cargando feature store (núcleo)...")
    feat_raw = load_features(CCAA_NUCLEO)
    n_antes = len(feat_raw)
    feat_df, calidad_report = sanitize_features(feat_raw)
    n_despues = len(feat_df)
    if not feat_df.empty:
        print(f"      {n_antes:,} filas -> {n_despues:,} tras saneo "
              f"({n_antes - n_despues:,} filas corruptas eliminadas)")

    print("\n[3/4] Generando gráficas...")
    ch: dict[str, str] = {}

    ch["hechos"] = chart_hechos_ccaa(cov_df)
    print("  [OK] hechos por CCAA")

    ch["cob"] = chart_cobertura_heatmap(fact_agg)
    print("  [OK] heatmap cobertura temporal")

    ch["evol"] = chart_evolucion_pre_obr(fact_agg, args.desde)
    print("  [OK] evolucion PRE vs OBR")

    ch["brecha"] = chart_brecha_ccaa(fact_agg, args.desde)
    print("  [OK] brecha por CCAA")

    ch["bdist"] = chart_distribucion_brecha(feat_df)
    print("  [OK] distribucion brecha_pct")

    ch["tasa"] = chart_tasa_ejecucion(fact_agg, args.desde)
    print("  [OK] tasa de ejecucion anual")

    ch["cap"] = chart_por_capitulo(cap_agg, args.desde)
    print("  [OK] PRE/OBR por capitulo")

    ch["heat"] = chart_heatmap_capitulo_anio(cap_agg, args.desde)
    print("  [OK] heatmap capitulo x anio")

    ch["ejec"] = chart_ejecutado_por_capitulo(feat_df)
    print("  [OK] ejecutado_pct por capitulo")

    ch["corr"] = chart_correlacion(feat_df)
    print("  [OK] matriz correlacion features")

    ch["desc_ev"] = chart_descriptivo_evolucion(fact_agg, desde=2015)
    print("  [OK] descriptivo: evolucion PRE")

    ch["desc_cap"] = chart_descriptivo_capitulo(cap_agg, args.desde)
    print("  [OK] descriptivo: PRE por capitulo")

    ch["qq"] = chart_qqplot(feat_df) if not feat_df.empty else ""
    print("  [OK] Q-Q plot normalidad OBR")

    ch["hist"] = chart_histogramas(feat_df) if not feat_df.empty else ""
    print("  [OK] histogramas de distribucion")

    # ── Tabla cobertura ──
    cov_show = cov_df[[
        "grupo", "nombre", "hechos_total", "anio_min", "anio_max",
        "n_anios", "n_entidades", "fases", "importe_meur",
    ]].copy()
    cov_show.columns = [
        "Grupo", "CCAA", "Hechos", "Año min", "Año max",
        "N años", "N entidades", "Fases", "Importe M€",
    ]
    cov_show["Hechos"] = cov_show["Hechos"].map("{:,}".format)
    tabla_cobertura = _df_to_html(cov_show)

    # ── Tabla features ──
    if not feat_df.empty:
        feat_cols = [c for c in [
            "PRE", "OBR", "CRE", "brecha_eur", "brecha_pct",
            "ejecutado_pct", "pago_pct", "obr_lag_1", "obr_rolling4_mean",
        ] if c in feat_df.columns]
        feat_stats = (
            feat_df[feat_cols]
            .describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9])
            .round(4)
            .reset_index()
            .rename(columns={"index": "Estadístico"})
        )
        tabla_features = _df_to_html(feat_stats)
    else:
        tabla_features = "<p><em>Feature store no disponible.</em></p>"

    # ── Tablas nuevas: calidad, descriptivos y supuestos (R1, R2, R4) ──
    if not feat_df.empty:
        tabla_calidad_html = tabla_calidad(calidad_report, n_antes, n_despues)
        tabla_descriptivos_html = tabla_descriptivos(feat_df)
        tabla_desc_cap_html = tabla_descriptivos_por_capitulo(feat_df)
        tabla_normalidad_html = tabla_normalidad(feat_df)
        tabla_homocedasticidad_html = tabla_homocedasticidad(feat_df)
    else:
        _na = "<p><em>Feature store no disponible.</em></p>"
        tabla_calidad_html = tabla_descriptivos_html = tabla_desc_cap_html = _na
        tabla_normalidad_html = tabla_homocedasticidad_html = _na

    print("\n[4/4] Generando informe HTML...")
    html = _HTML.format(
        fecha=datetime.now().strftime("%Y-%m-%d %H:%M"),
        total_hechos=total_hechos,
        desde=args.desde,
        tabla_cobertura=tabla_cobertura,
        tabla_features=tabla_features,
        tabla_calidad=tabla_calidad_html,
        tabla_descriptivos=tabla_descriptivos_html,
        tabla_desc_cap=tabla_desc_cap_html,
        tabla_normalidad=tabla_normalidad_html,
        tabla_homocedasticidad=tabla_homocedasticidad_html,
        **{f"ch_{k}": v for k, v in ch.items()},
    )

    html_path = out_dir / "eda_report.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"[OK] HTML     -> {html_path}")

    # ── Excel estadísticas ──
    excel_path = out_dir / "eda_stats.xlsx"
    agg_anual = fact_agg[fact_agg["fase"].isin(["PRE", "OBR", "CRE", "ARN"])].pivot_table(
        index=["ccaa_slug", "anio"],
        columns="fase",
        values="importe_total",
        aggfunc="sum",
    ).reset_index()

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        cov_df.to_excel(writer, sheet_name="Cobertura", index=False)
        agg_anual.to_excel(writer, sheet_name="Anual_por_fase", index=False)
        if not feat_df.empty:
            feat_df[feat_cols].describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9]).round(4).to_excel(
                writer, sheet_name="Features_stats"
            )
            if not calidad_report.empty:
                calidad_report[
                    ["nombre", "ccaa_slug", "n_filas", "n_corruptas", "pct_corruptas"]
                ].to_excel(writer, sheet_name="Calidad_datos", index=False)
        cap_wide = cap_agg[
            cap_agg["ccaa_slug"].isin(CCAA_NUCLEO)
            & cap_agg["fase"].isin(["PRE", "OBR"])
            & (cap_agg["anio"] >= args.desde)
        ].pivot_table(
            index=["ccaa_slug", "capitulo_id", "anio"],
            columns="fase",
            values="importe_total",
            aggfunc="sum",
        ).reset_index()
        cap_wide.to_excel(writer, sheet_name="Capitulo_PRE_OBR", index=False)

    print(f"[OK] Excel    -> {excel_path}")
    print(f"\n[EDA] Listo. Abrir: {html_path}")


if __name__ == "__main__":
    main()
