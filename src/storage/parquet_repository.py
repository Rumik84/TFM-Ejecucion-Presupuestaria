"""
Repositorio Parquet (capas staging, curated y features).

Convenciones:
  - Un dataset lógico se guarda como `{capa}/{ccaa}/{nombre}.parquet` o,
    si es particionable, como directorio Hive-style `{nombre}/anio=YYYY/part.parquet`.
  - Se usa pyarrow como engine por su mejor soporte de tipos y compresión snappy.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from src.utils import get_logger

logger = get_logger(__name__)


class ParquetRepository:
    """Escritura/lectura de Parquet con convenciones del data lake."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------
    def write(
        self,
        df: pd.DataFrame,
        name: str,
        partition_cols: list[str] | None = None,
        compression: str = "snappy",
    ) -> Path:
        """Persiste un DataFrame como Parquet.

        Si `partition_cols` se indica, se escribe en formato Hive-style (directorio).
        """
        if df.empty:
            logger.warning("DataFrame vacío, no se escribe Parquet para %s", name)
            return self.base_dir / f"{name}.parquet"

        if partition_cols:
            target = self.base_dir / name
            # Remove stale partition files so re-runs don't accumulate duplicates.
            if target.exists():
                shutil.rmtree(target)
            df.to_parquet(
                target,
                engine="pyarrow",
                compression=compression,
                partition_cols=partition_cols,
                index=False,
            )
        else:
            target = self.base_dir / f"{name}.parquet"
            df.to_parquet(target, engine="pyarrow", compression=compression, index=False)

        logger.info("Parquet escrito: %s (%d filas)", target, len(df))
        return target

    # ---------------------------------------------------------------
    def read(self, name: str, filters: list[tuple] | None = None) -> pd.DataFrame:
        """Lee un Parquet (archivo o directorio particionado)."""
        path = self.base_dir / f"{name}.parquet"
        if not path.exists():
            path = self.base_dir / name  # directorio particionado

        if not path.exists():
            raise FileNotFoundError(f"Parquet no encontrado: {name} en {self.base_dir}")

        return pd.read_parquet(path, engine="pyarrow", filters=filters)

    # ---------------------------------------------------------------
    def list_datasets(self) -> list[str]:
        """Lista los nombres de dataset (sin extensión) presentes en base_dir."""
        result = []
        for p in self.base_dir.iterdir():
            if p.suffix == ".parquet":
                result.append(p.stem)
            elif p.is_dir() and any(p.glob("**/*.parquet")):
                result.append(p.name)
        return sorted(result)
