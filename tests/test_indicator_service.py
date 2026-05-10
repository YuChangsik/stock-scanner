"""Tests for indicator computation logic."""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.service.indicator_service import _compute_ma, _compute_rsi


class TestComputeMa:
    def test_ma5_requires_5_bars(self):
        close = pd.Series([100.0] * 4)
        result = _compute_ma(close, 5)
        assert result.isna().all()

    def test_ma5_correct_value(self):
        closes = [10, 20, 30, 40, 50]
        close = pd.Series(closes, dtype=float)
        result = _compute_ma(close, 5)
        assert not result.isna().iloc[-1]
        assert abs(result.iloc[-1] - 30.0) < 1e-9

    def test_ma20_nan_before_20_bars(self):
        close = pd.Series([100.0] * 19)
        result = _compute_ma(close, 20)
        assert result.isna().all()

    def test_ma20_not_nan_at_20_bars(self):
        close = pd.Series([100.0] * 20)
        result = _compute_ma(close, 20)
        assert not result.isna().iloc[-1]


class TestComputeRsi:
    def test_rsi_range(self, sample_prices_df):
        rsi = _compute_rsi(sample_prices_df["close"].astype(float))
        valid = rsi.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_rsi_nan_before_period(self):
        close = pd.Series([100.0 + i for i in range(14)], dtype=float)
        rsi = _compute_rsi(close, period=14)
        # With only 14 values, RSI requires 15 to produce first non-NaN
        assert rsi.dropna().empty or len(rsi.dropna()) <= 1

    def test_rsi_all_gains_approaches_100(self):
        close = pd.Series([float(i) for i in range(1, 40)], dtype=float)
        rsi = _compute_rsi(close, period=14)
        assert rsi.dropna().iloc[-1] > 90

    def test_rsi_all_losses_approaches_0(self):
        close = pd.Series([float(40 - i) for i in range(40)], dtype=float)
        rsi = _compute_rsi(close, period=14)
        assert rsi.dropna().iloc[-1] < 10
