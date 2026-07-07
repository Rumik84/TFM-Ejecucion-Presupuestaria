"""
Crawler del catálogo de datos.gob.es.

Recorre las queries relevantes para el TFM (keyword=presupuesto, keyword=gastos,
keyword=ejecucion, theme=hacienda, spatial por CCAA, publisher por ID DIR3) y
persiste:

  1. Los JSON crudos de la API en data_lake/00_raw/{ccaa}/api_catalog/
  2. Un DataFrame consolidado de metadatos en la tabla SQLite `catalog_dataset`
     con deduplicación por URI.

El scoring de relevancia se calcula de forma análoga al usado para producir
el archivo Inventario_datasets_datos_gob_es.xlsx.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Iterable

import pandas as pd

from config import settings
from src.ingestion.api_client import DatosGobClient
from src.ingestion.ccaa_splitter import classify_ccaa
from src.storage import SQLiteRepository
from src.utils import get_logger, raw_path_for
from src.utils.paths import api_response_filename

logger = get_logger(__name__)


# Queries base del TFM (ajustar según el Resumen_datasets del inventario)
DEFAULT_QUERIES: list[tuple[str, str]] = [
    ("keyword", "presupuesto"),
    ("keyword", "gastos"),
    ("keyword", "ejecucion"),
    ("keyword", "liquidacion"),
    ("keyword", "obligaciones-reconocidas"),
    ("theme", "hacienda"),
    ("title", "presupuesto"),
    ("title", "ejecucion"),
]


# ---------------------------------------------------------------------------
#  Scoring de relevancia (heredado del inventario .xlsx)
# ---------------------------------------------------------------------------
RELEVANT_KEYWORDS = {
    "obligaciones reconocidas": 10,
    "liquidacion": 7,
    "ejecucion": 6,
    "presupuesto": 4,
    "gastos": 3,
    "credito definitivo": 5,
    "fases presupuestarias": 5,
}


def score_relevance(title: str, description: str | None = None) -> int:
    """Score simple por keywords ponderadas."""
    text = (title or "").lower()
    if description:
        text += " " + description.lower()
    return sum(weight for kw, weight in RELEVANT_KEYWORDS.items() if kw in text)


# ---------------------------------------------------------------------------
#  Crawler
# ---------------------------------------------------------------------------
class CatalogCrawler:
    def __init__(self, client: DatosGobClient | None = None, repo: SQLiteRepository | None = None):
        self.client = client or DatosGobClient()
        self.repo = repo or SQLiteRepository()

    # --------------------------------------------------------------
    def crawl(
        self,
        queries: Iterable[tuple[str, str]] | None = None,
        min_score: int = 4,
    ) -> pd.DataFrame:
        """Ejecuta todas las queries y devuelve un DataFrame consolidado."""
        queries = list(queries or DEFAULT_QUERIES)
        all_rows: list[dict] = []

        for kind, value in queries:
            logger.info("Crawling %s=%s", kind, value)
            method = {
                "keyword": self.client.datasets_by_keyword,
                "theme": self.client.datasets_by_theme,
                "title": self.client.datasets_by_title,
                "publisher": self.client.datasets_by_publisher,
            }.get(kind)
            if method is None:
                logger.warning("Tipo de query no soportado: %s", kind)
                continue

            for page_idx, payload in enumerate(method(value)):
                self._persist_raw(payload, kind=kind, value=value, page=page_idx)
                all_rows.extend(self._extract_rows(payload, kind=kind, value=value))

        df = pd.DataFrame(all_rows)
        if df.empty:
            logger.warning("No se obtuvieron datasets del catálogo")
            return df

        # Descartar filas sin URI (clave primaria obligatoria)
        df = df[df["uri"].notna() & (df["uri"] != "")].copy()
        df = df.drop_duplicates(subset=["uri"]).reset_index(drop=True)
        df["score_relevancia"] = df.apply(
            lambda r: score_relevance(r.get("titulo", ""), r.get("descripcion", "")),
            axis=1,
        )
        df = df[df["score_relevancia"] >= min_score].copy()
        df["ingested_at"] = datetime.utcnow().isoformat()

        logger.info("%d datasets relevantes (score>=%d)", len(df), min_score)
        self.repo.upsert_dataframe(df, table="catalog_dataset", if_exists="append")
        return df

    # --------------------------------------------------------------
    def _persist_raw(self, payload: dict, *, kind: str, value: str, page: int) -> None:
        """Guarda el JSON crudo en la carpeta del 'nacional' (no conocemos CCAA aún)."""
        path = raw_path_for("nacional", "api_catalog") / api_response_filename(kind, value, page)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # --------------------------------------------------------------
    def _extract_rows(self, payload: dict, *, kind: str, value: str) -> list[dict]:
        """Convierte la respuesta de la API en filas normalizadas."""
        items = payload.get("result", {}).get("items", []) or []
        rows: list[dict] = []
        for it in items:
            titulo = _extract_es_title(it.get("title", [])) or it.get("identifier") or ""
            descripcion = _extract_es_title(it.get("description", []))
            publisher_id = _extract_publisher_id(it.get("publisher"))
            ccaa_slug = classify_ccaa(publisher_id=publisher_id, spatial=it.get("spatial"))

            rows.append(
                {
                    "uri": it.get("_about") or it.get("identifier"),
                    "id": it.get("identifier"),
                    "titulo": titulo,
                    "descripcion": descripcion,
                    "publisher_id": publisher_id,
                    "ccaa_slug": ccaa_slug,
                    "issued": _extract_date(it.get("issued")),
                    "modified": _extract_date(it.get("modified")),
                    "raw_json_path": f"00_raw/{ccaa_slug}/api_catalog/",
                    "query_kind": kind,
                    "query_value": value,
                }
            )
        return rows


# ---------------------------------------------------------------------------
#  Helpers privados
# ---------------------------------------------------------------------------
def _extract_es_title(titles: list | str | None) -> str | None:
    if isinstance(titles, str):
        return titles
    if not titles:
        return None
    for t in titles:
        if isinstance(t, dict) and t.get("_lang") == "es":
            return t.get("_value")
    return titles[0].get("_value") if isinstance(titles[0], dict) else str(titles[0])


def _extract_publisher_id(publisher: str | dict | None) -> str | None:
    if publisher is None:
        return None
    if isinstance(publisher, str):
        return publisher.rstrip("/").split("/")[-1]
    return publisher.get("identifier")


def _extract_date(val: str | dict | None) -> str | None:
    if val is None:
        return None
    if isinstance(val, dict):
        return val.get("_value")
    return str(val)
