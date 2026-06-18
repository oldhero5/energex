from datetime import datetime, timezone

import pandas as pd
import pandera.pandas as pa
import pytest

from energex.core import quality, schemas
from energex.core.exceptions import QualityGateError


def test_all_seven_schemas_present_and_named():
    expected = {
        "OHLCV": schemas.OHLCV,
        "DATED_CONTRACTS": schemas.DATED_CONTRACTS,
        "EIA_GAS_STORAGE": schemas.EIA_GAS_STORAGE,
        "EIA_PETROLEUM": schemas.EIA_PETROLEUM,
        "ERCOT_DALMP": schemas.ERCOT_DALMP,
        "NOAA_HDDCDD": schemas.NOAA_HDDCDD,
        "FRED_SPOT": schemas.FRED_SPOT,
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


AS_OF = datetime(2026, 6, 11, 15, 30, tzinfo=timezone.utc)


def _ohlcv(rows, valid_times):
    return pd.DataFrame(
        {
            "instrument_id": ["CME.CL.FRONT"] * rows,
            "valid_time": pd.to_datetime(valid_times, utc=True),
            "Open": [70.0] * rows,
            "High": [71.0] * rows,
            "Low": [69.0] * rows,
            "Close": [70.5] * rows,
            "Volume": [1000] * rows,
        }
    )


def test_ohlcv_pass_returns_coerced_frame():
    frame = _ohlcv(2, ["2026-06-11T14:00:00Z", "2026-06-11T14:01:00Z"])
    frame["Volume"] = frame["Volume"].astype("float64")  # coercion target int64
    out = quality.validate(frame, schemas.OHLCV, as_of=AS_OF)
    assert out["Volume"].dtype == "int64"
    assert len(out) == 2


def test_ohlcv_fail_negative_price_blocked():
    frame = _ohlcv(1, ["2026-06-11T14:00:00Z"])
    frame.loc[0, "Low"] = -1.0
    with pytest.raises(QualityGateError) as ei:
        quality.validate(frame, schemas.OHLCV, as_of=AS_OF)
    assert (ei.value.failures["column"] == "Low").any()


def _dated(rows):
    return pd.DataFrame(
        {
            "instrument_id": ["CME.CL.CLF26"] * rows,
            "valid_time": pd.to_datetime(["2026-06-11T00:00:00Z"] * rows, utc=True),
            "ContractMonth": ["2026-01-01"] * rows,
            "Open": [70.0] * rows,
            "High": [71.0] * rows,
            "Low": [69.0] * rows,
            "Close": [70.5] * rows,
            "Volume": [10] * rows,
        }
    )


def test_dated_contracts_pass_coerces_contract_month():
    frame = _dated(1)
    out = quality.validate(frame, schemas.DATED_CONTRACTS, as_of=AS_OF)
    assert out["ContractMonth"].dtype == "datetime64[ns]"


def test_dated_contracts_fail_duplicate_keys_blocked():
    frame = _dated(2)  # identical (instrument_id, valid_time) rows
    with pytest.raises(QualityGateError) as ei:
        quality.validate(frame, schemas.DATED_CONTRACTS, as_of=AS_OF)
    checks = ei.value.failures["check"].astype(str)
    assert checks.str.contains("not unique").any()


def test_eia_petroleum_pass():
    frame = pd.DataFrame(
        {
            "instrument_id": ["EIA.PET.CRUDE.STOCKS"],
            "valid_time": pd.to_datetime(["2026-06-05"], utc=True),
            "value": [430_000.0],
        }
    )
    out = quality.validate(frame, schemas.EIA_PETROLEUM, as_of=AS_OF)
    assert len(out) == 1


def test_eia_petroleum_fail_empty_frame_blocked():
    frame = pd.DataFrame(
        {
            "instrument_id": pd.Series([], dtype=str),
            "valid_time": pd.Series([], dtype="datetime64[ns, UTC]"),
            "value": pd.Series([], dtype=float),
        }
    )
    with pytest.raises(QualityGateError) as ei:
        quality.validate(frame, schemas.EIA_PETROLEUM, as_of=AS_OF)
    checks = ei.value.failures["check"].astype(str)
    assert checks.str.contains("row-count below floor").any()


def _fred_frame(values, instrument_ids, valid_times):
    return pd.DataFrame(
        {
            "instrument_id": instrument_ids,
            "valid_time": pd.to_datetime(valid_times, utc=True),
            "value": values,
        }
    )


def test_fred_spot_pass_multi_instrument():
    as_of = datetime(2026, 6, 17, 14, 30, tzinfo=timezone.utc)
    frame = _fred_frame(
        [84.65, 84.36, 3.06],
        ["FRED.WTI.SPOT", "FRED.BRENT.SPOT", "FRED.HENRYHUB.SPOT"],
        ["2026-06-15", "2026-06-15", "2026-06-15"],
    )
    out = quality.validate(frame, schemas.FRED_SPOT, as_of=as_of)
    assert out["value"].dtype == "float64"
    assert len(out) == 3


def test_fred_spot_fail_negative_price_blocked():
    as_of = datetime(2026, 6, 17, 14, 30, tzinfo=timezone.utc)
    frame = _fred_frame([-1.0], ["FRED.WTI.SPOT"], ["2026-06-15"])
    with pytest.raises(QualityGateError) as ei:
        quality.validate(frame, schemas.FRED_SPOT, as_of=as_of)
    assert ei.value.schema_name == "FRED_SPOT"
    assert (ei.value.failures["column"] == "value").any()


def test_fred_spot_fail_stale_valid_time_blocked():
    as_of = datetime(2026, 6, 17, 14, 30, tzinfo=timezone.utc)
    frame = _fred_frame([84.65], ["FRED.WTI.SPOT"], ["2026-05-01"])  # weeks stale
    with pytest.raises(QualityGateError) as ei:
        quality.validate(frame, schemas.FRED_SPOT, as_of=as_of)
    checks = ei.value.failures["check"].astype(str)
    assert checks.str.contains("staler than").any()


def test_ercot_dalmp_pass_allows_negative_pricing():
    frame = pd.DataFrame(
        {
            "instrument_id": ["ERCOT.DALMP.HB_HOUSTON", "ERCOT.DALMP.HB_HOUSTON"],
            "valid_time": pd.to_datetime(
                ["2026-06-10T00:00:00Z", "2026-06-10T01:00:00Z"], utc=True
            ),
            "lmp": [-15.0, 42.5],  # negative LMP is real and must pass
        }
    )
    out = quality.validate(frame, schemas.ERCOT_DALMP, as_of=AS_OF)
    assert len(out) == 2


def test_ercot_dalmp_fail_absurd_lmp_blocked():
    frame = pd.DataFrame(
        {
            "instrument_id": ["ERCOT.DALMP.HB_HOUSTON"],
            "valid_time": pd.to_datetime(["2026-06-10T00:00:00Z"], utc=True),
            "lmp": [999_999.0],  # outside the sane band
        }
    )
    with pytest.raises(QualityGateError) as ei:
        quality.validate(frame, schemas.ERCOT_DALMP, as_of=AS_OF)
    assert (ei.value.failures["column"] == "lmp").any()


def test_noaa_hddcdd_pass_coerces_sentinel_to_null():
    frame = pd.DataFrame(
        {
            "instrument_id": ["NOAA.HDD.TX", "NOAA.HDD.TX"],
            "valid_time": pd.to_datetime(
                ["2026-05-01T00:00:00Z", "2026-04-01T00:00:00Z"], utc=True
            ),
            "hdd": [120.0, -9999.0],  # sentinel -> NULL before the 0-9999 check
            "cdd": [80.0, 60.0],
        }
    )
    as_of = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
    out = quality.validate(frame, schemas.NOAA_HDDCDD, as_of=as_of)
    assert out["hdd"].isna().sum() == 1  # sentinel became NULL, did not fail range


def test_noaa_hddcdd_fail_out_of_range_blocked():
    frame = pd.DataFrame(
        {
            "instrument_id": ["NOAA.HDD.TX"],
            "valid_time": pd.to_datetime(["2026-05-01T00:00:00Z"], utc=True),
            "hdd": [12000.0],  # > 9999 and not the sentinel
            "cdd": [80.0],
        }
    )
    as_of = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(QualityGateError) as ei:
        quality.validate(frame, schemas.NOAA_HDDCDD, as_of=as_of)
    assert (ei.value.failures["column"] == "hdd").any()


def test_freshness_fail_stale_valid_time_blocked():
    # Gas storage whose newest valid_time is months before as_of => stale.
    frame = pd.DataFrame(
        {
            "instrument_id": ["EIA.NG.STORAGE.LOWER48"],
            "valid_time": pd.to_datetime(["2026-01-02"], utc=True),
            "value": [3000.0],
        }
    )
    with pytest.raises(QualityGateError) as ei:
        quality.validate(frame, schemas.EIA_GAS_STORAGE, as_of=AS_OF)
    checks = ei.value.failures["check"].astype(str)
    assert checks.str.contains("staler than").any()
