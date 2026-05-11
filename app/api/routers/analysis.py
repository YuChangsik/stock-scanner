"""
analysis.py — 종목 분석 라우터 (ChatGPT 연동)

엔드포인트:
  GET  /analysis/template          활성 템플릿 조회
  PUT  /analysis/template          템플릿 수정 (admin)
  POST /analysis/template/reset    기본 템플릿으로 초기화 (admin)
  POST /analysis/run               종목 분석 실행
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers.auth import get_current_user
from app.api.routers.permissions import _require_admin
from app.core.config import settings
from app.db.models.analysis import AnalysisTemplateORM
from app.db.session import get_db

router = APIRouter(prefix="/analysis", tags=["Analysis"])

NAVER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
    "Referer": "https://m.stock.naver.com/",
}

# ── 기본 템플릿 ─────────────────────────────────────────────────────────────────

DEFAULT_SYSTEM_PROMPT = (
    "당신은 주식 투자 전문 애널리스트입니다. "
    "제공된 데이터와 리서치를 바탕으로 객관적이고 전문적인 분석을 제공해주세요. "
    "숫자와 근거를 기반으로 구체적인 수치를 포함하여 분석해주세요."
)

DEFAULT_SECTIONS = [
    {
        "key": "core_business",
        "title": "핵심사업",
        "prompt": "이 기업의 핵심 사업 모델, 주요 제품/서비스, 경쟁 우위, 시장 내 위치를 분석해주세요.",
    },
    {
        "key": "technical",
        "title": "기술적분석",
        "prompt": "제공된 기술 지표(RSI, MACD, 이동평균선 등)를 바탕으로 현재 차트 흐름과 지지/저항선, 매매 시점을 분석해주세요.",
    },
    {
        "key": "price_rise",
        "title": "최근 주가상승배경",
        "prompt": "최근 주가 상승의 주요 원인과 배경(실적, 업종 트렌드, 수급, 이슈 등)을 분석해주세요.",
    },
    {
        "key": "investor_view",
        "title": "투자자관점",
        "prompt": "현재 평단가 대비 수익/손실 상황을 고려한 투자자 관점에서의 대응 전략과 향후 전망을 제시해주세요.",
    },
]


async def _get_or_create_template(db: AsyncSession) -> AnalysisTemplateORM:
    row = (
        await db.execute(
            select(AnalysisTemplateORM)
            .where(AnalysisTemplateORM.is_active == True)  # noqa: E712
            .order_by(AnalysisTemplateORM.id)
            .limit(1)
        )
    ).scalar_one_or_none()

    if row is None:
        row = AnalysisTemplateORM(
            name="기본 템플릿",
            is_active=True,
            system_prompt=DEFAULT_SYSTEM_PROMPT,
            sections=DEFAULT_SECTIONS,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


# ── 리서치 수집 ────────────────────────────────────────────────────────────────

async def _fetch_recent_research(ticker: str, limit: int = 5) -> list[dict]:
    """네이버 금융 리서치 최신 N건 수집."""
    from datetime import date, timedelta
    today = date.today()
    sd = (today - timedelta(days=90)).strftime("%Y%m%d")
    ed = today.strftime("%Y%m%d")

    url = (
        f"https://m.stock.naver.com/api/research/company"
        f"?itemCode={ticker}&page=1&pageSize={limit}&startDate={sd}&endDate={ed}"
    )
    try:
        async with httpx.AsyncClient(headers=NAVER_HEADERS, timeout=8.0) as client:
            r = await client.get(url)
            items = r.json() if r.status_code == 200 else []
            if not isinstance(items, list):
                return []

            # 상세 내용 병렬 수집
            async def _detail(item: dict) -> None:
                rid = item.get("researchId")
                if not rid:
                    return
                try:
                    dr = await client.get(
                        f"https://m.stock.naver.com/api/research/company/{rid}",
                        timeout=5.0,
                    )
                    if dr.status_code == 200:
                        content = dr.json().get("researchContent", {})
                        item["opinion"]        = content.get("opinion")
                        item["goalPrice"]      = content.get("goalPrice")
                        item["summary"]        = content.get("summary", "")
                except Exception:
                    pass

            await asyncio.gather(*[_detail(it) for it in items])
            return items[:limit]
    except Exception:
        return []


# ── Schemas ───────────────────────────────────────────────────────────────────

class SectionModel(BaseModel):
    key: str
    title: str
    prompt: str


class TemplateUpdateRequest(BaseModel):
    name: str | None = None
    system_prompt: str | None = None
    sections: list[SectionModel] | None = None


class AnalysisRunRequest(BaseModel):
    ticker: str
    avg_price: float | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/template")
async def get_template(
    _=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tmpl = await _get_or_create_template(db)
    return {
        "id": tmpl.id,
        "name": tmpl.name,
        "system_prompt": tmpl.system_prompt,
        "sections": tmpl.sections,
        "updated_at": str(tmpl.updated_at),
    }


@router.put("/template")
async def update_template(
    body: TemplateUpdateRequest,
    _=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    tmpl = await _get_or_create_template(db)
    if body.name is not None:
        tmpl.name = body.name
    if body.system_prompt is not None:
        tmpl.system_prompt = body.system_prompt
    if body.sections is not None:
        tmpl.sections = [s.model_dump() for s in body.sections]
    await db.commit()
    await db.refresh(tmpl)
    return {
        "id": tmpl.id,
        "name": tmpl.name,
        "system_prompt": tmpl.system_prompt,
        "sections": tmpl.sections,
        "updated_at": str(tmpl.updated_at),
    }


@router.post("/template/reset")
async def reset_template(
    _=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    tmpl = await _get_or_create_template(db)
    tmpl.name = "기본 템플릿"
    tmpl.system_prompt = DEFAULT_SYSTEM_PROMPT
    tmpl.sections = DEFAULT_SECTIONS
    await db.commit()
    return {"message": "템플릿이 초기화되었습니다."}


@router.post("/run")
async def run_analysis(
    body: AnalysisRunRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OpenAI API 키가 설정되지 않았습니다.")

    ticker = body.ticker.strip().upper()

    # ── 지표 데이터 조회 ───────────────────────────────────────────────────────
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
        stock_name = row.get("name", ticker)
        avg_price = body.avg_price
        close_price = float(row.get("close") or row.get("close_price") or 0) or None

        profit_str = ""
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
    research_items = await _fetch_recent_research(ticker, limit=5)
    research_text = ""
    if research_items:
        lines = []
        for it in research_items:
            date_str  = it.get("date", "")[:10]
            provider  = it.get("stockFirmName") or it.get("providerName") or ""
            title_str = it.get("title", "")
            opinion   = it.get("opinion") or ""
            goal      = it.get("goalPrice") or ""
            summary   = (it.get("summary") or "")[:200]
            goal_str  = f"  목표주가: {goal}원  투자의견: {opinion}" if goal else ""
            lines.append(
                f"[{date_str}] {provider} — {title_str}{goal_str}"
                + (f"\n  요약: {summary}" if summary else "")
            )
        research_text = "\n".join(lines)

    # ── 템플릿 로드 ────────────────────────────────────────────────────────────
    tmpl = await _get_or_create_template(db)

    # ── OpenAI 클라이언트 ──────────────────────────────────────────────────────
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.openai_api_key)
    except ImportError:
        raise HTTPException(status_code=503, detail="openai 패키지가 설치되지 않았습니다.")

    async def _ask(prompt_text: str, max_tokens: int = 1200) -> str:
        try:
            resp = await client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": tmpl.system_prompt},
                    {"role": "user",   "content": f"{_build_base_context()}\n\n{prompt_text}"},
                ],
                max_tokens=max_tokens,
                temperature=0.7,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            return f"분석 중 오류 발생: {e}"

    # ── 1) 고정 요약 섹션: 매수/매도 구간 + 주가 흐름 전망 ────────────────────
    avg_price = body.avg_price
    if avg_price and close_price:
        profit_pct = (close_price - avg_price) / avg_price * 100
        position_str = (
            f"현재 {profit_pct:+.2f}% ({'수익' if profit_pct >= 0 else '손실'}) 상태입니다. "
            f"평단가 {avg_price:,.0f}원 / 현재가 {close_price:,.0f}원."
        )
    elif avg_price:
        position_str = f"평단가 {avg_price:,.0f}원으로 보유 중입니다."
    else:
        position_str = "평단가 미입력."

    # position_str을 base context에 포함 → 모든 섹션 GPT 호출에서 동일하게 활용
    def _build_base_context() -> str:
        ctx = f"[종목 데이터]\n{stock_info}"
        ctx += f"\n\n[포지션]\n{position_str}"
        if research_text:
            ctx += f"\n\n[최근 리서치 ({len(research_items)}건)]\n{research_text}"
        return ctx

    summary_prompt = f"""아래 종목의 종합 분석을 해주세요.

{position_str}

다음 항목을 **반드시 구체적인 수치**를 포함하여 작성하세요:

1. **매수 추천 구간** (단기/중기 지지선 기반, 구체적 주가 범위)
2. **매도 / 익절 구간** (단기/중기 저항선 기반, 구체적 주가 범위)
3. **손절 기준** (리스크 관리)
4. **향후 1~3개월 주가 흐름 전망** (상승/횡보/하락 시나리오)
5. **핵심 리스크 요인** (1~2가지)

최근 리서치 내용과 기술적 지표를 종합하여 근거 있는 분석을 제공해주세요."""

    # ── 2) 템플릿 섹션들 ──────────────────────────────────────────────────────
    section_prompts = []
    for section in tmpl.sections:
        p = f"""위 종목 데이터, 포지션 정보, 리서치를 모두 참고하여 아래 항목을 분석해주세요.

[분석 요청]
{section['prompt']}

분석 결과를 700자 내외로 작성해주세요."""
        section_prompts.append((section, p))

    # 모든 GPT 호출 병렬 실행
    tasks = [_ask(summary_prompt, max_tokens=1500)] + [_ask(p, max_tokens=1200) for _, p in section_prompts]
    responses = await asyncio.gather(*tasks)

    summary_content = responses[0]
    section_results = []
    for i, (section, _) in enumerate(section_prompts):
        section_results.append({
            "key":     section["key"],
            "title":   section["title"],
            "content": responses[i + 1],
        })

    return {
        "ticker":       ticker,
        "stock_name":   stock_name,
        "stock_info":   stock_info,
        "avg_price":    body.avg_price,
        "research_count": len(research_items),
        "summary":      summary_content,
        "sections":     section_results,
    }


def _fmt(val, digits: int = 2, pct: bool = False) -> str:
    if val is None:
        return "-"
    try:
        n = float(val)
        if pct:
            return f"{n:+.{digits}f}"
        return f"{n:,.{digits}f}"
    except Exception:
        return str(val)
