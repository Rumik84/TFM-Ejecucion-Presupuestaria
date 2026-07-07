"""
Factory de parsers por formato.

Uso:
    >>> from src.etl.parsers import get_parser
    >>> parser = get_parser("CSV")
    >>> df = parser.parse(Path(".../fichero.csv"))
"""
from pathlib import Path
from typing import Protocol

import pandas as pd

from src.etl.parsers.csv_parser import CSVParser
from src.etl.parsers.xlsx_parser import XLSXParser
from src.etl.parsers.json_parser import JSONParser
from src.etl.parsers.xml_parser import XMLParser
from src.etl.parsers.pcaxis_parser import PCAxisParser


class BaseParser(Protocol):
    def parse(self, path: Path) -> pd.DataFrame: ...


_REGISTRY: dict[str, type[BaseParser]] = {
    "CSV": CSVParser,
    "TSV": CSVParser,
    "XLSX": XLSXParser,
    "XLS": XLSXParser,
    "JSON": JSONParser,
    "XML": XMLParser,
    "PC-AXIS": PCAxisParser,
    "PX": PCAxisParser,
}


def get_parser(fmt: str) -> BaseParser:
    """Devuelve una instancia del parser apropiado. Lanza KeyError si no está soportado."""
    cls = _REGISTRY.get(fmt.upper())
    if cls is None:
        raise KeyError(f"Formato no soportado: {fmt}")
    return cls()
