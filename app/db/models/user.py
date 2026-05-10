from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class UserORM(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    nickname: Mapped[str] = mapped_column(String(50), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # 사용자 커스텀 스캔 조건
    scan_conditions: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: [
            {"name": "volume_rank", "params": {"threshold": 20}},
            {"name": "rsi14", "params": {"operator": "<", "threshold": 40}},
        ],
    )

    # 카카오톡 OAuth 토큰
    kakao_access_token: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    kakao_refresh_token: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    kakao_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 알림 전송 조건 (scan_conditions와 별개)
    notify_conditions: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # 알림 스케줄 JSON
    # {
    #   "enabled": true,
    #   "weekdays": [0,1,2,3,4],   # 0=월 … 6=일
    #   "time": "09:00",
    #   "min_matches": 1            # 매칭 종목 최소 수 (0이면 항상 전송)
    # }
    notify_schedule: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
