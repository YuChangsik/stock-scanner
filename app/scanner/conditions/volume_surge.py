"""
VolumeSurgeCondition — 거래량 급증 조건.

오늘 거래량이 20일 평균 거래량의 N배 이상일 때 통과.

params:
  multiplier (float): 급증 배율 기준 (default 2.0, 즉 평균의 200% 이상)
"""
from typing import Any
from app.scanner.conditions.base import Condition


class VolumeSurgeCondition(Condition):
    """거래량이 N일 평균의 M배 이상인 종목 필터."""

    name = "volume_surge"

    def evaluate(self, row: dict[str, Any]) -> bool:
        multiplier  = float(self.params.get("multiplier", 2.0))
        volume      = row.get("volume")
        volume_ma20 = row.get("volume_ma20")

        if volume is None or volume_ma20 is None or float(volume_ma20) == 0:
            return False

        return float(volume) >= float(volume_ma20) * multiplier
