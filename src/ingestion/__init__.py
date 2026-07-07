"""
Capa de ingesta: descubrimiento y descarga de datasets desde datos.gob.es.

Módulos:
  - api_client: cliente REST con rate limiting y reintentos.
  - catalog_crawler: descubre datasets relevantes (keyword/theme/spatial/publisher).
  - distribution_downloader: descarga los archivos (CSV/XLSX/JSON/XML/PC-AXIS).
  - ccaa_splitter: asigna cada dataset a una o varias CCAA según su ámbito territorial.
"""
from src.ingestion.api_client import DatosGobClient  # noqa: F401
from src.ingestion.catalog_crawler import CatalogCrawler  # noqa: F401
from src.ingestion.distribution_downloader import DistributionDownloader  # noqa: F401
from src.ingestion.ccaa_splitter import classify_ccaa  # noqa: F401
