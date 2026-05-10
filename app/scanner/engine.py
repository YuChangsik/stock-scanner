"""
ScanEngine — evaluates a set of conditions against indicator snapshots.

Workflow:
1. Load today's indicator snapshots for all tickers.
2. Load yesterday's snapshots for conditions that need prior-day data (golden_cross).
3. Build rows with merged today+prev data.
4. Apply each condition in AND logic — a ticker must pass ALL conditions.
5. Return list of ScanMatch domain objects.

This class has no DB dependency — it receives pre-loaded DataFrames, making
it easy to unit-test with mock data.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from app.core.logging import get_logger
from app.domain.models import IndicatorSnapshot, ScanMatch
from app.scanner.conditions import CONDITION_REGISTRY, Condition
from app.domain.schemas import ConditionDefinition

logger = get_logger(__name__)


class ScanEngine:

    def __init__(self, condition_defs: list[ConditionDefinition]) -> None:
        self._conditions: list[Condition] = self._build_conditions(condition_defs)

    def _build_conditions(self, defs: list[ConditionDefinition]) -> list[Condition]:
        conditions = []
        for cd in defs:
            cls = CONDITION_REGISTRY.get(cd.name)
            if cls is None:
                raise ValueError(
                    f"Unknown condition '{cd.name}'. "
                    f"Available: {list(CONDITION_REGISTRY.keys())}"
                )
            conditions.append(cls(params=cd.params))
        return conditions

    def scan(
        self,
        trade_date: date,
        today_snapshots: list[dict[str, Any]],
        prev_snapshots: list[dict[str, Any]],
        prev_history: list[list[dict[str, Any]]] | None = None,
    ) -> list[ScanMatch]:
        """
        today_snapshots: list of today's indicator dicts.
        prev_snapshots:  most-recent prior day (kept for backward compat).
        prev_history:    list of prior-day snapshot lists ordered newest→oldest,
                         e.g. [day-1_list, day-2_list, …].
                         When provided, conditions get row["prev_history"] as a
                         per-ticker list [day-1_dict, day-2_dict, …].
        """
        # Build per-ticker history: newest day first
        all_days: list[list[dict]] = [prev_snapshots] + (prev_history or [])
        history_by_ticker: dict[str, list[dict]] = {}
        for day_snaps in all_days:
            for r in day_snaps:
                t = r["ticker"]
                history_by_ticker.setdefault(t, []).append(r)

        matches: list[ScanMatch] = []
        for row in today_snapshots:
            ticker = row["ticker"]
            hist = history_by_ticker.get(ticker, [])
            row["prev"] = hist[0] if hist else None  # backward compat
            row["prev_history"] = hist               # newest → oldest

            passed = []
            all_pass = True
            for cond in self._conditions:
                try:
                    result = cond.evaluate(row)
                except Exception as exc:
                    logger.warning(
                        "condition.evaluate_error",
                        condition=cond.name,
                        ticker=ticker,
                        error=str(exc),
                    )
                    result = False
                if result:
                    passed.append(cond.name)
                else:
                    all_pass = False
                    break  # AND logic — short circuit

            if all_pass:
                snapshot = IndicatorSnapshot(
                    ticker=ticker,
                    trade_date=trade_date,
                    ma5=row.get("ma5"),
                    ma20=row.get("ma20"),
                    rsi14=row.get("rsi14"),
                    macd=row.get("macd"),
                    macd_signal=row.get("macd_signal"),
                    prev_high=row.get("prev_high"),
                    per=row.get("per"),
                    pbr=row.get("pbr"),
                    volume_rank=row.get("volume_rank"),
                )
                matches.append(
                    ScanMatch(
                        ticker=ticker,
                        trade_date=trade_date,
                        matched_conditions=passed,
                        snapshot=snapshot,
                    )
                )

        logger.info(
            "scan.complete",
            trade_date=str(trade_date),
            scanned=len(today_snapshots),
            matched=len(matches),
        )
        return matches
