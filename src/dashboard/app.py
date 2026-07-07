"""
Dashboard principal — Streamlit.

Home: visión global con KPIs en € reales, ejecución por CCAA y evolución temporal.
Los filtros del sidebar (CCAA / años / capítulo) se comparten con todas las páginas.

Backend: SQLite (local) o Azure PostgreSQL según la variable de entorno DATA_BACKEND.

Ejecución:
    $ streamlit run src/dashboard/app.py
    # contra Azure:
    $ DATA_BACKEND=azure PGPASSWORD=... streamlit run src/dashboard/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# La raíz del proyecto debe estar en sys.path para poder importar `src.*`
# aunque Streamlit se lance desde otro directorio (p. ej. src/dashboard).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

from src.dashboard.components.charts import (
    render_ejecucion_por_ccaa,
    render_ejecucion_temporal,
    render_tasa_por_ccaa,
)
from src.dashboard.components.data import ccaa_catalog, features
from src.dashboard.components.filters import apply_filters, render_sidebar_filters
from src.dashboard.components.kpi_cards import render_kpis

st.set_page_config(
    page_title="Ejecución Presupuestaria — TFM",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    st.title("🏛️ Ejecución Presupuestaria de las CCAA en España")
    st.caption(
        "TFM — Máster en Análisis y Visualización de Datos Masivos (UNIR) · "
        "Fuente: datos.gob.es y portales autonómicos · "
        "Autores: Eliesel Gómez Sánchez, Carlos A. Herrera Díaz"
    )

    ccaa_df = ccaa_catalog()
    fs = features()
    if fs.empty:
        st.warning(
            "No hay feature store. Genera las features (`python -m flows.flow_build_features`) "
            "o sincroniza Azure (`python scripts/sync_azure.py`)."
        )
        return

    f = render_sidebar_filters(ccaa_df, fs)
    fsel = apply_filters(fs, f)

    scope = f["ccaa_name"] or "todas las CCAA"
    lo, hi = f["years"]
    st.markdown(f"#### Resumen — {scope} · {lo}–{hi}")
    render_kpis(fsel)

    st.divider()
    col1, col2 = st.columns([3, 2])
    with col1:
        st.subheader("Ejecución por CCAA")
        st.caption("Presupuesto inicial vs crédito definitivo vs obligaciones reconocidas (M€).")
        render_ejecucion_por_ccaa(fsel, f["slug_to_name"])
    with col2:
        st.subheader("Tasa de ejecución")
        st.caption("OBR / crédito definitivo, por CCAA con ejecución.")
        render_tasa_por_ccaa(fsel, f["slug_to_name"])

    st.subheader("Evolución temporal")
    render_ejecucion_temporal(fsel)

    st.divider()
    st.markdown(
        "**Navegación** (menú lateral): 🏙️ Detalle por CCAA · 🔮 Predicciones · 🚦 Alertas."
    )


if __name__ == "__main__":
    main()
