from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import UserORM


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, username: str, nickname: str, hashed_password: str) -> UserORM:
        user = UserORM(username=username, nickname=nickname, hashed_password=hashed_password)
        self._session.add(user)
        await self._session.flush()
        return user

    async def get_by_username(self, username: str) -> UserORM | None:
        result = await self._session.execute(
            select(UserORM).where(UserORM.username == username)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: int) -> UserORM | None:
        return await self._session.get(UserORM, user_id)

    async def update_conditions(self, user_id: int, conditions: list) -> None:
        user = await self._session.get(UserORM, user_id)
        if user:
            user.scan_conditions = conditions
            await self._session.flush()

    # ── 카카오톡 토큰 ─────────────────────────────────────────────────────────

    async def save_kakao_token(
        self,
        user_id: int,
        access_token: str,
        refresh_token: str,
        expires_at: datetime,
    ) -> None:
        user = await self._session.get(UserORM, user_id)
        if user:
            user.kakao_access_token = access_token
            user.kakao_refresh_token = refresh_token
            user.kakao_token_expires_at = expires_at
            await self._session.flush()

    async def clear_kakao_token(self, user_id: int) -> None:
        user = await self._session.get(UserORM, user_id)
        if user:
            user.kakao_access_token = None
            user.kakao_refresh_token = None
            user.kakao_token_expires_at = None
            await self._session.flush()

    # ── 알림 설정 ─────────────────────────────────────────────────────────────

    async def update_notify_config(
        self,
        user_id: int,
        conditions: list,
        schedule: dict,
    ) -> None:
        user = await self._session.get(UserORM, user_id)
        if user:
            user.notify_conditions = conditions
            user.notify_schedule = schedule
            await self._session.flush()

    async def get_notify_enabled_users(self) -> list[UserORM]:
        """알림이 활성화된 + 카카오 토큰이 있는 사용자 목록."""
        result = await self._session.execute(
            select(UserORM).where(
                UserORM.kakao_access_token.isnot(None),
                UserORM.notify_schedule.isnot(None),
            )
        )
        users = list(result.scalars().all())
        return [
            u for u in users
            if (u.notify_schedule or {}).get("enabled") is True
        ]
