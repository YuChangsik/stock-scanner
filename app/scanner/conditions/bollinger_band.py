"""
BollingerBandCondition — 볼린저밴드 위치 조건.

params:
  position (str):
    "below_lower"  — 종가 < 하단밴드 (과매도 근접)
    "above_upper"  — 종가 > 상단밴드 (돌파/과매수)
    "below_mid"    — 종가 < 중단밴드 (하락 국면)
    "above_mid"    — 종가 > 중단밴드 (상승 국면, default)
    "near_lower"   — 종가가 하단밴드의 N% 이내 근접 (눌림목)
    "near_upper"   — 종가가 상단밴드의 N% 이내 근접 (돌파 직전)
  near_pct (float): "near_*" 사용 시 근접 허용 범위 % (default 2.0)
"""
from typing import Any
from app.scanner.conditions.base import Condition


class BollingerBandCondition(Condition):
    """볼린저밴드(20일, 2σ) 기준 위치 필터."""

    name = "bollinger_band"

    def evaluate(self, row: dict[str, Any]) -> bool:
        close    = row.get("close")
        bb_upper = row.get("bb_upper")
        bb_mid   = row.get("bb_mid")
        bb_lower = row.get("bb_lower")

        if any(v is None for v in [close, bb_upper, bb_mid, bb_lower]):
            return False

        close, bb_upper, bb_mid, bb_lower = (
            float(close), float(bb_upper), float(bb_mid), float(bb_lower)
        )
        position = self.params.get("position", "above_mid")
        near_pct = float(self.params.get("near_pct", 2.0)) / 100

        if position == "below_lower":
            return close < bb_lower
        if position == "above_upper":
            return close > bb_upper
        if position == "below_mid":
            return close < bb_mid
        if position == "above_mid":
            return close > bb_mid
        if position == "near_lower":
            band_width = bb_upper - bb_lower if bb_upper != bb_lower else 1
            return (close - bb_lower) / band_width <= near_pct
        if position == "near_upper":
            band_width = bb_upper - bb_lower if bb_upper != bb_lower else 1
            return (bb_upper - close) / band_width <= near_pct

        return False
