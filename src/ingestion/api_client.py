"""
Cliente HTTP para la API datos.gob.es.

Documentación oficial: https://datos.gob.es/es/apidata

Endpoints soportados:
  /catalog/dataset                              -> catálogo general
  /catalog/dataset/{id}                         -> dataset por URI
  /catalog/dataset/title/{title}
  /catalog/dataset/publisher/{id}
  /catalog/dataset/theme/{id}
  /catalog/dataset/format/{format}
  /catalog/dataset/keyword/{keyword}
  /catalog/dataset/spatial/{word1}/{word2}
  /catalog/dataset/modified/begin/{begin}/end/{end}
  /catalog/distribution
  /catalog/distribution/dataset/{id}
  /catalog/distribution/format/{format}
  /catalog/publisher
  /catalog/theme
  /catalog/spatial
  /nti/territory/Province, /Autonomous-region, /Country
  /nti/public-sector

Características del cliente:
  - Rate limiting (ratelimit library) -> respetuoso con la API pública.
  - Reintentos con backoff exponencial (tenacity).
  - Paginación automática (_pageSize=50 es el máximo).
  - Formato de respuesta JSON por defecto (extensión .json).
"""
from __future__ import annotations

from typing import Any, Iterator
from urllib.parse import quote

import requests
from ratelimit import limits, sleep_and_retry
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import settings
from src.utils import get_logger

logger = get_logger(__name__)


class DatosGobAPIError(Exception):
    """Error al consumir la API datos.gob.es."""


class DatosGobClient:
    """Cliente de alto nivel para la API datos.gob.es."""

    def __init__(
        self,
        base_url: str | None = None,
        page_size: int | None = None,
        timeout: int | None = None,
    ):
        self.base_url = (base_url or settings.api.base_url).rstrip("/")
        self.page_size = page_size or settings.api.page_size
        self.timeout = timeout or settings.api.timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "EjecucionPresupuestariaTFM/0.1 (+https://github.com/)",
            }
        )

    # =====================================================================
    #  LOW-LEVEL GET con retries + rate limit
    # =====================================================================
    @sleep_and_retry
    @limits(calls=settings.api.rate_limit_per_sec, period=1)
    @retry(
        reraise=True,
        stop=stop_after_attempt(settings.api.max_retries),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        retry=retry_if_exception_type((requests.RequestException, DatosGobAPIError)),
    )
    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        """GET crudo con rate limit (4 req/s por defecto) y retries exponenciales."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        if not url.endswith(".json"):
            url += ".json"

        resp = self.session.get(url, params=params, timeout=self.timeout)
        if resp.status_code >= 500:
            raise DatosGobAPIError(f"HTTP {resp.status_code} en {url}")
        resp.raise_for_status()
        return resp.json()

    # =====================================================================
    #  PAGINACIÓN
    # =====================================================================
    def paginate(
        self,
        path: str,
        extra_params: dict[str, Any] | None = None,
        max_pages: int | None = None,
    ) -> Iterator[dict]:
        """Itera todas las páginas de un endpoint. Devuelve el JSON de cada página."""
        page = 0
        while True:
            params: dict[str, Any] = {"_pageSize": self.page_size, "_page": page}
            if extra_params:
                params.update(extra_params)

            payload = self._get(path, params=params)
            yield payload

            items = payload.get("result", {}).get("items", []) or []
            if len(items) < self.page_size:
                break
            page += 1
            if max_pages is not None and page >= max_pages:
                break

    # =====================================================================
    #  ENDPOINTS DE ALTO NIVEL
    # =====================================================================
    # --- Catálogo ---
    def list_datasets(self, sort: str = "-modified") -> Iterator[dict]:
        yield from self.paginate("/catalog/dataset", {"_sort": sort})

    def datasets_by_keyword(self, keyword: str) -> Iterator[dict]:
        yield from self.paginate(f"/catalog/dataset/keyword/{quote(keyword)}")

    def datasets_by_theme(self, theme: str) -> Iterator[dict]:
        yield from self.paginate(f"/catalog/dataset/theme/{quote(theme)}")

    def datasets_by_spatial(self, word1: str, word2: str) -> Iterator[dict]:
        yield from self.paginate(f"/catalog/dataset/spatial/{quote(word1)}/{quote(word2)}")

    def datasets_by_publisher(self, publisher_id: str) -> Iterator[dict]:
        yield from self.paginate(f"/catalog/dataset/publisher/{quote(publisher_id)}")

    def datasets_by_title(self, title: str) -> Iterator[dict]:
        yield from self.paginate(f"/catalog/dataset/title/{quote(title)}")

    def datasets_modified_between(self, begin: str, end: str) -> Iterator[dict]:
        """begin/end en formato AAAA-MM-DDTHH:mmZ."""
        yield from self.paginate(
            f"/catalog/dataset/modified/begin/{begin}/end/{end}"
        )

    def get_dataset(self, dataset_id: str) -> dict:
        return self._get(f"/catalog/dataset/{quote(dataset_id)}")

    # --- Distribuciones ---
    def distributions_of(self, dataset_id: str) -> Iterator[dict]:
        yield from self.paginate(f"/catalog/distribution/dataset/{quote(dataset_id)}")

    # --- Taxonomías NTI ---
    def list_autonomous_regions(self) -> dict:
        return self._get("/nti/territory/Autonomous-region")

    def list_provinces(self) -> dict:
        return self._get("/nti/territory/Province")

    def list_public_sectors(self) -> dict:
        return self._get("/nti/public-sector")
