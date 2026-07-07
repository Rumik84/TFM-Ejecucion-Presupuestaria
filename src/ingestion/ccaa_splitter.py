"""
Clasificador de datasets por Comunidad Autónoma.

Heurística de asignación (ordenada):
  1. Publisher ID DIR3 explícitamente declarado en `config/ccaa_catalog.yaml`.
  2. Coincidencia en el prefijo del ID del publicador (ej. 'L01' + código INE provincia).
  3. Campo `spatial` del dataset (URI NTI de autonomía o provincia).
  4. Fallback: 'nacional'.
"""
from __future__ import annotations

from functools import lru_cache

from config import settings
from src.utils import get_logger

logger = get_logger(__name__)

# Códigos INE de provincia -> CCAA slug (para detectar L01{INE_PROV}{CODMUN})
_INE_PROVINCE_TO_CCAA: dict[str, str] = {
    "01": "pais-vasco", "20": "pais-vasco", "48": "pais-vasco",
    "04": "andalucia", "11": "andalucia", "14": "andalucia", "18": "andalucia",
    "21": "andalucia", "23": "andalucia", "29": "andalucia", "41": "andalucia",
    "22": "aragon", "44": "aragon", "50": "aragon",
    "33": "asturias",
    "07": "illes-balears",
    "35": "canarias", "38": "canarias",
    "39": "cantabria",
    "02": "castilla-la-mancha", "13": "castilla-la-mancha",
    "16": "castilla-la-mancha", "19": "castilla-la-mancha", "45": "castilla-la-mancha",
    "05": "castilla-y-leon", "09": "castilla-y-leon", "24": "castilla-y-leon",
    "34": "castilla-y-leon", "37": "castilla-y-leon", "40": "castilla-y-leon",
    "42": "castilla-y-leon", "47": "castilla-y-leon", "49": "castilla-y-leon",
    "08": "cataluna", "17": "cataluna", "25": "cataluna", "43": "cataluna",
    "03": "comunidad-valenciana", "12": "comunidad-valenciana", "46": "comunidad-valenciana",
    "06": "extremadura", "10": "extremadura",
    "15": "galicia", "27": "galicia", "32": "galicia", "36": "galicia",
    "28": "madrid",
    "30": "murcia",
    "31": "navarra",
    "26": "la-rioja",
    "51": "ceuta",
    "52": "melilla",
}


@lru_cache(maxsize=1)
def _publisher_to_ccaa_map() -> dict[str, str]:
    """Construye el índice publisher_id -> ccaa_slug desde el catálogo YAML."""
    result: dict[str, str] = {}
    for ccaa in settings.ccaa:
        for publisher in ccaa.get("publishers", []) or []:
            result[publisher] = ccaa["slug"]
    return result


@lru_cache(maxsize=1)
def _spatial_to_ccaa_map() -> dict[str, str]:
    """Índice uri_nti -> ccaa_slug."""
    return {ccaa["uri_nti"]: ccaa["slug"] for ccaa in settings.ccaa}


def classify_ccaa(
    publisher_id: str | None = None,
    spatial: str | list | None = None,
) -> str:
    """Devuelve el slug de la CCAA a la que pertenece el dataset. 'nacional' si no se puede determinar."""
    # 1. Publisher ID directo
    if publisher_id:
        m = _publisher_to_ccaa_map()
        if publisher_id in m:
            return m[publisher_id]

        # 2. Heurística por prefijo L01{INE_PROV} (entidades locales)
        if publisher_id.startswith("L01") and len(publisher_id) >= 5:
            prov = publisher_id[3:5]
            if prov in _INE_PROVINCE_TO_CCAA:
                return _INE_PROVINCE_TO_CCAA[prov]
        if publisher_id.startswith("L02"):
            # L02000020 = Agregador País Vasco
            return "pais-vasco"

    # 3. Campo spatial
    if spatial:
        m = _spatial_to_ccaa_map()
        spatials = spatial if isinstance(spatial, list) else [spatial]
        for s in spatials:
            s_str = s if isinstance(s, str) else str(s)
            for uri_nti, slug in m.items():
                if uri_nti in s_str:
                    return slug

    # 4. Fallback
    return "nacional"
