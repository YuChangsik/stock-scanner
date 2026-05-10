"""
MacdHistogramCondition — MACD 히스토그램 조건.

params:
  signal (str):
    "positive"        — 히스토그램 > 0 (MACD > Signal, 상승 모멘텀)
    "negative"        — 히스토그램 < 0
    "expanding_bull"  — 히스토그램이 양수이면서 오늘 > 어제 (모멘텀 확장, default)
    "expanding_bear"  — 히스토그램이 음수이면서 오늘 < 어제
    "turning_bull"    — 히스토그램이 음→양 전환 (골든크로스와 유사)
    "turning_bear"    — 히스토그램이 양→음 전환
"""
from typing import Any
from app.scanner.conditions.base import Condition


class MacdHistogramCondition(Condition):
    """MACD 히스토그램 패턴 필터."""

    name = "macd_histogram"

    def evaluate(self, row: dict[str, Any]) -> bool:
        hist_today = row.get("macd_hist")
        prev       = row.get("prev")

        if hist_today is None:
            return False

        hist_today = float(hist_today)
        signal = self.params.get("signal", "expanding_bull")

        if signal == "positive":
            return hist_today > 0
        if signal == "negative":
            return hist_today < 0

        if prev is None:
            return False

        hist_prev = prev.get("macd_hist")
        if hist_prev is None:
            return False
        hist_prev = float(hist_prev)

        if signal == "expanding_bull":
            return hist_today > 0 and hist_today > hist_prev
        if signal == "expanding_bear":
            return hist_today < 0 and hist_today < hist_prev
        if signal == "turning_bull":
            return hist_prev <= 0 < hist_today
        if signal == "turning_bear":
            return hist_prev >= 0 > hist_today

        return False
