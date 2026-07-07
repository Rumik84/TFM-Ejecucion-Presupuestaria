"""
Validación del esquema canónico de hechos mediante pandera.

La validación garantiza que los datos que llegan a la capa CURATED cumplen
con el contrato del schema SQL. Si falla, el curado aborta para esa CCAA
y se registra el error en `pipeline_run`.
"""
from __future__ import annotations

import pandas as pd
import pandera as pa
from pandera import Column, Check, DataFrameSchema

VALID_FASES = {"PRE", "CRE", "ARN", "DIS", "OBR", "PAG"}


fact_ejecucion_schema = DataFrameSchema(
    columns={
        "ccaa_slug": Column(str, nullable=False),
        "entidad_id": Column(str, nullable=True),
        "anio": Column(int, Check.in_range(1980, 2100), nullable=False, coerce=True),
        "trimestre": Column(
            pd.Int64Dtype(),
            Check.isin([1, 2, 3, 4]),
            nullable=True,
            coerce=False,  # pre-convert below, avoid coerce issue with None
        ),
        "capitulo_id": Column(pd.Int64Dtype(), Check.in_range(0, 9), nullable=True, coerce=False),
        "grupo_funcional_id": Column(str, nullable=True),
        "fase": Column(str, Check.isin(list(VALID_FASES)), nullable=False),
        "importe_eur": Column(float, Check.ge(-1e12), nullable=False),
        "dataset_uri": Column(str, nullable=False),
    },
    strict=False,
    coerce=True,
)


def validate_fact_ejecucion(df: pd.DataFrame) -> pd.DataFrame:
    """Valida el DataFrame contra el esquema canónico. Lanza `SchemaError` si no cumple."""
    df = df.copy()
    # Pre-cast nullable integer cols to avoid pandera coerce issues with None
    for col in ("trimestre", "capitulo_id"):
        if col in df.columns:
            df[col] = pd.array(df[col], dtype=pd.Int64Dtype())
    return fact_ejecucion_schema.validate(df, lazy=True)
