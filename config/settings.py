"""
Configuración central del proyecto.

Carga variables de entorno (.env) y expone un objeto `settings` único, inmutable,
consumido por todo el código.

Uso:
    >>> from config import settings
    >>> settings.api.base_url
    'https://datos.gob.es/apidata'
    >>> settings.paths.raw_dir
    PosixPath('.../data_lake/00_raw')
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
#  Sub-secciones de configuración
# ---------------------------------------------------------------------------
class APISettings(BaseSettings):
    """Configuración del cliente de la API datos.gob.es."""

    base_url: str = Field(default="https://datos.gob.es/apidata", alias="DATOSGOB_BASE_URL")
    page_size: int = Field(default=50, alias="DATOSGOB_PAGE_SIZE", le=50)
    max_retries: int = Field(default=5, alias="DATOSGOB_MAX_RETRIES")
    timeout: int = Field(default=30, alias="DATOSGOB_TIMEOUT")
    rate_limit_per_sec: float = Field(default=4.0, alias="DATOSGOB_RATE_LIMIT_PER_SEC")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)


class PathSettings(BaseSettings):
    """Rutas del data lake."""

    data_lake_root: Path = Field(default=PROJECT_ROOT / "data_lake", alias="DATA_LAKE_ROOT")
    raw_dir: Path = Field(default=PROJECT_ROOT / "data_lake" / "00_raw", alias="RAW_DIR")
    staging_dir: Path = Field(
        default=PROJECT_ROOT / "data_lake" / "01_staging", alias="STAGING_DIR"
    )
    curated_dir: Path = Field(
        default=PROJECT_ROOT / "data_lake" / "02_curated", alias="CURATED_DIR"
    )
    features_dir: Path = Field(
        default=PROJECT_ROOT / "data_lake" / "03_features", alias="FEATURES_DIR"
    )
    models_dir: Path = Field(
        default=PROJECT_ROOT / "data_lake" / "04_models", alias="MODELS_DIR"
    )
    sqlite_path: Path = Field(
        default=PROJECT_ROOT / "data_lake" / "catalog.db", alias="SQLITE_PATH"
    )
    log_dir: Path = Field(default=PROJECT_ROOT / "logs", alias="LOG_DIR")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)


class LoggingSettings(BaseSettings):
    level: str = Field(default="INFO", alias="LOG_LEVEL")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)


class DashboardSettings(BaseSettings):
    port: int = Field(default=8501, alias="STREAMLIT_SERVER_PORT")
    theme: str = Field(default="light", alias="STREAMLIT_THEME")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)


# ---------------------------------------------------------------------------
#  Objeto settings agregador
# ---------------------------------------------------------------------------
class Settings:
    """Contenedor inmutable de la configuración completa del proyecto."""

    def __init__(self) -> None:
        self.project_root: Path = PROJECT_ROOT
        self.api = APISettings()
        self.paths = PathSettings()
        self.logging = LoggingSettings()
        self.dashboard = DashboardSettings()

        # Cargar catálogo de CCAA
        self.ccaa: list[dict] = self._load_ccaa_catalog()

    # --------------------------------------------------------------------
    def _load_ccaa_catalog(self) -> list[dict]:
        """Lee config/ccaa_catalog.yaml y devuelve la lista de CCAA."""
        path = PROJECT_ROOT / "config" / "ccaa_catalog.yaml"
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f)["ccaa"]

    def ccaa_codes(self) -> list[str]:
        """Lista de códigos slug de CCAA (p.ej. ['andalucia', 'aragon', ...])."""
        return [c["slug"] for c in self.ccaa]

    def ccaa_by_slug(self, slug: str) -> dict:
        for c in self.ccaa:
            if c["slug"] == slug:
                return c
        raise KeyError(f"CCAA desconocida: {slug}")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
