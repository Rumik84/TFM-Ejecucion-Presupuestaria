#!/usr/bin/env python
"""
Informe focalizado — Calidad de datos, Estadísticos descriptivos y Supuestos
============================================================================
Genera un HTML autocontenido con ÚNICAMENTE las secciones:
  9.  Calidad de datos — evidencia de limpieza
  10. Estadísticos descriptivos (por variable y por capítulo)
  11. Validación de supuestos estadísticos (normalidad + homocedasticidad)

Reutiliza las funciones de `scripts/eda.py` (no duplica lógica).

Uso:
    python scripts/eda_calidad.py
    python scripts/eda_calidad.py --output reports/eda --nombre informe_calidad
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

# Reutiliza el módulo EDA (mismo directorio scripts/)
from eda import (
    CCAA_NUCLEO,
    chart_histogramas,
    chart_qqplot,
    load_features,
    sanitize_features,
    tabla_calidad,
    tabla_descriptivos,
    tabla_descriptivos_por_capitulo,
    tabla_homocedasticidad,
    tabla_normalidad,
)

ROOT = Path(__file__).resolve().parent.parent

_STYLE = """
body{font-family:Arial,sans-serif;margin:2rem;color:#222;background:#fafafa;max-width:1400px;margin:auto;padding:1rem 2rem}
h1{color:#1a237e;border-bottom:3px solid #1a237e;padding-bottom:.5rem}
h2{color:#283593;margin-top:2.5rem;border-left:4px solid #283593;padding-left:.75rem}
h3{color:#3949ab;margin-top:1.5rem}
.meta{color:#555;font-size:.9rem;margin-bottom:2rem}
.chart{margin:1.5rem 0;text-align:center}
.chart img{max-width:100%;border:1px solid #ddd;border-radius:4px;box-shadow:2px 2px 8px rgba(0,0,0,.1)}
.caption{font-size:.82rem;color:#555;font-style:italic;margin-top:.4rem}
table{border-collapse:collapse;width:100%;margin:1rem 0;font-size:.88rem}
th{background:#283593;color:white;padding:7px 12px;text-align:left}
td{padding:5px 12px;border-bottom:1px solid #ddd}
tr:nth-child(even){background:#f0f4ff}
.callout{background:#e8eaf6;border-left:4px solid #283593;padding:.9rem 1rem;margin:1rem 0;border-radius:0 4px 4px 0}
.toc{background:#f5f5f5;padding:1rem 2rem;border-radius:4px;margin-bottom:2rem}
.toc a{color:#283593;text-decoration:none}
.toc li{margin:.3rem 0}
.footer{margin-top:3rem;color:#aaa;font-size:.8rem;border-top:1px solid #ddd;padding-top:1rem}
"""


def build_html(secciones: dict[str, str], fecha: str, n_antes: int, n_despues: int) -> str:
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Informe de calidad, descriptivos y supuestos — Ejecución Presupuestaria</title>
<style>{_STYLE}</style>
</head>
<body>
<h1>Calidad de datos, Estadísticos descriptivos y Supuestos<br>
<small>Ejecución Presupuestaria — Entidades Locales España (feature store núcleo)</small></h1>
<div class="meta">
  Generado: {fecha}&nbsp;|&nbsp;
  Feature store: <strong>{n_antes:,}</strong> filas → <strong>{n_despues:,}</strong> tras saneo&nbsp;|&nbsp;
  Fuente: datos.gob.es → Arquitectura Medallion (03_features)
</div>

<div class="toc"><strong>Contenido</strong>
<ol>
<li><a href="#s9">Calidad de datos — evidencia de limpieza</a></li>
<li><a href="#s10">Estadísticos descriptivos</a></li>
<li><a href="#s11">Validación de supuestos estadísticos</a></li>
</ol></div>

<h2 id="s9">9. Calidad de datos — evidencia de limpieza</h2>
<div class="callout">
Antes de calcular cualquier estadístico se aplica un <strong>saneo</strong> sobre el feature store:
se descartan las filas con importes físicamente imposibles (|importe| &gt; 1×10¹¹ €), originadas
por errores de parseo en entidades concretas (p. ej. Ayuntamiento de Avilés, Asturias). Esto garantiza
que las métricas y los contrastes posteriores se calculan sobre <strong>datos limpios</strong>.
</div>
{secciones['calidad']}

<h2 id="s10">10. Estadísticos descriptivos</h2>
<div class="callout">
Medidas de tendencia central (media, mediana), dispersión (desviación típica) y percentiles
(10/25/50/75/90) de las variables clave, calculadas sobre el feature store saneado.
</div>
<h3>Resumen global por variable</h3>
{secciones['descriptivos']}
<h3>Tasa de ejecución (OBR/CRE) por capítulo económico</h3>
{secciones['desc_cap']}

<h2 id="s11">11. Validación de supuestos estadísticos</h2>
<div class="callout">
Contrastes que <strong>justifican la selección de algoritmos</strong>. La hipótesis nula de
normalidad/homocedasticidad se rechaza con p&lt;0.05. El rechazo esperado de ambas sustenta el
uso de modelos basados en árboles (Random Forest, XGBoost, LightGBM) frente a la regresión
lineal ordinaria (OLS), que asume residuos normales y varianza constante.
</div>
<h3>Normalidad</h3>
{secciones['normalidad']}
<div class="chart"><img src="data:image/png;base64,{secciones['ch_qq']}">
<div class="caption">Q-Q plot: los puntos se desvían de la recta → no normalidad. La transformación log(1+OBR) aproxima mejor pero no normaliza por completo.</div></div>
<div class="chart"><img src="data:image/png;base64,{secciones['ch_hist']}">
<div class="caption">Distribuciones de OBR (log), tasa de ejecución y brecha. Asimetría y colas pesadas evidentes en OBR.</div></div>
<h3>Homocedasticidad</h3>
{secciones['homocedasticidad']}

<div class="footer">
TFM — Análisis Predictivo y Visualización Dinámica de la Ejecución Presupuestaria de las Entidades Locales en España (2018-2025)<br>
UNIR · Máster en Análisis y Visualización de Datos Masivos · {fecha}
</div>
</body></html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="Informe de calidad, descriptivos y supuestos")
    ap.add_argument("--output", default="reports/eda", help="Directorio de salida")
    ap.add_argument("--nombre", default="informe_calidad", help="Nombre base del archivo")
    args = ap.parse_args()

    out_dir = ROOT / args.output
    out_dir.mkdir(parents=True, exist_ok=True)

    print("[1/3] Cargando feature store (núcleo)...")
    feat_raw = load_features(CCAA_NUCLEO)
    n_antes = len(feat_raw)
    feat_df, calidad_report = sanitize_features(feat_raw)
    n_despues = len(feat_df)
    print(f"      {n_antes:,} -> {n_despues:,} filas ({n_antes - n_despues:,} corruptas eliminadas)")

    if feat_df.empty:
        print("[ERROR] Feature store vacío. Aborta.")
        return

    print("[2/3] Calculando secciones (calidad, descriptivos, supuestos)...")
    secciones = {
        "calidad": tabla_calidad(calidad_report, n_antes, n_despues),
        "descriptivos": tabla_descriptivos(feat_df),
        "desc_cap": tabla_descriptivos_por_capitulo(feat_df),
        "normalidad": tabla_normalidad(feat_df),
        "homocedasticidad": tabla_homocedasticidad(feat_df),
        "ch_qq": chart_qqplot(feat_df),
        "ch_hist": chart_histogramas(feat_df),
    }

    print("[3/3] Generando informe HTML...")
    html = build_html(
        secciones,
        fecha=datetime.now().strftime("%Y-%m-%d %H:%M"),
        n_antes=n_antes,
        n_despues=n_despues,
    )
    html_path = out_dir / f"{args.nombre}.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"[OK] HTML -> {html_path}")
    print(f"\nListo. Abrir: {html_path}")


if __name__ == "__main__":
    main()
