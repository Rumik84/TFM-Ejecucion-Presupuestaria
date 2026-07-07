#!/usr/bin/env python
"""
Ingesta de la ejecución presupuestaria de la GENERALITAT VALENCIANA (gastos).

Fuente: Generalitat Valenciana (GVA), portal `dadesobertes.gva.es` (CKAN),
datasets `sec-nefis-visor-YYYY` ("Ejecución presupuestaria de la Generalitat y
sus organismos autónomos"). NO está federado en datos.gob.es (solo la ciudad de
Valencia lo estaba), por eso se ingiere directamente del portal regional.

El CSV de GASTOS trae grano subconcepto con columnas de ejecución completas:
  ejercicio, ac_mes (mes acumulado año-a-fecha), cd_cap (capítulo G1..G9),
  im_ci (crédito inicial=PRE), im_cd (crédito definitivo=CRE),
  im_recon (obligaciones reconocidas=OBR), im_pag (pagado=PAG).
Decimales ANGLOSAJONES (`17170.00`). Ejecución MENSUAL ACUMULADA -> se toma el
mes MÁXIMO de cada año. Se agrega a grano (año, CAPÍTULO) sumando las 12 entidades
(Generalitat + OOAA); el total casa con el presupuesto real de GVA (~30 B€), sin
inflación por transferencias internas.

Se escribe un CSV compacto con cabeceras que el `BudgetNormalizer` ya mapea y se
registra dataset + distribución en el catálogo (ccaa_slug=comunidad-valenciana).

Uso:  python scripts/fetch_valenciana_gva.py
"""
from __future__ import annotations

import io
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PORTAL = "https://dadesobertes.gva.es"
DATASET_URI = "https://dadesobertes.gva.es/dataset/ejecucion-presupuestaria-generalitat-valenciana-gastos"
PUBLISHER = "GVA-DADESOBERTES"
CCAA = "comunidad-valenciana"
DB = ROOT / "data_lake" / "catalog.db"
OUT_DIR = ROOT / "data_lake" / "00_raw" / CCAA / "distributions" / PUBLISHER
OUT_CSV = OUT_DIR / "gva_generalitat_gastos_capitulo_anual.csv"
LOCAL_PATH = str(OUT_CSV.relative_to(ROOT / "data_lake"))

# im_* -> cabecera que el normalizador ya entiende
FASE_FIELDS = {
    "im_ci": "credito inicial",              # -> importe_pre
    "im_cd": "credito definitivo",           # -> importe_cre
    "im_recon": "obligaciones reconocidas netas",  # -> importe_obr
    "im_pag": "pagos liquidos",              # -> importe_pag
}

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (TFM ejecucion presupuestaria)"


def _get(url: str, **kw):
    last = None
    for _ in range(4):
        try:
            return S.get(url, timeout=kw.pop("timeout", 240), **kw)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3)
    raise last


def discover_years() -> list[str]:
    r = _get(f"{PORTAL}/api/3/action/package_search",
             params={"q": "ejecucion presupuestaria generalitat organismos", "rows": 50}, timeout=60)
    names = {d.get("name", "") for d in r.json()["result"].get("results", [])}
    return sorted(n.replace("sec-nefis-visor-", "") for n in names if n.startswith("sec-nefis-visor-"))


def gastos_csv_url(year: str) -> str | None:
    r = _get(f"{PORTAL}/api/3/action/package_show", params={"id": f"sec-nefis-visor-{year}"}, timeout=60)
    for rs in r.json()["result"]["resources"]:
        if "GASTOS" in str(rs.get("name", "")).upper() and str(rs.get("format", "")).lower() == "csv":
            return rs["url"]
    return None


def fetch_year(year: str) -> pd.DataFrame | None:
    url = gastos_csv_url(year)
    if not url:
        print(f"   [skip] {year}: sin CSV de gastos")
        return None
    raw = _get(url, timeout=300).content
    df = pd.read_csv(io.BytesIO(raw), sep=None, engine="python", dtype=str)
    df["__mes"] = pd.to_numeric(df["ac_mes"], errors="coerce")
    df = df[df["__mes"] == df["__mes"].max()].copy()          # mes máximo (acumulado)
    df["capitulo"] = pd.to_numeric(df["cd_cap"].astype(str).str.extract(r"(\d)")[0], errors="coerce")
    df = df[df["capitulo"].between(1, 9)]
    for f in FASE_FIELDS:                                       # decimales anglosajones
        df[f] = pd.to_numeric(df[f], errors="coerce")
    g = df.groupby("capitulo", as_index=False)[list(FASE_FIELDS)].sum()
    g.insert(0, "anio", int(year))
    g = g.rename(columns=FASE_FIELDS)
    return g


def register_catalog() -> None:
    con = sqlite3.connect(str(DB))
    now = datetime.now(timezone.utc).isoformat()
    con.execute(
        """INSERT INTO catalog_dataset (uri, id, titulo, descripcion, publisher_id, ccaa_slug,
             issued, modified, score_relevancia, raw_json_path, query_kind, query_value, ingested_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(uri) DO UPDATE SET publisher_id=excluded.publisher_id, ccaa_slug=excluded.ccaa_slug""",
        (DATASET_URI, "gva-nefis-gastos",
         "Ejecución presupuestaria de la Generalitat Valenciana y OOAA (gastos)",
         "GVA dadesobertes.gva.es (sec-nefis-visor), mes máx/año, grano capítulo, todas las entidades.",
         PUBLISHER, CCAA, None, now, 10, None, "portal", "dadesobertes.gva.es", now),
    )
    con.execute("DELETE FROM catalog_distribution WHERE dataset_uri=? AND local_path=?",
                (DATASET_URI, LOCAL_PATH))
    con.execute(
        """INSERT INTO catalog_distribution (dataset_uri, formato, access_url, download_url,
             byte_size, local_path, downloaded_at, checksum_md5)
           VALUES (?,?,?,?,?,?,?,?)""",
        (DATASET_URI, "CSV", PORTAL, None, OUT_CSV.stat().st_size, LOCAL_PATH, now, None),
    )
    con.commit()
    con.close()


def main() -> None:
    years = discover_years()
    print(f"[fetch] GVA años disponibles: {years}")
    frames = []
    for y in years:
        print(f"   descargando y agregando {y}...")
        g = fetch_year(y)
        if g is not None:
            frames.append(g)
    if not frames:
        print("[ERROR] Sin datos."); sys.exit(1)
    out = pd.concat(frames, ignore_index=True).sort_values(["anio", "capitulo"])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False, encoding="utf-8")
    print(f"[ok] {len(out)} filas (año×capítulo) -> {OUT_CSV.name}")
    piv = out.groupby("anio")[["credito inicial", "obligaciones reconocidas netas"]].sum() / 1e6
    print("  PRE / OBR por año (M€):")
    for y, row in piv.iterrows():
        print(f"     {int(y)}: PRE={row['credito inicial']:,.0f}  OBR={row['obligaciones reconocidas netas']:,.0f}")
    register_catalog()
    print(f"[ok] Registrado en catálogo (ccaa={CCAA}).")


if __name__ == "__main__":
    main()
