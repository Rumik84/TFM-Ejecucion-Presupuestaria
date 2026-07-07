# Requerimientos — Refuerzo del EDA y modelo de datos (Entregable 2 → Entregable 3)

> Origen: feedback del evaluador sobre `Entregable2_TFM_Ejecucion_Presupuestaria.pdf`.
> Objetivo final: **disponer de estadísticos que (a) demuestren la factibilidad del análisis,
> (b) justifiquen la elección de algoritmos y (c) sustenten que los datos están limpios.**

## Feedback del evaluador (resumen)

El entregable tiene buena estructura formal y descripción de datos, pero para cumplir la fase falta:
1. Profundizar el análisis exploratorio (EDA).
2. Métricas descriptivas: medias, medianas, desviaciones.
3. Visualizaciones etiquetadas de distribución y tendencias de variables clave.
4. Validar supuestos estadísticos: normalidad y homocedasticidad.
5. Diagrama entidad-relación (esquema lógico y físico, claves y particiones).
6. Vincular los hallazgos del EDA con los objetivos para orientar la selección de técnicas.

## Plan de acción

- [ ] **R1 — Datos limpios (evidencia).** Sanear el feature store al cargarlo (umbral ±1e11,
  igual que la tabla de hechos) y reportar nº de filas corruptas filtradas por CCAA
  (caso Asturias / Ayto. de Avilés). Tabla antes/después + recuento de nulos.
- [ ] **R2 — Estadísticos descriptivos.** Tablas con media, mediana, desviación típica,
  percentiles (10/25/50/75/90), min/max de `importe_eur` (PRE/OBR/CRE), `brecha_eur`,
  `brecha_pct`, `ejecutado_pct`, `pago_pct`. Segmentado global, por capítulo y por CCAA.
- [ ] **R3 — Visualizaciones de distribución etiquetadas.** Histogramas/KDE de
  `ejecutado_pct` y `brecha_pct`; boxplots por capítulo y CCAA; tendencia temporal de
  la brecha. Todos con título, ejes y unidades (€, %).
- [ ] **R4 — Supuestos estadísticos.** Normalidad (Shapiro-Wilk / D'Agostino / KS) + Q-Q
  plots sobre OBR y log(OBR); homocedasticidad (Levene entre capítulos, Breusch-Pagan
  sobre regresión PRE→OBR). Tabla con estadístico, p-valor y conclusión.
- [ ] **R5 — Diagrama entidad-relación.** ER lógico (entidades/relaciones) + físico
  (tipos, PK/FK, clave única del hecho, índices, particionado SQLite vs Parquet por año).
  Base ya disponible en la página de Notion del proyecto.
- [ ] **R6 — Vínculo EDA ↔ objetivos/algoritmos.** Apartado que conecta cada hallazgo con
  una decisión analítica (no normalidad + heterocedasticidad → modelos de árboles;
  estacionalidad → features sin/cos; etc.).

## Criterio de "hecho"

Al finalizar, el informe `reports/eda/eda_report.html` debe contener, con datos saneados:
- Sección de **calidad de datos** (evidencia de limpieza).
- Sección de **estadísticos descriptivos**.
- Sección de **supuestos estadísticos** que justifique usar RF/XGBoost frente a OLS.
- ER lógico+físico exportable al documento.
</content>
