from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.scan import ScanJobORM, ScanResultORM


class ScanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_job(self, job: dict) -> ScanJobORM:
        obj = ScanJobORM(**job)
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def update_job(self, job_id: str, updates: dict) -> None:
        obj = await self._session.get(ScanJobORM, job_id)
        if obj:
            for k, v in updates.items():
                setattr(obj, k, v)
            await self._session.flush()

    async def get_job(self, job_id: str) -> ScanJobORM | None:
        return await self._session.get(ScanJobORM, job_id)

    async def get_latest_job(self, job_type: str = "daily_batch") -> ScanJobORM | None:
        result = await self._session.execute(
            select(ScanJobORM)
            .where(ScanJobORM.job_type == job_type)
            .where(ScanJobORM.status == "success")
            .order_by(ScanJobORM.trade_date.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_job_by_date(self, trade_date: date, job_type: str) -> ScanJobORM | None:
        result = await self._session.execute(
            select(ScanJobORM)
            .where(ScanJobORM.trade_date == trade_date)
            .where(ScanJobORM.job_type == job_type)
            .order_by(ScanJobORM.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def insert_results(self, results: list[dict]) -> int:
        if not results:
            return 0
        await self._session.execute(insert(ScanResultORM).values(results))
        return len(results)

    async def get_results_by_job(self, job_id: str) -> list[ScanResultORM]:
        result = await self._session.execute(
            select(ScanResultORM).where(ScanResultORM.job_id == job_id)
        )
        return list(result.scalars().all())
