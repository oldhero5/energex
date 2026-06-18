---
id: operations
title: Operations
sidebar_label: Operations
---

# Operations

Day-to-day running of the always-on stack: monitoring, orphan reconciliation, garbage
collection, and backups.

## Monitoring

- **Dagster UI** (http://localhost:3000) is the operator console: schedule status, run
  history, asset materializations and their metadata (rows written, versions, source
  URL, `vintage_reconstructed`), and asset-check results.
- **MinIO console** (http://localhost:9001) shows the ArcticDB bucket and object usage.
- Every service has a Docker **healthcheck** (the Dagster webserver hits
  `/server_info`, the daemon runs `dagster-daemon liveness-check`, MinIO hits its health
  endpoint). `docker compose ps` shows health at a glance.
- Logs rotate automatically (`json-file`, 10 MB × 5 files per service).

## Orphan reconciliation

The commit protocol writes data, then appends to the per-symbol version index — and that
index append is the atomic commit point (see
[Storage & Point-in-Time](./storage-point-in-time.md)). A crash *between* the two steps
leaves an **orphan**: a data version with no committed index entry. Orphans are invisible
to readers (all reads resolve against the committed index), but they should be cleaned up.

`energex.core.storage.reconcile_orphans` does exactly that — it deletes every data
version that has no committed index entry and returns the list of removed versions:

```python
from energex.core import storage

removed = storage.reconcile_orphans(lib, symbol)   # -> list[int] of deleted versions
```

Committed versions carry UI snapshots; orphans do not, so deleting an orphan never
touches a live vintage.

:::note Reserved: the scheduled reconcile asset
An out-of-band Dagster reconcile/GC asset (`energex.orchestration.reconcile`) is reserved
and currently a stub. Until it lands, run `reconcile_orphans` manually (or from a small
script) if a run is killed mid-commit. In normal operation orphans do not occur.
:::

## Garbage collection

ArcticDB keeps every version. Over time, superseded data versions accumulate. Pruning is
a deliberate operation — keep enough history to satisfy point-in-time reads back as far
as you need, then prune older committed versions through ArcticDB's version-management
APIs. The same reserved reconcile asset is the intended home for a scheduled GC policy.

## Backups

There are three independent stores to protect:

1. **ArcticDB (the store of record) → the `minio-data` volume.** This is the important
   one. Back it up by mirroring the bucket to off-host storage with the MinIO client, for
   example:

   ```bash
   docker run --rm --network=container:energex-minio \
     quay.io/minio/mc mirror local/arctic /path/to/backup/arctic
   ```

   or by snapshotting the `minio-data` Docker volume while the stack is quiesced.

2. **Dagster history → the `dagster-pg-data` volume.** Standard Postgres backup
   (`pg_dump` against the `dagster-postgres` container) preserves run/schedule history.
   This is operational metadata, not market data — lower priority than the store of
   record.

3. **Legacy service DB → the `energex-data` volume.** The legacy FastAPI service exports
   DuckDB snapshots (`EXPORT DATABASE`) to the `./backups` bind mount, which is visible on
   the host.

Restore is the reverse: stop the stack, restore the volume(s) or re-import the snapshot,
and bring it back up. Because ArcticDB is content-versioned, a restored bucket replays its
full vintage history exactly.

## Routine commands

```bash
docker compose --profile full ps          # service + health status
docker compose --profile full logs -f dagster-daemon   # follow a service's logs
docker compose --profile full restart dagster-webserver
docker compose --profile full down        # stop (keeps volumes)
docker compose --profile full down -v     # stop AND delete volumes (destroys data)
```
