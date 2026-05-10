"""
FdrMarketDataProvider — FinanceDataReader 기반 MarketDataProvider 구현체.

pykrx의 벌크 엔드포인트가 KRX 서버 변경으로 깨진 상태이므로
FinanceDataReader(fdr)로 교체.

- get_stock_list     : fdr.StockListing('KOSPI' | 'KOSDAQ')
- get_ohlcv_by_ticker: fdr.DataReader(ticker, start, end)
- get_ohlcv_by_date  : 종목 리스트 + 개별 pykrx OHLCV (fdr은 단일일자 전종목 지원 없음)
"""
from __future__ import annotations

import asyncio
import warnings
from datetime import date, timedelta
from functools import partial

import pandas as pd

warnings.filterwarnings("ignore")

from app.core.config import settings
from app.core.exceptions import DataProviderError
from app.core.logging import get_logger
from app.provider.base import MarketDataProvider

logger = get_logger(__name__)

_PYKRX_DATE_FMT = "%Y%m%d"


def _fmt(d: date) -> str:
    return d.strftime(_PYKRX_DATE_FMT)


class FdrMarketDataProvider(MarketDataProvider):

    def __init__(self, request_delay_ms: int | None = None) -> None:
        self._delay = (request_delay_ms or settings.pykrx_request_delay_ms) / 1000.0

    async def _run_sync(self, func, *args, **kwargs):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(func, *args, **kwargs))

    async def _throttle(self) -> None:
        if self._delay > 0:
            await asyncio.sleep(self._delay)

    # ── 종목 리스트 ────────────────────────────────────────────────────────────

    async def get_stock_list(self, market: str) -> pd.DataFrame:
        """fdr.StockListing 으로 종목 리스트 조회."""
        import FinanceDataReader as fdr

        try:
            df = await self._run_sync(fdr.StockListing, market)
            await self._throttle()

            if df is None or df.empty:
                logger.warning("get_stock_list.empty", market=market)
                return pd.DataFrame()

            # Code → ticker, Name → name, Sector/Industry → sector
            df = df.rename(columns={"Code": "ticker", "Name": "name"})
            # fdr 버전마다 컬럼명이 다를 수 있음: Sector 우선, 없으면 Industry 사용
            if "Sector" in df.columns:
                df = df.rename(columns={"Sector": "sector"})
            elif "Industry" in df.columns:
                df = df.rename(columns={"Industry": "sector"})
            else:
                df["sector"] = None

            df["market"] = market
            cols = ["ticker", "name", "market", "sector"]
            df = df[[c for c in cols if c in df.columns]].copy()
            if "sector" not in df.columns:
                df["sector"] = None

            df = df.dropna(subset=["ticker", "name"])
            df["ticker"] = df["ticker"].astype(str).str.zfill(6)
            # 빈 문자열 · pandas NaN → None (to_dict 전에 정리)
            df["sector"] = df["sector"].where(df["sector"].notna(), None)
            df["sector"] = df["sector"].replace("", None)

            logger.info("get_stock_list.done", market=market, count=len(df))
            return df

        except Exception as exc:
            logger.error("get_stock_list.failed", market=market, error=str(exc))
            raise DataProviderError(f"Failed to fetch stock list for {market}: {exc}") from exc

    # ── 단일 종목 OHLCV ────────────────────────────────────────────────────────

    async def get_ohlcv_by_ticker(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """fdr.DataReader 로 단일 종목 기간 OHLCV 조회."""
        import FinanceDataReader as fdr

        try:
            df = await self._run_sync(
                fdr.DataReader,
                ticker,
                start_date.strftime("%Y-%m-%d"),
                end_date.strftime("%Y-%m-%d"),
            )
            await self._throttle()

            if df is None or df.empty:
                return pd.DataFrame()

            df = self._normalize_fdr_ohlcv(df)
            df.index = pd.to_datetime(df.index).date
            df.index.name = "trade_date"
            df["ticker"] = ticker
            return df[["ticker", "open", "high", "low", "close", "volume", "amount"]]

        except Exception as exc:
            logger.error("get_ohlcv_by_ticker.failed", ticker=ticker, error=str(exc))
            raise DataProviderError(f"Failed to fetch OHLCV for {ticker}: {exc}") from exc

    # ── 특정 날짜 전종목 OHLCV ─────────────────────────────────────────────────

    async def get_ohlcv_by_date(self, trade_date: date) -> pd.DataFrame:
        """
        특정 날짜의 전종목 OHLCV 수집.
        fdr은 단일 날짜 전종목 조회를 지원하지 않으므로
        종목 리스트 → 개별 pykrx OHLCV 방식으로 수집.
        pykrx의 개별 종목 조회(get_market_ohlcv)는 정상 작동 확인됨.
        """
        from pykrx import stock as krx

        date_str = _fmt(trade_date)
        results = []
        failed = 0

        # KOSPI + KOSDAQ 종목 리스트를 fdr에서 가져옴
        all_tickers: list[str] = []
        for market in ("KOSPI", "KOSDAQ"):
            try:
                stock_df = await self.get_stock_list(market)
                if not stock_df.empty:
                    all_tickers.extend(stock_df["ticker"].tolist())
            except Exception as exc:
                logger.error("get_ohlcv_by_date.list_failed", market=market, error=str(exc))

        if not all_tickers:
            logger.warning("get_ohlcv_by_date.no_tickers", date=date_str)
            return pd.DataFrame()

        logger.info("get_ohlcv_by_date.start", date=date_str, total=len(all_tickers))

        for i, ticker in enumerate(all_tickers):
            try:
                df = await self._run_sync(
                    krx.get_market_ohlcv,
                    date_str,
                    date_str,
                    ticker,
                )
                await self._throttle()

                if df is None or df.empty:
                    continue

                df = df.rename(columns={
                    "시가": "open", "고가": "high", "저가": "low",
                    "종가": "close", "거래량": "volume", "거래대금": "amount",
                })

                # 거래대금 컬럼 없을 수 있음
                if "amount" not in df.columns:
                    df["amount"] = 0

                row = df.iloc[-1]
                results.append({
                    "ticker": ticker,
                    "trade_date": trade_date,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": int(row["volume"]),
                    "amount": int(row.get("amount", 0)),
                })

                if (i + 1) % 100 == 0:
                    logger.info(
                        "get_ohlcv_by_date.progress",
                        done=i + 1,
                        total=len(all_tickers),
                        saved=len(results),
                    )

            except Exception as exc:
                failed += 1
                logger.debug("get_ohlcv_by_date.ticker_skip", ticker=ticker, error=str(exc))

        logger.info(
            "get_ohlcv_by_date.done",
            date=date_str,
            saved=len(results),
            failed=failed,
        )
        return pd.DataFrame(results) if results else pd.DataFrame()

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_fdr_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
        """fdr 컬럼명 정규화 (Open/High/Low/Close/Volume → 소문자)."""
        return df.rename(columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
            "Amount": "amount",
            "Change": "change",
        }).assign(amount=lambda x: x.get("amount", 0))
