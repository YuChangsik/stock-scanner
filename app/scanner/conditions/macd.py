"""
MACDCondition — MACD line crosses above Signal line (golden cross).

Logic requires TWO consecutive day snapshots:
  today:     macd > macd_signal
  yesterday: macd <= macd_signal

row['prev'] is injected by ScanEngine (same structure as row, or None).
"""
from typing import Any

from app.scanner.conditions.base import Condition


class MACDCondition(Condition):
    """MACD(12,26,9) crosses above Signal line today."""

    name = "macd"

    def evaluate(self, row: dict[str, Any]) -> bool:
        macd_today   = row.get("macd")
        signal_today = row.get("macd_signal")
        prev         = row.get("prev")

        if macd_today is None or signal_today is None:
            return False

        if prev is None:
            return False

        macd_prev   = prev.get("macd")
        signal_prev = prev.get("macd_signal")

        if macd_prev is None or signal_prev is None:
            return False

        today_above = float(macd_today) > float(signal_today)
        prev_below  = float(macd_prev) <= float(signal_prev)

        return today_above and prev_below
