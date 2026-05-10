"""
GoldenCrossCondition — MA5 crosses above MA20 within the last N trading days.

params:
  within_days (int, default 1): 골든크로스 발생을 허용하는 최근 거래일 수.
    - 1: 오늘 당일에만 골든크로스가 발생한 종목
    - 5: 최근 5 거래일 이내에 골든크로스가 발생한 종목

row['prev_history'] is a list of dicts ordered newest→oldest (day-1, day-2, …),
provided by the ScanEngine from multiple prior-day snapshots.
"""
from typing import Any

from app.scanner.conditions.base import Condition


class GoldenCrossCondition(Condition):
    """MA5 crosses above MA20 within the last `within_days` trading days."""

    name = "golden_cross"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params or {})
        self._within_days = max(1, int((params or {}).get("within_days", 1)))

    def evaluate(self, row: dict[str, Any]) -> bool:
        # sequence[0] = today, sequence[1] = day-1, sequence[2] = day-2, …
        prev_history: list[dict] = row.get("prev_history") or []
        sequence = [row] + prev_history

        # Check if a cross occurred within the last `within_days` candles.
        # Cross on index i means: sequence[i] MA5>MA20 AND sequence[i+1] MA5≤MA20
        for i in range(min(self._within_days, len(sequence) - 1)):
            curr = sequence[i]
            prev = sequence[i + 1]
            ma5_c  = curr.get("ma5")
            ma20_c = curr.get("ma20")
            ma5_p  = prev.get("ma5")
            ma20_p = prev.get("ma20")
            if None in (ma5_c, ma20_c, ma5_p, ma20_p):
                continue
            if float(ma5_c) > float(ma20_c) and float(ma5_p) <= float(ma20_p):
                return True
        return False
