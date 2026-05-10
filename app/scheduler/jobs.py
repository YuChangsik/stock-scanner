"""
Daily batch job — runs after market close (default 17:30 KST).

Pipeline:
  1. Refresh stock list
  2. Collect daily prices
  3. Calculate indicators
  4. Run condition scan with default conditions
  5. Persist results

Each step is wrapped independently so a failure in one step is logged
without silently skipping subsequent steps (unless data dependency exists).

Idempotency: upsert semantics on all writes mean re-running the same date
is safe and produces the same outcome.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionFactory
from app.domain.schemas import ConditionDefinition, ScanRequest
from app.provider.fdr_provider import FdrMarketDataProvider
from app.repository.indicator_repository import IndicatorRepository
from app.repository.price_repository import PriceRepository
from app.repository.scan_repository import ScanRepository
from app.repository.stock_repository import StockRepository
from app.service.collect_service import CollectService
from app.service.indicator_service import IndicatorService
from app.service.scan_service import ScanService

logger = get_logger(__name__)

# Default conditions applied in the daily batch scan.
# Override via environment/config as the product evolves.
DEFAULT_SCAN_CONDITIONS: list[dict] = [
    {"name": "volume_rank", "params": {"threshold": 20}},
    {"name": "rsi14", "params": {"operator": "<", "threshold": 40}},
    {"name": "golden_cross", "params": {}},
]



# 한국 공휴일 (주요 날짜 — 매년 업데이트 필요)
KR_HOLIDAYS: set[date] = {
    # 2025
    date(2025, 1, 1),   # 신정
    date(2025, 1, 28),  # 설날 연휴
    date(2025, 1, 29),  # 설날
    date(2025, 1, 30),  # 설날 연휴
    date(2025, 3, 1),   # 삼일절
    date(2025, 5, 1),   # 노동절
    date(2025, 5, 5),   # 어린이날
    date(2025, 5, 6),   # 부처님오신날
    date(2025, 6, 6),   # 현충일
    date(2025, 8, 15),  # 광복절
    date(2025, 10, 3),  # 개천절
    date(2025, 10, 5),  # 추석 연휴
    date(2025, 10, 6),  # 추석
    date(2025, 10, 7),  # 추석 연휴
    date(2025, 10, 9),  # 한글날
    date(2025, 12, 25), # 크리스마스
    # 2026
    date(2026, 1, 1),   # 신정
    date(2026, 2, 16),  # 설날 연휴
    date(2026, 2, 17),  # 설날
    date(2026, 2, 18),  # 설날 연휴
    date(2026, 3, 1),   # 삼일절 (일요일 → 3/2 대체공휴일)
    date(2026, 3, 2),   # 삼일절 대체공휴일
    date(2026, 5, 1),   # 노동절
    date(2026, 5, 5),   # 어린이날
    date(2026, 5, 25),  # 부처님오신날
    date(2026, 6, 6),   # 현충일 (토요일)
    date(2026, 8, 15),  # 광복절 (토요일)
    date(2026, 9, 24),  # 추석 연휴
    date(2026, 9, 25),  # 추석
    date(2026, 9, 26),  # 추석 연휴
    date(2026, 10, 3),  # 개천절 (토요일)
    date(2026, 10, 9),  # 한글날 (금요일)
    date(2026, 12, 25), # 크리스마스
}


def get_latest_trading_day(ref: date | None = None) -> date:
    """주말 + 한국 공휴일을 건너뛰고 가장 최근 거래일을 반환."""
    d = ref or date.today()
    while d.weekday() >= 5 or d in KR_HOLIDAYS:
        d -= timedelta(days=1)
    return d


async def run_daily_batch(trade_date: date | None = None) -> None:
    """Entry point called by APScheduler."""
    from app import batch_state

    if trade_date is None:
        trade_date = get_latest_trading_day()
    else:
        trade_date = get_latest_trading_day(trade_date)

    batch_state.start(str(trade_date))
    logger.info("daily_batch.start", trade_date=str(trade_date))
    provider = FdrMarketDataProvider()

    async with AsyncSessionFactory() as session:
        stock_repo = StockRepository(session)
        price_repo = PriceRepository(session)
        indicator_repo = IndicatorRepository(session)
        scan_repo = ScanRepository(session)

        collect_svc = CollectService(provider, stock_repo, price_repo)
        indicator_svc = IndicatorService(price_repo, indicator_repo, stock_repo=stock_repo)
        scan_svc = ScanService(scan_repo, indicator_repo, price_repo, stock_repo)

        # ── Step 1: 종목 목록 갱신 ─────────────────────────────────────────
        batch_state.log("Step 1/4 — 종목 목록 갱신 중...")
        try:
            result = await collect_svc.refresh_stock_list()
            batch_state.log(f"Step 1/4 완료 — 총 {result.get('active', 0)}개 종목 (업종 포함)")
            logger.info("daily_batch.step1.done", **result)
            await session.commit()
        except Exception as exc:
            batch_state.log(f"Step 1/4 오류 (계속 진행) — {exc}")
            logger.error("daily_batch.step1.failed", error=str(exc))
            await session.rollback()

        # ── Step 2: 가격 수집 ──────────────────────────────────────────────
        batch_state.log("Step 2/4 — 가격 데이터 수집 중... (10~40분 소요)")
        try:
            result = await collect_svc.collect_daily_prices(trade_date)
            batch_state.log(f"Step 2/4 완료 — {result.get('saved', 0)}개 저장")
            logger.info("daily_batch.step2.done", **result)
            await session.commit()
            if result["saved"] == 0:
                batch_state.finish(False, f"{trade_date} 가격 데이터 없음 (공휴일 또는 데이터 미제공일)")
                logger.warning("daily_batch.no_prices.aborting", trade_date=str(trade_date))
                return
        except Exception as exc:
            batch_state.finish(False, f"Step 2 실패 — {exc}")
            logger.error("daily_batch.step2.failed", error=str(exc))
            await session.rollback()
            return

        # ── Step 3: 지표 계산 ──────────────────────────────────────────────
        batch_state.log("Step 3/4 — 기술적 지표 계산 중...")
        try:
            result = await indicator_svc.calculate_for_date(trade_date)
            batch_state.log(f"Step 3/4 완료 — {result.get('calculated', 0)}개 지표 저장")
            logger.info("daily_batch.step3.done", **result)
            await session.commit()
        except Exception as exc:
            batch_state.finish(False, f"Step 3 실패 — {exc}")
            logger.error("daily_batch.step3.failed", error=str(exc))
            await session.rollback()
            return

        # ── Step 4: 스캔 실행 ──────────────────────────────────────────────
        batch_state.log("Step 4/4 — 기본 조건 스캔 실행 중...")
        try:
            conditions = [ConditionDefinition(**c) for c in DEFAULT_SCAN_CONDITIONS]
            request = ScanRequest(trade_date=trade_date, conditions=conditions)
            result = await scan_svc.run_scan(request, job_type="daily_batch")
            matched = len(result.get("matches", []))
            batch_state.log(f"Step 4/4 완료 — {matched}개 종목 매칭")
            await session.commit()
            logger.info("daily_batch.step4.done", trade_date=str(trade_date), matched=matched)
        except Exception as exc:
            batch_state.finish(False, f"Step 4 실패 — {exc}")
            logger.error("daily_batch.step4.failed", error=str(exc))
            await session.rollback()
            return

    batch_state.finish(True, f"배치 완료 — {trade_date} 처리 성공")
    logger.info("daily_batch.complete", trade_date=str(trade_date))


def get_trading_days_in_range(start: date, end: date) -> list[date]:
    """start ~ end 사이의 거래일 목록 (주말·공휴일 제외, 오름차순)."""
    days = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5 and cur not in KR_HOLIDAYS:
            days.append(cur)
        cur += timedelta(days=1)
    return days


async def run_range_batch(start_date: date, end_date: date) -> None:
    """
    기간 내 모든 거래일에 대해 가격 수집 + 지표 계산 실행.

    - 종목 목록은 최초 1회만 갱신
    - 각 거래일마다 가격 수집 → 지표 계산 순서로 실행
    - 데이터 없는 날(공휴일/미제공)은 건너뜀
    - 멱등: upsert 구조라 재실행해도 중복 없음
    """
    from app import batch_state

    trading_days = get_trading_days_in_range(start_date, end_date)
    if not trading_days:
        logger.warning("range_batch.no_trading_days", start=str(start_date), end=str(end_date))
        return

    label = f"{start_date} ~ {end_date} ({len(trading_days)}일)"
    batch_state.start(label)
    logger.info("range_batch.start", start=str(start_date), end=str(end_date), days=len(trading_days))

    provider = FdrMarketDataProvider()

    async with AsyncSessionFactory() as session:
        stock_repo = StockRepository(session)
        price_repo = PriceRepository(session)
        indicator_repo = IndicatorRepository(session)

        collect_svc = CollectService(provider, stock_repo, price_repo)
        indicator_svc = IndicatorService(price_repo, indicator_repo, stock_repo=stock_repo)

        # ── Step 1: 종목 목록 갱신 (1회) ──────────────────────────────────
        batch_state.log("Step 1 — 종목 목록 갱신 중...")
        try:
            result = await collect_svc.refresh_stock_list()
            batch_state.log(f"Step 1 완료 — {result.get('active', 0)}개 종목")
            await session.commit()
        except Exception as exc:
            batch_state.log(f"Step 1 오류 (계속 진행) — {exc}")
            logger.error("range_batch.step1.failed", error=str(exc))
            await session.rollback()

        # ── Step 2~3: 날짜별 수집 + 지표 ──────────────────────────────────
        success, skipped = 0, 0
        total = len(trading_days)
        for i, trade_date in enumerate(trading_days, 1):
            batch_state.log(f"[{i}/{total}] {trade_date} — 가격 수집 중...")
            try:
                price_result = await collect_svc.collect_daily_prices(trade_date)
                await session.commit()
                saved = price_result.get("saved", 0)
                if saved == 0:
                    batch_state.log(f"[{i}/{total}] {trade_date} — 가격 없음, 건너뜀")
                    skipped += 1
                    continue
                batch_state.log(f"[{i}/{total}] {trade_date} — {saved}개 저장, 지표 계산 중...")
            except Exception as exc:
                batch_state.log(f"[{i}/{total}] {trade_date} — 가격 수집 실패: {exc}")
                logger.error("range_batch.price.failed", date=str(trade_date), error=str(exc))
                await session.rollback()
                skipped += 1
                continue

            try:
                ind_result = await indicator_svc.calculate_for_date(trade_date)
                await session.commit()
                batch_state.log(
                    f"[{i}/{total}] {trade_date} — 지표 {ind_result.get('calculated', 0)}개 완료"
                )
                success += 1
            except Exception as exc:
                batch_state.log(f"[{i}/{total}] {trade_date} — 지표 계산 실패: {exc}")
                logger.error("range_batch.indicator.failed", date=str(trade_date), error=str(exc))
                await session.rollback()
                skipped += 1

    summary = f"기간 배치 완료 — 성공 {success}일 / 건너뜀 {skipped}일 (전체 {total}일)"
    batch_state.finish(True, summary)
    logger.info("range_batch.complete", success=success, skipped=skipped, total=total)


async def run_backfill(lookback_days: int | None = None) -> None:
    """
    전종목 과거 OHLCV 백필.
    최초 1회 실행 필수 — 지표 계산에 필요한 최소 60일치 데이터를 수집.

    전략: 종목별로 fdr.DataReader(ticker, start, end) 1회 호출 → 기간 전체 수집.
    upsert 구조라 재실행해도 중복 저장 없음(멱등).
    """
    days = lookback_days or settings.default_lookback_days + 10  # 여유분 포함
    end_date = get_latest_trading_day()
    start_date = end_date - timedelta(days=days)

    logger.info("backfill.start", start=str(start_date), end=str(end_date), days=days)

    provider = FdrMarketDataProvider()

    async with AsyncSessionFactory() as session:
        stock_repo = StockRepository(session)
        price_repo = PriceRepository(session)
        collect_svc = CollectService(provider, stock_repo, price_repo)

        tickers = await stock_repo.get_active_tickers()

        if not tickers:
            logger.warning("backfill.no_tickers — run trigger-batch first to populate stocks")
            return

        logger.info("backfill.ticker_count", count=len(tickers))

        success, failed = 0, 0
        for i, ticker in enumerate(tickers):
            try:
                result = await collect_svc.collect_historical(ticker, start_date, end_date)
                await session.commit()
                success += 1
            except Exception as exc:
                await session.rollback()
                failed += 1
                logger.warning("backfill.ticker_failed", ticker=ticker, error=str(exc))

            if (i + 1) % 100 == 0:
                logger.info(
                    "backfill.progress",
                    done=i + 1,
                    total=len(tickers),
                    success=success,
                    failed=failed,
                )

    logger.info("backfill.complete", success=success, failed=failed, total=len(tickers))
