"""
PykrxMarketDataProvider — wraps pykrx 1.2.x behind the MarketDataProvider interface.

pykrx 1.2.7 API 변경 사항:
- get_market_ohlcv(from, to, ticker) : 단일 종목 OHLCV (market 키워드 제거됨)
- get_market_ticker_list(date, market) : 종목 리스트 (최신 날짜 응답 빈 경우 있음)

대응 전략:
- get_stock_list : 최근일부터 최대 90일 전까지 거슬러 올라가며 데이터 있는 날 탐색
- get_ohlcv_by_date : ticker 리스트 획득 후 종목별 개별 OHLCV 수집 (market 키워드 사용 안 함)
"""
from __future__ import annotations

import asyncio
import warnings
from datetime import date, timedelta
from functools import partial

import pandas as pd

# pykrx 경고 억제
warnings.filterwarnings("ignore", message=".*KRX.*")

from app.core.config import settings
from app.core.exceptions import DataProviderError
from app.core.logging import get_logger
from app.provider.base import MarketDataProvider

logger = get_logger(__name__)

_PYKRX_DATE_FMT = "%Y%m%d"
_MAX_LOOKBACK_DAYS = 90  # 공휴일 연속 최대치 + 최신 날짜 응답 없는 경우 대비


def _fmt(d: date) -> str:
    return d.strftime(_PYKRX_DATE_FMT)


def _skip_weekend(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


class PykrxMarketDataProvider(MarketDataProvider):

    def __init__(self, request_delay_ms: int | None = None) -> None:
        self._delay = (request_delay_ms or settings.pykrx_request_delay_ms) / 1000.0

    async def _run_sync(self, func, *args, **kwargs):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(func, *args, **kwargs))

    async def _throttle(self) -> None:
        if self._delay > 0:
            await asyncio.sleep(self._delay)

    async def _find_latest_trading_date_with_data(self) -> str:
        """
        오늘부터 최대 90일 전까지 거슬러 올라가며
        get_market_ticker_list 가 실제 종목을 반환하는 날짜를 탐색.
        주말 + 공휴일 + 최신 날짜 응답 없는 경우 모두 자동 skip.
        """
        from pykrx import stock as krx

        d = _skip_weekend(date.today())

        for _ in range(_MAX_LOOKBACK_DAYS):
            date_str = _fmt(d)
            try:
                tickers = await self._run_sync(
                    krx.get_market_ticker_list, date_str, market="KOSPI"
                )
                if tickers and len(tickers) > 10:  # 10개 미만이면 오류 응답으로 간주
                    logger.info("provider.trading_date_found", date=date_str)
                    return date_str
            except Exception:
                pass

            logger.debug("provider.skip_date_no_data", date=date_str)
            d = _skip_weekend(d - timedelta(days=1))

        raise DataProviderError("최근 90일 내 유효한 거래일 데이터를 찾을 수 없습니다.")

    async def get_stock_list(self, market: str) -> pd.DataFrame:
        from pykrx import stock as krx

        try:
            trading_date = await self._find_latest_trading_date_with_data()
            logger.info("get_stock_list.using_date", market=market, date=trading_date)

            tickers = await self._run_sync(
                krx.get_market_ticker_list, trading_date, market=market
            )
            await self._throttle()

            if not tickers:
                logger.warning("get_stock_list.empty", market=market, date=trading_date)
                return pd.DataFrame()

            rows = []
            for ticker in tickers:
                try:
                    name = await self._run_sync(krx.get_market_ticker_name, ticker)
                    await self._throttle()
                    rows.append({"ticker": ticker, "name": name, "market": market})
                except Exception as exc:
                    logger.warning("get_stock_list.name_failed", ticker=ticker, error=str(exc))

            logger.info("get_stock_list.done", market=market, count=len(rows))
            return pd.DataFrame(rows)

        except DataProviderError:
            raise
        except Exception as exc:
            logger.error("get_stock_list.failed", market=market, error=str(exc))
            raise DataProviderError(f"Failed to fetch stock list for {market}: {exc}") from exc

    async def get_ohlcv_by_ticker(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        from pykrx import stock as krx

        try:
            df = await self._run_sync(
                krx.get_market_ohlcv,
                _fmt(start_date),
                _fmt(end_date),
                ticker,
            )
            await self._throttle()

            if df is None or df.empty:
                return pd.DataFrame()

            df = self._normalize_ohlcv(df)
            df.index = pd.to_datetime(df.index).date
            df.index.name = "trade_date"
            df["ticker"] = ticker
            return df[["ticker", "open", "high", "low", "close", "volume", "amount"]]

        except Exception as exc:
            logger.error("get_ohlcv_by_ticker.failed", ticker=ticker, error=str(exc))
            raise DataProviderError(f"Failed to fetch OHLCV for {ticker}: {exc}") from exc

    async def get_ohlcv_by_date(self, trade_date: date) -> pd.DataFrame:
        """
        특정 날짜의 전종목 OHLCV 수집.
        pykrx 1.2.7에서 market 키워드가 제거되어, ticker 리스트 → 개별 수집 방식으로 변경.
        """
        from pykrx import stock as krx

        date_str = _fmt(trade_date)
        results = []

        for market in ("KOSPI", "KOSDAQ"):
            try:
                tickers = await self._run_sync(
                    krx.get_market_ticker_list, date_str, market=market
                )
                await self._throttle()

                if not tickers:
                    logger.warning("get_ohlcv_by_date.empty_ticker_list", market=market, date=date_str)
                    continue

                for ticker in tickers:
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

                        df = self._normalize_ohlcv(df)
                        if df.empty:
                            continue

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
                    except Exception as exc:
                        logger.warning(
                            "get_ohlcv_by_date.ticker_failed",
                            ticker=ticker,
                            error=str(exc),
                        )

            except Exception as exc:
                logger.error("get_ohlcv_by_date.market_failed", market=market, error=str(exc))

        if not results:
            return pd.DataFrame()

        return pd.DataFrame(results)

    @staticmethod
    def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
        """한국어 컬럼명 → 영문 정규화."""
        return df.rename(columns={
            "시가": "open",
            "고가": "high",
            "저가": "low",
            "종가": "close",
            "거래량": "volume",
            "거래대금": "amount",
        })
