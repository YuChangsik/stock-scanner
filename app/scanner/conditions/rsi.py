from typing import Any

from app.scanner.conditions.base import Condition


class RsiCondition(Condition):
    """
    Passes if RSI14 satisfies a comparison against a threshold.

    params:
      operator (str): '<' | '<=' | '>' | '>=' | '==' (default '<')
      threshold (float, default 40.0)
    """

    name = "rsi14"

    _OPS = {
        "<": lambda a, b: a < b,
        "<=": lambda a, b: a <= b,
        ">": lambda a, b: a > b,
        ">=": lambda a, b: a >= b,
        "==": lambda a, b: a == b,
    }

    def evaluate(self, row: dict[str, Any]) -> bool:
        rsi = row.get("rsi14")
        if rsi is None:
            return False
        op = self.params.get("operator", "<")
        threshold = float(self.params.get("threshold", 40.0))
        comparator = self._OPS.get(op)
        if comparator is None:
            raise ValueError(f"Unknown RSI operator: {op}")
        return comparator(float(rsi), threshold)
