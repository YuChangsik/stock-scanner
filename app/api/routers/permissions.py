"""
permissions.py — 권한관리 라우터 (admin 전용)

엔드포인트:
  GET  /permissions/pages          전체 페이지 목록
  GET  /permissions/roles          역할별 권한 조회
  PUT  /permissions/roles/{role}   역할 권한 수정
  GET  /permissions/users          사용자 목록 + 역할
  PUT  /permissions/users/{uid}    사용자 역할 변경
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers.auth import get_current_user
from app.db.models.analysis import RolePermissionORM
from app.db.models.user import UserORM
from app.db.session import get_db

router = APIRouter(prefix="/permissions", tags=["Permissions"])

# 전체 페이지 정의
ALL_PAGES = [
    {"key": "home",        "label": "홈",        "path": "/main.html"},
    {"key": "settings",    "label": "조건설정",   "path": "/settings.html"},
    {"key": "sector",      "label": "업종현황",   "path": "/sector.html"},
    {"key": "research",    "label": "리서치",     "path": "/research.html"},
    {"key": "analysis",    "label": "종목분석",   "path": "/analysis.html"},
    {"key": "notify",      "label": "알림설정",   "path": "/notify.html"},
    {"key": "admin",       "label": "배치관리",   "path": "/admin.html"},
    {"key": "permissions", "label": "권한관리",   "path": "/permissions.html"},
]

ROLES = ["admin", "user"]


def _require_admin(current_user=Depends(get_current_user)):
    if getattr(current_user, "role", "user") != "admin":
        raise HTTPException(status_code=403, detail="관리자만 접근 가능합니다.")
    return current_user


# ── 기본 권한 초기화 헬퍼 ─────────────────────────────────────────────────────

async def ensure_default_permissions(session: AsyncSession) -> None:
    """앱 시작 시 기본 권한 행이 없으면 생성."""
    defaults = {
        "admin": [p["key"] for p in ALL_PAGES],  # 모든 페이지
        "user":  ["home", "settings", "sector", "research", "analysis"],
    }
    for role, pages in defaults.items():
        result = await session.execute(
            select(RolePermissionORM).where(RolePermissionORM.role == role)
        )
        if result.scalar_one_or_none() is None:
            session.add(RolePermissionORM(role=role, allowed_pages=pages))
    await session.commit()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/pages")
async def get_pages(_=Depends(_require_admin)):
    return {"pages": ALL_PAGES}


@router.get("/roles")
async def get_role_permissions(
    _=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(select(RolePermissionORM))).scalars().all()
    result = {r.role: r.allowed_pages for r in rows}
    # 없는 역할은 기본값으로 채우기
    for role in ROLES:
        if role not in result:
            result[role] = [p["key"] for p in ALL_PAGES] if role == "admin" else ["home", "settings", "sector", "research", "analysis"]
    return {"roles": result, "pages": ALL_PAGES}


class UpdateRolePermRequest(BaseModel):
    allowed_pages: list[str]


@router.put("/roles/{role}")
async def update_role_permissions(
    role: str,
    body: UpdateRolePermRequest,
    _=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    if role not in ROLES:
        raise HTTPException(status_code=400, detail=f"유효한 역할: {ROLES}")
    if role == "admin":
        raise HTTPException(status_code=400, detail="관리자 권한은 변경할 수 없습니다.")

    # 유효한 페이지 키만 허용
    valid_keys = {p["key"] for p in ALL_PAGES}
    allowed = [k for k in body.allowed_pages if k in valid_keys]

    row = (await db.execute(
        select(RolePermissionORM).where(RolePermissionORM.role == role)
    )).scalar_one_or_none()

    if row:
        row.allowed_pages = allowed
    else:
        db.add(RolePermissionORM(role=role, allowed_pages=allowed))

    await db.commit()
    return {"role": role, "allowed_pages": allowed}


@router.get("/users")
async def get_users(
    _=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    users = (await db.execute(select(UserORM))).scalars().all()
    return {
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "nickname": u.nickname,
                "role": getattr(u, "role", "user"),
                "is_active": u.is_active,
                "created_at": str(u.created_at),
            }
            for u in users
        ]
    }


class UpdateUserRoleRequest(BaseModel):
    role: str


@router.put("/users/{uid}")
async def update_user_role(
    uid: int,
    body: UpdateUserRoleRequest,
    current_user=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    if body.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"유효한 역할: {ROLES}")

    user = (await db.execute(
        select(UserORM).where(UserORM.id == uid)
    )).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    user.role = body.role
    await db.commit()
    return {"id": uid, "role": body.role}
