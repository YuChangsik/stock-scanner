import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.logging import get_logger
from app.scheduler.jobs import run_daily_batch

logger = get_logger(__name__)


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.batch_timezone)

    scheduler.add_job(
        run_daily_batch,
        trigger=CronTrigger(
            hour=settings.batch_cron_hour,
            minute=settings.batch_cron_minute,
            timezone=settings.batch_timezone,
        ),
        id="daily_batch",
        name="Daily KOSPI/KOSDAQ batch",
        replace_existing=True,
        misfire_grace_time=3600,  # allow 1h late start if server was down
    )

    logger.info(
        "scheduler.configured",
        hour=settings.batch_cron_hour,
        minute=settings.batch_cron_minute,
        tz=settings.batch_timezone,
    )
    return scheduler
