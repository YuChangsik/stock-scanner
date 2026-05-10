"""
PrevHighBreakoutCondition — 오늘 종가가 이전 기간 전고점을 돌파한 종목.

Logic:
  close_today > prev_high
  (prev_high = 직전 N 거래일간의 고가 최댓값, 오늘 제외)

indicator_snapshots.prev_high 컬럼에 저장된 값을 사용.
"""
from typing import Any

from app.scanner.conditions.base import Condition


class PrevHighBreakoutCondition(Condition):
    """오늘 종가 > 이전 기간 최고가(전고점)."""

    name = "prev_high_breakout"

    def evaluate(self, row: dict[str, Any]) -> bool:
        close     = row.get("close")   # 스캔 시 price 데이터로 주입됨
        prev_high = row.get("prev_high")

        if close is None or prev_high is None:
            return False

        return float(close) > float(prev_high)
