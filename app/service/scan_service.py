"""
ScanService — ties together the ScanEngine with DB persistence.

Responsibilities:
- Create/update ScanJob records.
- Load indicator snapshots (today + prev day) from DB.
- Invoke ScanEngine.
- Persist ScanResult rows.
- Return results for API consumption.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from app.core.exceptions import ScanJobNotFoundError
from app.core.logging import get_logger
from app.domain.models import ScanMatch
from app.domain.schemas import ConditionDefinition, ScanRequest
from app.repository.indicator_repository import IndicatorRepository
from app.repository.price_repository import PriceRepository
from app.repository.scan_repository import ScanRepository
from app.repository.stock_repository import StockRepository
from app.scanner.engine import ScanEngine

logger = get_logger(__name__)


class ScanService:
    def __init__(
        self,
        scan_repo: ScanRepository,
        indicator_repo: IndicatorRepository,
        price_repo: PriceRepository,
        stock_repo: StockRepository,
    ) -> None:
        self._scan_repo = scan_repo
        self._indicator_repo = indicator_repo
        self._price_repo = price_repo
        self._stock_repo = stock_repo

    async def run_scan(self, request: ScanRequest, job_type: str = "manual_scan") -> dict:
        job_id = str(uuid.uuid4())
        job = await self._scan_repo.create_job({
            "id": job_id,
            "job_type": job_type,
            "trade_date": request.trade_date,
            "status": "running",
            "started_at": datetime.now(tz=timezone.utc),
            "meta": {"conditions": [c.model_dump() for c in request.conditions]},
        })

        try:
            today_snaps = await self._indicator_repo.get_by_date(request.trade_date)
            if not today_snaps:
                await self._scan_repo.update_job(job_id, {
                    "status": "failed",
                    "finished_at": datetime.now(tz=timezone.utc),
                    "error_msg": f"No indicator data for {request.trade_date}",
                })
                return {"job_id": job_id, "status": "failed", "matches": []}

            # 과거 거래일 수 결정 — 조건별 lookback 파라미터 합산
            max_within_days = 1
            for c in request.conditions:
                params = c.params or {}
                if c.name == "golden_cross":
                    max_within_days = max(max_within_days, int(params.get("within_days", 1)))
                elif c.name == "obv_rising":
                    max_within_days = max(max_within_days, int(params.get("lookback_days", 5)))
                elif c.name == "volume_recovery":
                    max_within_days = max(max_within_days, int(params.get("lookback", 5)))

            # Load previous trading day snapshots (최대 max_within_days 일치)
            prev_dates = await self._get_prev_trade_dates(request.trade_date, max_within_days)
            prev_snaps_list: list[list] = []
            for pd_ in prev_dates:
                snaps = await self._indicator_repo.get_by_date(pd_)
                prev_snaps_list.append(snaps)

            today_rows = [self._snap_to_dict(s) for s in today_snaps]

            # 과거 날짜별 가격 데이터 로드 (volume_recovery, obv_rising 등에서 volume 사용)
            prev_prices_maps: list[dict] = []
            for pd_ in prev_dates:
                prev_prices = await self._price_repo.get_by_date(pd_)
                prev_prices_maps.append({p.ticker: p for p in prev_prices})

            # most-recent prev day (for backward compat) + older days
            prev_rows = [self._snap_to_dict(s) for s in prev_snaps_list[0]] if prev_snaps_list else []
            # prev_rows에 거래량/종가 주입
            if prev_prices_maps:
                pm = prev_prices_maps[0]
                for row in prev_rows:
                    p = pm.get(row["ticker"])
                    if p:
                        row["volume"] = int(p.volume)
                        row["close"]  = float(p.close)

            extra_prev = []
            for i, day_snaps in enumerate(prev_snaps_list[1:], start=1):
                day_rows = [self._snap_to_dict(s) for s in day_snaps]
                if i < len(prev_prices_maps):
                    pm = prev_prices_maps[i]
                    for row in day_rows:
                        p = pm.get(row["ticker"])
                        if p:
                            row["volume"] = int(p.volume)
                            row["close"]  = float(p.close)
                extra_prev.append(day_rows)

            # 업종(sector) 주입 — sector 조건 및 결과 표시에 사용
            sector_map = await self._stock_repo.get_sector_map()
            for row in today_rows:
                row["sector"] = sector_map.get(row["ticker"])

            # 종가/거래량을 rows에 미리 주입 (전고점 돌파 등 가격 기반 조건에 필요)
            day_prices = await self._price_repo.get_by_date(request.trade_date)
            prices_map = {p.ticker: p for p in day_prices}
            for row in today_rows:
                p = prices_map.get(row["ticker"])
                if p:
                    row["close"]  = float(p.close)
                    row["volume"] = int(p.volume)
                    row["amount"] = int(p.amount)

            # PER/PBR 온디맨드 주입 ─ DB에 데이터 없으면 pykrx에서 즉시 수집
            _FUND_CONDITIONS = {"per", "pbr"}
            requested_funds = {c.name for c in request.conditions if c.name in _FUND_CONDITIONS}
            if requested_funds:
                needs_fetch = any(row.get(f) is None for row in today_rows for f in requested_funds)
                if needs_fetch:
                    from app.service.indicator_service import IndicatorService
                    tickers = [row["ticker"] for row in today_rows]
                    fundamentals = await IndicatorService._fetch_fundamentals(tickers)
                    if not fundamentals:
                        raise ValueError(
                            f"PER/PBR 데이터를 {request.trade_date} 기준으로 수집하지 못했습니다. "
                            "장 마감 전이거나 공휴일·주말이면 데이터가 제공되지 않습니다. "
                            "전 거래일 날짜로 변경하거나, 배치관리에서 배치를 실행한 뒤 다시 시도하세요."
                        )
                    for row in today_rows:
                        fund = fundamentals.get(row["ticker"], {})
                        if row.get("per") is None:
                            row["per"] = fund.get("per")
                        if row.get("pbr") is None:
                            row["pbr"] = fund.get("pbr")
                    logger.info("scan.fundamentals_injected", date=str(request.trade_date), count=len(fundamentals))

            engine = ScanEngine(request.conditions)
            matches = engine.scan(request.trade_date, today_rows, prev_rows, extra_prev)

            # 거래량 순위 오름차순 정렬 (1위가 가장 거래량 많음)
            matches.sort(
                key=lambda m: m.snapshot.volume_rank
                if m.snapshot.volume_rank is not None
                else 999999
            )

            await self._persist_results(job_id, matches)
            await self._scan_repo.update_job(job_id, {
                "status": "success",
                "finished_at": datetime.now(tz=timezone.utc),
                "meta": {
                    "conditions": [c.model_dump() for c in request.conditions],
                    "scanned": len(today_rows),
                    "matched": len(matches),
                },
            })

            # 종목명 조회 (prices_map은 이미 위에서 생성)
            stock_names: dict[str, str | None] = {}

            for m in matches:
                if m.ticker not in stock_names:
                    stock = await self._stock_repo.get_by_ticker(m.ticker)
                    stock_names[m.ticker] = stock.name if stock else None

            return {
                "job_id": job_id,
                "status": "success",
                "matches": [
                    self._match_to_dict(
                        m,
                        stock_names.get(m.ticker),
                        prices_map.get(m.ticker),
                        sector_map.get(m.ticker),
                    )
                    for m in matches
                ],
            }

        except Exception as exc:
            logger.error("scan_service.run_scan.error", job_id=job_id, error=str(exc))
            await self._scan_repo.update_job(job_id, {
                "status": "failed",
                "finished_at": datetime.now(tz=timezone.utc),
                "error_msg": str(exc),
            })
            raise

    async def get_latest_results(self) -> dict | None:
        job = await self._scan_repo.get_latest_job(job_type="daily_batch")
        if job is None:
            return None

        results = await self._scan_repo.get_results_by_job(job.id)

        # 거래량 순위 오름차순 정렬
        results.sort(key=lambda r: (r.snapshot or {}).get("volume_rank") or 999999)

        # Enrich with stock names, sector and price data (open/close for change_pct)
        stock_names: dict[str, str | None] = {}
        for r in results:
            if r.ticker not in stock_names:
                stock = await self._stock_repo.get_by_ticker(r.ticker)
                stock_names[r.ticker] = stock.name if stock else None

        sector_map = await self._stock_repo.get_sector_map()
        day_prices = await self._price_repo.get_by_date(job.trade_date)
        prices_map = {p.ticker: p for p in day_prices}

        def _enrich_snapshot(r) -> dict:
            snap = dict(r.snapshot) if r.snapshot else {}
            price = prices_map.get(r.ticker)
            if price:
                snap["open"] = float(price.open)
                snap["close"] = float(price.close)
                snap["volume"] = int(price.volume)
                snap["amount"] = int(price.amount)
                o = float(price.open)
                snap["change_pct"] = (
                    round((float(price.close) - o) / o * 100, 2) if o != 0 else None
                )
            return snap

        return {
            "job": {
                "job_id": job.id,
                "trade_date": job.trade_date,
                "status": job.status,
                "match_count": len(results),
                "started_at": job.started_at,
                "finished_at": job.finished_at,
            },
            "matches": [
                {
                    "ticker": r.ticker,
                    "name": stock_names.get(r.ticker),
                    "sector": sector_map.get(r.ticker),
                    "trade_date": r.trade_date,
                    "matched_conditions": r.conditions,
                    "indicators": _enrich_snapshot(r),
                }
                for r in results
            ],
        }

    async def _persist_results(self, job_id: str, matches: list[ScanMatch]) -> None:
        rows = [
            {
                "job_id": job_id,
                "ticker": m.ticker,
                "trade_date": m.trade_date,
                "conditions": m.matched_conditions,
                "snapshot": {
                    "ma5": float(m.snapshot.ma5) if m.snapshot.ma5 else None,
                    "ma20": float(m.snapshot.ma20) if m.snapshot.ma20 else None,
                    "rsi14": float(m.snapshot.rsi14) if m.snapshot.rsi14 else None,
                    "macd": float(m.snapshot.macd) if m.snapshot.macd else None,
                    "macd_signal": float(m.snapshot.macd_signal) if m.snapshot.macd_signal else None,
                    "prev_high": float(m.snapshot.prev_high) if m.snapshot.prev_high else None,
                    "per": float(m.snapshot.per) if m.snapshot.per else None,
                    "pbr": float(m.snapshot.pbr) if m.snapshot.pbr else None,
                    "volume_rank": m.snapshot.volume_rank,
                },
            }
            for m in matches
        ]
        await self._scan_repo.insert_results(rows)

    async def _get_prev_trade_date(self, trade_date: date) -> date | None:
        dates = await self._get_prev_trade_dates(trade_date, 1)
        return dates[0] if dates else None

    async def _get_prev_trade_dates(self, trade_date: date, n: int) -> list[date]:
        """Return up to n previous trading dates before trade_date, newest first."""
        from datetime import timedelta
        result: list[date] = []
        # Search up to n*3 calendar days to account for weekends/holidays
        for i in range(1, n * 3 + 10):
            candidate = trade_date - timedelta(days=i)
            prices = await self._price_repo.get_by_date(candidate)
            if prices:
                result.append(candidate)
                if len(result) >= n:
                    break
        return result

    @staticmethod
    def _snap_to_dict(snap) -> dict:
        return {
            "ticker":       snap.ticker,
            "trade_date":   snap.trade_date,
            "ma5":          snap.ma5,
            "ma20":         snap.ma20,
            "ma60":         getattr(snap, "ma60",        None),
            "ma120":        getattr(snap, "ma120",       None),
            "rsi14":        snap.rsi14,
            "macd":         snap.macd,
            "macd_signal":  snap.macd_signal,
            "macd_hist":    getattr(snap, "macd_hist",   None),
            "atr14":        getattr(snap, "atr14",       None),
            "bb_upper":     getattr(snap, "bb_upper",    None),
            "bb_mid":       getattr(snap, "bb_mid",      None),
            "bb_lower":     getattr(snap, "bb_lower",    None),
            "obv":          getattr(snap, "obv",         None),
            "volume_ma20":  getattr(snap, "volume_ma20", None),
            "prev_high":    snap.prev_high,
            "per":          snap.per,
            "pbr":          snap.pbr,
            "volume_rank":  snap.volume_rank,
            # prev_history 조건(obv_rising, volume_recovery)에서 사용
            "volume":       None,  # price 주입 후 채워짐 (today_rows 전용)
        }

    @staticmethod
    def _match_to_dict(m: ScanMatch, name: str | None = None, price=None, sector: str | None = None) -> dict:
        return {
            "ticker": m.ticker,
            "name": name,
            "sector": sector,
            "trade_date": str(m.trade_date),
            "matched_conditions": m.matched_conditions,
            "indicators": {
                "open": float(price.open) if price else None,
                "close": float(price.close) if price else None,
                "change_pct": (
                    round((float(price.close) - float(price.open)) / float(price.open) * 100, 2)
                    if price and float(price.open) != 0 else None
                ),
                "volume": int(price.volume) if price else None,
                "amount": int(price.amount) if price else None,
                "ma5": float(m.snapshot.ma5) if m.snapshot.ma5 else None,
                "ma20": float(m.snapshot.ma20) if m.snapshot.ma20 else None,
                "rsi14": float(m.snapshot.rsi14) if m.snapshot.rsi14 else None,
                "macd": float(m.snapshot.macd) if m.snapshot.macd else None,
                "macd_signal": float(m.snapshot.macd_signal) if m.snapshot.macd_signal else None,
                "prev_high": float(m.snapshot.prev_high) if m.snapshot.prev_high else None,
                "per": float(m.snapshot.per) if m.snapshot.per else None,
                "pbr": float(m.snapshot.pbr) if m.snapshot.pbr else None,
                "volume_rank": m.snapshot.volume_rank,
            },
        }
