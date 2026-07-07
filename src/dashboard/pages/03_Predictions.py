"""Predicciones de cierre de ejercicio (obligaciones reconocidas) y desviación."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
import streamlit as st

from src.dashboard.components.charts import render_alertas_scatter
from src.dashboard.components.data import ccaa_catalog, features, predictions
from src.dashboard.components.filters import CAPITULOS, fmt_eur, fmt_pct, render_sidebar_filters

st.set_page_config(page_title="Predicciones", page_icon="🔮", layout="wide")

ccaa_df = ccaa_catalog()
fs = features()
f = render_sidebar_filters(ccaa_df, fs)
preds = predictions()

st.title("🔮 Predicciones de cierre de ejercicio")
st.markdown(
    "Predicción de las **obligaciones reconocidas** (gasto real devengado) al cierre, "
    "por CCAA·capítulo. La *desviación relativa* = (real − predicho) / predicho."
)

if preds.empty:
    st.info("Aún no hay predicciones. Ejecuta `python scripts/generate_predictions.py`.")
    st.stop()

# Filtros: CCAA seleccionada + rango de años.
d = preds.copy()
if f["ccaa_slug"]:
    d = d[d["ccaa_slug"] == f["ccaa_slug"]]
if "anio" in d.columns:
    lo, hi = f["years"]
    d = d[d["anio"].between(lo, hi)]

if d.empty:
    st.info("No hay predicciones para la selección. Solo hay modelo para las CCAA con "
            "ejecución (OBR) e histórico suficiente.")
    st.stop()

c1, c2, c3 = st.columns(3)
c1.metric("Predicciones", f"{len(d):,}")
c2.metric("CCAA modeladas", d["ccaa_slug"].nunique())
c3.metric("MAPE mediano", fmt_pct(float(np.nanmedian(d["mape"]))) if "mape" in d.columns else "—")

st.subheader("Predicho vs. real")
render_alertas_scatter(d)

st.subheader("Detalle de predicciones")
show = d.copy()
show["CCAA"] = show["ccaa_slug"].map(lambda s: f["slug_to_name"].get(s, s))
if "capitulo_id" in show.columns:
    show["Capítulo"] = show["capitulo_id"].map(lambda c: CAPITULOS.get(int(c), c) if c == c else "—")
for col in ["importe_predicho", "importe_real"]:
    if col in show.columns:
        show[col] = show[col].map(fmt_eur)
if "desviacion_rel" in show.columns:
    show["desviacion_rel"] = show["desviacion_rel"].map(fmt_pct)
cols = [c for c in ["CCAA", "anio", "Capítulo", "modelo", "importe_predicho",
                    "importe_real", "desviacion_rel", "alerta"] if c in show.columns]
st.dataframe(show[cols].sort_values(["CCAA", "anio"]) if cols else show,
             width='stretch', hide_index=True)
