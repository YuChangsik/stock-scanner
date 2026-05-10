from typing import Any
from app.scanner.conditions.base import Condition


class MaAboveCondition(Condition):
    """
    종가가 N일 이동평균선 위에 있는 조건.

    params:
      period (int): 20 | 30 | 60 | 120 (default: 60)
    """
    name = "ma_above"

    def evaluate(self, row: dict[str, Any]) -> bool:
        period = int(self.params.get("period", 60))
        close = row.get("close")

        ma_map = {
            5:   row.get("ma5"),
            20:  row.get("ma20"),
            60:  row.get("ma60"),
            120: row.get("ma120"),
        }
        ma = ma_map.get(period)

        if close is None or ma is None:
            return False
        return float(close) > float(ma)
