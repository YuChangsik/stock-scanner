"""
CollectService — orchestrates data collection from a MarketDataProvider.

Retry strategy: tenacity wraps each per-ticker call so a single failing
ticker doesn't abort the entire batch. The service logs failures and
continues, returning a summary of success/failure counts.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type

from app.core.config import settings
from app.core.exceptions import DataProviderError
from app.core.logging import get_logger
from app.provider.base import MarketDataProvider
from app.repository.stock_repository import StockRepository
from app.repository.price_repository import PriceRepository

logger = get_logger(__name__)

_NAVER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
    ),
    "Accept": "application/json",
    "Referer": "https://m.stock.naver.com/",
}

# 네이버 금융 업종코드(WICS/upjong) → 한글 업종명 매핑
# 출처: https://finance.naver.com/sise/sise_group.naver?type=upjong
_WICS_CODE_MAP: dict[str, str] = {
    "25":  "기타",
    "261": "제약",
    "262": "생명과학도구및서비스",
    "263": "게임엔터테인먼트",
    "264": "백화점과일반상점",
    "265": "판매업체",
    "266": "화장품",
    "267": "IT서비스",
    "268": "식품",
    "269": "디스플레이장비및부품",
    "270": "자동차부품",
    "271": "레저용장비와제품",
    "272": "화학",
    "273": "자동차",
    "274": "섬유,의류,신발,호화품",
    "275": "담배",
    "276": "복합기업",
    "277": "창업투자",
    "278": "반도체와반도체장비",
    "279": "건설",
    "280": "부동산",
    "281": "건강관리장비와용품",
    "282": "전자장비와기기",
    "283": "전기제품",
    "284": "우주항공과국방",
    "285": "방송과엔터테인먼트",
    "286": "생물공학",
    "287": "소프트웨어",
    "288": "건강관리기술",
    "289": "건축자재",
    "290": "교육서비스",
    "291": "조선",
    "292": "핸드셋",
    "293": "컴퓨터와주변기기",
    "294": "통신장비",
    "295": "에너지장비및서비스",
    "296": "운송인프라",
    "297": "가정용품",
    "298": "가정용기기와용품",
    "299": "기계",
    "300": "양방향미디어와서비스",
    "301": "은행",
    "302": "식품과기본식료품소매",
    "303": "가구",
    "304": "철강",
    "305": "항공사",
    "306": "전기장비",
    "307": "전자제품",
    "308": "인터넷과카탈로그소매",
    "309": "음료",
    "310": "광고",
    "311": "포장재",
    "312": "가스유틸리티",
    "313": "석유와가스",
    "314": "출판",
    "315": "손해보험",
    "316": "건강관리업체및서비스",
    "317": "호텔,레스토랑,레저",
    "318": "종이와목재",
    "319": "기타금융",
    "320": "건축제품",
    "321": "증권",
    "322": "비철금속",
    "323": "해운사",
    "324": "상업서비스와공급품",
    "325": "전기유틸리티",
    "326": "항공화물운송과물류",
    "327": "디스플레이패널",
    "328": "전문소매",
    "329": "도로와철도운송",
    "330": "생명보험",
    "331": "복합유틸리티",
    "332": "문구류",
    "333": "무선통신서비스",
    "334": "무역회사와판매업체",
    "336": "다각화된통신서비스",
    "337": "카드",
    "338": "사무용전자제품",
    "339": "다각화된소비자서비스",
}


async def _fetch_naver_sectors(tickers: list[str]) -> dict[str, str | None]:
    """
    네이버 증권 integration API의 industryCode(WICS 코드)를 가져온 뒤
    _WICS_CODE_MAP으로 업종명을 변환.
    최대 30 동시 요청. 실패한 종목은 None으로 처리.
    """
    import httpx

    result: dict[str, str | None] = {}
    sem = asyncio.Semaphore(30)

    async def _fetch_one(client: httpx.AsyncClient, ticker: str) -> None:
        async with sem:
            try:
                r = await client.get(
                    f"https://m.stock.naver.com/api/stock/{ticker}/integration",
                    timeout=5.0,
                )
                if r.status_code != 200:
                    result[ticker] = None
                    return
                obj = r.json()
                code = str(obj.get("industryCode") or "")
                result[ticker] = _WICS_CODE_MAP.get(code)
            except Exception:
                pass

    async with httpx.AsyncClient(headers=_NAVER_HEADERS) as client:
        await asyncio.gather(*[_fetch_one(client, t) for t in tickers])

    found = sum(1 for v in result.values() if v)
    logger.info("fetch_naver_sectors.done", total=len(tickers), found=found)
    return result


class CollectService:
    def __init__(
        self,
        provider: MarketDataProvider,
        stock_repo: StockRepository,
        price_repo: PriceRepository,
    ) -> None:
        self._provider = provider
        self._stock_repo = stock_repo
        self._price_repo = price_repo

    async def refresh_stock_list(self) -> dict:
        """Update stocks table from provider. Returns summary dict."""
        import math

        def _clean(row: dict) -> dict:
            """pandas NaN → None (asyncpg는 float NaN을 VARCHAR에 못 씀)."""
            return {
                k: (None if isinstance(v, float) and math.isnan(v) else v)
                for k, v in row.items()
            }

        rows = []
        for market in ("KOSPI", "KOSDAQ"):
            df = await self._provider.get_stock_list(market)
            if df.empty:
                logger.warning("refresh_stock_list.empty", market=market)
                continue
            rows.extend(_clean(r) for r in df.to_dict("records"))

        if not rows:
            logger.error("refresh_stock_list.no_data")
            return {"upserted": 0, "deactivated": 0}

        tickers = [r["ticker"] for r in rows]

        # fdr은 업종 데이터 미제공 → DB의 기존 업종 데이터 유지
        # 업종 업데이트는 지표 배치(Step 3)에서 integration API와 함께 처리
        # DB에 업종이 전혀 없을 때만 초기 로딩 수행
        existing_sectors = await self._stock_repo.get_sector_map()
        if not any(existing_sectors.values()):
            logger.info("refresh_stock_list.fetching_sectors_initial", count=len(tickers))
            sectors = await _fetch_naver_sectors(tickers)
            for r in rows:
                if not r.get("sector"):
                    r["sector"] = sectors.get(r["ticker"])
            logger.info(
                "refresh_stock_list.sectors_initial_done",
                found=sum(1 for r in rows if r.get("sector")),
                total=len(rows),
            )
        else:
            # 기존 업종 데이터 보존 (덮어쓰기 방지)
            for r in rows:
                if not r.get("sector"):
                    r["sector"] = existing_sectors.get(r["ticker"])

        upserted = await self._stock_repo.upsert_many(rows)
        await self._stock_repo.deactivate_missing(tickers)

        logger.info("refresh_stock_list.done", upserted=upserted, total=len(tickers))
        return {"upserted": upserted, "active": len(tickers)}

    async def collect_daily_prices(self, trade_date: date) -> dict:
        """
        Collect OHLCV for all active tickers on trade_date.
        Uses bulk date-based endpoint first; per-ticker fallback is a future option.
        """
        df = await self._provider.get_ohlcv_by_date(trade_date)

        if df.empty:
            logger.warning("collect_daily_prices.empty", trade_date=str(trade_date))
            return {"saved": 0, "failed": 0}

        active_tickers = set(await self._stock_repo.get_active_tickers())
        df = df[df["ticker"].isin(active_tickers)]

        rows = []
        for _, row in df.iterrows():
            rows.append({
                "ticker": row["ticker"],
                "trade_date": trade_date,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
                "amount": int(row.get("amount", 0)),
            })

        saved = await self._price_repo.upsert_many(rows)
        logger.info("collect_daily_prices.done", trade_date=str(trade_date), saved=saved)
        return {"saved": saved, "failed": 0}

    async def collect_historical(self, ticker: str, start_date: date, end_date: date) -> dict:
        """Collect history for a single ticker. Used for backfill."""
        @retry(
            stop=stop_after_attempt(settings.collect_retry_attempts),
            wait=wait_fixed(settings.collect_retry_wait_seconds),
            retry=retry_if_exception_type(DataProviderError),
            reraise=True,
        )
        async def _fetch():
            return await self._provider.get_ohlcv_by_ticker(ticker, start_date, end_date)

        try:
            df = await _fetch()
        except DataProviderError as exc:
            logger.error("collect_historical.failed", ticker=ticker, error=str(exc))
            return {"ticker": ticker, "saved": 0, "error": str(exc)}

        if df.empty:
            return {"ticker": ticker, "saved": 0}

        rows = []
        for idx_date, row in df.iterrows():
            rows.append({
                "ticker": ticker,
                "trade_date": idx_date,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
                "amount": int(row.get("amount", 0)),
            })

        saved = await self._price_repo.upsert_many(rows)
        return {"ticker": ticker, "saved": saved}
