"""Parser de JSON (catálogo OData / datos estructurados / JSON anidados)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


class JSONParser:
    """Parser de JSON usando pandas.json_normalize sobre el nodo de datos detectado."""

    # Rutas comunes donde suelen anidarse los registros en los JSON de datos.gob.es
    _COMMON_DATA_PATHS = [
        ["result", "items"],
        ["value"],
        ["data"],
        ["items"],
        ["records"],
    ]

    def parse(self, path: Path) -> pd.DataFrame:
        # utf-8-sig handles BOM transparently (common in Spanish open-data portals)
        try:
            with path.open("r", encoding="utf-8-sig") as f:
                payload = json.load(f)
        except (UnicodeDecodeError, json.JSONDecodeError):
            with path.open("r", encoding="latin-1") as f:
                payload = json.load(f)

        records = self._find_records(payload)
        if records is None:
            return pd.json_normalize(payload)
        return pd.json_normalize(records)

    # ------------------------------------------------------------------
    def _find_records(self, payload) -> list | None:
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return None

        for path in self._COMMON_DATA_PATHS:
            node = payload
            try:
                for key in path:
                    node = node[key]
                if isinstance(node, list):
                    return node
            except (KeyError, TypeError):
                continue

        # Fallback: buscar la primera lista de dicts en el payload
        for v in payload.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
        return None
