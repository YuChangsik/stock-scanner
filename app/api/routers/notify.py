"""
notify.py — 카카오톡 알림 설정 & OAuth 라우터.

엔드포인트:
  GET  /notify/kakao/auth-url        OAuth 인증 URL 반환
  GET  /notify/kakao/callback        OAuth 코드 교환 후 토큰 저장 → 리다이렉트
  GET  /notify/kakao/status          연동 상태 (connected / disconnected + 만료일)
  DELETE /notify/kakao/disconnect    토큰 삭제 (연동 해제)
  POST /notify/kakao/test            테스트 메시지 전송
  GET  /notify/config                현재 알림 조건 + 스케줄 조회
  PUT  /notify/config                알림 조건 + 스케줄 저장
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers.auth import get_current_user
from app.db.session import get_db
from app.repository.user_repository import UserRepository
from app.service.notify_service import KakaoOAuthError, NotifyService

router = APIRouter(prefix="/notify", tags=["Notify"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class KakaoStatusResponse(BaseModel):
    connected: bool
    expires_at: str | None = None          # ISO 8601


class NotifyConfig(BaseModel):
    conditions: list[dict[str, Any]] = []
    schedule: dict[str, Any] = {}


# ── Helper ────────────────────────────────────────────────────────────────────

def _user_dep():
    """get_current_user 주입 shorthand."""
    return Depends(get_current_user)


def _db_dep():
    return Depends(get_db)


# ── OAuth ─────────────────────────────────────────────────────────────────────

@router.get("/kakao/auth-url")
async def kakao_auth_url(current_user=Depends(get_current_user)):
    """카카오 OAuth 인증 URL 반환."""
    try:
        url = NotifyService.get_auth_url()
    except KakaoOAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"auth_url": url}


@router.get("/kakao/callback")
async def kakao_callback(
    code: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    카카오 OAuth 콜백.
    인증 코드를 토큰으로 교환한 뒤 DB에 저장하고
    프론트엔드 알림 설정 페이지로 리다이렉트한다.

    ⚠️ 이 엔드포인트는 JWT 인증 없이 호출된다 (카카오 서버가 리다이렉트).
       실 서비스라면 state 파라미터로 CSRF 방어 필요.
       여기서는 단순 구현으로 마지막 로그인 사용자(id=1)에 저장한다.
       멀티유저 환경에서는 state=<user_id> 패턴 사용 권장.
    """
    try:
        token_data = await NotifyService.exchange_code(code)
    except KakaoOAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))

    access_token  = token_data["access_token"]
    refresh_token = token_data.get("refresh_token", "")
    expires_in    = token_data.get("expires_in", 21600)
    expires_at    = datetime.now(tz=timezone.utc).__class__.now(tz=timezone.utc)
    from datetime import timedelta
    expires_at    = datetime.now(tz=timezone.utc) + timedelta(seconds=expires_in)

    # state 파라미터로 user_id를 전달받을 수 있으면 사용, 없으면 id=1
    # (간단한 관리자 전용 구현)
    repo = UserRepository(db)
    # 가장 먼저 가입된 사용자(관리자)에 저장
    from sqlalchemy import select
    from app.db.models.user import UserORM
    result = await db.execute(select(UserORM).order_by(UserORM.id).limit(1))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    await repo.save_kakao_token(user.id, access_token, refresh_token, expires_at)
    await db.commit()

    # 프론트엔드 알림 설정 페이지로 리다이렉트
    return RedirectResponse(url="/notify.html?kakao=connected")


@router.get("/kakao/status", response_model=KakaoStatusResponse)
async def kakao_status(current_user=Depends(get_current_user)):
    """카카오 연동 상태 조회."""
    connected  = bool(current_user.kakao_access_token)
    expires_at = None
    if current_user.kakao_token_expires_at:
        expires_at = current_user.kakao_token_expires_at.isoformat()
    return KakaoStatusResponse(connected=connected, expires_at=expires_at)


@router.delete("/kakao/disconnect")
async def kakao_disconnect(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """카카오 연동 해제 (토큰 삭제)."""
    repo = UserRepository(db)
    await repo.clear_kakao_token(current_user.id)
    await db.commit()
    return {"ok": True, "message": "카카오톡 연동이 해제되었습니다."}


@router.post("/kakao/test")
async def kakao_test(current_user=Depends(get_current_user)):
    """테스트 메시지 전송."""
    if not current_user.kakao_access_token:
        raise HTTPException(status_code=400, detail="카카오톡 연동이 필요합니다.")
    try:
        access_token = await NotifyService.get_valid_token(current_user)
    except KakaoOAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))

    now_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ok = await NotifyService.send_message(
        access_token,
        f"🐶 댕댕투자 테스트 메시지\n\n연동이 정상적으로 완료되었습니다.\n전송 시각: {now_str}",
    )
    if not ok:
        raise HTTPException(status_code=502, detail="카카오 메시지 전송에 실패했습니다.")
    return {"ok": True, "message": "테스트 메시지가 전송되었습니다."}


# ── 알림 설정 CRUD ─────────────────────────────────────────────────────────────

@router.get("/config", response_model=NotifyConfig)
async def get_notify_config(current_user=Depends(get_current_user)):
    """현재 알림 조건 + 스케줄 조회."""
    return NotifyConfig(
        conditions=current_user.notify_conditions or [],
        schedule=current_user.notify_schedule or {},
    )


@router.put("/config", response_model=NotifyConfig)
async def update_notify_config(
    body: NotifyConfig,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """알림 조건 + 스케줄 저장."""
    # schedule 유효성 검사
    sch = body.schedule
    if sch.get("time"):
        try:
            datetime.strptime(sch["time"], "%H:%M")
        except ValueError:
            raise HTTPException(status_code=400, detail="time 형식은 HH:MM 이어야 합니다.")
    weekdays = sch.get("weekdays", [])
    if not isinstance(weekdays, list) or any(d not in range(7) for d in weekdays):
        raise HTTPException(status_code=400, detail="weekdays는 0~6 정수 리스트여야 합니다.")

    repo = UserRepository(db)
    await repo.update_notify_config(
        current_user.id,
        [c if isinstance(c, dict) else c.model_dump() for c in body.conditions],
        body.schedule,
    )
    await db.commit()

    # 스케줄러 동적 업데이트
    try:
        from app.scheduler.notify_jobs import reschedule_user_notify
        await reschedule_user_notify(current_user.id, body.schedule)
    except Exception:
        pass  # 스케줄러 미등록 시 무시

    return body
