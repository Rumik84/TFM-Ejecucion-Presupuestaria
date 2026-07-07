"""Tests del normalizador de presupuestos."""
import pandas as pd

from src.etl.normalizer import BudgetNormalizer
from src.utils.text import parse_euro_amount


def test_parse_euro_amount_europeo():
    assert parse_euro_amount("1.234.567,89") == 1234567.89


def test_parse_euro_amount_anglosajon():
    assert parse_euro_amount("1,234,567.89") == 1234567.89


def test_parse_euro_amount_simbolo():
    assert parse_euro_amount("€ 123,45") == 123.45


def test_parse_euro_amount_none():
    assert parse_euro_amount(None) is None
    assert parse_euro_amount("") is None
    assert parse_euro_amount("N/A") is None


def test_normalizer_wide_to_long():
    raw = pd.DataFrame(
        {
            "anio": [2023, 2023],
            "capitulo": [1, 2],
            "importe_pre": [1000.0, 500.0],
            "importe_obr": [900.0, 480.0],
        }
    )
    norm = BudgetNormalizer(ccaa_slug="test", dataset_uri="test://").normalize(raw)
    assert not norm.empty
    assert set(norm["fase"].unique()).issubset({"PRE", "OBR"})
    assert (norm["ccaa_slug"] == "test").all()
