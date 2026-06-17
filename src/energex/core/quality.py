"""Pre-write quality gate: run a pandera schema, fail loud on any violation.

This is the GATE path. The post-hoc audit path (analysis/quality.py's
DataQualityChecker) is unrelated and unchanged — no rename, no import shim.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pandera.pandas as pa

from energex.core import schemas
from energex.core.exceptions import QualityGateError


def validate(frame: pd.DataFrame, schema: pa.DataFrameSchema, *, as_of: datetime) -> pd.DataFrame:
    """Validate ``frame`` against ``schema`` and return the coerced frame.

    ``as_of`` (the knowledge timestamp) is threaded to the freshness wide-check
    via a ContextVar. Schema-specific preprocessors (e.g. the NOAA -9999.
    sentinel -> NULL) run BEFORE validation. ``lazy=True`` collects every
    violation; any failure raises ``QualityGateError`` carrying failure_cases.
    """
    pre = schemas.PREPROCESSORS.get(schema.name)
    if pre is not None:
        frame = pre(frame)
    token = schemas.AS_OF.set(as_of)
    try:
        return schema.validate(frame, lazy=True)
    except pa.errors.SchemaErrors as exc:
        raise QualityGateError(schema_name=schema.name, failures=exc.failure_cases) from exc
    finally:
        schemas.AS_OF.reset(token)
