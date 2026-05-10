"""
MaAlignmentCondition — 이동평균선 정배열 조건.

정배열: MA20 > MA60 > MA120 (단기 > 중기 > 장기)
역배열: MA20 < MA60 < MA120

params:
  type (str): "bull" (정배열, default) | "bear" (역배열)
  require_ma60  (bool): MA60 포함 여부 (default True)
  require_ma120 (bool): MA120 포함 여부 (default True)
"""
from typing import Any
from app.scanner.conditions.base import Condition


class MaAlignmentCondition(Condition):
    """정배열 / 역배열 조건."""

    name = "ma_alignment"

    def evaluate(self, row: dict[str, Any]) -> bool:
        align_type   = self.params.get("type", "bull")
        req_ma60     = bool(self.params.get("require_ma60",  True))
        req_ma120    = bool(self.params.get("require_ma120", True))

        ma5   = row.get("ma5")
        ma20  = row.get("ma20")
        ma60  = row.get("ma60")
        ma120 = row.get("ma120")

        if ma5 is None or ma20 is None:
            return False
        if req_ma60  and ma60  is None:
            return False
        if req_ma120 and ma120 is None:
            return False

        ma5, ma20 = float(ma5), float(ma20)
        ma60  = float(ma60)  if ma60  is not None else None
        ma120 = float(ma120) if ma120 is not None else None

        if align_type == "bull":
            # 정배열: MA5 > MA20, MA20 > MA60(옵션), MA60 > MA120(옵션)
            if ma5 <= ma20:
                return False
            if req_ma60 and ma60 is not None and ma20 <= ma60:
                return False
            if req_ma120 and ma120 is not None and (ma60 or ma20) <= ma120:
                return False
            return True
        else:
            # 역배열: MA5 < MA20, MA20 < MA60(옵션), MA60 < MA120(옵션)
            if ma5 >= ma20:
                return False
            if req_ma60 and ma60 is not None and ma20 >= ma60:
                return False
            if req_ma120 and ma120 is not None and (ma60 or ma20) >= ma120:
                return False
            return True
