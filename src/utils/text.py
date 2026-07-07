"""Helpers de normalización de texto (slugs, limpieza, locales)."""
from __future__ import annotations

import re
import unicodedata


def slugify(value: str) -> str:
    """
    Convierte un texto a slug seguro para nombres de archivo y carpetas.
    'País Vasco' -> 'pais-vasco'
    """
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value


def parse_euro_amount(raw: str | float | int | None) -> float | None:
    """
    Convierte un importe en euros a float.

    Soporta formatos:
      - '1.234.567,89'  (europeo clásico)
      - '1,234,567.89'  (anglosajón)
      - '1234567.89'
      - con símbolos '€', 'EUR', espacios, 'miles', etc.

    Devuelve None si no es parseable.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)

    s = str(raw).strip()
    if not s or s.lower() in {"n/a", "nd", "-", "s/d"}:
        return None

    # Quitar símbolos
    s = re.sub(r"[€\s]|EUR", "", s, flags=re.IGNORECASE)

    # Decidir separador decimal
    if "," in s and "." in s:
        # El último símbolo que aparece es el decimal
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # Solo coma: asumir decimal europeo
        s = s.replace(".", "").replace(",", ".")
    # else: solo punto => ya está en formato anglosajón

    try:
        return float(s)
    except ValueError:
        return None
