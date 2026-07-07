# Resumen – Datasets disponibles en datos.gob.es para el TFM

**Proyecto:** Análisis Predictivo y Visualización Dinámica de la Ejecución Presupuestaria
de las Entidades Locales en España (2018-2025)

**Fuente consultada:** `https://datos.gob.es/apidata` (API oficial del portal de datos abiertos
del Gobierno de España) — accedida el 16/04/2026.

---

## 1. Cifras globales del inventario

| Concepto | Valor |
|---|---|
| Datasets únicos consultados (unión de 5 queries) | **2 458** |
| Datasets relevantes para el TFM (score ≥ 4) | **522** |
| Alta relevancia (ejecución / liquidación / obligaciones reconocidas) | 485 |
| Relevancia media (presupuesto o gastos genéricos) | 37 |
| Publicadores distintos con datasets relevantes | **> 40** |
| Cobertura geográfica | 17 CCAA + 2 Ciudades Autónomas |

**Formatos más frecuentes en los datasets relevantes:** CSV (1 683), XLSX (1 344),
JSON (1 266), HTML (1 055), XML (740), PC-AXIS (534), PDF (458), TSV (322).

**Queries ejecutadas al API:**

- `/catalog/dataset/keyword/presupuesto.json` → 1 246 registros
- `/catalog/dataset/keyword/gastos.json` → 1 096 registros
- `/catalog/dataset/keyword/ejecucion.json` → 18 registros (muy específico)
- `/catalog/dataset/title/presupuesto.json` → 1 232 registros
- `/catalog/dataset/title/ejecucion.json` → 21 registros

---

## 2. Comunidades Autónomas a las que se puede aplicar el proyecto

La tabla muestra los datasets relevantes (ya filtrados y puntuados) por CCAA.
**El proyecto es aplicable en las 17 CCAA**, aunque con intensidad muy desigual:

| CCAA | Datasets tema *hacienda* | Datasets relevantes ejecución/presupuesto | Cobertura |
|---|---:|---:|---|
| País Vasco | 545 | **209** | Muy alta |
| Canarias | 78 | 48 | Alta |
| Aragón | 253 | 47 | Alta |
| Cantabria | 119 | 42 | Alta |
| Comunidad de Madrid | 80 | 26 | Media |
| Principado de Asturias | 83 | 25 | Media |
| Galicia | 95 | 18 | Media |
| Región de Murcia | 105 | 16 | Media |
| Castilla y León | 79 | 11 | Media |
| Cataluña | 94 | 10 | Media |
| Comunitat Valenciana | 80 | 7 | Baja |
| Castilla-La Mancha | 79 | 6 | Baja |
| Andalucía | 78 | 4 | Baja |
| Comunidad Foral de Navarra | 141 | 4 | Baja |
| Extremadura | 74 | 4 | Baja |
| Illes Balears | 78 | 4 | Baja |
| La Rioja | 74 | 4 | Baja |
| Ceuta | 63 | 0 | Sin datos específicos |
| Melilla | 63 | 0 | Sin datos específicos |

> Nota: la columna "tema hacienda" incluye datos de contratación, tasas, etc. Sólo la
> columna "datasets relevantes" corresponde estrictamente al objeto del TFM
> (presupuesto aprobado, ejecución, gasto devengado / obligaciones reconocidas).

---

## 3. Datasets clave para el TFM

### 3.1 Datasets nacionales agregados (punto de partida recomendado)

| Publicador | URL | Descripción |
|---|---|---|
| MINHAP `E05250001` | <https://datos.gob.es/catalogo/e05250001-liquidacion-de-presupuestos-de-las-comunidades-y-ciudades-autonomas-base-de-datos> | Liquidación de Presupuestos de todas las CCAA y Ciudades Autónomas. **Base nacional.** |
| Admin. Central `E05073401` | <https://datos.gob.es/catalogo/e05073401-presupuesto-inicial-credito-definitivo-del-presupuesto-de-gasto-y-obligaciones-reconocidas-netas> | Presupuesto inicial, crédito definitivo y **obligaciones reconocidas netas** – cuadro clásico "presupuestado vs. ejecutado". |
| Senado `I00000061` | <https://datos.gob.es/catalogo/i00000061-estado-de-ejecucion-del-presupuesto-del-senado> | Estado de ejecución del presupuesto del Senado (nivel institucional). |

### 3.2 Datasets autonómicos con serie histórica multi-año

| CCAA | Publicador | URL |
|---|---|---|
| Canarias (EELL) | `A05003423` (ISTAC) | <https://datos.gob.es/catalogo/a05003423-liquidacion-del-presupuesto-consolidado-de-gastos-de-las-entidades-locales-segun-estructura-funcional-capitulos-de-la-estructura-economica-y-fases-presupuestarias-islas-y-municipios-de-canarias-por-anos> |
| Aragón (municipios) | `A02002834` (Gob. Aragón) | <https://datos.gob.es/catalogo/a02002834-presupuesto-y-ejecucion-presupuestaria-de-municipios-de-aragon> |
| País Vasco (Dip. Forales) | `A16003011` (Eustat) | <https://datos.gob.es/catalogo/a16003011-ejecucion-presupuestaria-de-las-diputaciones-forales-evolucion-de-la-ejecucion-del-presupuesto-de-gastos-obligaciones-reconocidas-miles-de-euros> |
| Castilla y León | `A07002862` | <https://datos.gob.es/catalogo/a07002862-ejecucion-del-presupuesto-de-la-administracion-de-la-comunidad-gastos1> |
| Castilla-La Mancha | `A13002908` | <https://datos.gob.es/catalogo/a13002908-presupuestos-liquidados-gastos-consolidados-por-capitulos-y-fases-de-ejecucion-obligaciones-reconocidas> |
| Cataluña (Generalitat) | `A10002983` | <https://datos.gob.es/catalogo/a10002983-ejecucion-presupuestaria-de-la-generalitat-y-sus-organismos-autonomos-2025> |
| Galicia (Xunta) | `A12002994` | <https://datos.gob.es/catalogo/a12002994-gastos-del-presupuesto-20201> |
| Illes Balears (CAIB) | `A04003003` | <https://datos.gob.es/catalogo/a04003003-partidas-presupuesto-inicial-gastos-2022-2023-comunidad-autonoma-de-las-illes-balears1> |
| La Rioja | `A14002961` | <https://datos.gob.es/catalogo/a14002961-evolucion-del-presupuesto-inicial-de-gasto-sanitario> |

### 3.3 Datasets municipales (entidades locales) destacados

| Ámbito | URL |
|---|---|
| Madrid (Ayto.) | <https://datos.gob.es/catalogo/l01280066-presupuestos-20221> |
| Alcobendas | <https://datos.gob.es/catalogo/l01280148-presupuesto-municipal-2016> |
| Barcelona | <https://datos.gob.es/catalogo/l01080193-presupuestos-consolidados-de-la-ciudad-de-barcelona-iniciales-segun-lgep-y-loepsf> |
| Mataró | <https://datos.gob.es/catalogo/l01082798-presupuesto-municipal-de-ingresos-y-gastos-ejecucion1> |
| Badalona | <https://datos.gob.es/catalogo/l01082114-ingresos-del-presupuesto-municipal-ejecutado> |
| Zaragoza | <https://datos.gob.es/catalogo/l01502973-presupuesto-municipal-20101> |
| Zaragoza (RDF) | <https://datos.gob.es/catalogo/l01390759-presupuestos-ejecutados> |
| Vitoria-Gasteiz | <https://datos.gob.es/catalogo/l01010590-presupuestos-ejecucion-presupuestaria-2025> |
| Antzuola (PV) | <https://datos.gob.es/catalogo/l02000020-datos-de-la-liquidacion-del-presupuesto-ayuntamiento-de-antzuola> |
| Avilés | <https://datos.gob.es/catalogo/l01330045-ejecucion-de-presupuestos-2018-ayuntamiento-de-aviles> |
| Gijón | <https://datos.gob.es/catalogo/l01380380-presupuesto-consolidado1> |
| Pamplona | <https://datos.gob.es/catalogo/l01312016-ayto-de-pamplona-ejecucion-del-presupuesto-de-gastos-2016> |
| Murcia (Alhama) | <https://datos.gob.es/catalogo/l01300243-ejecucion-del-presupuesto-de-gastos-para-el-1er-trimestre-de-2018> |
| Coslada | <https://datos.gob.es/catalogo/l01281150-datos-economico-financieros> |
| Valladolid | <https://datos.gob.es/catalogo/l01471868-estados-de-ejecucion-del-presupuesto> |
| San Sebastián de los Reyes | <https://datos.gob.es/catalogo/l01280796-presupuestos-ejecucion-anual-historico> |

---

## 4. Endpoints API listos para el pipeline ETL

```text
# Catálogo general (paginado)
GET https://datos.gob.es/apidata/catalog/dataset?_pageSize=50&_page=0

# Tema principal (hacienda)
GET https://datos.gob.es/apidata/catalog/dataset/theme/hacienda.json?_pageSize=50&_page=0

# Por palabra clave
GET https://datos.gob.es/apidata/catalog/dataset/keyword/presupuesto.json?_pageSize=50&_page=0
GET https://datos.gob.es/apidata/catalog/dataset/keyword/gastos.json?_pageSize=50&_page=0
GET https://datos.gob.es/apidata/catalog/dataset/keyword/ejecucion.json?_pageSize=50&_page=0

# Por ámbito territorial (CCAA)
GET https://datos.gob.es/apidata/catalog/dataset/spatial/Autonomia/Pais-Vasco.json
GET https://datos.gob.es/apidata/catalog/dataset/spatial/Autonomia/Canarias.json
GET https://datos.gob.es/apidata/catalog/dataset/spatial/Autonomia/Aragon.json
# ...(17 CCAA)

# Por publicador concreto
GET https://datos.gob.es/apidata/catalog/dataset/publisher/E05250001.json   # MINHAP
GET https://datos.gob.es/apidata/catalog/dataset/publisher/A05003423.json   # ISTAC
GET https://datos.gob.es/apidata/catalog/dataset/publisher/A02002834.json   # Aragón
GET https://datos.gob.es/apidata/catalog/dataset/publisher/A16003011.json   # País Vasco

# Por ventana temporal (modificados)
GET https://datos.gob.es/apidata/catalog/dataset/modified/begin/2024-01-01T00:00Z/end/2025-12-31T00:00Z.json

# Taxonomías auxiliares (NTI)
GET https://datos.gob.es/apidata/nti/territory/Autonomous-region
GET https://datos.gob.es/apidata/nti/territory/Province
GET https://datos.gob.es/apidata/nti/public-sector
```

**Parámetros útiles:**
- `_pageSize=50` (máximo permitido)
- `_page=N` (0-indexado)
- `_sort=-issued` o `_sort=-modified`

---

## 5. Conclusión para el planteamiento del TFM

1. **El proyecto es viable en las 17 CCAA**, pero la profundidad del análisis predictivo
   debe calibrarse a la cobertura: País Vasco, Canarias, Aragón y Cantabria son los
   laboratorios ideales por tener series multianuales completas; el resto se cubre con
   datasets puntuales (municipios representativos + agregados MINHAP).
2. **Núcleo recomendado del dataset final:** combinar el dataset MINHAP `E05250001`
   (liquidación CCAA a nivel nacional) con los datasets ISTAC (`A05003423`) y Gob. Aragón
   (`A02002834`) para tener, desde el primer sprint del TFM, una base estructurada,
   multianual y en formato CSV/JSON directo desde API.
3. **Variable objetivo** recomendada: *obligaciones reconocidas netas* anuales o
   trimestrales (equivalente al gasto real devengado), presente explícitamente en
   `E05073401`, `A16003011`, `A13002908` y la mayor parte de los datasets destacados.
4. **Completar la cobertura** de las CCAA con menor disponibilidad (Extremadura, La Rioja,
   Navarra, Baleares) apoyándose en los portales de transparencia municipales
   referenciados desde cada dataset (campo `distribution.accessURL`).

---

**Entregable acompañante:** `Inventario_datasets_datos_gob_es.xlsx` (6 hojas) con el
detalle completo: resumen, CCAA, publicadores, datasets destacados, endpoints API y el
pipeline TFM propuesto.
