from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class IndicatorSnapshotORM(Base):
    __tablename__ = "indicator_snapshots"
    __table_args__ = (
        UniqueConstraint("ticker", "trade_date", name="uq_indicator_ticker_date"),
        Index("ix_indicator_trade_date", "trade_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.ticker"), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    ma5: Mapped[float | None] = mapped_column(Numeric(15, 4), nullable=True)
    ma20: Mapped[float | None] = mapped_column(Numeric(15, 4), nullable=True)
    rsi14: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    macd: Mapped[float | None] = mapped_column(Numeric(15, 6), nullable=True)
    macd_signal: Mapped[float | None] = mapped_column(Numeric(15, 6), nullable=True)
    prev_high: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    per: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    pbr: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    volume_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # ── 신규 지표 ─────────────────────────────────────────────────────────────
    ma60:        Mapped[float | None] = mapped_column(Numeric(15, 4), nullable=True)
    ma120:       Mapped[float | None] = mapped_column(Numeric(15, 4), nullable=True)
    atr14:       Mapped[float | None] = mapped_column(Numeric(15, 4), nullable=True)
    bb_upper:    Mapped[float | None] = mapped_column(Numeric(15, 4), nullable=True)
    bb_mid:      Mapped[float | None] = mapped_column(Numeric(15, 4), nullable=True)
    bb_lower:    Mapped[float | None] = mapped_column(Numeric(15, 4), nullable=True)
    obv:         Mapped[float | None] = mapped_column(Numeric(20, 0), nullable=True)
    volume_ma20: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    macd_hist:   Mapped[float | None] = mapped_column(Numeric(15, 6), nullable=True)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    stock: Mapped["StockORM"] = relationship(back_populates="indicators", lazy="noload")  # noqa: F821
