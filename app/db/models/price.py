from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class DailyPriceORM(Base):
    __tablename__ = "daily_prices"
    __table_args__ = (
        UniqueConstraint("ticker", "trade_date", name="uq_daily_prices_ticker_date"),
        Index("ix_daily_prices_trade_date", "trade_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.ticker"), nullable=False, index=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    high: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    low: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    close: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    stock: Mapped["StockORM"] = relationship(back_populates="prices", lazy="noload")  # noqa: F821
