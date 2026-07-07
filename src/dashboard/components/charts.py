"""Gráficos del dashboard (Plotly Express), alimentados por el feature store filtrado.

Todos reciben DataFrames YA FILTRADOS (feature store / predicciones) para que la
composición sea sencilla y las páginas apliquen los filtros del sidebar una sola vez.
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from src.storage.feature_store import sanitize_feature_store

FASES = ["PRE", "CRE", "OBR"]
_FASE_LABEL = {"PRE": "Presupuesto inicial", "CRE": "Crédito definitivo",
               "OBR": "Obligaciones reconocidas"}
_COLORS = {"Presupuesto inicial": "#4C78A8", "Crédito definitivo": "#F58518",
           "Obligaciones reconocidas": "#54A24B"}


def _present(df: pd.DataFrame) -> list[str]:
    return [f for f in FASES if f in df.columns]


def _melt(df: pd.DataFrame, group_col: str) -> pd.DataFrame | None:
    df = sanitize_feature_store(df)
    present = _present(df)
    if not present or df.empty:
        return None
    agg = df.groupby(group_col)[present].sum().reset_index()
    long = agg.melt(id_vars=group_col, value_vars=present, var_name="fase", value_name="importe")
    long["Fase"] = long["fase"].map(_FASE_LABEL)
    long["M€"] = long["importe"] / 1e6
    return long


def render_ejecucion_por_ccaa(fs: pd.DataFrame, slug_to_name: dict | None = None) -> None:
    """Barras PRE/CRE/OBR por CCAA (suma de la selección), en M€, ordenadas."""
    if fs.empty or "ccaa_slug" not in fs.columns:
        st.info("Sin datos para la selección.")
        return
    long = _melt(fs, "ccaa_slug")
    if long is None:
        st.info("El feature store no contiene fases PRE/CRE/OBR.")
        return
    long["CCAA"] = long["ccaa_slug"].map(lambda s: (slug_to_name or {}).get(s, s))
    ref_fase = "Presupuesto inicial" if "PRE" in fs.columns else long["Fase"].iloc[0]
    order = (long[long["Fase"] == ref_fase].sort_values("M€", ascending=False)["CCAA"].tolist())
    fig = px.bar(long, x="CCAA", y="M€", color="Fase", barmode="group",
                 category_orders={"CCAA": order}, color_discrete_map=_COLORS,
                 labels={"M€": "Importe (M€)"}, height=460)
    fig.update_layout(margin=dict(t=10, b=0), legend_title_text="")
    st.plotly_chart(fig, width='stretch')


def render_ejecucion_temporal(fs: pd.DataFrame) -> None:
    """Evolución anual de PRE/CRE/OBR (suma de la selección), en M€."""
    if fs.empty or "anio" not in fs.columns:
        st.info("Sin datos temporales para la selección.")
        return
    long = _melt(fs, "anio")
    if long is None:
        st.info("El feature store no contiene fases PRE/CRE/OBR.")
        return
    fig = px.line(long.sort_values("anio"), x="anio", y="M€", color="Fase", markers=True,
                  color_discrete_map=_COLORS, labels={"M€": "Importe (M€)", "anio": "Año"}, height=420)
    fig.update_layout(margin=dict(t=10, b=0), legend_title_text="", xaxis=dict(dtick=1))
    st.plotly_chart(fig, width='stretch')


def render_tasa_por_ccaa(fs: pd.DataFrame, slug_to_name: dict | None = None) -> None:
    """Tasa de ejecución (OBR/CRE) por CCAA, solo las que tienen ejecución."""
    fs = sanitize_feature_store(fs)
    if fs.empty or not {"OBR", "CRE", "ccaa_slug"} <= set(fs.columns):
        st.info("La selección no tiene ejecución (OBR/CRE) para calcular la tasa.")
        return
    ex = fs[(fs["OBR"].fillna(0) > 0) & (fs["CRE"].fillna(0) > 0)]
    if ex.empty:
        st.info("La selección no tiene CCAA con ejecución.")
        return
    g = ex.groupby("ccaa_slug").agg(OBR=("OBR", "sum"), CRE=("CRE", "sum")).reset_index()
    g["tasa"] = (g["OBR"] / g["CRE"] * 100).round(1)
    g["CCAA"] = g["ccaa_slug"].map(lambda s: (slug_to_name or {}).get(s, s))
    g = g.sort_values("tasa", ascending=True)
    fig = px.bar(g, x="tasa", y="CCAA", orientation="h",
                 labels={"tasa": "Tasa de ejecución OBR/CRE (%)", "CCAA": ""},
                 height=max(300, 26 * len(g)), color="tasa", color_continuous_scale="RdYlGn")
    fig.update_layout(margin=dict(t=10, b=0), coloraxis_showscale=False)
    st.plotly_chart(fig, width='stretch')


def render_alertas_scatter(preds: pd.DataFrame) -> None:
    """Scatter predicho vs real, coloreado por alerta."""
    if preds.empty or "importe_real" not in preds.columns:
        st.info("Aún no hay predicciones para la selección.")
        return
    d = preds.copy()
    d["M€ predicho"] = d["importe_predicho"] / 1e6
    d["M€ real"] = d["importe_real"] / 1e6
    fig = px.scatter(
        d, x="M€ predicho", y="M€ real", color="alerta",
        hover_data=["ccaa_slug", "anio", "capitulo_id", "modelo"],
        color_discrete_map={"verde": "#2ecc71", "amarillo": "#f1c40f",
                            "rojo": "#e74c3c", "gris": "#95a5a6"},
        labels={"alerta": "Alerta"}, height=460,
    )
    mx = float(d[["M€ predicho", "M€ real"]].max().max() or 1)
    fig.add_shape(type="line", x0=0, y0=0, x1=mx, y1=mx, line=dict(dash="dash", color="#888"))
    fig.update_layout(margin=dict(t=10, b=0))
    st.plotly_chart(fig, width='stretch')
