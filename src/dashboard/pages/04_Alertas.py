"""Sistema de alertas tipo semáforo por desviación de la predicción."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import plotly.express as px
import streamlit as st

from src.dashboard.components.data import ccaa_catalog, features, predictions
from src.dashboard.components.filters import CAPITULOS, fmt_pct, render_sidebar_filters

st.set_page_config(page_title="Alertas", page_icon="🚦", layout="wide")

ccaa_df = ccaa_catalog()
fs = features()
f = render_sidebar_filters(ccaa_df, fs)
preds = predictions()

st.title("🚦 Alertas de desviación presupuestaria")
st.markdown(
    "Semáforo según la desviación relativa (real vs. predicho): "
    "🟢 **< 5 %** · 🟡 **5–15 %** · 🔴 **> 15 %**."
)

if preds.empty:
    st.info("Sin predicciones generadas todavía.")
    st.stop()

d = preds.copy()
if f["ccaa_slug"]:
    d = d[d["ccaa_slug"] == f["ccaa_slug"]]
if "anio" in d.columns:
    lo, hi = f["years"]
    d = d[d["anio"].between(lo, hi)]
if d.empty:
    st.info("No hay predicciones para la selección.")
    st.stop()

d["CCAA"] = d["ccaa_slug"].map(lambda s: f["slug_to_name"].get(s, s))
cmap = {"verde": "#2ecc71", "amarillo": "#f1c40f", "rojo": "#e74c3c", "gris": "#95a5a6"}

col1, col2 = st.columns([2, 3])
with col1:
    st.subheader("Distribución")
    counts = d["alerta"].value_counts().reset_index()
    counts.columns = ["alerta", "n"]
    fig = px.pie(counts, names="alerta", values="n", hole=0.5,
                 color="alerta", color_discrete_map=cmap)
    fig.update_layout(margin=dict(t=10, b=10), showlegend=True)
    st.plotly_chart(fig, width='stretch')
with col2:
    st.subheader("Alertas por CCAA")
    piv = d.pivot_table(index="CCAA", columns="alerta", values="pred_id",
                        aggfunc="count", fill_value=0)
    for a in ["verde", "amarillo", "rojo", "gris"]:
        if a not in piv.columns:
            piv[a] = 0
    st.dataframe(piv[["verde", "amarillo", "rojo", "gris"]], width='stretch')

st.subheader("🔴 Casos en rojo (mayor desviación)")
rojo = d[d["alerta"] == "rojo"].copy()
if rojo.empty:
    st.success("No hay casos en rojo en la selección.")
else:
    if "capitulo_id" in rojo.columns:
        rojo["Capítulo"] = rojo["capitulo_id"].map(lambda c: CAPITULOS.get(int(c), c) if c == c else "—")
    rojo["desviacion_rel_fmt"] = rojo["desviacion_rel"].map(fmt_pct)
    rojo = rojo.reindex(rojo["desviacion_rel"].abs().sort_values(ascending=False).index)
    cols = [c for c in ["CCAA", "anio", "Capítulo", "modelo", "desviacion_rel_fmt", "alerta"]
            if c in rojo.columns]
    st.dataframe(rojo[cols], width='stretch', hide_index=True)
