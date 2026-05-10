from datetime import datetime

from sqlalchemy import distinct, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.stock import StockORM


class StockRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_many(self, stocks: list[dict]) -> int:
        """Insert-or-update stocks. Returns number of affected rows."""
        if not stocks:
            return 0
        stmt = insert(StockORM).values(stocks)
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker"],
            set_={
                "name": stmt.excluded.name,
                "market": stmt.excluded.market,
                "sector": stmt.excluded.sector,
                "is_active": stmt.excluded.is_active,
                "updated_at": datetime.utcnow(),
            },
        )
        result = await self._session.execute(stmt)
        return result.rowcount

    async def deactivate_missing(self, active_tickers: list[str]) -> None:
        """Mark tickers not in the active list as inactive."""
        await self._session.execute(
            update(StockORM)
            .where(StockORM.ticker.not_in(active_tickers))
            .values(is_active=False)
        )

    async def get_active_tickers(self) -> list[str]:
        result = await self._session.execute(
            select(StockORM.ticker).where(StockORM.is_active == True)  # noqa: E712
        )
        return list(result.scalars().all())

    async def get_all(self, market: str | None = None) -> list[StockORM]:
        q = select(StockORM).where(StockORM.is_active == True)  # noqa: E712
        if market:
            q = q.where(StockORM.market == market)
        result = await self._session.execute(q)
        return list(result.scalars().all())

    async def get_by_ticker(self, ticker: str) -> StockORM | None:
        result = await self._session.execute(
            select(StockORM).where(StockORM.ticker == ticker)
        )
        return result.scalar_one_or_none()

    async def get_sectors(self) -> list[str]:
        """Return distinct non-null sector values, sorted."""
        result = await self._session.execute(
            select(distinct(StockORM.sector))
            .where(StockORM.is_active == True)  # noqa: E712
            .where(StockORM.sector.isnot(None))
            .order_by(StockORM.sector)
        )
        return list(result.scalars().all())

    async def get_sector_map(self) -> dict[str, str | None]:
        """Return {ticker: sector} for all active stocks."""
        result = await self._session.execute(
            select(StockORM.ticker, StockORM.sector).where(StockORM.is_active == True)  # noqa: E712
        )
        return {row.ticker: row.sector for row in result}

    async def batch_update_sectors(self, sector_map: dict[str, str]) -> int:
        """
        ticker → sector 맵으로 업종명 일괄 업데이트.
        None이 아닌 값만 업데이트하며 기존 업종은 덮어쓰지 않음.
        Returns the number of rows updated.
        """
        if not sector_map:
            return 0
        count = 0
        for ticker, sector in sector_map.items():
            if sector:
                await self._session.execute(
                    update(StockORM)
                    .where(StockORM.ticker == ticker)
                    .values(sector=sector)
                )
                count += 1
        return count
