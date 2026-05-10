from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class ScanJobORM(Base):
    __tablename__ = "scan_jobs"
    __table_args__ = (Index("ix_scan_jobs_trade_date", "trade_date"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    results: Mapped[list["ScanResultORM"]] = relationship(
        back_populates="job", lazy="noload", cascade="all, delete-orphan"
    )


class ScanResultORM(Base):
    __tablename__ = "scan_results"
    __table_args__ = (
        Index("ix_scan_results_job_id", "job_id"),
        Index("ix_scan_results_trade_date", "trade_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("scan_jobs.id"), nullable=False)
    ticker: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.ticker"), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    conditions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    job: Mapped["ScanJobORM"] = relationship(back_populates="results", lazy="noload")
