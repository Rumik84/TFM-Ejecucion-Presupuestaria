import sqlite3
import pandas as pd

conn = sqlite3.connect("data_lake/catalog.db")

print("=== ASTURIAS OBR después de re-ETL ===")
sql = """
SELECT COUNT(*) as total, SUM(importe_eur) as total_eur,
       MAX(importe_eur) as max, AVG(importe_eur) as avg,
       SUM(CASE WHEN importe_eur > 1e10 THEN 1 ELSE 0 END) as n_corrupt
FROM fact_ejecucion_presupuestaria
WHERE ccaa_slug = 'asturias' AND fase = 'OBR'
"""
df = pd.read_sql(sql, conn)
pd.set_option("display.float_format", "{:.3e}".format)
print(df.to_string(index=False))

print("\n=== BRECHA PRE-OBR post-fix (2018-2025) ===")
sql2 = """
SELECT ccaa_slug, fase,
       SUM(importe_eur) as total_eur
FROM fact_ejecucion_presupuestaria
WHERE fase IN ('PRE','OBR') AND anio >= 2018
  AND ccaa_slug IN ('aragon','asturias','madrid','cataluna','pais-vasco',
                    'illes-balears','castilla-la-mancha','castilla-y-leon','nacional')
GROUP BY ccaa_slug, fase
ORDER BY ccaa_slug, fase
"""
df2 = pd.read_sql(sql2, conn)
pivot = df2.pivot(index="ccaa_slug", columns="fase", values="total_eur").fillna(0)
pivot["brecha"] = pivot["PRE"] - pivot["OBR"]
pivot["brecha_pct"] = pivot["brecha"] / pivot["PRE"] * 100
print(pivot[["PRE", "OBR", "brecha", "brecha_pct"]].to_string())

conn.close()
