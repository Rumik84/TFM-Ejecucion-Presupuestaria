"""
Descarga de distribuciones (archivos adjuntos) de los datasets relevantes.

Dado un dataset URI, consulta /catalog/distribution/dataset/{id} y descarga
cada distribución a data_lake/00_raw/{ccaa}/distributions/{publisher}/{filename}.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings
from src.ingestion.api_client import DatosGobClient
from src.storage import SQLiteRepository
from src.utils import get_logger, raw_path_for

logger = get_logger(__name__)


class DistributionDownloader:
    SUPPORTED_FORMATS = {"CSV", "XLSX", "XLS", "JSON", "XML", "TSV", "PC-AXIS", "PX", "RDF"}

    def __init__(self, client: DatosGobClient | None = None, repo: SQLiteRepository | None = None):
        self.client = client or DatosGobClient()
        self.repo = repo or SQLiteRepository()

    # --------------------------------------------------------------
    def download_for_dataset(
        self,
        dataset_uri: str,
        dataset_id: str,
        ccaa_slug: str,
        publisher_id: str | None,
    ) -> list[dict]:
        """Descarga todas las distribuciones del dataset. Persiste metadatos en SQLite."""
        records: list[dict] = []
        publisher_dir = raw_path_for(ccaa_slug, "distributions") / (publisher_id or "unknown")
        publisher_dir.mkdir(parents=True, exist_ok=True)

        # La API de distribuciones necesita el identificador corto (último segmento de _about).
        # dataset_uri = "http://datos.gob.es/apidata/catalog/dataset/{short-id}"
        # dataset_id  = URI larga del identifier → no funciona en el endpoint de distribuciones
        short_id = (dataset_uri or "").rstrip("/").split("/")[-1] if dataset_uri else dataset_id
        if not short_id:
            return records

        for page in self.client.distributions_of(short_id):
            for dist in page.get("result", {}).get("items", []) or []:
                fmt = _normalize_format(dist.get("format"))
                if fmt not in self.SUPPORTED_FORMATS:
                    continue

                access_url = dist.get("accessURL") or dist.get("downloadURL")
                if not access_url:
                    continue

                try:
                    local_path = self._download_file(access_url, publisher_dir, fmt, dataset_id)
                    checksum = _md5(local_path)
                    records.append(
                        {
                            "dataset_uri": dataset_uri,
                            "formato": fmt,
                            "access_url": access_url,
                            "download_url": dist.get("downloadURL"),
                            "byte_size": dist.get("byteSize"),
                            "local_path": str(local_path.relative_to(settings.paths.data_lake_root)),
                            "downloaded_at": datetime.utcnow().isoformat(),
                            "checksum_md5": checksum,
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Fallo descargando %s: %s", access_url, exc)

        if records:
            import pandas as pd

            self.repo.upsert_dataframe(
                pd.DataFrame(records), table="catalog_distribution", if_exists="append"
            )
        return records

    # --------------------------------------------------------------
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
    def _download_file(self, url: str, out_dir: Path, fmt: str, dataset_id: str) -> Path:
        """Descarga `url` a disco de forma ATÓMICA y verificada. Devuelve la ruta local.

        Integridad: se escribe a un fichero temporal `.part` y solo se renombra al
        nombre final si la descarga se completa. Si el servidor anuncia `Content-Length`
        (y la respuesta no viene comprimida), se comprueba que los bytes escritos
        coinciden; si no, se descarta el parcial y se lanza excepción para que `@retry`
        reintente. Así una descarga truncada (corte de red) NUNCA queda como fichero
        válido en disco (bug que dejó Canarias 2015 e Illes Balears incompletos).
        """
        fname = _safe_filename(url, fmt, dataset_id)
        out = out_dir / fname
        if out.exists():
            logger.debug("Ya existe, se omite: %s", out)
            return out

        tmp = out.with_name(out.name + ".part")
        with requests.get(url, stream=True, timeout=settings.api.timeout) as r:
            r.raise_for_status()
            expected = r.headers.get("Content-Length")
            expected = int(expected) if expected and expected.isdigit() else None
            # Content-Length se refiere al cuerpo comprimido; si viene gzip/deflate,
            # iter_content entrega bytes descomprimidos y no cuadraría → no verificar.
            encoding = (r.headers.get("Content-Encoding") or "").lower().strip()
            verify = expected is not None and encoding in ("", "identity")
            written = 0
            with tmp.open("wb") as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    f.write(chunk)
                    written += len(chunk)

        if verify and written != expected:
            tmp.unlink(missing_ok=True)
            raise OSError(
                f"Descarga truncada de {url}: {written} de {expected} bytes "
                f"({written / expected:.0%})"
            )
        tmp.replace(out)  # rename atómico: el fichero final solo aparece si está completo
        logger.info("Descargado %s (%d bytes)", out, out.stat().st_size)
        return out


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------
_FORMAT_MAP = {
    "text/csv": "CSV",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "XLSX",
    "application/vnd.ms-excel": "XLS",
    "application/json": "JSON",
    "application/xml": "XML",
    "text/xml": "XML",
    "application/rdf+xml": "RDF",
    "text/tab-separated-values": "TSV",
    "application/x-pc-axis": "PC-AXIS",
}


def _normalize_format(fmt: str | dict | None) -> str:
    if not fmt:
        return "UNKNOWN"
    # La API devuelve format como dict: {"_about": "...", "type": "...", "value": "text/csv"}
    # Prioridad: value (MIME type) > label > _about (URL del recurso, no útil)
    if isinstance(fmt, dict):
        fmt = fmt.get("value") or fmt.get("label") or ""
    if not fmt:
        return "UNKNOWN"
    fmt_lower = str(fmt).lower().strip()
    if fmt_lower in _FORMAT_MAP:
        return _FORMAT_MAP[fmt_lower]
    return fmt_lower.split("/")[-1].upper()


def _safe_filename(url: str, fmt: str, dataset_id: str | None) -> str:
    parsed = urlparse(url)
    tail = Path(parsed.path).name or "data"
    # Include a short hash of the full URL to avoid collisions when multiple formats share the same tail
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    safe_id = re.sub(r'[\\/:*?"<>|]', '_', (dataset_id or "unknown")[:40])
    return f"{safe_id}__{url_hash}__{tail}"


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
