"""
Test fixtures and provider mocks.

All tests use an in-memory mock provider so no real network calls are made.
The MockMarketDataProvider returns predictable, deterministic data.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from app.provider.base import MarketDataProvider
from app.domain.schemas import ConditionDefinition


class MockMarketDataProvider(MarketDataProvider):
    """Deterministic test double for MarketDataProvider."""

    def __init__(self, stocks: list[dict] | None = None, prices: dict | None = None):
        self._stocks = stocks or [
            {"ticker": "005930", "name": "삼성전자", "market": "KOSPI"},
            {"ticker": "000660", "name": "SK하이닉스", "market": "KOSPI"},
            {"ticker": "035720", "name": "카카오", "market": "KOSDAQ"},
        ]
        # prices: {ticker: {date: {open,high,low,close,volume,amount}}}
        self._prices = prices or {}

    async def get_stock_list(self, market: str) -> pd.DataFrame:
        rows = [s for s in self._stocks if s["market"] == market]
        return pd.DataFrame(rows)

    async def get_ohlcv_by_ticker(
        self, ticker: str, start_date: date, end_date: date
    ) -> pd.DataFrame:
        ticker_data = self._prices.get(ticker, {})
        rows = []
        current = start_date
        while current <= end_date:
            if current in ticker_data:
                row = {"ticker": ticker, **ticker_data[current]}
                rows.append(row)
            current += timedelta(days=1)

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df = df.set_index(pd.to_datetime([r["ticker"] for r in rows]))  # placeholder
        df.index = [r for r in (start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1))
                    if r in ticker_data]
        df.index.name = "trade_date"
        return df

    async def get_ohlcv_by_date(self, trade_date: date) -> pd.DataFrame:
        rows = []
        for ticker, dates in self._prices.items():
            if trade_date in dates:
                rows.append({"ticker": ticker, "trade_date": trade_date, **dates[trade_date]})
        return pd.DataFrame(rows)


@pytest.fixture
def mock_provider():
    return MockMarketDataProvider()


@pytest.fixture
def sample_prices_df():
    """30 days of synthetic price data for indicator testing."""
    base_close = 50000.0
    rows = []
    start = date(2024, 1, 1)
    for i in range(30):
        d = start + timedelta(days=i)
        close = base_close + (i * 100) + ((-1) ** i * 500)
        rows.append({
            "trade_date": d,
            "close": close,
            "volume": 1_000_000 + i * 10_000,
        })
    df = pd.DataFrame(rows).set_index("trade_date")
    return df


@pytest.fixture
def make_condition_def():
    def _make(name: str, **params) -> ConditionDefinition:
        return ConditionDefinition(name=name, params=params)
    return _make
