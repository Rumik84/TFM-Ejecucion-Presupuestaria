"""Parser de XML genérico (OData, DCAT, XBRL-ES simplificado)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from lxml import etree


class XMLParser:
    """Convierte XML a DataFrame. Por defecto extrae los nodos hoja que tienen
    estructura repetitiva (equivalente a 'tabla' en XML)."""

    def parse(self, path: Path) -> pd.DataFrame:
        tree = etree.parse(str(path))
        root = tree.getroot()

        # Heurística: elegir el elemento cuyo name se repite más veces
        tag_counts: dict[str, int] = {}
        for elem in root.iter():
            tag = etree.QName(elem).localname
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

        # Excluir la raíz; elegir el tag con mayor frecuencia y al menos 2 apariciones
        candidates = sorted(
            (t for t in tag_counts if t != etree.QName(root).localname and tag_counts[t] >= 2),
            key=lambda t: tag_counts[t],
            reverse=True,
        )
        if not candidates:
            return pd.DataFrame()

        tag = candidates[0]
        records = []
        for elem in root.iter():
            if etree.QName(elem).localname == tag:
                record = {etree.QName(c).localname: c.text for c in elem}
                record.update({f"@{k}": v for k, v in elem.attrib.items()})
                records.append(record)

        return pd.DataFrame(records)
