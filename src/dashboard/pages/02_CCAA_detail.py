"""Detalle por Comunidad Autónoma."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

from src.dashboard.components.charts import render_ejecucion_temporal
from src.dashboard.components.data import ccaa_catalog, features
from src.dashboard.components.filters import CAPITULOS, apply_filters, render_sidebar_filters
from src.dashboard.components.kpi_cards import render_kpis

st.set_page_config(page_title="Detalle por CCAA", page_icon="🏙️", layout="wide")

ccaa_df = ccaa_catalog()
fs = features()
if fs.empty:
    st.warning("No hay feature store disponible.")
    st.stop()

f = render_sidebar_filters(ccaa_df, fs)

# Si no hay CCAA en el filtro, permitir elegir una aquí.
slug = f["ccaa_slug"]
if not slug:
    slugs = sorted(fs["ccaa_slug"].unique())
    slug = st.selectbox("Elige una CCAA", slugs,
                        format_func=lambda s: f["slug_to_name"].get(s, s))

nombre = f["slug_to_name"].get(slug, slug)
st.title(f"🏙️ {nombre}")

fsel = apply_filters(fs[fs["ccaa_slug"] == slug], {**f, "ccaa_slug": slug})
lo, hi = f["years"]
st.caption(f"Periodo {lo}–{hi}.")
render_kpis(fsel)

st.subheader("Evolución temporal de las fases")
render_ejecucion_temporal(fsel)

st.subheader("Variables explicativas (feature store)")
st.caption("Grano nativo (capítulo × año) con fases, ratios y lags que alimentan los modelos.")
show = fsel.copy()
if "capitulo_id" in show.columns:
    show.insert(0, "Capítulo", show["capitulo_id"].map(lambda c: CAPITULOS.get(int(c), c)
                                                       if c == c else "—"))
cols = [c for c in ["Capítulo", "anio", "PRE", "CRE", "OBR", "PAG",
                    "ratio_cre_pre", "ejecutado_pct", "brecha_pct", "obr_lag_1"] if c in show.columns]
st.dataframe(show[cols] if cols else show, width='stretch', hide_index=True)
