"""Dagster ConfigurableResources for the S1 write side.

``ArcticDBResource`` opens Arctic against MinIO in ``setup_for_execution``. The S3
credentials are sourced from Dagster ``EnvVar`` (Dagster keeps EnvVar values out of the
UI and run logs), but ArcticDB 6.18.1's S3 backend requires them **embedded in the
connection URI**: the AWS default credential chain (``AWS_ACCESS_KEY_ID``/``SECRET`` env,
``~/.aws/credentials``) returns HTTP 403 against MinIO here, so URI embedding is the only
working path (verified). Because the URI therefore carries the secret, it MUST NEVER be
logged -- it is held only on the instance, passed once to ``Arctic()``, and any
connection error is re-raised with a **redacted** message (endpoint/bucket only) so the
credential cannot leak through a traceback.

arcticdb is imported BEFORE pandas/pyarrow per the phase-0 AWS-SDK load-order hazard
(energex.__init__ already pins this process-wide; belt-and-suspenders here). ``HttpResource``
is a thin httpx + tenacity client for keyless/REST connectors.
"""

from __future__ import annotations

from typing import Any

# arcticdb MUST load before pandas/pyarrow (phase-0 findings).
import arcticdb  # noqa: F401
import httpx
from dagster import ConfigurableResource, EnvVar
from pydantic import PrivateAttr

from energex.core.exceptions import StorageError


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

        # _uri() embeds the S3 secret (ArcticDB requirement). Never log it; redact on error
        # so the credential cannot leak through a connection-failure traceback.
        try:
            self._arctic = Arctic(self._uri())
        except Exception as exc:
            raise StorageError(
                f"ArcticDB connection failed (endpoint={self.endpoint}, "
                f"bucket={self.bucket}): {type(exc).__name__}"
            ) from None

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
