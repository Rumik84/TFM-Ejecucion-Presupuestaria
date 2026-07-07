"""Comparativa entre Comunidades Autónomas."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

from src.dashboard.components.charts import render_ejecucion_por_ccaa
from src.dashboard.components.data import ccaa_catalog, features
from src.dashboard.components.filters import apply_filters, fmt_eur, fmt_pct, render_sidebar_filters
from src.storage.feature_store import sanitize_feature_store

st.set_page_config(page_title="Comparativa CCAA", page_icon="🗺️", layout="wide")

ccaa_df = ccaa_catalog()
fs = features()
if fs.empty:
    st.warning("No hay feature store disponible.")
    st.stop()

f = render_sidebar_filters(ccaa_df, fs)
fsel = sanitize_feature_store(apply_filters(fs, f))

st.title("🗺️ Comparativa entre Comunidades Autónomas")
lo, hi = f["years"]
st.caption(f"Agregado {lo}–{hi}. Ordena las columnas haciendo clic en su cabecera.")

rows = []
for slug, g in fsel.groupby("ccaa_slug"):
    pre = g["PRE"].where(g["PRE"] > 0).sum() if "PRE" in g.columns else 0
    obr_g = g[g["OBR"].fillna(0) > 0] if "OBR" in g.columns else g.iloc[0:0]
    obr = obr_g["OBR"].sum() if len(obr_g) else 0
    cre = obr_g["CRE"].where(obr_g["CRE"] > 0).sum() if ("CRE" in obr_g.columns and len(obr_g)) else 0
    pre_e = obr_g["PRE"].where(obr_g["PRE"] > 0).sum() if ("PRE" in obr_g.columns and len(obr_g)) else 0
    rows.append({
        "CCAA": f["slug_to_name"].get(slug, slug),
        "Presupuesto inicial": float(pre or 0),
        "Obligaciones reconocidas": float(obr or 0),
        "Tasa ejecución": (obr / cre) if cre else None,
        "Brecha": ((pre_e - obr) / pre_e) if pre_e else None,
        "Ejecución": "Sí" if obr > 0 else "Solo presupuesto",
    })
tabla = pd.DataFrame(rows).sort_values("Presupuesto inicial", ascending=False)

disp = tabla.copy()
disp["Presupuesto inicial"] = disp["Presupuesto inicial"].map(fmt_eur)
disp["Obligaciones reconocidas"] = disp["Obligaciones reconocidas"].map(lambda v: fmt_eur(v) if v else "—")
disp["Tasa ejecución"] = disp["Tasa ejecución"].map(fmt_pct)
disp["Brecha"] = disp["Brecha"].map(fmt_pct)
st.dataframe(disp, width='stretch', hide_index=True)

st.subheader("Ejecución por CCAA")
render_ejecucion_por_ccaa(fsel, f["slug_to_name"])
