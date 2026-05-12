from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.exceptions import DataNotAvailableError, ScanJobNotFoundError
from app.core.logging import configure_logging, get_logger
from app.api.routers import stocks, scan, auth, notify, permissions, analysis, public
from fastapi.staticfiles import StaticFiles
from app.db.session import engine, Base
from app.db.models import *  # noqa: F401, F403 — ensure all ORM models are registered
from app.scheduler.setup import create_scheduler

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("app.startup", env=settings.app_env)

    # Create tables (use Alembic in production instead)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # ADD COLUMN IF NOT EXISTS — 이미 존재하는 테이블에 새 컬럼을 안전하게 추가
        migrations = [
            "ALTER TABLE indicator_snapshots ADD COLUMN IF NOT EXISTS macd        NUMERIC(15,6)",
            "ALTER TABLE indicator_snapshots ADD COLUMN IF NOT EXISTS macd_signal NUMERIC(15,6)",
            "ALTER TABLE indicator_snapshots ADD COLUMN IF NOT EXISTS prev_high   NUMERIC(15,2)",
            "ALTER TABLE indicator_snapshots ADD COLUMN IF NOT EXISTS per         NUMERIC(10,2)",
            "ALTER TABLE indicator_snapshots ADD COLUMN IF NOT EXISTS pbr         NUMERIC(10,2)",
            "ALTER TABLE stocks              ADD COLUMN IF NOT EXISTS sector      VARCHAR(100)",
            # 신규 기술적 지표 컬럼
            "ALTER TABLE indicator_snapshots ADD COLUMN IF NOT EXISTS ma60        NUMERIC(15,4)",
            "ALTER TABLE indicator_snapshots ADD COLUMN IF NOT EXISTS ma120       NUMERIC(15,4)",
            "ALTER TABLE indicator_snapshots ADD COLUMN IF NOT EXISTS atr14       NUMERIC(15,4)",
            "ALTER TABLE indicator_snapshots ADD COLUMN IF NOT EXISTS bb_upper    NUMERIC(15,4)",
            "ALTER TABLE indicator_snapshots ADD COLUMN IF NOT EXISTS bb_mid      NUMERIC(15,4)",
            "ALTER TABLE indicator_snapshots ADD COLUMN IF NOT EXISTS bb_lower    NUMERIC(15,4)",
            "ALTER TABLE indicator_snapshots ADD COLUMN IF NOT EXISTS obv         NUMERIC(20,0)",
            "ALTER TABLE indicator_snapshots ADD COLUMN IF NOT EXISTS volume_ma20 NUMERIC(20,2)",
            "ALTER TABLE indicator_snapshots ADD COLUMN IF NOT EXISTS macd_hist   NUMERIC(15,6)",
            # 카카오톡 알림 관련 컬럼
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS kakao_access_token   VARCHAR(2000)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS kakao_refresh_token  VARCHAR(2000)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS kakao_token_expires_at TIMESTAMPTZ",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS notify_conditions    JSONB",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS notify_schedule      JSONB",
            # 역할 관리
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'user'",
        ]
        from sqlalchemy import text
        for sql in migrations:
            await conn.execute(text(sql))

    # 기본 권한 초기화
    from app.api.routers.permissions import ensure_default_permissions
    from app.db.session import AsyncSessionFactory
    async with AsyncSessionFactory() as perm_session:
        await ensure_default_permissions(perm_session)

    scheduler = create_scheduler()
    scheduler.start()
    app.state.scheduler = scheduler

    # 알림 스케줄 잡 부팅 (DB에서 활성 사용자 읽어 등록)
    from app.scheduler.notify_jobs import boot_notify_jobs
    await boot_notify_jobs(scheduler)

    yield

    scheduler.shutdown(wait=False)
    await engine.dispose()
    logger.info("app.shutdown")


app = FastAPI(
    title="Stock Scanner API",
    version="0.1.0",
    description="Korean stock condition scanning system (KOSPI/KOSDAQ)",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── Clean URL middleware (/page → /page.html, /page.html → /page) ─────────────
import os as _os
from fastapi.responses import FileResponse as _FileResponse, RedirectResponse as _RedirectResponse

_FRONTEND_DIR = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "frontend")
_SKIP_PREFIXES = ("/api/", "/docs", "/redoc", "/openapi", "/health")

@app.middleware("http")
async def clean_url_middleware(request: Request, call_next):
    path = request.url.path

    # API / docs / built-in 경로는 그대로 통과
    if any(path.startswith(p) for p in _SKIP_PREFIXES):
        return await call_next(request)

    last = path.rstrip("/").rsplit("/", 1)[-1]

    # /xxx.html → 301 redirect /xxx  (쿼리스트링 유지)
    if path.endswith(".html"):
        base = path[:-5] or "/"
        qs = request.url.query
        return _RedirectResponse(url=base + (f"?{qs}" if qs else ""), status_code=301)

    # 확장자가 있는 정적 파일(css, js, png 등)은 그대로 통과
    if "." in last:
        return await call_next(request)

    # /page 또는 / → frontend/page.html 또는 frontend/index.html 서빙
    if path == "/" or path == "":
        html_file = _os.path.join(_FRONTEND_DIR, "index.html")
    else:
        page = path.strip("/")          # 'main', 'analysis' 등 단일 세그먼트
        if "/" in page:                 # 다단계 경로는 통과
            return await call_next(request)
        html_file = _os.path.join(_FRONTEND_DIR, f"{page}.html")

    if _os.path.isfile(html_file):
        return _FileResponse(html_file)

    return await call_next(request)


# ── Exception handlers ────────────────────────────────────────────────────────

@app.exception_handler(DataNotAvailableError)
async def data_not_available_handler(request: Request, exc: DataNotAvailableError):
    return JSONResponse(status_code=404, content={"error": "not_found", "detail": str(exc)})


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"error": "bad_request", "detail": str(exc)})


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(auth.router,        prefix=settings.api_prefix)
app.include_router(stocks.router,      prefix=settings.api_prefix)
app.include_router(scan.router,        prefix=settings.api_prefix)
app.include_router(notify.router,      prefix=settings.api_prefix)
app.include_router(permissions.router, prefix=settings.api_prefix)
app.include_router(analysis.router,    prefix=settings.api_prefix)
app.include_router(public.router,      prefix=settings.api_prefix)


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.app_env}


@app.post(f"{settings.api_prefix}/admin/trigger-batch")
async def trigger_batch(request: Request, date: str | None = None):
    """Manually trigger the daily batch. date 파라미터로 날짜 지정 가능 (YYYY-MM-DD)."""
    import asyncio
    from datetime import date as date_type
    from app.scheduler.jobs import run_daily_batch, get_latest_trading_day
    from app import batch_state

    # 이미 실행 중이면 거부
    if batch_state.get()["status"] == "running":
        return {"status": "already_running", "trade_date": batch_state.get()["trade_date"]}

    if date:
        trade_date = date_type.fromisoformat(date)
    else:
        trade_date = get_latest_trading_day()

    asyncio.create_task(run_daily_batch(trade_date))
    return {"status": "triggered", "trade_date": str(trade_date)}


@app.post(f"{settings.api_prefix}/admin/trigger-range")
async def trigger_range(request: Request, start_date: str, end_date: str):
    """기간 배치 실행 — start_date ~ end_date 모든 거래일 가격 수집 + 지표 계산."""
    import asyncio
    from datetime import date as date_type
    from app.scheduler.jobs import run_range_batch, get_trading_days_in_range
    from app import batch_state

    if batch_state.get()["status"] == "running":
        return {"status": "already_running", "trade_date": batch_state.get()["trade_date"]}

    try:
        sd = date_type.fromisoformat(start_date)
        ed = date_type.fromisoformat(end_date)
    except ValueError:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"error": "날짜 형식이 올바르지 않습니다 (YYYY-MM-DD)"})

    if sd > ed:
        sd, ed = ed, sd  # 순서 바꿔도 동작

    trading_days = get_trading_days_in_range(sd, ed)
    asyncio.create_task(run_range_batch(sd, ed))
    return {
        "status": "triggered",
        "start_date": str(sd),
        "end_date": str(ed),
        "trading_days": len(trading_days),
    }


@app.get(f"{settings.api_prefix}/admin/batch-status")
async def batch_status():
    """현재 배치 실행 상태 조회."""
    from app import batch_state
    return batch_state.get()


@app.get(f"{settings.api_prefix}/admin/data-dates")
async def admin_data_dates(months: int = 6):
    """
    데이터가 존재하는 거래일 목록 조회.
    price_count(가격), indicator_count(지표) 를 날짜별로 합산 반환.
    months: 조회 범위 (기본 6개월)
    """
    from app.db.session import AsyncSessionFactory
    from app.repository.price_repository import PriceRepository
    from app.repository.indicator_repository import IndicatorRepository

    async with AsyncSessionFactory() as session:
        price_repo = PriceRepository(session)
        ind_repo   = IndicatorRepository(session)

        price_dates = await price_repo.get_available_dates(months=months)
        ind_dates   = await ind_repo.get_available_dates(months=months)

    # 날짜 기준으로 merge
    price_map = {d["date"]: d["price_count"] for d in price_dates}
    ind_map   = {d["date"]: d["indicator_count"] for d in ind_dates}
    all_dates = sorted(set(price_map) | set(ind_map))

    return {
        "months": months,
        "total_days": len(all_dates),
        "dates": [
            {
                "date": d,
                "price_count":     price_map.get(d, 0),
                "indicator_count": ind_map.get(d, 0),
            }
            for d in all_dates
        ],
    }


@app.get(f"{settings.api_prefix}/admin/latest-trading-day")
async def latest_trading_day_api():
    """최근 거래일 반환 (공휴일·주말 제외)."""
    from app.scheduler.jobs import get_latest_trading_day
    return {"trade_date": str(get_latest_trading_day())}


@app.get(f"{settings.api_prefix}/admin/naver-sector-test")
async def naver_sector_test(ticker: str = "005930"):
    """네이버 industryCode → 업종명 변환 테스트."""
    import httpx
    from app.service.collect_service import _WICS_CODE_MAP
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
        "Referer": "https://m.stock.naver.com/",
    }
    async with httpx.AsyncClient(headers=headers, timeout=10.0) as client:
        r = await client.get(f"https://m.stock.naver.com/api/stock/{ticker}/integration")

    obj = r.json() if r.status_code == 200 else {}
    code = str(obj.get("industryCode") or "")
    return {
        "ticker": ticker,
        "industryCode": code,
        "sectorName": _WICS_CODE_MAP.get(code),
        "status": r.status_code,
    }


@app.post(f"{settings.api_prefix}/admin/backfill")
async def backfill(request: Request):
    """
    전종목 과거 OHLCV 백필 실행.
    최초 1회 실행 필수 — MA/RSI 계산에 필요한 최소 60일치 데이터를 수집.
    백그라운드 실행이므로 즉시 응답 반환, 완료까지 수십 분 소요.
    """
    import asyncio
    from app.scheduler.jobs import run_backfill

    asyncio.create_task(run_backfill())
    return {"status": "backfill_started", "message": "백그라운드에서 실행 중. 서버 로그에서 진행상황 확인 가능."}


# Static files must be mounted LAST — it's a catch-all that would block API routes above it
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
