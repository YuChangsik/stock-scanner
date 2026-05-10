"""
ObvRisingCondition — OBV 상승 조건.

오늘 OBV가 N일 전 OBV보다 높으면 통과 (매집 신호).

params:
  lookback_days (int): 비교 기준 일수 (default 5 — 5일 전 OBV와 비교)
"""
from typing import Any
from app.scanner.conditions.base import Condition


class ObvRisingCondition(Condition):
    """OBV가 N일 전 대비 상승 중인 종목 필터."""

    name = "obv_rising"

    def evaluate(self, row: dict[str, Any]) -> bool:
        lookback  = int(self.params.get("lookback_days", 5))
        today_obv = row.get("obv")
        prev_hist = row.get("prev_history", [])

        if today_obv is None:
            return False

        if len(prev_hist) < lookback:
            return False

        # lookback 번째 과거 (newest first → index = lookback-1)
        past = prev_hist[lookback - 1] if prev_hist else None
        if past is None:
            return False

        past_obv = past.get("obv")
        if past_obv is None:
            return False

        return float(today_obv) > float(past_obv)
