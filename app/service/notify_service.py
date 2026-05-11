"""
NotifyService — 카카오톡 알림 전송 서비스.

흐름:
  1. 사용자가 카카오 REST API Key를 .env에 설정
  2. OAuth 인증 → access_token / refresh_token 저장
  3. 스케줄 + 알림 조건 설정
  4. APScheduler가 설정된 시각에 run_notify_for_user() 호출
     → 스캔 → 매칭 종목 카카오 "나에게 보내기" 전송
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

KAKAO_AUTH_BASE = "https://kauth.kakao.com"
KAKAO_API_BASE  = "https://kapi.kakao.com"


class KakaoOAuthError(Exception):
    pass


class NotifyService:

    # ── OAuth ─────────────────────────────────────────────────────────────────

    @staticmethod
    def get_auth_url() -> str:
        """카카오 OAuth 인증 URL 반환."""
        if not settings.kakao_rest_api_key:
            raise KakaoOAuthError("KAKAO_REST_API_KEY가 설정되지 않았습니다.")
        params = (
            f"client_id={settings.kakao_rest_api_key}"
            f"&redirect_uri={settings.kakao_redirect_uri}"
            f"&response_type=code"
            f"&scope=talk_message"
        )
        return f"{KAKAO_AUTH_BASE}/oauth/authorize?{params}"

    @staticmethod
    async def exchange_code(code: str) -> dict:
        """인증 코드 → access_token / refresh_token 교환."""
        data: dict[str, str] = {
            "grant_type":   "authorization_code",
            "client_id":    settings.kakao_rest_api_key,
            "redirect_uri": settings.kakao_redirect_uri,
            "code":         code,
        }
        # Client Secret 활성화된 앱은 필수로 포함
        if settings.kakao_client_secret:
            data["client_secret"] = settings.kakao_client_secret

        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{KAKAO_AUTH_BASE}/oauth/token",
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10.0,
            )
        if r.status_code != 200:
            raise KakaoOAuthError(f"토큰 교환 실패: {r.text}")
        return r.json()

    @staticmethod
    async def refresh_access_token(refresh_token: str) -> dict:
        """refresh_token으로 새 access_token 발급."""
        data: dict[str, str] = {
            "grant_type":    "refresh_token",
            "client_id":     settings.kakao_rest_api_key,
            "refresh_token": refresh_token,
        }
        if settings.kakao_client_secret:
            data["client_secret"] = settings.kakao_client_secret

        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{KAKAO_AUTH_BASE}/oauth/token",
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10.0,
            )
        if r.status_code != 200:
            raise KakaoOAuthError(f"토큰 갱신 실패: {r.text}")
        return r.json()

    @staticmethod
    async def get_valid_token(user) -> str:
        """
        유효한 access_token 반환.
        만료 5분 전이면 자동 갱신 후 DB 저장.
        """
        from app.db.session import AsyncSessionFactory
        from app.repository.user_repository import UserRepository

        now = datetime.now(tz=timezone.utc)
        expires_at = user.kakao_token_expires_at

        # 만료 5분 전이면 갱신
        if expires_at and now >= expires_at - timedelta(minutes=5):
            if not user.kakao_refresh_token:
                raise KakaoOAuthError("refresh_token이 없습니다. 재연동이 필요합니다.")
            data = await NotifyService.refresh_access_token(user.kakao_refresh_token)
            new_access  = data["access_token"]
            new_refresh = data.get("refresh_token", user.kakao_refresh_token)
            new_expires = now + timedelta(seconds=data.get("expires_in", 21600))

            async with AsyncSessionFactory() as session:
                repo = UserRepository(session)
                await repo.save_kakao_token(user.id, new_access, new_refresh, new_expires)
                await session.commit()

            logger.info("kakao.token_refreshed", user_id=user.id)
            return new_access

        return user.kakao_access_token

    # ── 메시지 전송 ───────────────────────────────────────────────────────────

    @staticmethod
    async def send_message(access_token: str, text: str) -> bool:
        """카카오 '나에게 보내기' (talk/memo)."""
        template = {
            "object_type": "text",
            "text": text[:2000],   # 카카오 최대 2000자
            "link": {
                "web_url":        settings.kakao_redirect_uri.split("/api")[0],
                "mobile_web_url": settings.kakao_redirect_uri.split("/api")[0],
            },
            "button_title": "댕댕투자 열기",
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{KAKAO_API_BASE}/v2/api/talk/memo/default/send",
                data={"template_object": json.dumps(template, ensure_ascii=False)},
                headers={
                    "Authorization":  f"Bearer {access_token}",
                    "Content-Type":   "application/x-www-form-urlencoded;charset=utf-8",
                },
                timeout=10.0,
            )
        if r.status_code == 200 and r.json().get("result_code") == 0:
            return True
        logger.warning("kakao.send_failed", status=r.status_code, body=r.text[:200])
        return False

    # ── 스캔 → 메시지 포맷 ───────────────────────────────────────────────────

    @staticmethod
    def format_message(matches: list[dict], trade_date: str, conditions: list) -> str:
        """매칭 종목 리스트를 카카오 메시지 텍스트로 변환."""
        cond_labels = {
            "volume_rank":        "거래량 순위",
            "rsi14":              "RSI14",
            "golden_cross":       "골든크로스",
            "macd":               "MACD",
            "prev_high_breakout": "전고점 돌파",
            "ma_above":           "기준선 위",
            "per":                "PER",
            "pbr":                "PBR",
            "sector":             "업종",
        }
        cond_strs = []
        for c in (conditions or []):
            name   = c.get("name", "")
            params = c.get("params", {})
            label  = cond_labels.get(name, name)
            if name == "volume_rank":
                label = f"거래량 Top{params.get('threshold', 20)}"
            elif name == "rsi14":
                label = f"RSI {params.get('operator','<')} {params.get('threshold', 40)}"
            elif name == "per":
                label = f"PER {params.get('operator','<')} {params.get('threshold', 15)}"
            elif name == "pbr":
                label = f"PBR {params.get('operator','<')} {params.get('threshold', 1)}"
            cond_strs.append(label)

        lines = [
            "🐶 댕댕투자 알림",
            f"📅 {trade_date}",
            f"조건: {' | '.join(cond_strs)}",
            f"매칭 종목 {len(matches)}개\n",
        ]
        for i, m in enumerate(matches[:20], 1):
            ind  = m.get("indicators") or {}
            per  = f"PER {ind['per']:.1f}" if ind.get("per") else ""
            rsi  = f"RSI {ind['rsi14']:.1f}" if ind.get("rsi14") else ""
            vrank = f"거래량#{ind['volume_rank']}" if ind.get("volume_rank") else ""
            stats = " | ".join(filter(None, [per, rsi, vrank]))
            sector = m.get("sector") or ""
            lines.append(
                f"{i}. {m.get('name') or m['ticker']} ({m['ticker']})"
                + (f" [{sector}]" if sector else "")
                + (f"\n   {stats}" if stats else "")
            )
        if len(matches) > 20:
            lines.append(f"\n…외 {len(matches) - 20}개")
        return "\n".join(lines)

    # ── 스케줄 실행 진입점 ────────────────────────────────────────────────────

    @staticmethod
    async def run_notify_for_user(user_id: int) -> None:
        """
        단일 사용자에 대해 스캔 실행 후 카카오 전송.
        APScheduler에서 호출.
        """
        from app.db.session import AsyncSessionFactory
        from app.repository.user_repository import UserRepository
        from app.repository.indicator_repository import IndicatorRepository
        from app.repository.price_repository import PriceRepository
        from app.repository.stock_repository import StockRepository
        from app.repository.scan_repository import ScanRepository
        from app.service.scan_service import ScanService
        from app.domain.schemas import ConditionDefinition, ScanRequest
        from app.scheduler.jobs import get_latest_trading_day

        async with AsyncSessionFactory() as session:
            user_repo = UserRepository(session)
            user = await user_repo.get_by_id(user_id)
            if not user or not user.kakao_access_token:
                return

            schedule = user.notify_schedule or {}
            if not schedule.get("enabled"):
                return

            conditions_raw = user.notify_conditions or user.scan_conditions or []
            min_matches    = schedule.get("min_matches", 1)

            try:
                access_token = await NotifyService.get_valid_token(user)
            except KakaoOAuthError as e:
                logger.error("notify.token_error", user_id=user_id, error=str(e))
                return

            # 스캔 실행
            trade_date = get_latest_trading_day()
            try:
                conditions = [ConditionDefinition(**c) for c in conditions_raw]
                request    = ScanRequest(trade_date=trade_date, conditions=conditions)

                indicator_repo = IndicatorRepository(session)
                price_repo     = PriceRepository(session)
                stock_repo     = StockRepository(session)
                scan_repo      = ScanRepository(session)
                scan_svc       = ScanService(scan_repo, indicator_repo, price_repo, stock_repo)

                result  = await scan_svc.run_scan(request, job_type="notify")
                matches = result.get("matches", [])
            except Exception as e:
                logger.error("notify.scan_error", user_id=user_id, error=str(e))
                return

            if len(matches) < min_matches:
                logger.info("notify.skipped_min", user_id=user_id,
                            matches=len(matches), min=min_matches)
                return

            text = NotifyService.format_message(matches, str(trade_date), conditions_raw)
            ok   = await NotifyService.send_message(access_token, text)
            logger.info("notify.sent", user_id=user_id, matches=len(matches), ok=ok)
