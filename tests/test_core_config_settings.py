from energex.core.config import (
    ArcticDBConfig,
    ConnectorConfig,
    EnergexSettings,
    Neo4jConfig,
    get_settings,
    reset_settings,
)


def test_new_config_classes_are_nested_on_settings():
    s = EnergexSettings()
    assert isinstance(s.arctic, ArcticDBConfig)
    assert isinstance(s.neo4j, Neo4jConfig)
    assert isinstance(s.connectors, ConnectorConfig)


def test_legacy_database_alias_preserved():
    # test_api_contract / test_database_ergonomics rely on settings.database.db_path.
    s = EnergexSettings()
    assert s.database.db_path is not None


def test_env_binding_for_arctic_neo4j_connectors(monkeypatch):
    monkeypatch.setenv("MINIO_ENDPOINT", "minio:9000")
    monkeypatch.setenv("ARCTIC_BUCKET", "arctic")
    monkeypatch.setenv("NEO4J_URI", "bolt://db:7687")
    monkeypatch.setenv("EIA_API_KEY", "secret-eia")
    monkeypatch.setenv("ERCOT_SUBSCRIPTION_KEY", "sub-key")
    monkeypatch.setenv("NOAA_TOKEN", "noaa-tok")
    reset_settings()
    s = get_settings(reload=True)
    assert s.arctic.minio_endpoint == "minio:9000"
    assert s.arctic.minio_bucket == "arctic"
    assert s.neo4j.uri == "bolt://db:7687"
    assert s.connectors.eia_api_key.get_secret_value() == "secret-eia"
    assert s.connectors.ercot_subscription_key.get_secret_value() == "sub-key"
    assert s.connectors.noaa_token.get_secret_value() == "noaa-tok"
    reset_settings()


def test_config_old_and_new_paths_are_identical():
    from energex.config import get_settings as old
    from energex.core.config import get_settings as new

    assert old is new
