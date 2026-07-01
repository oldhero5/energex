import httpx
import pytest

from energex.observer import supabase_client as sc


def _capture(calls, status=201, body=None):
    def _req(self, method, url, **kw):
        calls.append((method, url, kw.get("json"), kw.get("headers")))
        return httpx.Response(
            status,
            json=body if body is not None else [{"id": 1}],
            request=httpx.Request(method, url),
        )

    return _req


def test_write_issue_ack_posts_to_postgrest(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://sb.local")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "svc-key")
    calls = []
    monkeypatch.setattr(httpx.Client, "request", _capture(calls))
    sc.write_issue_ack("uid-1", "check:ercot_load_pass_quality_gate", "ack", "looks transient")
    method, url, body, headers = calls[0]
    assert method == "POST" and url.endswith("/rest/v1/issue_acks")
    assert body == {
        "issue_key": "check:ercot_load_pass_quality_gate",
        "user_id": "uid-1",
        "status": "ack",
        "note": "looks transient",
    }
    assert headers["apikey"] == "svc-key" and headers["Authorization"] == "Bearer svc-key"


def test_not_configured_raises(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    assert sc.is_configured() is False
    with pytest.raises(sc.SupabaseError):
        sc.write_audit_log("ack_issue", "check:x", {}, "uid-1")


def test_write_audit_log_posts_to_postgrest(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://sb.local")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "svc-key")
    calls = []
    monkeypatch.setattr(httpx.Client, "request", _capture(calls, status=201, body=[]))
    result = sc.write_audit_log("ack_issue", "check:x", {"foo": "bar"}, "uid-2")
    assert result is None
    method, url, body, headers = calls[0]
    assert method == "POST" and url.endswith("/rest/v1/audit_log")
    assert body == {
        "action": "ack_issue",
        "target": "check:x",
        "detail": {"foo": "bar"},
        "user_id": "uid-2",
    }


def test_read_issue_acks_gets_with_params(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://sb.local")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "svc-key")
    calls = []
    monkeypatch.setattr(
        httpx.Client,
        "request",
        _capture(calls, status=200, body=[{"id": 1, "status": "ack"}]),
    )
    rows = sc.read_issue_acks()
    method, url, body, headers = calls[0]
    assert method == "GET" and url.endswith("/rest/v1/issue_acks")
    assert rows == [{"id": 1, "status": "ack"}]


def test_write_issue_ack_returns_row(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://sb.local")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "svc-key")
    monkeypatch.setattr(
        httpx.Client,
        "request",
        _capture([], status=201, body=[{"id": 99, "status": "ack"}]),
    )
    row = sc.write_issue_ack("u", "k", "ack")
    assert row == {"id": 99, "status": "ack"}


def test_write_issue_ack_empty_response_returns_empty_dict(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://sb.local")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "svc-key")
    monkeypatch.setattr(httpx.Client, "request", _capture([], status=201, body=[]))
    row = sc.write_issue_ack("u", "k", "ack")
    assert row == {}


def test_is_configured_true_when_both_set(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://sb.local")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "svc-key")
    assert sc.is_configured() is True


def test_http_error_raises_supabase_error(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://sb.local")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "svc-key")

    def _fail(self, method, url, **kw):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.Client, "request", _fail)
    with pytest.raises(sc.SupabaseError, match="supabase POST issue_acks"):
        sc.write_issue_ack("u", "k", "ack")
