"""
Entry point unificado del pipeline.

Permite ejecutar por etapas o end-to-end desde consola:

    $ python scripts/run_pipeline.py                      # pipeline completo
    $ python scripts/run_pipeline.py --ccaa pais-vasco
    $ python scripts/run_pipeline.py --only ingest
    $ python scripts/run_pipeline.py --only etl --ccaa canarias aragon

Etapas disponibles: ingest | download | etl | features | train | all
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from flows.flow_build_features import build_features_flow  # noqa: E402
from flows.flow_download_distributions import download_distributions_flow  # noqa: E402
from flows.flow_etl_by_ccaa import etl_by_ccaa_flow  # noqa: E402
from flows.flow_ingest_catalog import ingest_catalog_flow  # noqa: E402
from flows.flow_main import main_pipeline  # noqa: E402
from flows.flow_train_models import train_models_flow  # noqa: E402


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Pipeline Ejecución Presupuestaria TFM")
    ap.add_argument(
        "--ccaa",
        nargs="+",
        default=None,
        help="Slugs de CCAA a procesar (por defecto: todas). 'all' = todas.",
    )
    ap.add_argument(
        "--only",
        choices=["ingest", "download", "etl", "features", "train", "all"],
        default="all",
    )
    ap.add_argument("--min-score", type=int, default=4)
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    slugs = None if (args.ccaa is None or "all" in args.ccaa) else args.ccaa

    if args.only == "all":
        main_pipeline(ccaa_slugs=slugs, min_score=args.min_score)
    elif args.only == "ingest":
        ingest_catalog_flow(min_score=args.min_score)
    elif args.only == "download":
        download_distributions_flow(ccaa_slugs=slugs)
    elif args.only == "etl":
        etl_by_ccaa_flow(ccaa_slugs=slugs)
    elif args.only == "features":
        build_features_flow(ccaa_slugs=slugs)
    elif args.only == "train":
        train_models_flow(ccaa_slugs=slugs)


if __name__ == "__main__":
    main()
