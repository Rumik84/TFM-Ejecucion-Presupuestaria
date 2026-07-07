"""Filtros de sidebar compartidos por todas las páginas + utilidades de formato.

Streamlit ejecuta cada página de forma independiente, así que los widgets del
sidebar se renderizan en CADA página llamando a `render_sidebar_filters`; el uso
de claves de `session_state` hace que la selección persista al navegar.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

# Capítulo económico -> etiqueta legible.
CAPITULOS = {
    1: "1 · Personal",
    2: "2 · Bienes y servicios",
    3: "3 · Gastos financieros",
    4: "4 · Transferencias corrientes",
    5: "5 · Fondo de contingencia",
    6: "6 · Inversiones reales",
    7: "7 · Transferencias de capital",
    8: "8 · Activos financieros",
    9: "9 · Pasivos financieros",
}
_LABEL_TO_CAP = {v: k for k, v in CAPITULOS.items()}


def fmt_eur(v) -> str:
    """Formatea un importe en € a la escala legible (B€ / M€ / k€)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    a = abs(v)
    if a >= 1e9:
        return f"{v/1e9:,.1f} B€"
    if a >= 1e6:
        return f"{v/1e6:,.0f} M€"
    if a >= 1e3:
        return f"{v/1e3:,.0f} k€"
    return f"{v:,.0f} €"


def fmt_pct(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v*100:.1f}%"


def _name_slug_maps(ccaa_df: pd.DataFrame) -> tuple[dict, dict]:
    if ccaa_df.empty or "slug" not in ccaa_df.columns:
        return {}, {}
    name_to_slug = dict(zip(ccaa_df["nombre"], ccaa_df["slug"]))
    slug_to_name = dict(zip(ccaa_df["slug"], ccaa_df["nombre"]))
    return name_to_slug, slug_to_name


def render_sidebar_filters(ccaa_df: pd.DataFrame, fs: pd.DataFrame) -> dict:
    """Renderiza los filtros y devuelve la selección aplicable a las páginas.

    Solo ofrece CCAA que realmente tienen datos en el feature store, y limita el
    rango de años a los presentes en los datos.
    """
    present_slugs = set(fs["ccaa_slug"].unique()) if "ccaa_slug" in fs.columns else set()
    name_to_slug, slug_to_name = _name_slug_maps(ccaa_df)
    # Nombres con datos (orden alfabético); fallback a slug si no hay catálogo.
    if name_to_slug:
        names = sorted(n for n, s in name_to_slug.items() if s in present_slugs)
    else:
        names = sorted(present_slugs)
        name_to_slug = {s: s for s in names}

    if "anio" in fs.columns and fs["anio"].notna().any():
        y_min, y_max = int(fs["anio"].min()), int(fs["anio"].max())
    else:
        y_min, y_max = 2018, 2026

    with st.sidebar:
        st.header("🔎 Filtros")
        ccaa_name = st.selectbox("Comunidad Autónoma", ["— Todas —"] + names, key="f_ccaa")
        default = (max(y_min, 2018), y_max)
        yr = st.slider("Años", y_min, y_max, default, key="f_years") if y_min < y_max else (y_min, y_max)
        cap_label = st.selectbox("Capítulo económico", ["Todos"] + list(CAPITULOS.values()), key="f_cap")
        st.caption("Los filtros afectan a todas las páginas.")

    return {
        "ccaa_slug": name_to_slug.get(ccaa_name) if ccaa_name != "— Todas —" else None,
        "ccaa_name": ccaa_name if ccaa_name != "— Todas —" else None,
        "years": yr,
        "capitulo": _LABEL_TO_CAP.get(cap_label),
        "slug_to_name": slug_to_name,
    }


def apply_filters(df: pd.DataFrame, f: dict) -> pd.DataFrame:
    """Aplica los filtros (CCAA, rango de años, capítulo) a un df con esas columnas."""
    if df.empty:
        return df
    out = df
    if f.get("ccaa_slug") and "ccaa_slug" in out.columns:
        out = out[out["ccaa_slug"] == f["ccaa_slug"]]
    if f.get("years") and "anio" in out.columns:
        lo, hi = f["years"]
        out = out[out["anio"].between(lo, hi)]
    if f.get("capitulo") and "capitulo_id" in out.columns:
        out = out[out["capitulo_id"] == f["capitulo"]]
    return out
