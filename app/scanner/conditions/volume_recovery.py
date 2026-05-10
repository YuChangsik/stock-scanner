"""
VolumeRecoveryCondition — 거래량 감소 후 재증가 조건 (눌림목 신호).

최근 N일 동안 거래량이 감소하다가 오늘 반등한 경우를 탐지.

알고리즘:
  1. 오늘(today) 거래량 V_0
  2. 직전 prev_history에서 감소 구간 확인
  3. 감소 구간이 min_down_days 일 이상이고
     오늘 거래량이 감소 구간 평균보다 up_ratio 배 이상이면 통과

params:
  min_down_days (int):  감소 구간 최소 일수 (default 2)
  up_ratio (float):     재증가 배율 (default 1.3)
  lookback (int):       과거 조회 최대 일수 (default 5)
"""
from typing import Any
from app.scanner.conditions.base import Condition


class VolumeRecoveryCondition(Condition):
    """거래량 N일 감소 후 오늘 재증가 포착."""

    name = "volume_recovery"

    def evaluate(self, row: dict[str, Any]) -> bool:
        min_down_days = int(self.params.get("min_down_days", 2))
        up_ratio      = float(self.params.get("up_ratio", 1.3))
        lookback      = int(self.params.get("lookback", 5))

        today_vol  = row.get("volume")
        prev_hist  = row.get("prev_history", [])

        if today_vol is None or len(prev_hist) < min_down_days:
            return False

        # 최근 lookback 일치 거래량 수집 (newest first)
        vols = []
        for h in prev_hist[:lookback]:
            v = h.get("volume") if h else None
            if v is not None:
                vols.append(float(v))

        if len(vols) < min_down_days:
            return False

        # 연속 감소 구간 탐지 (인덱스 0 = 가장 최근)
        down_streak = 0
        for i in range(len(vols) - 1):
            if vols[i] < vols[i + 1]:  # 최근이 이전보다 작으면 감소
                down_streak += 1
            else:
                break

        if down_streak < min_down_days:
            return False

        avg_down_vol = sum(vols[:down_streak]) / down_streak
        return float(today_vol) >= avg_down_vol * up_ratio
