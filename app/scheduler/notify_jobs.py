"""
notify_jobs.py — APScheduler 기반 카카오톡 알림 스케줄 관리.

사용자별로 CronTrigger 잡을 동적으로 등록/수정/삭제한다.
"""
from __future__ import annotations

import logging
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.logging import get_logger
from app.service.notify_service import NotifyService

logger = get_logger(__name__)

# 앱 기동 후 setup.py에서 주입
_scheduler: AsyncIOScheduler | None = None


def set_scheduler(scheduler: AsyncIOScheduler) -> None:
    global _scheduler
    _scheduler = scheduler


def _job_id(user_id: int) -> str:
    return f"notify_user_{user_id}"


async def reschedule_user_notify(user_id: int, schedule: dict[str, Any]) -> None:
    """
    사용자의 알림 스케줄을 APScheduler에 등록/수정/삭제한다.
    schedule = {
        "enabled":   bool,
        "weekdays":  [0,1,2,3,4],   # 0=월 … 6=일
        "time":      "09:00",
        "min_matches": 1,
    }
    """
    if _scheduler is None:
        logger.warning("notify_jobs.no_scheduler", user_id=user_id)
        return

    job_id = _job_id(user_id)
    enabled = schedule.get("enabled", False)

    # 비활성화 → 잡 제거
    if not enabled:
        if _scheduler.get_job(job_id):
            _scheduler.remove_job(job_id)
            logger.info("notify.job_removed", user_id=user_id)
        return

    time_str  = schedule.get("time", "09:00")
    weekdays  = schedule.get("weekdays", [0, 1, 2, 3, 4])
    try:
        hour, minute = map(int, time_str.split(":"))
    except Exception:
        logger.error("notify.bad_time", user_id=user_id, time=time_str)
        return

    # APScheduler의 day_of_week: 0=월 … 6=일  (mon=0)
    dow_map = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}
    day_of_week = ",".join(dow_map[d] for d in weekdays if d in dow_map) or "mon-fri"

    trigger = CronTrigger(
        day_of_week=day_of_week,
        hour=hour,
        minute=minute,
        timezone="Asia/Seoul",
    )

    _scheduler.add_job(
        NotifyService.run_notify_for_user,
        trigger=trigger,
        args=[user_id],
        id=job_id,
        name=f"KakaoNotify user={user_id}",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info(
        "notify.job_scheduled",
        user_id=user_id,
        day_of_week=day_of_week,
        hour=hour,
        minute=minute,
    )


async def boot_notify_jobs(scheduler: AsyncIOScheduler) -> None:
    """
    앱 기동 시 DB에서 알림 활성 사용자를 읽어 스케줄 등록.
    setup.py의 lifespan 후반부에서 호출.
    """
    set_scheduler(scheduler)

    from app.db.session import AsyncSessionFactory
    from app.repository.user_repository import UserRepository

    try:
        async with AsyncSessionFactory() as session:
            repo = UserRepository(session)
            users = await repo.get_notify_enabled_users()

        for u in users:
            sch = u.notify_schedule or {}
            if sch.get("enabled"):
                await reschedule_user_notify(u.id, sch)

        logger.info("notify.boot_jobs_registered", count=len(users))
    except Exception as e:
        logger.warning("notify.boot_jobs_error", error=str(e))
