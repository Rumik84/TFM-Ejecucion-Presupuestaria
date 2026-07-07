"""Parser de XLSX/XLS.

Concatena todas las hojas del libro en un DataFrame largo, añadiendo la columna
`__sheet__` para trazabilidad. Detecta la fila de cabecera ignorando filas de
metadatos típicas de los Excel de ayuntamientos (título del informe, notas, etc.).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.utils import get_logger

logger = get_logger(__name__)


class XLSXParser:
    def parse(self, path: Path, max_header_row_search: int = 10) -> pd.DataFrame:
        # Use xlrd only for confirmed .xls files; everything else (including files
        # with no extension, as happens with Bizkaia downloads) needs openpyxl.
        # If openpyxl fails (e.g. XLS binary disguised as .px), fall back to xlrd.
        engine = "xlrd" if path.suffix.lower() == ".xls" else "openpyxl"
        try:
            xl = pd.ExcelFile(path, engine=engine)
        except Exception:
            fallback = "xlrd" if engine == "openpyxl" else "openpyxl"
            xl = pd.ExcelFile(path, engine=fallback)

        frames = []
        for sheet_name in xl.sheet_names:
            raw = xl.parse(sheet_name, header=None, dtype=object)
            header_row = self._find_header_row(raw, max_header_row_search)
            if header_row is None:
                logger.debug("Hoja %s sin cabecera identificada, se omite", sheet_name)
                continue
            df = xl.parse(sheet_name, header=header_row)
            df["__sheet__"] = sheet_name
            frames.append(df)

        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True, sort=False)

    # ------------------------------------------------------------------
    def _find_header_row(self, raw: pd.DataFrame, max_rows: int) -> int | None:
        """Heurística: la primera fila donde todas las celdas sean no nulas
        y ninguna sea numérica (es decir, parecen nombres de columnas)."""
        for i in range(min(max_rows, len(raw))):
            row = raw.iloc[i]
            non_null = row.notna().sum()
            non_numeric = sum(1 for v in row if isinstance(v, str))
            if non_null >= max(3, int(0.5 * len(row))) and non_numeric >= non_null * 0.6:
                return i
        return 0
