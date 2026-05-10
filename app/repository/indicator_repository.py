from datetime import date

from sqlalchemy import distinct, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.indicator import IndicatorSnapshotORM


class IndicatorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_many(self, rows: list[dict]) -> int:
        """
        asyncpg 바인드 파라미터 한계(32,767)를 피하기 위해 청크 단위로 upsert.
        컬럼 수: 20개 → chunk_size = 32767 // 20 = 1638 → 여유 있게 1,500 사용.
        """
        if not rows:
            return 0

        CHUNK_SIZE = 1_500  # 20 cols × 1500 = 30,000 params < 32,767
        total = 0

        for i in range(0, len(rows), CHUNK_SIZE):
            chunk = rows[i: i + CHUNK_SIZE]
            stmt = insert(IndicatorSnapshotORM).values(chunk)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_indicator_ticker_date",
                set_={
                    "ma5":          stmt.excluded.ma5,
                    "ma20":         stmt.excluded.ma20,
                    "ma60":         stmt.excluded.ma60,
                    "ma120":        stmt.excluded.ma120,
                    "rsi14":        stmt.excluded.rsi14,
                    "macd":         stmt.excluded.macd,
                    "macd_signal":  stmt.excluded.macd_signal,
                    "macd_hist":    stmt.excluded.macd_hist,
                    "atr14":        stmt.excluded.atr14,
                    "bb_upper":     stmt.excluded.bb_upper,
                    "bb_mid":       stmt.excluded.bb_mid,
                    "bb_lower":     stmt.excluded.bb_lower,
                    "obv":          stmt.excluded.obv,
                    "volume_ma20":  stmt.excluded.volume_ma20,
                    "prev_high":    stmt.excluded.prev_high,
                    "per":          stmt.excluded.per,
                    "pbr":          stmt.excluded.pbr,
                    "volume_rank":  stmt.excluded.volume_rank,
                    "calculated_at": stmt.excluded.calculated_at,
                },
            )
            result = await self._session.execute(stmt)
            total += result.rowcount

        return total

    async def get_by_ticker_date(
        self, ticker: str, trade_date: date
    ) -> IndicatorSnapshotORM | None:
        result = await self._session.execute(
            select(IndicatorSnapshotORM)
            .where(IndicatorSnapshotORM.ticker == ticker)
            .where(IndicatorSnapshotORM.trade_date == trade_date)
        )
        return result.scalar_one_or_none()

    async def get_by_date(self, trade_date: date) -> list[IndicatorSnapshotORM]:
        result = await self._session.execute(
            select(IndicatorSnapshotORM).where(
                IndicatorSnapshotORM.trade_date == trade_date
            )
        )
        return list(result.scalars().all())

    async def exists_for_date(self, trade_date: date) -> bool:
        result = await self._session.execute(
            select(IndicatorSnapshotORM.id)
            .where(IndicatorSnapshotORM.trade_date == trade_date)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def get_available_dates(self, months: int = 6) -> list[dict]:
        """
        지표 데이터가 존재하는 거래일 목록 반환.
        {date, indicator_count} 형태. 최근 months 개월 치.
        """
        from datetime import date as date_type
        today = date_type.today()
        total_months = today.year * 12 + today.month - months
        y, m = divmod(total_months - 1, 12)
        cutoff = date_type(y, m + 1, today.day)

        result = await self._session.execute(
            select(
                IndicatorSnapshotORM.trade_date,
                func.count(distinct(IndicatorSnapshotORM.ticker)).label("indicator_count"),
            )
            .where(IndicatorSnapshotORM.trade_date >= cutoff)
            .group_by(IndicatorSnapshotORM.trade_date)
            .order_by(IndicatorSnapshotORM.trade_date)
        )
        return [{"date": str(r.trade_date), "indicator_count": r.indicator_count}
                for r in result.all()]

    async def get_sector_stats(self) -> list[dict]:
        """최신 거래일 기준 업종별 평균 PER/PBR/RSI 집계."""
        from app.db.models.stock import StockORM

        latest_date_subq = select(func.max(IndicatorSnapshotORM.trade_date)).scalar_subquery()

        result = await self._session.execute(
            select(
                StockORM.sector,
                func.count(distinct(IndicatorSnapshotORM.ticker)).label("stock_count"),
                func.avg(IndicatorSnapshotORM.per).label("avg_per"),
                func.avg(IndicatorSnapshotORM.pbr).label("avg_pbr"),
                func.avg(IndicatorSnapshotORM.rsi14).label("avg_rsi"),
                func.max(IndicatorSnapshotORM.trade_date).label("trade_date"),
            )
            .join(StockORM, IndicatorSnapshotORM.ticker == StockORM.ticker)
            .where(IndicatorSnapshotORM.trade_date == latest_date_subq)
            .where(StockORM.sector.isnot(None))
            .where(StockORM.is_active == True)  # noqa: E712
            .group_by(StockORM.sector)
            .order_by(StockORM.sector)
        )
        rows = result.all()
        return [
            {
                "sector": r.sector,
                "stock_count": r.stock_count,
                "avg_per": round(float(r.avg_per), 2) if r.avg_per else None,
                "avg_pbr": round(float(r.avg_pbr), 2) if r.avg_pbr else None,
                "avg_rsi": round(float(r.avg_rsi), 2) if r.avg_rsi else None,
                "trade_date": str(r.trade_date),
            }
            for r in rows
        ]

    async def get_by_sector(self, sector: str) -> list[dict]:
        """최신 거래일 기준 특정 업종 종목의 지표 + 종목 기본정보 반환."""
        from app.db.models.stock import StockORM

        latest_date_subq = select(func.max(IndicatorSnapshotORM.trade_date)).scalar_subquery()

        result = await self._session.execute(
            select(
                StockORM.ticker,
                StockORM.name,
                StockORM.market,
                IndicatorSnapshotORM.per,
                IndicatorSnapshotORM.pbr,
                IndicatorSnapshotORM.rsi14,
                IndicatorSnapshotORM.ma5,
                IndicatorSnapshotORM.ma20,
                IndicatorSnapshotORM.volume_rank,
                IndicatorSnapshotORM.trade_date,
            )
            .join(IndicatorSnapshotORM, StockORM.ticker == IndicatorSnapshotORM.ticker)
            .where(IndicatorSnapshotORM.trade_date == latest_date_subq)
            .where(StockORM.sector == sector)
            .where(StockORM.is_active == True)  # noqa: E712
        )
        rows = result.all()
        return [
            {
                "ticker": r.ticker,
                "name": r.name,
                "market": r.market,
                "per": float(r.per) if r.per else None,
                "pbr": float(r.pbr) if r.pbr else None,
                "rsi14": float(r.rsi14) if r.rsi14 else None,
                "ma5": float(r.ma5) if r.ma5 else None,
                "ma20": float(r.ma20) if r.ma20 else None,
                "volume_rank": r.volume_rank,
                "trade_date": str(r.trade_date),
            }
            for r in rows
        ]
