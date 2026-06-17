"""Dagster ConfigurableResources for the S1 write side.

``ArcticDBResource`` builds the phase-0-verified MinIO s3 URI from EnvVar config
(secrets never live in URI literals) and opens Arctic in ``setup_for_execution``.
arcticdb is imported here BEFORE pandas/pyarrow per the phase-0 AWS-SDK load-order
hazard (energex.__init__ already pins this process-wide; this is belt-and-suspenders
for any path that imports resources directly). ``HttpResource`` is a thin httpx +
tenacity client for keyless/REST connectors.
"""

from __future__ import annotations

from typing import Any

# arcticdb MUST load before pandas/pyarrow (phase-0 findings).
import arcticdb  # noqa: F401
import httpx
from dagster import ConfigurableResource, EnvVar
from pydantic import PrivateAttr


class ArcticDBResource(ConfigurableResource):
    """Opens an Arctic client against MinIO; hands out create-if-missing libraries."""

    endpoint: str  # host:port, e.g. localhost:9000
    bucket: str
    access_key: str
    secret_key: str
    secure: bool = False

    _arctic: Any = PrivateAttr(default=None)

    def _uri(self) -> str:
        host, _, port = self.endpoint.partition(":")
        port = port or ("443" if self.secure else "9000")
        scheme = "s3s" if self.secure else "s3"
        # phase-0 grammar: s3://<host>:<bucket>?access=&secret=&port=&use_virtual_addressing=false
        return (
            f"{scheme}://{host}:{self.bucket}"
            f"?access={self.access_key}&secret={self.secret_key}"
            f"&port={port}&use_virtual_addressing=false"
        )

    def setup_for_execution(self, context) -> None:  # noqa: ARG002 (dagster hook signature)
        from arcticdb import Arctic

        self._arctic = Arctic(self._uri())

    def get_library(self, name: str) -> Any:
        # 6.18.1 has no get_or_create_library; use create_if_missing (phase-0 findings).
        return self._arctic.get_library(name, create_if_missing=True)


class HttpResource(ConfigurableResource):
    """A thin httpx client factory for keyless/REST connectors."""

    timeout: float = 30.0

    def client(self) -> httpx.Client:
        return httpx.Client(timeout=self.timeout)


RESOURCES: dict[str, object] = {
    "arctic": ArcticDBResource(
        endpoint=EnvVar("MINIO_ENDPOINT"),
        bucket=EnvVar("ARCTIC_BUCKET"),
        # Scoped service-account key from env (NOT MinIO root, NOT a literal).
        access_key=EnvVar("MINIO_ACCESS_KEY"),
        secret_key=EnvVar("MINIO_SECRET_KEY"),
    ),
    "http": HttpResource(),
}
