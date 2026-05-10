from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, decode_token, hash_password, verify_password
from app.db.session import get_db
from app.domain.schemas import ConditionDefinition
from app.repository.user_repository import UserRepository

router = APIRouter(prefix="/auth", tags=["Auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


# ── Schemas ───────────────────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    username: str
    password: str
    nickname: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    nickname: str


class UserMeResponse(BaseModel):
    id: int
    username: str
    nickname: str
    scan_conditions: list


class UpdateConditionsRequest(BaseModel):
    conditions: list[ConditionDefinition]


# ── Dependency: current user ──────────────────────────────────────────────────

async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        user_id: int = payload.get("sub")
        if user_id is None:
            raise credentials_exc
    except JWTError:
        raise credentials_exc

    repo = UserRepository(db)
    user = await repo.get_by_id(int(user_id))
    if user is None:
        raise credentials_exc
    return user


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/signup", response_model=TokenResponse, status_code=201)
async def signup(
    body: SignupRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    repo = UserRepository(db)
    existing = await repo.get_by_username(body.username)
    if existing:
        raise HTTPException(status_code=400, detail="이미 사용 중인 아이디입니다.")

    user = await repo.create(
        username=body.username,
        nickname=body.nickname,
        hashed_password=hash_password(body.password),
    )
    await db.commit()
    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(access_token=token, nickname=user.nickname)


@router.post("/login", response_model=TokenResponse)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    repo = UserRepository(db)
    user = await repo.get_by_username(form.username)
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")

    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(access_token=token, nickname=user.nickname)


@router.get("/me", response_model=UserMeResponse)
async def get_me(current_user=Depends(get_current_user)):
    return UserMeResponse(
        id=current_user.id,
        username=current_user.username,
        nickname=current_user.nickname,
        scan_conditions=current_user.scan_conditions,
    )


@router.put("/me/conditions", response_model=UserMeResponse)
async def update_conditions(
    body: UpdateConditionsRequest,
    current_user=Depends(get_current_user),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    repo = UserRepository(db)
    conditions = [c.model_dump() for c in body.conditions]
    await repo.update_conditions(current_user.id, conditions)
    await db.commit()
    current_user.scan_conditions = conditions
    return UserMeResponse(
        id=current_user.id,
        username=current_user.username,
        nickname=current_user.nickname,
        scan_conditions=conditions,
    )
