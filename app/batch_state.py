"""
배치 실행 상태를 메모리에 보관.
단일 프로세스 환경에서 동작 (멀티 워커 사용 시 Redis 등으로 교체 필요).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_state: dict[str, Any] = {
    "status": "idle",       # idle | running | success | failed
    "trade_date": None,
    "started_at": None,
    "finished_at": None,
    "logs": [],             # [{time, message}]
}


def get() -> dict[str, Any]:
    return dict(_state)


def start(trade_date: str) -> None:
    _state.update(
        status="running",
        trade_date=trade_date,
        started_at=_now(),
        finished_at=None,
        logs=[],
    )
    _log(f"배치 시작 — 기준일: {trade_date}")


def finish(success: bool, message: str = "") -> None:
    _state.update(
        status="success" if success else "failed",
        finished_at=_now(),
    )
    _log(message or ("완료" if success else "실패"))


def log(message: str) -> None:
    _log(message)


def _log(message: str) -> None:
    _state["logs"].append({"time": _now(), "message": message})
    if len(_state["logs"]) > 100:
        _state["logs"] = _state["logs"][-100:]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")
