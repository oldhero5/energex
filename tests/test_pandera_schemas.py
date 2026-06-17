import pandera.pandas as pa

from energex.core import schemas


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
