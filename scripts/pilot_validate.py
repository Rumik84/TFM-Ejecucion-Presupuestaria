"""
Piloto de validación end-to-end contra la API de datos.gob.es.

Ejecuta las 4 fases del pipeline para una CCAA concreta con un subconjunto
de datasets, y produce un informe de consistencia y explotabilidad.

Uso local:
    python scripts/pilot_validate.py --ccaa pais-vasco
    python scripts/pilot_validate.py --ccaa pais-vasco --only ingest
    python scripts/pilot_validate.py --ccaa pais-vasco --max-datasets 10 --max-distrib 2

Uso Docker:
    docker compose --profile validate run --rm validate
    docker compose --profile validate run --rm validate --only ingest
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests

from config import settings
from src.etl import Curator
from src.ingestion import CatalogCrawler, DatosGobClient, DistributionDownloader
from src.storage import SQLiteRepository
from src.utils import get_logger

logger = get_logger(__name__)

# ─────────────────────────────────────────────
#  Helpers de presentación
# ─────────────────────────────────────────────

SEP = "-" * 60


def _header(text: str) -> None:
    print(f"\n{SEP}")
    print(f"  {text}")
    print(SEP)


def _ok(msg: str) -> None:
    print(f"  ✓  {msg}")


def _warn(msg: str) -> None:
    print(f"  ⚠  {msg}")


def _fail(msg: str) -> None:
    print(f"  ✗  {msg}")


def _row(label: str, value: object) -> None:
    print(f"  {label:<30} {value}")


# ─────────────────────────────────────────────
#  Stage 0: Conectividad API
# ─────────────────────────────────────────────

def check_connectivity() -> bool:
    _header("Stage 0 — Conectividad API datos.gob.es")
    url = f"{settings.api.base_url}/catalog/dataset.json"
    try:
        t0 = time.time()
        resp = requests.get(url, params={"_pageSize": 1}, timeout=settings.api.timeout)
        elapsed = time.time() - t0
        resp.raise_for_status()
        _ok(f"API accesible  ({elapsed:.1f}s)  →  {url}")
        return True
    except Exception as exc:
        _fail(f"No se puede conectar a la API: {exc}")
        return False


# ─────────────────────────────────────────────
#  Stage 1: Ingesta del catálogo
# ─────────────────────────────────────────────

def run_ingest(ccaa_slug: str, min_score: int = 4) -> int:
    _header(f"Stage 1 — Ingesta catálogo  [{ccaa_slug}]")

    repo = SQLiteRepository()
    repo.init_schema()

    client = DatosGobClient()
    crawler = CatalogCrawler(client=client, repo=repo)

    df = crawler.crawl(min_score=min_score)

    if df.empty:
        _warn("No se encontraron datasets con score suficiente.")
        return 0

    df_ccaa = df[df["ccaa_slug"] == ccaa_slug] if "ccaa_slug" in df.columns else df

    _ok(f"Datasets totales ingestados:          {len(df)}")
    _ok(f"Datasets para '{ccaa_slug}':           {len(df_ccaa)}")

    if not df_ccaa.empty and "score_relevancia" in df_ccaa.columns:
        score_dist = df_ccaa["score_relevancia"].value_counts().sort_index(ascending=False)
        print("\n  Distribución de scores de relevancia:")
        for score, count in score_dist.items():
            print(f"    score={score:>2}  →  {count:>3} datasets")

    if not df_ccaa.empty and "titulo" in df_ccaa.columns:
        top = df_ccaa.nlargest(10, "score_relevancia") if "score_relevancia" in df_ccaa.columns else df_ccaa.head(10)
        print("\n  Top-10 datasets por relevancia:")
        for _, row in top.iterrows():
            titulo = str(row.get("titulo", ""))[:55]
            score = row.get("score_relevancia", "?")
            print(f"    [{score:>2}]  {titulo}")

    return len(df_ccaa)


# ─────────────────────────────────────────────
#  Stage 2: Descarga de distribuciones (muestra)
# ─────────────────────────────────────────────

def run_download(ccaa_slug: str, max_datasets: int, max_distrib: int) -> dict:
    _header(f"Stage 2 — Descarga de distribuciones  [{ccaa_slug}]  (max {max_datasets} datasets, {max_distrib} distrib/dataset)")

    repo = SQLiteRepository()
    client = DatosGobClient()
    downloader = DistributionDownloader(client=client, repo=repo)

    import sqlalchemy as sa
    with repo.connection() as conn:
        rows = conn.execute(
            sa.text(
                """
                SELECT cd.uri, cd.id, cd.publisher_id, cd.ccaa_slug, cd.score_relevancia
                FROM catalog_dataset cd
                WHERE cd.ccaa_slug = :slug AND cd.score_relevancia >= 4
                ORDER BY cd.score_relevancia DESC
                LIMIT :lim
                """
            ),
            {"slug": ccaa_slug, "lim": max_datasets},
        ).fetchall()

    if not rows:
        _warn(f"No hay datasets en SQLite para '{ccaa_slug}'. ¿Ejecutaste la fase ingest?")
        return {}

    _ok(f"Datasets a descargar: {len(rows)}")

    stats: dict[str, int] = {}
    total_bytes = 0

    for row in rows:
        dataset_uri = row[0]
        dataset_id = row[1]
        publisher_id = row[2] or ""

        try:
            records = downloader.download_for_dataset(
                dataset_uri=dataset_uri,
                dataset_id=dataset_id,
                ccaa_slug=ccaa_slug,
                publisher_id=publisher_id,
            )
            # Limitar distribuciones descargadas por dataset al máximo pedido
            records = records[:max_distrib]
            for rec in records:
                fmt = rec.get("formato", "UNKNOWN")
                stats[fmt] = stats.get(fmt, 0) + 1
                total_bytes += rec.get("file_size_bytes", 0) or 0
        except Exception as exc:
            logger.warning("Error descargando dataset %s: %s", dataset_id, exc)

    _ok(f"Archivos descargados:  {sum(stats.values())}")
    _ok(f"Tamaño total:          {total_bytes / 1_048_576:.1f} MB")

    if stats:
        print("\n  Distribución por formato:")
        for fmt, count in sorted(stats.items(), key=lambda x: -x[1]):
            print(f"    {fmt:<10} →  {count:>3} archivos")

    return stats


# ─────────────────────────────────────────────
#  Stage 3: ETL + validación
# ─────────────────────────────────────────────

def run_etl(ccaa_slug: str) -> dict:
    _header(f"Stage 3 — ETL + validación de esquema  [{ccaa_slug}]")

    curator = Curator()
    result = {"total_rows": 0, "valid_rows": 0, "errors": []}

    try:
        df_curated = curator.run_for_ccaa(ccaa_slug)
    except Exception as exc:
        _fail(f"Fallo en ETL: {exc}")
        result["errors"].append(str(exc))
        return result

    if df_curated is None or (hasattr(df_curated, "empty") and df_curated.empty):
        _warn("El curador no produjo datos. Verifica que existan distribuciones descargadas.")
        return result

    result["total_rows"] = len(df_curated)

    # Validación con pandera
    from src.etl import validate_fact_ejecucion
    try:
        df_valid = validate_fact_ejecucion(df_curated)
        result["valid_rows"] = len(df_valid)
        pct = result["valid_rows"] / max(result["total_rows"], 1) * 100
        _ok(f"Filas procesadas:  {result['total_rows']:>7,}")
        _ok(f"Filas válidas:     {result['valid_rows']:>7,}  ({pct:.1f}%)")
    except Exception as exc:
        _warn(f"Validación Pandera con errores: {exc}")
        result["valid_rows"] = result["total_rows"]
        result["errors"].append(str(exc))

    # Análisis exploratorio del DataFrame normalizado
    if not df_curated.empty:
        print("\n  ── Muestra de datos normalizados (5 filas) ──")
        sample_cols = [c for c in ["ccaa_slug", "anio", "capitulo_id", "fase", "importe_eur", "entidad_id"]
                       if c in df_curated.columns]
        print(df_curated[sample_cols].head(5).to_string(index=False))

        if "fase" in df_curated.columns:
            print("\n  ── Distribución por fase presupuestaria ──")
            fase_counts = df_curated["fase"].value_counts()
            for fase, cnt in fase_counts.items():
                print(f"    {fase:<6} →  {cnt:>7,} registros")

        if "anio" in df_curated.columns:
            years = sorted(df_curated["anio"].dropna().unique().tolist())
            print(f"\n  ── Años cubiertos: {years[0]} – {years[-1]}  ({len(years)} ejercicios) ──")

        if "capitulo_id" in df_curated.columns:
            print("\n  ── Capítulos económicos presentes ──")
            caps = sorted(df_curated["capitulo_id"].dropna().unique().tolist())
            print(f"    {caps}")

        if "importe_eur" in df_curated.columns:
            total_eur = df_curated["importe_eur"].sum()
            print(f"\n  ── Volumen total importes: {total_eur:,.0f} EUR ──")

    return result


# ─────────────────────────────────────────────
#  Stage 4: Informe final
# ─────────────────────────────────────────────

def print_final_report(ccaa_slug: str, n_datasets: int, fmt_stats: dict,
                       etl_result: dict) -> None:
    _header("Stage 4 — Informe final de explotabilidad")

    valid = etl_result.get("valid_rows", 0)
    total = etl_result.get("total_rows", 0)
    errors = etl_result.get("errors", [])
    pct = valid / max(total, 1) * 100

    _row("CCAA analizada:", ccaa_slug)
    _row("Datasets descubiertos:", n_datasets)
    _row("Formatos disponibles:", ", ".join(fmt_stats.keys()) if fmt_stats else "—")
    _row("Filas normalizadas:", f"{total:,}")
    _row("Filas válidas (esquema):", f"{valid:,}  ({pct:.1f}%)")
    _row("Errores de validación:", len(errors))

    print()
    if pct >= 80 and total > 0:
        _ok("CONCLUSIÓN: Datos EXPLOTABLES para entrenamiento de modelos ML.")
        _ok("  → Ejecutar siguiente fase: pipeline completo (features + train)")
    elif pct >= 50 and total > 0:
        _warn("CONCLUSIÓN: Datos PARCIALMENTE explotables. Revisar errores de normalización.")
    elif total == 0:
        _warn("CONCLUSIÓN: Sin datos normalizados. Verificar parsers y formatos disponibles.")
    else:
        _fail("CONCLUSIÓN: Datos con alta tasa de errores. Revisar normalizer.py y validator.py.")

    if errors:
        print("\n  Detalle de errores:")
        for e in errors[:3]:
            print(f"    · {str(e)[:100]}")


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Piloto de validación API + ETL — Ejecución Presupuestaria TFM"
    )
    ap.add_argument("--ccaa", default="pais-vasco",
                    help="Slug de la CCAA a analizar (default: pais-vasco)")
    ap.add_argument("--max-datasets", type=int, default=20,
                    help="Nº máximo de datasets a descargar (default: 20)")
    ap.add_argument("--max-distrib", type=int, default=3,
                    help="Distribuciones máximas por dataset (default: 3)")
    ap.add_argument("--only", choices=["all", "ingest", "download", "etl"],
                    default="all", help="Ejecutar solo una fase")
    ap.add_argument("--min-score", type=int, default=4,
                    help="Score mínimo de relevancia (default: 4)")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    ccaa = args.ccaa

    print(f"\n{'='*60}")
    print(f"  PILOTO VALIDACION -- {ccaa.upper()}")
    print(f"{'='*60}")
    print(f"  max_datasets={args.max_datasets}  max_distrib={args.max_distrib}  min_score={args.min_score}")

    # Stage 0 siempre
    if not check_connectivity():
        sys.exit(1)

    n_datasets = 0
    fmt_stats: dict = {}
    etl_result: dict = {"total_rows": 0, "valid_rows": 0, "errors": []}

    if args.only in ("all", "ingest"):
        n_datasets = run_ingest(ccaa, min_score=args.min_score)

    if args.only in ("all", "download"):
        fmt_stats = run_download(ccaa, args.max_datasets, args.max_distrib)

    if args.only in ("all", "etl"):
        etl_result = run_etl(ccaa)

    if args.only == "all":
        print_final_report(ccaa, n_datasets, fmt_stats, etl_result)

    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
