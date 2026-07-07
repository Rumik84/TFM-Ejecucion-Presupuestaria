"""Tests del clasificador de CCAA."""
from src.ingestion.ccaa_splitter import classify_ccaa


def test_publisher_direct_mapping():
    # E05250001 es MINHAP => 'nacional'
    assert classify_ccaa(publisher_id="E05250001") == "nacional"


def test_publisher_ine_heuristic_madrid():
    # L01280066 = Ayto. Madrid (prov. 28)
    assert classify_ccaa(publisher_id="L01280066") == "madrid"


def test_publisher_ine_heuristic_pais_vasco():
    # L01200006 (prov. 20 = Gipuzkoa)
    assert classify_ccaa(publisher_id="L01200006") == "pais-vasco"


def test_agregador_pais_vasco():
    assert classify_ccaa(publisher_id="L02000020") == "pais-vasco"


def test_fallback_nacional():
    assert classify_ccaa(publisher_id=None, spatial=None) == "nacional"


def test_spatial_matching():
    assert classify_ccaa(spatial="http://datos.gob.es/.../Pais-Vasco") == "pais-vasco"
