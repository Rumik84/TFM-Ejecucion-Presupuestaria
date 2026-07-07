"""Diagnóstico final: cuándo se cargaron los valores corruptos de Asturias."""
import sqlite3
import pandas as pd

conn = sqlite3.connect("data_lake/catalog.db")

print("=== Fechas de carga de filas corruptas (importe > 1e10) ===")
sql = """
SELECT loaded_at, COUNT(*) as n, SUM(importe_eur) as total
FROM fact_ejecucion_presupuestaria
WHERE ccaa_slug = 'asturias' AND importe_eur > 1e10
GROUP BY loaded_at
ORDER BY loaded_at
"""
df = pd.read_sql(sql, conn)
pd.set_option("display.float_format", "{:.2e}".format)
print(df.to_string(index=False))

print("\n=== Fechas de carga normales (asturias OBR 2018-2025, < 1e10) ===")
sql2 = """
SELECT loaded_at, COUNT(*) as n, AVG(importe_eur) as avg
FROM fact_ejecucion_presupuestaria
WHERE ccaa_slug = 'asturias' AND fase = 'OBR'
  AND anio >= 2018 AND importe_eur < 1e10
GROUP BY loaded_at
ORDER BY loaded_at
"""
df2 = pd.read_sql(sql2, conn)
print(df2.to_string(index=False))

print("\n=== JSON parser - qué produce en Avilés 2021 ===")
import sys
from pathlib import Path
sys.path.insert(0, ".")
from src.etl.parsers.json_parser import JSONParser

p = Path("data_lake/00_raw/asturias/distributions/L01330045/https___datos.aviles.es_dataset_ejecucio__edacea51__6dd931d8-213e-45f8-9c2b-1bb173cdc91c")
if p.exists():
    try:
        raw = JSONParser().parse(p)
        print(f"JSON parser OK: {raw.shape}")
        print(raw.dtypes)
        print(raw.head(3).to_string())
    except Exception as e:
        print(f"JSON parser error: {e}")
        # Ver el contenido raw del JSON
        with open(p, "rb") as f:
            content = f.read(500)
        print(f"JSON contenido: {content}")
else:
    print(f"Archivo no encontrado: {p}")

conn.close()
