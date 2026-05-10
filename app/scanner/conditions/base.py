"""
Condition ABC — Strategy pattern for scan conditions.

Each Condition is a stateless, parameterized predicate that receives a row
from the merged DataFrame (daily_prices + indicator_snapshots) and returns
True if the condition is satisfied.

Design goals:
- Adding a new condition requires only creating a new subclass here.
- Conditions are composable via AND by the ScanEngine.
- Conditions receive the full indicators dict so they can cross-reference values.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Condition(ABC):
    name: str  # unique identifier used in API requests and scan_results.conditions

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params = params or {}

    @abstractmethod
    def evaluate(self, row: dict[str, Any]) -> bool:
        """
        row keys: ticker, trade_date, open, high, low, close, volume, amount,
                  ma5, ma20, rsi14, volume_rank  (None if not computable)
        """

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.params})"
