"""
Lectura del feature store en parquet (`data_lake/03_features/<ccaa>/features`).

El parquet es la FUENTE DE VERDAD del feature store de modelado. Esta función lo
lee (una CCAA o todas) y devuelve el DataFrame wide (PRE/CRE/OBR/PAG + ratios +
lags), reconstruyendo la columna `anio` desde el nombre de la partición si hiciera
falta. La usan tanto el `SQLiteRepository` (dashboard local) como
`scripts/build_feature_store_azure.py` (subida a Azure).
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from config import settings

# Umbral de saneo de importes corruptos (mismo criterio que el EDA y el modelado:
# valores |importe| > 1e11 € son basura de origen y deben descartarse antes de
# agregar o modelar).
MAX_IMPORTE = 1e11
FASE_COLS = ["PRE", "CRE", "OBR", "PAG"]


def sanitize_feature_store(df: pd.DataFrame, max_importe: float = MAX_IMPORTE) -> pd.DataFrame:
    """Descarta filas con algún importe de fase por encima del umbral (corruptos).

    Replica el filtro `abs(importe) > MAX_IMPORTE` que aplican `scripts/eda.py` y
    los scripts de modelado, para que los agregados del dashboard sean coherentes.
    """
    if df.empty:
        return df
    mask = pd.Series(True, index=df.index)
    for c in FASE_COLS:
        if c in df.columns:
            mask &= ~(df[c].abs() > max_importe)
    return df[mask]


def read_feature_store_parquet(
    features_dir: Path | None = None,
    ccaa_slug: str | None = None,
) -> pd.DataFrame:
    """Lee el feature store parquet. Si `ccaa_slug` es None, lee todas las CCAA."""
    root = features_dir or settings.paths.features_dir
    slugs = [ccaa_slug] if ccaa_slug else [p.name for p in sorted(root.glob("*")) if p.is_dir()]

    parts: list[pd.DataFrame] = []
    for slug in slugs:
        files = sorted((root / slug / "features").rglob("*.parquet"))
        for f in files:
            d = pd.read_parquet(f)
            if "anio" not in d.columns:
                m = re.search(r"anio=(\d+)", str(f))
                if m:
                    d["anio"] = int(m.group(1))
            if "ccaa_slug" not in d.columns:
                d["ccaa_slug"] = slug
            parts.append(d)

    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True, sort=False)
