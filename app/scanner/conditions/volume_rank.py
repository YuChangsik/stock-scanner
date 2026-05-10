from typing import Any

from app.scanner.conditions.base import Condition


class VolumeRankCondition(Condition):
    """
    Passes if the ticker's volume_rank <= threshold on the target date.

    params:
      threshold (int, default 20): max rank to include
    """

    name = "volume_rank"

    def evaluate(self, row: dict[str, Any]) -> bool:
        threshold = int(self.params.get("threshold", 20))
        rank = row.get("volume_rank")
        if rank is None:
            return False
        return int(rank) <= threshold
