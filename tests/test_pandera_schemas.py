from datetime import datetime, timezone

import pandas as pd
import pandera.pandas as pa
import pytest

from energex.core import quality, schemas
from energex.core.exceptions import QualityGateError


def test_all_six_schemas_present_and_named():
    expected = {
        "OHLCV": schemas.OHLCV,
        "DATED_CONTRACTS": schemas.DATED_CONTRACTS,
        "EIA_GAS_STORAGE": schemas.EIA_GAS_STORAGE,
        "EIA_PETROLEUM": schemas.EIA_PETROLEUM,
        "ERCOT_DALMP": schemas.ERCOT_DALMP,
        "NOAA_HDDCDD": schemas.NOAA_HDDCDD,
    }
    for name, schema in expected.items():
        assert isinstance(schema, pa.DataFrameSchema)
        assert schema.name == name


def _gas_frame(values, valid_times):
    return pd.DataFrame(
        {
            "instrument_id": ["EIA.NG.STORAGE.LOWER48"] * len(values),
            "valid_time": pd.to_datetime(valid_times, utc=True),
            "value": values,
        }
    )


def test_validate_returns_coerced_frame_for_good_gas_storage():
    as_of = datetime(2026, 6, 11, 15, 30, tzinfo=timezone.utc)
    frame = _gas_frame([2100, 2150], ["2026-06-05", "2026-06-05"])
    # Make keys unique and value-coercible from int.
    frame.loc[1, "valid_time"] = pd.Timestamp("2026-05-29", tz="UTC")
    out = quality.validate(frame, schemas.EIA_GAS_STORAGE, as_of=as_of)
    assert out["value"].dtype == "float64"
    assert len(out) == 2


def test_validate_raises_quality_gate_error_with_failures():
    as_of = datetime(2026, 6, 11, 15, 30, tzinfo=timezone.utc)
    frame = _gas_frame([-5.0], ["2026-06-05"])  # negative storage is impossible
    with pytest.raises(QualityGateError) as ei:
        quality.validate(frame, schemas.EIA_GAS_STORAGE, as_of=as_of)
    assert ei.value.schema_name == "EIA_GAS_STORAGE"
    assert (ei.value.failures["column"] == "value").any()
