"""Integration-style tests for ScanEngine (no DB required)."""
from datetime import date

import pytest

from app.domain.schemas import ConditionDefinition
from app.scanner.engine import ScanEngine


TODAY = date(2024, 1, 15)


def _snap(ticker: str, ma5: float, ma20: float, rsi14: float, volume_rank: int) -> dict:
    return {
        "ticker": ticker,
        "trade_date": TODAY,
        "ma5": ma5,
        "ma20": ma20,
        "rsi14": rsi14,
        "volume_rank": volume_rank,
    }


def _prev(ticker: str, ma5: float, ma20: float) -> dict:
    return {
        "ticker": ticker,
        "trade_date": date(2024, 1, 14),
        "ma5": ma5,
        "ma20": ma20,
        "rsi14": 50.0,
        "volume_rank": 10,
    }


class TestScanEngine:
    def test_volume_rank_only(self):
        engine = ScanEngine([ConditionDefinition(name="volume_rank", params={"threshold": 5})])
        snapshots = [
            _snap("AAA", ma5=1.0, ma20=1.0, rsi14=50.0, volume_rank=3),
            _snap("BBB", ma5=1.0, ma20=1.0, rsi14=50.0, volume_rank=6),
        ]
        matches = engine.scan(TODAY, snapshots, [])
        assert len(matches) == 1
        assert matches[0].ticker == "AAA"

    def test_rsi_filter(self):
        engine = ScanEngine([ConditionDefinition(name="rsi14", params={"operator": "<", "threshold": 40})])
        snapshots = [
            _snap("AAA", ma5=1.0, ma20=1.0, rsi14=35.0, volume_rank=1),
            _snap("BBB", ma5=1.0, ma20=1.0, rsi14=45.0, volume_rank=2),
        ]
        matches = engine.scan(TODAY, snapshots, [])
        tickers = [m.ticker for m in matches]
        assert "AAA" in tickers
        assert "BBB" not in tickers

    def test_golden_cross_with_prev_data(self):
        engine = ScanEngine([ConditionDefinition(name="golden_cross")])
        today_snaps = [
            _snap("GC_TICKER", ma5=20200.0, ma20=20000.0, rsi14=50.0, volume_rank=5),
            _snap("NO_CROSS", ma5=19500.0, ma20=20000.0, rsi14=50.0, volume_rank=10),
        ]
        prev_snaps = [
            _prev("GC_TICKER", ma5=19800.0, ma20=20000.0),  # was below
            _prev("NO_CROSS", ma5=19400.0, ma20=20000.0),
        ]
        matches = engine.scan(TODAY, today_snaps, prev_snaps)
        assert len(matches) == 1
        assert matches[0].ticker == "GC_TICKER"

    def test_combined_conditions_all_must_pass(self):
        engine = ScanEngine([
            ConditionDefinition(name="volume_rank", params={"threshold": 10}),
            ConditionDefinition(name="rsi14", params={"operator": "<", "threshold": 40}),
        ])
        snapshots = [
            _snap("BOTH", ma5=1.0, ma20=1.0, rsi14=35.0, volume_rank=5),
            _snap("ONLY_RANK", ma5=1.0, ma20=1.0, rsi14=55.0, volume_rank=3),
            _snap("ONLY_RSI", ma5=1.0, ma20=1.0, rsi14=30.0, volume_rank=15),
        ]
        matches = engine.scan(TODAY, snapshots, [])
        assert len(matches) == 1
        assert matches[0].ticker == "BOTH"
        assert "volume_rank" in matches[0].matched_conditions
        assert "rsi14" in matches[0].matched_conditions

    def test_empty_snapshots(self):
        engine = ScanEngine([ConditionDefinition(name="volume_rank")])
        matches = engine.scan(TODAY, [], [])
        assert matches == []

    def test_unknown_condition_raises(self):
        with pytest.raises(ValueError, match="Unknown condition"):
            ScanEngine([ConditionDefinition(name="nonexistent_condition")])

    def test_none_indicator_does_not_crash(self):
        engine = ScanEngine([ConditionDefinition(name="rsi14")])
        snapshots = [_snap("AAA", ma5=None, ma20=None, rsi14=None, volume_rank=None)]
        matches = engine.scan(TODAY, snapshots, [])
        assert matches == []
