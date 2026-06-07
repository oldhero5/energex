"""In-process APScheduler factory for recurring ingestion."""

import logging
from collections.abc import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

INGEST_JOB_ID = "ingest"


def build_scheduler(
    job: Callable[[], object],
    cron: str = "*/5 * * * *",
    timezone: str = "America/Chicago",
) -> BackgroundScheduler:
    """Build a BackgroundScheduler with a single tz-aware cron ingestion job.

    coalesce + misfire_grace_time make a brief outage self-healing (one catch-up run,
    not a storm); max_instances=1 prevents overlapping ingests.
    """
    scheduler = BackgroundScheduler(timezone=timezone)
    trigger = CronTrigger.from_crontab(cron, timezone=timezone)
    scheduler.add_job(
        job,
        trigger,
        id=INGEST_JOB_ID,
        misfire_grace_time=300,
        coalesce=True,
        max_instances=1,
    )
    logger.info("Scheduled ingestion job '%s' (cron=%s, tz=%s)", INGEST_JOB_ID, cron, timezone)
    return scheduler
