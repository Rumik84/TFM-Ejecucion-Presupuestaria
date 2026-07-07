"""
Parser de PC-AXIS (.px).

PC-AXIS es el formato histórico del INE, Eustat e IGAE. Se usa la librería
`pyaxis`. Soporta:
  - Archivos de una sola fase (TITLE indica OBR/CRE/PRE):
      STUB=[Capítulo] HEADING=[Período] → (capítulo × año) × importe
  - Archivos multi-fase con dimensión 'Indicadores':
      STUB=[Capitulo] HEADING=[Indicadores, Periodo] → fase ya en datos

Si el archivo no es PC-AXIS textual (bytes OLE2/PK = Excel real), se delega
a XLSXParser como fallback.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

import unicodedata

from src.utils import get_logger
from src.utils.text import parse_euro_amount

logger = get_logger(__name__)


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )

# Mapeo de keywords del TITLE/CONTENTS al código de fase canónico
_TITLE_TO_FASE: list[tuple[str, str]] = [
    ("obligaciones reconocidas", "OBR"),
    ("obligacion", "OBR"),
    ("credito definitivo", "CRE"),
    ("presupuesto definitivo", "CRE"),
    ("credito inicial", "PRE"),
    ("presupuesto inicial", "PRE"),
    ("pagos", "PAG"),
]

# Nombres de columnas (lowercased) que son dimensión de año
_YEAR_COLS = {"período", "periodo", "año", "ano", "ejercicio", "year", "time_period"}

# Nombres de columnas que son dimensión de capítulo
_CHAPTER_COLS = {"capítulo", "capitulo", "chapter", "cap.", "capitulos"}

# Nombres de columnas que actúan como dimensión de fase
_INDICADORES_COLS = {"indicadores", "indicador", "tipo", "magnitud"}

# Valores de Indicadores → código de fase canónico
_INDICADOR_TO_FASE: list[tuple[str, str]] = [
    ("obligaciones reconocidas", "OBR"),
    ("credito definitivo", "CRE"),
    ("presupuesto definitivo", "CRE"),
    ("presupuesto inicial", "PRE"),
    ("creditos iniciales", "PRE"),
    ("pagos", "PAG"),
    ("autorizaciones", "ARN"),
    ("compromisos", "DIS"),
]


def _detect_encoding(path: Path) -> str:
    """Lee el CODEPAGE del encabezado PC-AXIS."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(1024).decode("ascii", errors="ignore")
        m = re.search(r'CODEPAGE\s*=\s*"([^"]+)"', head, re.IGNORECASE)
        if m:
            return m.group(1).lower()
    except Exception:
        pass
    return "iso-8859-15"


def _is_text_pcaxis(path: Path) -> bool:
    """PC-AXIS texto empieza con 'AXIS-VERSION' o 'CHARSET'."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(64)
        return head.lstrip().startswith(b"AXIS") or head.lstrip().startswith(b"CHARSET")
    except Exception:
        return False


def _fase_from_title(meta: dict[str, Any]) -> str:
    """Extrae fase del TITLE/CONTENTS cuando el archivo es mono-fase."""
    texts = meta.get("TITLE", []) + meta.get("CONTENTS", [])
    combined = " ".join(str(t) for t in texts).lower()
    for keyword, code in _TITLE_TO_FASE:
        if keyword in combined:
            return code
    return "PRE"


def _indicador_to_fase(value: str) -> str | None:
    """Convierte un valor de la columna 'Indicadores' al código de fase."""
    v = _strip_accents(str(value).lower().strip())
    for keyword, code in _INDICADOR_TO_FASE:
        if keyword in v:
            return code
    return None


def _extract_chapter(value: Any) -> int | None:
    """Extrae el nº de capítulo de strings como 'Cap. 1 Gastos de personal'."""
    if not isinstance(value, str):
        return None
    m = re.search(r"\b([1-9])\b", value)
    if m:
        return int(m.group(1))
    return None


class PCAxisParser:
    def parse(self, path: Path) -> pd.DataFrame:
        if not _is_text_pcaxis(path):
            return self._fallback_xlsx(path)

        try:
            from pyaxis import pyaxis
        except ImportError:
            logger.warning("pyaxis no instalado; omitiendo %s", path)
            return pd.DataFrame()

        encoding = _detect_encoding(path)
        try:
            result = pyaxis.parse(uri=str(path), encoding=encoding)
        except Exception as exc:
            logger.warning("pyaxis falló %s: %s; intentando XLSX fallback", path.name, exc)
            return self._fallback_xlsx(path)

        meta = result.get("METADATA", {})
        data_df: pd.DataFrame | None = result.get("DATA")
        if data_df is None or data_df.empty:
            return pd.DataFrame()

        df = data_df.copy()

        # Normalizar nombres de columnas a minúsculas
        df.columns = [str(c).strip().lower() for c in df.columns]

        # Parsear DATA → importe_eur
        if "data" not in df.columns:
            return pd.DataFrame()
        df["importe_eur"] = df["data"].apply(parse_euro_amount)
        df = df.drop(columns=["data"])
        df = df.dropna(subset=["importe_eur"])

        # Detectar dimensión de fase (Indicadores) → manejar antes del año/capítulo
        indicadores_col = next(
            (c for c in df.columns if c in _INDICADORES_COLS), None
        )
        if indicadores_col:
            df["fase"] = df[indicadores_col].apply(_indicador_to_fase)
            df = df.drop(columns=[indicadores_col])
            df = df.dropna(subset=["fase"])
        else:
            # Archivo mono-fase: extraer fase del TITLE
            df["fase"] = _fase_from_title(meta)

        # Detectar columna de año
        year_col = next((c for c in df.columns if c in _YEAR_COLS), None)
        if year_col:
            df["anio"] = pd.to_numeric(df[year_col], errors="coerce")
            if year_col != "anio":
                df = df.drop(columns=[year_col])
        df = df.dropna(subset=["anio"])
        df["anio"] = df["anio"].astype(int)

        # Detectar columna de capítulo
        chap_col = next((c for c in df.columns if c in _CHAPTER_COLS), None)
        if chap_col:
            df["capitulo_id"] = df[chap_col].apply(_extract_chapter)
            if chap_col != "capitulo_id":
                df = df.drop(columns=[chap_col])

        # Descartar columnas dimensionales restantes (CCAA, entidad, etc.)
        keep = {"anio", "capitulo_id", "fase", "importe_eur"}
        extra = [c for c in df.columns if c not in keep]
        if extra:
            logger.debug("PCAxisParser: descartando columnas extra %s en %s", extra, path.name)
            df = df.drop(columns=extra)

        return df.reset_index(drop=True)

    # ------------------------------------------------------------------
    def _fallback_xlsx(self, path: Path) -> pd.DataFrame:
        """Intenta parsear como XLS/XLSX (para archivos OLE2 con extensión .px)."""
        try:
            from src.etl.parsers.xlsx_parser import XLSXParser
            return XLSXParser().parse(path)
        except Exception as exc:
            logger.warning("Fallback XLS también falló para %s: %s", path.name, exc)
            return pd.DataFrame()
