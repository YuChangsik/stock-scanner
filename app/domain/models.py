"""Pure business domain objects — no ORM, no HTTP, no I/O."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Stock:
    ticker: str
    name: str
    market: str  # KOSPI | KOSDAQ
    is_active: bool = True


@dataclass(frozen=True)
class DailyPrice:
    ticker: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    amount: int


@dataclass(frozen=True)
class IndicatorSnapshot:
    ticker: str
    trade_date: date
    ma5: Decimal | None
    ma20: Decimal | None
    rsi14: Decimal | None
    macd: Decimal | None
    macd_signal: Decimal | None
    prev_high: Decimal | None
    per: Decimal | None
    pbr: Decimal | None
    volume_rank: int | None


@dataclass(frozen=True)
class ScanMatch:
    ticker: str
    trade_date: date
    matched_conditions: list[str]
    snapshot: IndicatorSnapshot


@dataclass
class ScanJob:
    id: str
    job_type: str
    trade_date: date
    status: str  # pending | running | success | failed
    error_msg: str | None = None
    meta: dict = field(default_factory=dict)
