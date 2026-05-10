"""Unit tests for individual scan conditions."""
from datetime import date

import pytest

from app.scanner.conditions import CONDITION_REGISTRY
from app.scanner.conditions.golden_cross import GoldenCrossCondition
from app.scanner.conditions.rsi import RsiCondition
from app.scanner.conditions.volume_rank import VolumeRankCondition


def make_row(**kwargs) -> dict:
    defaults = {
        "ticker": "005930",
        "trade_date": date(2024, 1, 15),
        "ma5": None,
        "ma20": None,
        "rsi14": None,
        "volume_rank": None,
        "prev": None,
    }
    defaults.update(kwargs)
    return defaults


# ── VolumeRankCondition ───────────────────────────────────────────────────────

class TestVolumeRankCondition:
    def test_passes_within_threshold(self):
        cond = VolumeRankCondition(params={"threshold": 20})
        assert cond.evaluate(make_row(volume_rank=1)) is True
        assert cond.evaluate(make_row(volume_rank=20)) is True

    def test_fails_above_threshold(self):
        cond = VolumeRankCondition(params={"threshold": 20})
        assert cond.evaluate(make_row(volume_rank=21)) is False
        assert cond.evaluate(make_row(volume_rank=100)) is False

    def test_fails_when_rank_is_none(self):
        cond = VolumeRankCondition()
        assert cond.evaluate(make_row(volume_rank=None)) is False

    def test_default_threshold_is_20(self):
        cond = VolumeRankCondition()
        assert cond.evaluate(make_row(volume_rank=20)) is True
        assert cond.evaluate(make_row(volume_rank=21)) is False


# ── RsiCondition ─────────────────────────────────────────────────────────────

class TestRsiCondition:
    def test_less_than(self):
        cond = RsiCondition(params={"operator": "<", "threshold": 40})
        assert cond.evaluate(make_row(rsi14=39.9)) is True
        assert cond.evaluate(make_row(rsi14=40.0)) is False

    def test_less_than_or_equal(self):
        cond = RsiCondition(params={"operator": "<=", "threshold": 40})
        assert cond.evaluate(make_row(rsi14=40.0)) is True
        assert cond.evaluate(make_row(rsi14=40.1)) is False

    def test_greater_than(self):
        cond = RsiCondition(params={"operator": ">", "threshold": 70})
        assert cond.evaluate(make_row(rsi14=70.1)) is True
        assert cond.evaluate(make_row(rsi14=70.0)) is False

    def test_fails_when_rsi_is_none(self):
        cond = RsiCondition()
        assert cond.evaluate(make_row(rsi14=None)) is False

    def test_default_params(self):
        cond = RsiCondition()
        assert cond.evaluate(make_row(rsi14=39.0)) is True
        assert cond.evaluate(make_row(rsi14=40.0)) is False

    def test_invalid_operator_raises(self):
        cond = RsiCondition(params={"operator": "!="})
        with pytest.raises(ValueError):
            cond.evaluate(make_row(rsi14=35.0))


# ── GoldenCrossCondition ──────────────────────────────────────────────────────

class TestGoldenCrossCondition:
    def test_golden_cross(self):
        """Today: MA5 > MA20; Yesterday: MA5 <= MA20."""
        cond = GoldenCrossCondition()
        row = make_row(
            ma5=20200.0,
            ma20=20000.0,
            prev={"ma5": 19900.0, "ma20": 20000.0},  # yesterday: below
        )
        assert cond.evaluate(row) is True

    def test_no_cross_already_above(self):
        """Both today and yesterday MA5 > MA20 — not a fresh cross."""
        cond = GoldenCrossCondition()
        row = make_row(
            ma5=20200.0,
            ma20=20000.0,
            prev={"ma5": 20100.0, "ma20": 20000.0},
        )
        assert cond.evaluate(row) is False

    def test_no_cross_still_below(self):
        cond = GoldenCrossCondition()
        row = make_row(
            ma5=19800.0,
            ma20=20000.0,
            prev={"ma5": 19700.0, "ma20": 20000.0},
        )
        assert cond.evaluate(row) is False

    def test_no_prev_data(self):
        cond = GoldenCrossCondition()
        row = make_row(ma5=20200.0, ma20=20000.0, prev=None)
        assert cond.evaluate(row) is False

    def test_none_ma_values(self):
        cond = GoldenCrossCondition()
        row = make_row(ma5=None, ma20=None, prev={"ma5": 100.0, "ma20": 100.0})
        assert cond.evaluate(row) is False


# ── Registry ──────────────────────────────────────────────────────────────────

def test_condition_registry_contains_required():
    assert "volume_rank" in CONDITION_REGISTRY
    assert "rsi14" in CONDITION_REGISTRY
    assert "golden_cross" in CONDITION_REGISTRY
