"""Open ArcticDB for the observer using the same URI grammar as the read API."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from energex.core.config import get_settings

VINTAGE_SUFFIX = "__vintages"


def _uri() -> str:
    uri = os.environ.get("ENERGEX_ARCTIC_URI")
    if uri:
        return uri
    cfg = get_settings().arctic
    access = cfg.minio_access_key.get_secret_value() if cfg.minio_access_key else ""
    secret = cfg.minio_secret_key.get_secret_value() if cfg.minio_secret_key else ""
    host, _, port = cfg.minio_endpoint.partition(":")
    port = port or ("443" if cfg.arctic_secure else "9000")
    scheme = "s3s" if cfg.arctic_secure else "s3"
    return (
        f"{scheme}://{host}:{cfg.minio_bucket}?access={access}&secret={secret}"
        f"&port={port}&use_virtual_addressing=false"
    )


@lru_cache(maxsize=1)
def get_arctic() -> Any:
    from arcticdb import Arctic

    return Arctic(_uri())
