"""
PbrCondition — PBR(주가순자산비율) 기준 필터.

params:
  operator  : '<' | '<=' | '>' | '>='  (default '<')
  threshold : float (default 1.0)

PBR 데이터 없는 종목(None)은 항상 제외.
"""
from typing import Any

from app.scanner.conditions.base import Condition

_OPS = {
    "<":  lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">":  lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
}


class PbrCondition(Condition):
    name = "pbr"

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        self._op = _OPS.get(params.get("operator", "<"), _OPS["<"])
        self._threshold = float(params.get("threshold", 1.0))

    def evaluate(self, row: dict[str, Any]) -> bool:
        pbr = row.get("pbr")
        if pbr is None:
            return False
        return self._op(float(pbr), self._threshold)
