"""
SectorCondition — 지정한 업종(들) 중 하나에 속하는 종목만 통과.

params:
  sectors (list[str]): 허용할 업종 이름 목록 (다중 선택 OR 조건)
                       예) ["음식료품", "전기전자"]

row["sector"]는 ScanEngine이 scan_service로부터 주입한 업종명.
"""
from typing import Any

from app.scanner.conditions.base import Condition


class SectorCondition(Condition):
    name = "sector"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params or {})
        raw = (params or {}).get("sectors", [])
        # sectors는 list 또는 comma-separated string 모두 허용
        if isinstance(raw, str):
            raw = [s.strip() for s in raw.split(",") if s.strip()]
        self._sectors: set[str] = {s.strip() for s in raw if s}

    def evaluate(self, row: dict[str, Any]) -> bool:
        if not self._sectors:
            return True  # 비어 있으면 전체 통과
        sector = row.get("sector")
        if sector is None:
            return False
        return sector in self._sectors
