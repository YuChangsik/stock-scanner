"""API request/response schemas (Pydantic v2)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict


# ── Stocks ──────────────────────────────────────────────────────────────────

class StockResponse(BaseModel):
    ticker: str
    name: str
    market: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class StockListResponse(BaseModel):
    total: int
    items: list[StockResponse]


# ── Indicators ───────────────────────────────────────────────────────────────

class IndicatorResponse(BaseModel):
    ticker: str
    trade_date: date
    close: Decimal | None
    volume: int | None        # 거래량 (주)
    amount: int | None        # 거래대금 (원)
    volume_rank: int | None   # 당일 전종목 거래량 순위
    ma5: Decimal | None
    ma20: Decimal | None
    rsi14: Decimal | None

    model_config = ConfigDict(from_attributes=True)


# ── Scan ─────────────────────────────────────────────────────────────────────

class ConditionDefinition(BaseModel):
    name: str = Field(description="Condition identifier, e.g. 'volume_rank', 'rsi14', 'golden_cross'")
    params: dict[str, Any] = Field(default_factory=dict)


class ScanRequest(BaseModel):
    trade_date: date | None = Field(default=None, description="Scan target date (KST); defaults to latest available")
    conditions: list[ConditionDefinition] = Field(
        min_length=1,
        description="List of conditions that must ALL be satisfied",
    )


class ScanMatchResponse(BaseModel):
    ticker: str
    name: str | None = None
    sector: str | None = None
    trade_date: date
    matched_conditions: list[str]
    indicators: dict[str, Any]


class ScanJobResponse(BaseModel):
    job_id: str
    trade_date: date
    status: str
    match_count: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_msg: str | None = None


class ScanResultsResponse(BaseModel):
    job: ScanJobResponse
    matches: list[ScanMatchResponse]


# ── Generic ───────────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
