"""
MarketDataProvider ABC — all data source adapters must implement this.

Design rationale: service / scheduler layers depend ONLY on this interface.
Swapping pykrx for KIS API, CSV, or a mock requires zero changes outside
the provider package.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import pandas as pd


class MarketDataProvider(ABC):

    @abstractmethod
    async def get_stock_list(self, market: str) -> pd.DataFrame:
        """
        Returns active tickers for a market.

        Returns DataFrame with columns: ticker, name, market
        market: 'KOSPI' | 'KOSDAQ'
        """

    @abstractmethod
    async def get_ohlcv_by_ticker(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """
        Returns daily OHLCV for a single ticker over a date range.

        Returns DataFrame with index=trade_date and columns:
          open, high, low, close, volume, amount
        Empty DataFrame if no data is available.
        """

    @abstractmethod
    async def get_ohlcv_by_date(self, trade_date: date) -> pd.DataFrame:
        """
        Returns OHLCV for ALL tickers on a single trading day.

        Returns DataFrame with columns: ticker, open, high, low, close, volume, amount
        Empty DataFrame if market was closed that day.
        """
