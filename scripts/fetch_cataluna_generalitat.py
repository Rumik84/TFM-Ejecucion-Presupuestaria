#!/usr/bin/env python
"""
Ingesta de la ejecución presupuestaria de la GENERALITAT DE CATALUNYA (gastos).

Fuente: Generalitat de Catalunya (publisher DIR3 A09002970), dataset
`a09002970-ejecucion-mensual-del-presupuesto-de-la-generalitat-de-catalunya-gastos`,
publicado en el portal Socrata `analisi.transparenciacatalunya.cat` (recurso ajns-4mi7)
y federado en datos.gob.es.

El dataset es ejecución MENSUAL ACUMULADA año-a-fecha (verificado: OBR crece
monótonamente ene→dic) y desglosa por `entitat` (84 entidades del sector público).
Para tener una cifra comparable con el resto de CCAA (administración autonómica
NÚCLEO, sin doble contar transferencias internas Generalitat→CatSalut→…), se toma:
  - `entitat = 'Generalitat'` (el núcleo; ~51 B€/año, escala real de Catalunya),
  - el MES MÁXIMO de cada año (diciembre en años cerrados = total anual),
  - grano CAPÍTULO económico (cap_tol_codi 1-9).

Se agrega en el servidor (Socrata $select/$group) → resultado diminuto. Se escribe
un CSV con cabeceras en catalán que el `BudgetNormalizer` ya entiende (exercici,
capítol codi, crèdits inicials, pressupost definitiu, obligacions reconegudes,
obligacions pagades) en la ruta de distribuciones del data lake, y se registra el
dataset + distribución en el catálogo (ccaa_slug=cataluna).

Uso:  python scripts/fetch_cataluna_generalitat.py
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SOCRATA = "https://analisi.transparenciacatalunya.cat/resource/ajns-4mi7.json"
ENTITAT = "Generalitat"
DATASET_URI = ("https://datos.gob.es/catalogo/"
               "a09002970-ejecucion-mensual-del-presupuesto-de-la-generalitat-de-catalunya-gastos")
PUBLISHER = "A09002970"
CCAA = "cataluna"
DB = ROOT / "data_lake" / "catalog.db"
OUT_DIR = ROOT / "data_lake" / "00_raw" / CCAA / "distributions" / PUBLISHER
OUT_CSV = OUT_DIR / "generalitat_catalunya_gastos_capitulo_anual.csv"
LOCAL_PATH = str(OUT_CSV.relative_to(ROOT / "data_lake"))

FASE_FIELDS = {
    "cr_dits_inicials": "credits inicials",           # -> importe_pre
    "pressupost_definitiu": "pressupost definitiu",   # -> importe_cre
    "obligacions_reconegudes": "obligacions reconegudes",  # -> importe_obr
    "obligacions_pagades": "obligacions pagades",     # -> importe_pag
}


def fetch() -> pd.DataFrame:
    sums = ", ".join(f"sum({f})" for f in FASE_FIELDS)
    params = {
        "$select": f"exercici, mes, cap_tol_codi, {sums}",
        "$where": f"entitat='{ENTITAT}'",
        "$group": "exercici, mes, cap_tol_codi",
        "$limit": "50000",
    }
    r = requests.get(SOCRATA, params=params, timeout=120)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    # renombrar sum_* -> nombre de campo
    df = df.rename(columns={f"sum_{f}": f for f in FASE_FIELDS})
    for f in FASE_FIELDS:
        df[f] = pd.to_numeric(df[f], errors="coerce")
    df["exercici"] = pd.to_numeric(df["exercici"], errors="coerce")
    df["cap_tol_codi"] = pd.to_numeric(df["cap_tol_codi"], errors="coerce")
    df["__mesnum"] = pd.to_numeric(df["mes"].str.slice(0, 2), errors="coerce")
    # Mes MÁXIMO por año (último snapshot acumulado)
    df = df[df["cap_tol_codi"].between(1, 9)].dropna(subset=["exercici", "cap_tol_codi"])
    maxmes = df.groupby("exercici")["__mesnum"].transform("max")
    df = df[df["__mesnum"] == maxmes].copy()
    # CSV con cabeceras que el normalizador ya mapea
    out = pd.DataFrame({
        "exercici": df["exercici"].astype(int),
        "capitol codi": df["cap_tol_codi"].astype(int),
    })
    for field, header in FASE_FIELDS.items():
        out[header] = df[field].values
    return out.sort_values(["exercici", "capitol codi"]).reset_index(drop=True)


def register_catalog() -> None:
    con = sqlite3.connect(str(DB))
    now = datetime.now(timezone.utc).isoformat()
    con.execute(
        """INSERT INTO catalog_dataset (uri, id, titulo, descripcion, publisher_id, ccaa_slug,
             issued, modified, score_relevancia, raw_json_path, query_kind, query_value, ingested_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(uri) DO UPDATE SET publisher_id=excluded.publisher_id, ccaa_slug=excluded.ccaa_slug""",
        (DATASET_URI, "a09002970-generalitat-gastos",
         "Ejecución mensual del presupuesto de la Generalitat de Catalunya (gastos)",
         "Generalitat de Catalunya, núcleo (entitat='Generalitat'), mes máx/año, grano capítulo.",
         PUBLISHER, CCAA, None, now, 10, None, "publisher", PUBLISHER, now),
    )
    con.execute("DELETE FROM catalog_distribution WHERE dataset_uri=? AND local_path=?",
                (DATASET_URI, LOCAL_PATH))
    con.execute(
        """INSERT INTO catalog_distribution (dataset_uri, formato, access_url, download_url,
             byte_size, local_path, downloaded_at, checksum_md5)
           VALUES (?,?,?,?,?,?,?,?)""",
        (DATASET_URI, "CSV", SOCRATA, None, OUT_CSV.stat().st_size, LOCAL_PATH, now, None),
    )
    con.commit()
    con.close()


def main() -> None:
    print(f"[fetch] Generalitat de Catalunya (entitat='{ENTITAT}') desde Socrata...")
    df = fetch()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8")
    print(f"[ok] {len(df)} filas (año×capítulo) -> {OUT_CSV.name}")
    print("  PRE (crèdits inicials) por año, M€:")
    piv = df.groupby("exercici")["credits inicials"].sum() / 1e6
    for y, v in piv.items():
        print(f"     {int(y)}: {v:,.0f} M€")
    register_catalog()
    print(f"[ok] Registrado en catálogo: dataset + distribución (ccaa={CCAA}).")


if __name__ == "__main__":
    main()
