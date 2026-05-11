"""
public.py — 로그인 없이 접근 가능한 공개 엔드포인트

엔드포인트:
  GET  /public/stocks/search   종목명·코드 검색 (인증 불필요)
  POST /public/analysis/run    종목 분석 실행 (인증 불필요)
"""
from __future__ import annotations

import asyncio

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.analysis import AnalysisTemplateORM
from app.db.models.stock import StockORM
from app.db.session import get_db

router = APIRouter(prefix="/public", tags=["Public"])

NAVER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
    "Referer": "https://m.stock.naver.com/",
}


# ── 종목 검색 ──────────────────────────────────────────────────────────────────

@router.get("/stocks/search")
async def public_search_stocks(
    q: str = Query(..., description="종목명 또는 종목코드"),
    db: AsyncSession = Depends(get_db),
):
    q = q.strip()
    result = await db.execute(
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


# ── 분석 실행 ──────────────────────────────────────────────────────────────────

class PublicAnalysisRequest(BaseModel):
    ticker: str
    avg_price: float | None = None


@router.post("/analysis/run")
async def public_run_analysis(
    body: PublicAnalysisRequest,
    db: AsyncSession = Depends(get_db),
):
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="분석 서비스를 준비 중입니다.")

    ticker = body.ticker.strip().upper()

    # ── 지표 데이터 ────────────────────────────────────────────────────────────
    from sqlalchemy import text as sql_text
    ind_row = (
        await db.execute(
            sql_text("""
                SELECT s.name, s.sector, i.*
                FROM indicator_snapshots i
                JOIN stocks s ON s.ticker = i.ticker
                WHERE i.ticker = :ticker
                ORDER BY i.trade_date DESC
                LIMIT 1
            """),
            {"ticker": ticker},
        )
    ).mappings().first()

    stock_name = ticker
    stock_info = ""
    close_price: float | None = None

    if ind_row:
        row = dict(ind_row)
        stock_name  = row.get("name", ticker)
        close_price = float(row.get("close") or row.get("close_price") or 0) or None

        avg_price   = body.avg_price
        profit_str  = ""
        if avg_price and close_price:
            profit_pct = (close_price - avg_price) / avg_price * 100
            profit_str = f"\n- 평단가: {avg_price:,.0f}원  현재가: {close_price:,.0f}원  수익률: {profit_pct:+.2f}%"

        stock_info = f"""종목명: {stock_name}  종목코드: {ticker}
업종: {row.get('sector') or '알 수 없음'}  기준일: {row.get('trade_date', '')}

■ 가격
  현재가: {_fmt(close_price)}원  전일대비: {_fmt(row.get('chg_pct'), pct=True)}%
  거래량: {_fmt(row.get('volume'), 0)}주{profit_str}

■ 기술 지표
  RSI(14): {_fmt(row.get('rsi14'), 1)}
  MACD: {_fmt(row.get('macd'), 4)}  Signal: {_fmt(row.get('macd_signal'), 4)}  Hist: {_fmt(row.get('macd_hist'), 4)}
  MA5: {_fmt(row.get('ma5'))}  MA20: {_fmt(row.get('ma20'))}  MA60: {_fmt(row.get('ma60'))}  MA120: {_fmt(row.get('ma120'))}
  BB상단: {_fmt(row.get('bb_upper'))}  BB중간: {_fmt(row.get('bb_mid'))}  BB하단: {_fmt(row.get('bb_lower'))}
  OBV: {_fmt(row.get('obv'), 0)}  ATR(14): {_fmt(row.get('atr14'))}
  PER: {_fmt(row.get('per'), 1)}  PBR: {_fmt(row.get('pbr'), 2)}"""
    else:
        stock_info = f"종목코드: {ticker}"
        if body.avg_price:
            stock_info += f"\n평단가: {body.avg_price:,.0f}원"

    # ── 리서치 수집 ────────────────────────────────────────────────────────────
    research_items = await _fetch_recent_research(ticker)
    research_text  = _format_research(research_items)

    # ── 템플릿 ────────────────────────────────────────────────────────────────
    tmpl_row = (
        await db.execute(
            select(AnalysisTemplateORM)
            .where(AnalysisTemplateORM.is_active == True)  # noqa: E712
            .order_by(AnalysisTemplateORM.id)
            .limit(1)
        )
    ).scalar_one_or_none()

    system_prompt = (
        tmpl_row.system_prompt if tmpl_row
        else "당신은 주식 투자 전문 애널리스트입니다. 제공된 데이터를 바탕으로 객관적이고 전문적인 분석을 제공해주세요."
    )
    sections = tmpl_row.sections if tmpl_row else []

    # ── OpenAI ────────────────────────────────────────────────────────────────
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.openai_api_key)
    except ImportError:
        raise HTTPException(status_code=503, detail="분석 서비스를 준비 중입니다.")

    def _base_ctx() -> str:
        ctx = f"[종목 데이터]\n{stock_info}"
        if research_text:
            ctx += f"\n\n[최근 리서치 ({len(research_items)}건)]\n{research_text}"
        return ctx

    async def _ask(prompt_text: str, max_tokens: int = 1200) -> str:
        try:
            resp = await client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": f"{_base_ctx()}\n\n{prompt_text}"},
                ],
                max_tokens=max_tokens,
                temperature=0.7,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            return f"분석 중 오류 발생: {e}"

    # 요약 프롬프트
    avg_price = body.avg_price
    if avg_price and close_price:
        pct = (close_price - avg_price) / avg_price * 100
        pos = f"현재 {pct:+.2f}% ({'수익' if pct >= 0 else '손실'}) 상태. 평단가 {avg_price:,.0f}원 / 현재가 {close_price:,.0f}원."
    elif avg_price:
        pos = f"평단가 {avg_price:,.0f}원으로 보유 중."
    else:
        pos = "평단가 미입력."

    summary_prompt = f"""{pos}

다음 항목을 **구체적인 주가 수치**를 포함하여 작성해주세요:

1. **매수 추천 구간** (단기/중기 지지선 기반, 구체적 주가 범위)
2. **매도 / 익절 구간** (저항선 기반, 구체적 주가 범위)
3. **손절 기준**
4. **향후 1~3개월 주가 흐름 전망** (상승/횡보/하락 시나리오)
5. **핵심 리스크 요인** (1~2가지)

최근 리서치와 기술적 지표를 종합하여 근거 있는 분석을 제공해주세요."""

    section_asks = [
        (s, f"[분석 요청]\n{s['prompt']}\n\n분석 결과를 600자 내외로 작성해주세요.")
        for s in sections
    ]

    tasks = [_ask(summary_prompt, 1500)] + [_ask(p, 1000) for _, p in section_asks]
    responses = await asyncio.gather(*tasks)

    return {
        "ticker":         ticker,
        "stock_name":     stock_name,
        "stock_info":     stock_info,
        "avg_price":      body.avg_price,
        "research_count": len(research_items),
        "summary":        responses[0],
        "sections": [
            {"key": s["key"], "title": s["title"], "content": responses[i + 1]}
            for i, (s, _) in enumerate(section_asks)
        ],
    }


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

async def _fetch_recent_research(ticker: str, limit: int = 5) -> list[dict]:
    from datetime import date, timedelta
    today = date.today()
    sd    = (today - timedelta(days=90)).strftime("%Y%m%d")
    ed    = today.strftime("%Y%m%d")
    url   = (
        f"https://m.stock.naver.com/api/research/company"
        f"?itemCode={ticker}&page=1&pageSize={limit}&startDate={sd}&endDate={ed}"
    )
    try:
        async with httpx.AsyncClient(headers=NAVER_HEADERS, timeout=8.0) as client:
            r     = await client.get(url)
            items = r.json() if r.status_code == 200 else []
            if not isinstance(items, list):
                return []

            async def _detail(item: dict) -> None:
                rid = item.get("researchId")
                if not rid:
                    return
                try:
                    dr = await client.get(
                        f"https://m.stock.naver.com/api/research/company/{rid}", timeout=5.0
                    )
                    if dr.status_code == 200:
                        c = dr.json().get("researchContent", {})
                        item["opinion"]   = c.get("opinion")
                        item["goalPrice"] = c.get("goalPrice")
                        item["summary"]   = c.get("summary", "")
                except Exception:
                    pass

            await asyncio.gather(*[_detail(it) for it in items])
            return items[:limit]
    except Exception:
        return []


def _format_research(items: list[dict]) -> str:
    if not items:
        return ""
    lines = []
    for it in items:
        date_str = it.get("date", "")[:10]
        provider = it.get("stockFirmName") or it.get("providerName") or ""
        title    = it.get("title", "")
        opinion  = it.get("opinion") or ""
        goal     = it.get("goalPrice") or ""
        summary  = (it.get("summary") or "")[:200]
        goal_str = f"  목표주가: {goal}원  투자의견: {opinion}" if goal else ""
        lines.append(
            f"[{date_str}] {provider} — {title}{goal_str}"
            + (f"\n  요약: {summary}" if summary else "")
        )
    return "\n".join(lines)


def _fmt(val, digits: int = 2, pct: bool = False) -> str:
    if val is None:
        return "-"
    try:
        n = float(val)
        return f"{n:+.{digits}f}" if pct else f"{n:,.{digits}f}"
    except Exception:
        return str(val)
