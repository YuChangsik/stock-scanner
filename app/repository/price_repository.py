from datetime import date

from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.price import DailyPriceORM


class PriceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_many(self, rows: list[dict]) -> int:
        """
        Upsert daily prices. Idempotent on (ticker, trade_date).
        asyncpg 바인드 파라미터 한계(32,767)를 피하기 위해 청크 단위로 실행.
        컬럼 수: 8개 → chunk_size = 32767 // 8 = 4095 → 여유 있게 3,000 사용.
        """
        if not rows:
            return 0

        CHUNK_SIZE = 3_000  # 8 cols × 3000 = 24,000 params < 32,767
        total = 0

        for i in range(0, len(rows), CHUNK_SIZE):
            chunk = rows[i: i + CHUNK_SIZE]
            stmt = insert(DailyPriceORM).values(chunk)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_daily_prices_ticker_date",
                set_={
                    "open":   stmt.excluded.open,
                    "high":   stmt.excluded.high,
                    "low":    stmt.excluded.low,
                    "close":  stmt.excluded.close,
                    "volume": stmt.excluded.volume,
                    "amount": stmt.excluded.amount,
                },
            )
            result = await self._session.execute(stmt)
            total += result.rowcount

        return total

    async def get_by_ticker(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[DailyPriceORM]:
        result = await self._session.execute(
            select(DailyPriceORM)
            .where(DailyPriceORM.ticker == ticker)
            .where(DailyPriceORM.trade_date >= start_date)
            .where(DailyPriceORM.trade_date <= end_date)
            .order_by(DailyPriceORM.trade_date)
        )
        return list(result.scalars().all())

    async def get_by_date(self, trade_date: date) -> list[DailyPriceORM]:
        result = await self._session.execute(
            select(DailyPriceORM).where(DailyPriceORM.trade_date == trade_date)
        )
        return list(result.scalars().all())

    async def get_latest_date(self) -> date | None:
        result = await self._session.execute(
            select(func.max(DailyPriceORM.trade_date))
        )
        return result.scalar_one_or_none()

    async def get_available_dates(self, months: int = 6) -> list[dict]:
        """
        데이터가 존재하는 거래일 목록 반환.
        {date, price_count} 형태. 최근 months 개월 치.
        """
        from datetime import date as date_type
        today = date_type.today()
        # months 개월 전 날짜 계산 (표준 라이브러리만 사용)
        total_months = today.year * 12 + today.month - months
        y, m = divmod(total_months - 1, 12)
        cutoff = date_type(y, m + 1, today.day)

        result = await self._session.execute(
            select(
                DailyPriceORM.trade_date,
                func.count(DailyPriceORM.ticker).label("price_count"),
            )
            .where(DailyPriceORM.trade_date >= cutoff)
            .group_by(DailyPriceORM.trade_date)
            .order_by(DailyPriceORM.trade_date)
        )
        return [{"date": str(r.trade_date), "price_count": r.price_count}
                for r in result.all()]

    async def exists(self, ticker: str, trade_date: date) -> bool:
        result = await self._session.execute(
            select(DailyPriceORM.id)
            .where(DailyPriceORM.ticker == ticker)
            .where(DailyPriceORM.trade_date == trade_date)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None
