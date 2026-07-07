"""Tests para el cliente de la API datos.gob.es."""
from unittest.mock import patch

from src.ingestion.api_client import DatosGobClient


def test_paginate_stops_when_items_lt_page_size():
    client = DatosGobClient()
    payload_p0 = {"result": {"items": [{"x": 1}] * 50}}
    payload_p1 = {"result": {"items": [{"x": 2}] * 10}}  # última página

    with patch.object(client, "_get", side_effect=[payload_p0, payload_p1]):
        pages = list(client.paginate("/catalog/dataset"))

    assert len(pages) == 2
    assert pages[1]["result"]["items"][0]["x"] == 2
