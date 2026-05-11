import asyncio
import re
from datetime import date
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import get_indicator_repo, get_indicator_service, get_price_repo, get_stock_repo
from app.domain.schemas import IndicatorResponse, StockListResponse, StockResponse
from app.repository.indicator_repository import IndicatorRepository
from app.repository.price_repository import PriceRepository
from app.repository.stock_repository import StockRepository
from app.service.indicator_service import IndicatorService

router = APIRouter(prefix="/stocks", tags=["Stocks"])

NAVER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
    "Referer": "https://m.stock.naver.com/",
}
NAVER_BASE = "https://m.stock.naver.com/api/stock"


def _parse_market_cap_eok(v) -> float | None:
    """Naver 시가총액 문자열 '12조 3,456억' → 억원 단위 float."""
    if not v:
        return None
    s = str(v).replace(",", "").strip()
    total = 0.0
    m = re.search(r"([\d.]+)\s*조", s)
    if m:
        total += float(m.group(1)) * 10000
    m = re.search(r"([\d.]+)\s*억", s)
    if m:
        total += float(m.group(1))
    return total if total > 0 else None


async def _fetch_market_caps(tickers: list[str]) -> dict[str, float]:
    """종목 리스트의 시가총액(억원)을 Naver integration API에서 병렬 수집."""
    result: dict[str, float] = {}
    sem = asyncio.Semaphore(30)

    async def _one(client: httpx.AsyncClient, ticker: str) -> None:
        async with sem:
            try:
                r = await client.get(f"{NAVER_BASE}/{ticker}/integration", timeout=5.0)
                if r.status_code != 200:
                    return
                obj = r.json()
                infos = {
                    item["code"]: item.get("value")
                    for item in obj.get("totalInfos", [])
                    if "code" in item
                }
                mc = infos.get("marketValue") or infos.get("capitalization")
                parsed = _parse_market_cap_eok(mc)
                if parsed:
                    result[ticker] = parsed
            except Exception:
                pass

    async with httpx.AsyncClient(headers=NAVER_HEADERS, timeout=10.0) as client:
        await asyncio.gather(*[_one(client, t) for t in tickers])

    return result


@router.get("/sectors")
async def list_sectors(
    stock_repo: Annotated[StockRepository, Depends(get_stock_repo)] = None,
):
    """활성 종목의 업종 목록 반환 (중복 제거, 가나다 정렬)."""
    sectors = await stock_repo.get_sectors()
    return {"sectors": sectors}


@router.get("/sector-stats")
async def get_sector_stats(
    indicator_repo: Annotated[IndicatorRepository, Depends(get_indicator_repo)] = None,
):
    """최신 거래일 기준 업종별 평균 PER/PBR/RSI 집계."""
    stats = await indicator_repo.get_sector_stats()
    return {"stats": stats, "count": len(stats)}


@router.get("/sector/{sector_name}/stocks")
async def get_sector_stocks(
    sector_name: str,
    indicator_repo: Annotated[IndicatorRepository, Depends(get_indicator_repo)] = None,
):
    """특정 업종의 종목 목록 (시가총액 내림차순 정렬)."""
    stocks = await indicator_repo.get_by_sector(sector_name)
    if not stocks:
        return {"sector": sector_name, "stocks": []}

    tickers = [s["ticker"] for s in stocks]
    market_caps = await _fetch_market_caps(tickers)

    for s in stocks:
        s["market_cap_eok"] = market_caps.get(s["ticker"])  # 억원, 없으면 None

    # 시가총액 내림차순 → 없는 종목은 뒤로
    stocks.sort(key=lambda s: s["market_cap_eok"] or -1, reverse=True)

    return {"sector": sector_name, "stocks": stocks, "count": len(stocks)}


@router.get("/search")
async def search_stocks(
    q: str = Query(..., description="종목명 또는 종목코드 (부분 일치)"),
    stock_repo: Annotated[StockRepository, Depends(get_stock_repo)] = None,
):
    """종목명 또는 종목코드로 검색 (최대 20개)."""
    from sqlalchemy import select
    from app.db.models.stock import StockORM
    from app.db.session import get_db

    q = q.strip()
    # repo session을 직접 사용
    session = stock_repo._session
    result = await session.execute(
        select(StockORM)
        .where(StockORM.is_active == True)  # noqa: E712
        .where(
            (StockORM.name.ilike(f"%{q}%")) | (StockORM.ticker.ilike(f"%{q}%"))
        )
        .order_by(StockORM.name)
        .limit(20)
    )
    stocks = result.scalars().all()
    return {
        "total": len(stocks),
        "items": [{"ticker": s.ticker, "name": s.name, "market": s.market} for s in stocks],
    }


@router.get("", response_model=StockListResponse)
async def list_stocks(
    market: str | None = Query(None, description="Filter by market: KOSPI | KOSDAQ"),
    stock_repo: Annotated[StockRepository, Depends(get_stock_repo)] = None,
):
    """Return active stock list, optionally filtered by market."""
    stocks = await stock_repo.get_all(market=market)
    return StockListResponse(
        total=len(stocks),
        items=[StockResponse.model_validate(s) for s in stocks],
    )


@router.get("/{ticker}/indicators", response_model=IndicatorResponse)
async def get_indicators(
    ticker: str,
    trade_date: date = Query(default=None, description="Target date (YYYY-MM-DD); defaults to latest"),
    indicator_service: Annotated[IndicatorService, Depends(get_indicator_service)] = None,
    stock_repo: Annotated[StockRepository, Depends(get_stock_repo)] = None,
):
    """Return technical indicator snapshot for a ticker on a given date."""
    stock = await stock_repo.get_by_ticker(ticker)
    if stock is None:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker!r} not found")

    if trade_date is None:
        from app.repository.price_repository import PriceRepository
        from app.db.session import AsyncSessionFactory
        async with AsyncSessionFactory() as session:
            price_repo = PriceRepository(session)
            trade_date = await price_repo.get_latest_date()

    if trade_date is None:
        raise HTTPException(status_code=404, detail="No price data available")

    # DB에 없으면 provider에서 자동 수집 후 계산
    data = await indicator_service.get_or_fetch_for_ticker_date(ticker, trade_date)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail=f"No indicator data for {ticker} on {trade_date}",
        )

    # daily_prices에서 거래량, 거래대금, 종가 함께 조회
    from app.repository.price_repository import PriceRepository
    from app.db.session import AsyncSessionFactory
    async with AsyncSessionFactory() as session:
        price_repo = PriceRepository(session)
        prices = await price_repo.get_by_ticker(ticker, trade_date, trade_date)
        price = prices[0] if prices else None

    return IndicatorResponse(
        ticker=data["ticker"],
        trade_date=data["trade_date"],
        close=price.close if price else None,
        volume=price.volume if price else None,
        amount=price.amount if price else None,
        volume_rank=data["volume_rank"],
        ma5=data["ma5"],
        ma20=data["ma20"],
        rsi14=data["rsi14"],
    )


@router.get("/research")
async def get_research(
    date: str | None = Query(None, description="단일 날짜 YYYY-MM-DD (start_date/end_date와 함께 쓰지 않을 때)"),
    start_date: str | None = Query(None, description="조회 시작일 YYYY-MM-DD"),
    end_date: str | None = Query(None, description="조회 종료일 YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
):
    """기간별 리서치 목록 — 네이버 금융 리서치 API 프록시 (목표주가/의견 포함)."""
    from datetime import date as date_type

    today_str = date_type.today().strftime("%Y%m%d")

    def _fmt(d: str | None) -> str:
        return d.replace("-", "") if d else today_str

    if start_date or end_date:
        sd = _fmt(start_date)
        ed = _fmt(end_date or start_date)
    elif date:
        sd = ed = _fmt(date)
    else:
        sd = ed = today_str

    list_url = (
        f"https://m.stock.naver.com/api/research/company"
        f"?page={page}&pageSize={page_size}&startDate={sd}&endDate={ed}"
    )

    async with httpx.AsyncClient(headers=NAVER_HEADERS, timeout=10.0) as client:
        try:
            r = await client.get(list_url)
            items: list = r.json() if r.status_code == 200 else []
        except Exception:
            items = []

        if not isinstance(items, list):
            items = []

        # 각 리서치 상세 조회 (opinion, goalPrice, priceAtWriteDate)
        sem = asyncio.Semaphore(20)

        async def _fetch_detail(item: dict) -> None:
            research_id = item.get("researchId")
            if not research_id:
                return
            async with sem:
                try:
                    dr = await client.get(
                        f"https://m.stock.naver.com/api/research/company/{research_id}",
                        timeout=5.0,
                    )
                    if dr.status_code == 200:
                        content = dr.json().get("researchContent", {})
                        item["opinion"] = content.get("opinion")
                        item["goalPrice"] = content.get("goalPrice")
                        item["priceAtWriteDate"] = content.get("priceAtWriteDate")
                except Exception:
                    pass

        await asyncio.gather(*[_fetch_detail(it) for it in items])

    def _dash(s: str) -> str:
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"

    return {
        "start_date": _dash(sd),
        "end_date": _dash(ed),
        "items": items,
    }


@router.get("/{ticker}/prices")
async def get_prices(
    ticker: str,
    days: int = Query(90, ge=5, le=365, description="조회할 거래일 수"),
    price_repo: Annotated[PriceRepository, Depends(get_price_repo)] = None,
):
    """종목 OHLCV 시계열 — 차트 렌더링용."""
    from datetime import date, timedelta
    end_date   = date.today()
    start_date = end_date - timedelta(days=days * 2)  # 주말/휴일 여유분 포함
    prices = await price_repo.get_by_ticker(ticker, start_date, end_date)
    # 최근 days 거래일만 반환
    prices = prices[-days:]
    return [
        {
            "date":   str(p.trade_date),
            "open":   float(p.open),
            "high":   float(p.high),
            "low":    float(p.low),
            "close":  float(p.close),
            "volume": int(p.volume),
        }
        for p in prices
    ]


@router.get("/{ticker}/detail")
async def get_stock_detail(
    ticker: str,
    stock_repo: Annotated[StockRepository, Depends(get_stock_repo)],
):
    """종목 상세 정보 — 네이버 금융에서 연간실적, 분기실적, 리서치, 투자자 조회."""
    stock = await stock_repo.get_by_ticker(ticker)
    if stock is None:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker!r} not found")

    async with httpx.AsyncClient(headers=NAVER_HEADERS, timeout=10.0) as client:
        async def _get(url: str):
            try:
                r = await client.get(url)
                return r.json() if r.status_code == 200 else None
            except Exception:
                return None

        annual, quarter, research, integration = await asyncio.gather(
            _get(f"{NAVER_BASE}/{ticker}/finance/annual"),
            _get(f"{NAVER_BASE}/{ticker}/finance/quarter"),
            _get(f"https://m.stock.naver.com/api/research/company?itemCode={ticker}&page=1&pageSize=15"),
            _get(f"{NAVER_BASE}/{ticker}/integration"),
        )
        # dealTrendInfos: 최근 5거래일 투자자별 순매수수량
        investor = (integration or {}).get("dealTrendInfos", [])

    return {
        "ticker": ticker,
        "name": stock.name,
        "market": stock.market,
        "annual": annual,
        "quarter": quarter,
        "research": research,
        "investor": investor,
    }


