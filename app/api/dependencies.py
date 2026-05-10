"""
Dependency injection — wires together repositories and services
using FastAPI's Depends() system.

Provider singleton is created once at startup and shared across requests.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.provider.base import MarketDataProvider
from app.provider.fdr_provider import FdrMarketDataProvider
from app.repository.indicator_repository import IndicatorRepository
from app.repository.price_repository import PriceRepository
from app.repository.scan_repository import ScanRepository
from app.repository.stock_repository import StockRepository
from app.service.collect_service import CollectService
from app.service.indicator_service import IndicatorService
from app.service.scan_service import ScanService


@lru_cache(maxsize=1)
def get_provider() -> MarketDataProvider:
    return FdrMarketDataProvider()


# ── Repository factories ────────────────────────────────────────────────────

def get_stock_repo(db: Annotated[AsyncSession, Depends(get_db)]) -> StockRepository:
    return StockRepository(db)


def get_price_repo(db: Annotated[AsyncSession, Depends(get_db)]) -> PriceRepository:
    return PriceRepository(db)


def get_indicator_repo(db: Annotated[AsyncSession, Depends(get_db)]) -> IndicatorRepository:
    return IndicatorRepository(db)


def get_scan_repo(db: Annotated[AsyncSession, Depends(get_db)]) -> ScanRepository:
    return ScanRepository(db)


# ── Service factories ────────────────────────────────────────────────────────

def get_collect_service(
    provider: Annotated[MarketDataProvider, Depends(get_provider)],
    stock_repo: Annotated[StockRepository, Depends(get_stock_repo)],
    price_repo: Annotated[PriceRepository, Depends(get_price_repo)],
) -> CollectService:
    return CollectService(provider, stock_repo, price_repo)


def get_indicator_service(
    price_repo: Annotated[PriceRepository, Depends(get_price_repo)],
    indicator_repo: Annotated[IndicatorRepository, Depends(get_indicator_repo)],
    provider: Annotated[MarketDataProvider, Depends(get_provider)],
) -> IndicatorService:
    # provider 주입 → 온디맨드 수집 활성화
    return IndicatorService(price_repo, indicator_repo, provider=provider)


def get_scan_service(
    scan_repo: Annotated[ScanRepository, Depends(get_scan_repo)],
    indicator_repo: Annotated[IndicatorRepository, Depends(get_indicator_repo)],
    price_repo: Annotated[PriceRepository, Depends(get_price_repo)],
    stock_repo: Annotated[StockRepository, Depends(get_stock_repo)],
) -> ScanService:
    return ScanService(scan_repo, indicator_repo, price_repo, stock_repo)
