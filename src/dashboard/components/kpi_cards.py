"""KPIs agregados de la página principal (desde el feature store, ya con escala real).

Tras el saneo del ETL (dedup jerárquico/temporal/formato, exclusión de ingresos y
fuentes mal adscritas), los importes € del feature store son de escala realista, por
lo que ya se muestran los TOTALES en € además de los indicadores por ratio.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.dashboard.components.filters import fmt_eur, fmt_pct
from src.storage.feature_store import sanitize_feature_store

FASES = ["PRE", "CRE", "OBR", "PAG"]


def _agg(fs: pd.DataFrame) -> dict:
    """Totales € e indicadores agregados sobre las filas con ejecución (OBR)."""
    out = {f: (fs[f].where(fs[f] > 0).sum() if f in fs.columns else None) for f in FASES}
    # Ratios: sobre filas donde existe OBR (ejecución real), para consistencia.
    if "OBR" in fs.columns:
        ex = fs[fs["OBR"].fillna(0) > 0]
        s_pre = ex["PRE"].where(ex["PRE"] > 0).sum() if "PRE" in ex else 0
        s_cre = ex["CRE"].where(ex["CRE"] > 0).sum() if "CRE" in ex else 0
        s_obr = ex["OBR"].sum()
        s_pag = ex["PAG"].where(ex["PAG"] > 0).sum() if "PAG" in ex else 0
        out["tasa"] = (s_obr / s_cre) if s_cre else None
        out["brecha"] = ((s_pre - s_obr) / s_pre) if s_pre else None
        out["pago"] = (s_pag / s_obr) if s_obr else None
        out["obr_rows"] = int(len(ex))
    return out


def render_kpis(fs: pd.DataFrame) -> None:
    """KPIs sobre el feature store YA FILTRADO."""
    if fs is None or fs.empty:
        st.warning("No hay datos para la selección actual.")
        return
    fs = sanitize_feature_store(fs)
    a = _agg(fs)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Presupuesto inicial (PRE)", fmt_eur(a.get("PRE")),
              help="Suma de créditos iniciales en la selección.")
    c2.metric("Obligaciones reconocidas (OBR)", fmt_eur(a.get("OBR")),
              help="Gasto real devengado (ejecución).")
    c3.metric("Tasa de ejecución (OBR/CRE)", fmt_pct(a.get("tasa")),
              help="Obligaciones reconocidas sobre crédito definitivo.")
    c4.metric("Brecha de ejecución", fmt_pct(a.get("brecha")),
              help="(PRE − OBR) / PRE: cuánto del presupuesto inicial no se ejecutó.")

    # Cobertura: CCAA con ejecución (OBR) vs solo presupuesto inicial.
    if "ccaa_slug" in fs.columns:
        obr_col = fs["OBR"] if "OBR" in fs.columns else pd.Series(dtype=float)
        con_obr = fs.loc[obr_col.fillna(0) > 0, "ccaa_slug"].nunique() if "OBR" in fs.columns else 0
        total = fs["ccaa_slug"].nunique()
        st.caption(
            f"Selección: **{total}** CCAA · **{con_obr}** con ejecución (OBR), "
            f"**{total - con_obr}** solo presupuesto inicial · "
            f"Tasa de pago (PAG/OBR): **{fmt_pct(a.get('pago'))}**."
        )


# Compatibilidad con la firma antigua (recibía `repo`).
def render_global_kpis(repo) -> None:
    render_kpis(repo.load_feature_store())
