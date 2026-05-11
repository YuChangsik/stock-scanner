from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class AnalysisTemplateORM(Base):
    """ChatGPT 종목 분석 템플릿."""
    __tablename__ = "analysis_templates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="기본 템플릿")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # 시스템 프롬프트 (ChatGPT role 설정)
    system_prompt: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="당신은 주식 투자 전문 애널리스트입니다. 제공된 데이터를 바탕으로 객관적이고 전문적인 분석을 제공해주세요.",
    )

    # 분석 섹션 목록
    # [{"key": "core_business", "title": "핵심사업", "prompt": "..."}]
    sections: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: [
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
        ],
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RolePermissionORM(Base):
    """역할별 페이지 접근 권한."""
    __tablename__ = "role_permissions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    role: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  # admin | user

    # 허용된 페이지 키 목록
    # ["home","settings","sector","research","notify","admin","analysis","permissions"]
    allowed_pages: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: ["home", "settings", "sector", "research", "analysis"],
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
