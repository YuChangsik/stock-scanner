"""
AtrCondition — ATR(14) 변동성 조건.

params:
  operator  (str):   '<' | '>' | '<=' | '>=' (default '>')
  threshold (float): ATR 기준값 (원, default 500)
  use_ratio (bool):  True이면 ATR/종가(%) 비교 (default False)
  ratio_threshold (float): ATR/종가 비율 기준 % (default 3.0)
"""
from typing import Any
from app.scanner.conditions.base import Condition


class AtrCondition(Condition):
    """ATR 기반 변동성 필터."""

    name = "atr"

    def evaluate(self, row: dict[str, Any]) -> bool:
        atr14     = row.get("atr14")
        if atr14 is None:
            return False

        use_ratio = bool(self.params.get("use_ratio", False))

        if use_ratio:
            close = row.get("close")
            if close is None or float(close) == 0:
                return False
            value     = float(atr14) / float(close) * 100
            threshold = float(self.params.get("ratio_threshold", 3.0))
        else:
            value     = float(atr14)
            threshold = float(self.params.get("threshold", 500))

        operator = self.params.get("operator", ">")
        if operator == ">":  return value >  threshold
        if operator == ">=": return value >= threshold
        if operator == "<":  return value <  threshold
        if operator == "<=": return value <= threshold
        return False
