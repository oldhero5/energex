"""Supabase PostgREST client (service key), used server-side AFTER the router enforces the role.
The service key never reaches the browser. Sync httpx (routers are sync).

Reads SUPABASE_URL and SUPABASE_SERVICE_KEY directly from the environment to avoid
requiring OBSERVER_JWT_SECRET when the module is used in isolation."""

from __future__ import annotations

import os

import httpx


class SupabaseError(RuntimeError):
    pass


def _url() -> str | None:
    return os.environ.get("SUPABASE_URL")


def _key() -> str | None:
    return os.environ.get("SUPABASE_SERVICE_KEY")


def is_configured() -> bool:
    return bool(_url() and _key())


def _headers() -> dict:
    key = _key()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _request(method: str, table: str, *, json=None, params=None) -> httpx.Response:
    url_base = _url()
    if not (url_base and _key()):
        raise SupabaseError("Supabase not configured (set SUPABASE_URL + SUPABASE_SERVICE_KEY)")
    url = f"{url_base}/rest/v1/{table}"
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.request(method, url, json=json, params=params, headers=_headers())
            resp.raise_for_status()
            return resp
    except httpx.HTTPError as exc:
        raise SupabaseError(f"supabase {method} {table}: {exc}") from exc


def read_issue_acks() -> list[dict]:
    resp = _request("GET", "issue_acks", params={"select": "*", "order": "created_at.desc"})
    return resp.json()


def write_issue_ack(user_id: str, issue_key: str, status: str, note: str | None = None) -> dict:
    resp = _request(
        "POST",
        "issue_acks",
        json={"issue_key": issue_key, "user_id": user_id, "status": status, "note": note},
    )
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else {}


def write_audit_log(action: str, target: str, detail: dict, user_id: str) -> None:
    _request(
        "POST",
        "audit_log",
        json={"action": action, "target": target, "detail": detail or {}, "user_id": user_id},
    )
