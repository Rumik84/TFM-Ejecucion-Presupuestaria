"""
Helpers para construir rutas del data lake de forma coherente.

Todas las rutas del data lake siguen el patrón:

    data_lake/{capa}/{ccaa}/{...}

donde capa ∈ {00_raw, 01_staging, 02_curated, 03_features, 04_models}.
"""
from __future__ import annotations

from pathlib import Path

from config import settings


def ensure_dir(path: Path) -> Path:
    """Crea el directorio si no existe (incluyendo padres) y lo devuelve."""
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
#  Rutas por capa y CCAA
# ---------------------------------------------------------------------------
def raw_path_for(ccaa_slug: str, subdir: str | None = None) -> Path:
    """Devuelve la ruta RAW para una CCAA. `subdir` puede ser 'api_catalog' o 'distributions'."""
    p = settings.paths.raw_dir / ccaa_slug
    if subdir:
        p = p / subdir
    return ensure_dir(p)


def staging_path_for(ccaa_slug: str) -> Path:
    return ensure_dir(settings.paths.staging_dir / ccaa_slug)


def curated_path_for(ccaa_slug: str) -> Path:
    return ensure_dir(settings.paths.curated_dir / ccaa_slug)


def features_path_for(ccaa_slug: str) -> Path:
    return ensure_dir(settings.paths.features_dir / ccaa_slug)


def models_path() -> Path:
    return ensure_dir(settings.paths.models_dir)


# ---------------------------------------------------------------------------
#  Nombres de archivo canónicos
# ---------------------------------------------------------------------------
def api_response_filename(query_kind: str, query_value: str, page: int) -> str:
    """
    query_kind: 'keyword' | 'theme' | 'spatial' | 'publisher' | 'modified'
    query_value: valor del parámetro (p. ej. 'presupuesto', 'Pais-Vasco')
    page: número de página
    """
    safe_value = query_value.replace("/", "_").replace(" ", "_")
    return f"{query_kind}__{safe_value}__p{page:04d}.json"
