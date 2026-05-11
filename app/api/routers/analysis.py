"""
analysis.py — 종목 분석 라우터 (ChatGPT 연동)

엔드포인트:
  GET  /analysis/template          활성 템플릿 조회
  PUT  /analysis/template          템플릿 수정 (admin)
  POST /analysis/template/reset    기본 템플릿으로 초기화 (admin)
  POST /analysis/run               종목 분석 실행
"""
from __future__ import annotations

import json
from typing import Annotated, Any

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


# ── 기본 템플릿 ─────────────────────────────────────────────────────────────────

DEFAULT_SYSTEM_PROMPT = (
    "당신은 주식 투자 전문 애널리스트입니다. "
    "제공된 데이터를 바탕으로 객관적이고 전문적인 분석을 제공해주세요."
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
    """활성 템플릿 조회, 없으면 기본 생성."""
    row = (
        await db.execute(
            select(AnalysisTemplateORM)
            .where(AnalysisTemplateORM.is_active == True)
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

    # 지표 데이터 조회
    from sqlalchemy import text as sql_text
    ind_row = (
        await db.execute(
            sql_text(
                """
                SELECT s.name, s.sector, i.*
                FROM indicator_snapshots i
                JOIN stocks s ON s.ticker = i.ticker
                WHERE i.ticker = :ticker
                ORDER BY i.trade_date DESC
                LIMIT 1
                """
            ),
            {"ticker": ticker},
        )
    ).mappings().first()

    stock_info = ""
    if ind_row:
        row = dict(ind_row)
        avg_price = body.avg_price
        close = row.get("close") or row.get("close_price")
        profit_str = ""
        if avg_price and close:
            profit_pct = (float(close) - float(avg_price)) / float(avg_price) * 100
            profit_str = f"\n- 평단가: {avg_price:,.0f}원\n- 현재가: {float(close):,.0f}원\n- 수익률: {profit_pct:+.2f}%"

        stock_info = f"""
종목명: {row.get('name', ticker)}
종목코드: {ticker}
업종: {row.get('sector') or '알 수 없음'}
기준일: {row.get('trade_date', '')}
---
현재가: {_fmt(row.get('close') or row.get('close_price'))}원
전일대비: {_fmt(row.get('chg_pct'), pct=True)}%
거래량: {_fmt(row.get('volume'), 0)}주
시가총액: {row.get('market_cap') or '-'}
---
기술 지표:
- RSI(14): {_fmt(row.get('rsi14'), 1)}
- MACD: {_fmt(row.get('macd'), 4)} / Signal: {_fmt(row.get('macd_signal'), 4)} / Hist: {_fmt(row.get('macd_hist'), 4)}
- MA5: {_fmt(row.get('ma5'))} / MA20: {_fmt(row.get('ma20'))} / MA60: {_fmt(row.get('ma60'))} / MA120: {_fmt(row.get('ma120'))}
- BB상단: {_fmt(row.get('bb_upper'))} / BB중간: {_fmt(row.get('bb_mid'))} / BB하단: {_fmt(row.get('bb_lower'))}
- OBV: {_fmt(row.get('obv'), 0)}
- ATR(14): {_fmt(row.get('atr14'))}
- PER: {_fmt(row.get('per'), 1)} / PBR: {_fmt(row.get('pbr'), 2)}{profit_str}
""".strip()
    else:
        # 종목 기본 정보만 사용
        stock_info = f"종목코드: {ticker}"
        if body.avg_price:
            stock_info += f"\n평단가: {body.avg_price:,.0f}원"

    # 템플릿 로드
    tmpl = await _get_or_create_template(db)

    # 섹션별로 ChatGPT 호출
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.openai_api_key)
    except ImportError:
        raise HTTPException(status_code=503, detail="openai 패키지가 설치되지 않았습니다.")

    results = []
    for section in tmpl.sections:
        user_message = f"""아래 종목 데이터를 참고하여 분석해주세요.

[종목 데이터]
{stock_info}

[분석 요청]
{section['prompt']}

분석 결과를 500자 내외로 간결하게 작성해주세요."""

        try:
            response = await client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": tmpl.system_prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=1000,
                temperature=0.7,
            )
            content = response.choices[0].message.content or ""
        except Exception as e:
            content = f"분석 중 오류 발생: {str(e)}"

        results.append({
            "key": section["key"],
            "title": section["title"],
            "content": content,
        })

    return {
        "ticker": ticker,
        "stock_info": stock_info,
        "avg_price": body.avg_price,
        "sections": results,
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
