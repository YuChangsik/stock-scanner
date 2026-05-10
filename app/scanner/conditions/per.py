"""
PerCondition — PER(주가수익비율) 기준 필터.

params:
  operator  : '<' | '<=' | '>' | '>='  (default '<')
  threshold : float (default 15)

PER 데이터 없는 종목(None)은 항상 제외.
"""
from typing import Any

from app.scanner.conditions.base import Condition

_OPS = {
    "<":  lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">":  lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
}


class PerCondition(Condition):
    name = "per"

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        self._op = _OPS.get(params.get("operator", "<"), _OPS["<"])
        self._threshold = float(params.get("threshold", 15))

    def evaluate(self, row: dict[str, Any]) -> bool:
        per = row.get("per")
        if per is None:
            return False
        return self._op(float(per), self._threshold)
