"""
IndicatorService — calculates technical indicators from stored price data.

온디맨드 수집 지원:
- get_or_fetch_for_ticker_date(): DB에 데이터 없으면 provider에서 직접 수집 후 계산
- 배치 없이도 특정 종목 즉시 조회 가능
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from app.core.config import settings
from app.core.logging import get_logger
from app.repository.price_repository import PriceRepository
from app.repository.indicator_repository import IndicatorRepository

logger = get_logger(__name__)

RSI_PERIOD = 14
MA_SHORT = 5
MA_LONG = 20
MIN_BARS_MA_LONG = MA_LONG


def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _compute_ma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window=window, min_periods=window).mean()


def _compute_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series]:
    """Return (macd_line, signal_line). Uses EMA with adjust=False (Wilder-compatible)."""
    ema_fast = close.ewm(span=fast, min_periods=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, min_periods=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, min_periods=signal, adjust=False).mean()
    return macd_line, signal_line


def _compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """ATR (Average True Range) — Wilder smoothing."""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def _compute_bollinger(close: pd.Series, window: int = 20, n_std: float = 2.0):
    """Return (upper, mid, lower) bands."""
    mid   = close.rolling(window=window, min_periods=window).mean()
    std   = close.rolling(window=window, min_periods=window).std(ddof=0)
    upper = mid + n_std * std
    lower = mid - n_std * std
    return upper, mid, lower


def _compute_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume."""
    direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    return (direction * volume).cumsum()


class IndicatorService:
    def __init__(
        self,
        price_repo: PriceRepository,
        indicator_repo: IndicatorRepository,
        provider=None,  # MarketDataProvider (온디맨드 수집용, 선택)
        stock_repo=None,  # StockRepository (업종 업데이트용, 선택)
    ) -> None:
        self._price_repo = price_repo
        self._indicator_repo = indicator_repo
        self._provider = provider
        self._stock_repo = stock_repo

    def _compute_for_ticker(self, prices: pd.DataFrame) -> dict[str, Any]:
        close  = prices["close"].astype(float)
        high   = prices["high"].astype(float)  if "high"   in prices.columns else close
        low    = prices["low"].astype(float)   if "low"    in prices.columns else close
        volume = prices["volume"].astype(float) if "volume" in prices.columns else pd.Series(0.0, index=close.index)

        ma5   = _compute_ma(close, 5)
        ma20  = _compute_ma(close, 20)
        ma60  = _compute_ma(close, 60)
        ma120 = _compute_ma(close, 120)
        rsi14 = _compute_rsi(close, RSI_PERIOD)
        macd_line, macd_sig = _compute_macd(close)
        macd_hist = macd_line - macd_sig

        atr14 = _compute_atr(high, low, close, 14)
        bb_upper, bb_mid, bb_lower = _compute_bollinger(close, 20, 2.0)
        obv = _compute_obv(close, volume)
        volume_ma20 = _compute_ma(volume, 20)

        # 전고점: 오늘(마지막 행) 제외한 이전 전체 기간의 high 최댓값
        prev_high = round(float(high.iloc[:-1].max()), 2) if len(high) > 1 else None

        def _f(s: pd.Series, digits: int = 4):
            v = s.iloc[-1]
            return None if pd.isna(v) else round(float(v), digits)

        return {
            "ma5":         _f(ma5),
            "ma20":        _f(ma20),
            "ma60":        _f(ma60),
            "ma120":       _f(ma120),
            "rsi14":       _f(rsi14),
            "macd":        _f(macd_line, 6),
            "macd_signal": _f(macd_sig,  6),
            "macd_hist":   _f(macd_hist, 6),
            "atr14":       _f(atr14),
            "bb_upper":    _f(bb_upper),
            "bb_mid":      _f(bb_mid),
            "bb_lower":    _f(bb_lower),
            "obv":         _f(obv, 0),
            "volume_ma20": _f(volume_ma20, 2),
            "prev_high":   prev_high,
        }

    # ── PER/PBR 수집 (Naver Finance) ─────────────────────────────────────────

    @staticmethod
    async def _fetch_fundamentals(tickers: list[str]) -> dict[str, dict]:
        """
        네이버 금융 integration API로 PER/PBR 병렬 수집.
        실패 시 빈 dict 반환 (배치 중단 없이 계속).

        Endpoint: GET https://m.stock.naver.com/api/stock/{ticker}/integration
        응답 totalInfos 리스트에서 code=="per", code=="pbr" 항목 추출.
        value 예시: "40.52배" → 40.52 (단위 접미사 제거)
        """
        import httpx  # noqa: PLC0415

        _HEADERS = {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
            ),
            "Accept": "application/json",
            "Referer": "https://m.stock.naver.com/",
        }

        result: dict[str, dict] = {}
        sem = asyncio.Semaphore(30)

        def _parse(v) -> float | None:
            if v is None:
                return None
            cleaned = str(v).replace("배", "").replace(",", "").strip()
            try:
                f = float(cleaned)
                return None if f <= 0 else round(f, 2)
            except (ValueError, TypeError):
                return None

        async def _fetch_one(client: httpx.AsyncClient, ticker: str) -> None:
            async with sem:
                try:
                    r = await client.get(
                        f"https://m.stock.naver.com/api/stock/{ticker}/integration",
                        timeout=5.0,
                    )
                    if r.status_code != 200:
                        return
                    obj = r.json()
                    infos = {
                        item["code"]: item.get("value")
                        for item in obj.get("totalInfos", [])
                        if "code" in item
                    }
                    result[ticker] = {
                        "per": _parse(infos.get("per")),
                        "pbr": _parse(infos.get("pbr")),
                        "industryCode": str(obj.get("industryCode") or ""),
                    }
                except Exception:
                    pass

        async with httpx.AsyncClient(headers=_HEADERS) as client:
            await asyncio.gather(*[_fetch_one(client, t) for t in tickers])

        logger.info("indicator.fundamentals_loaded", count=len(result))
        return result

    # ── 전종목 배치 계산 ────────────────────────────────────────────────────────

    async def calculate_for_date(self, trade_date: date) -> dict:
        lookback_days = settings.default_lookback_days
        start_date = trade_date - timedelta(days=lookback_days)

        day_prices = await self._price_repo.get_by_date(trade_date)
        if not day_prices:
            logger.warning("indicator.no_prices", trade_date=str(trade_date))
            return {"calculated": 0}

        volumes = {p.ticker: p.volume for p in day_prices}
        sorted_by_vol = sorted(volumes.items(), key=lambda x: x[1], reverse=True)
        volume_rank = {ticker: rank + 1 for rank, (ticker, _) in enumerate(sorted_by_vol)}

        # PER/PBR + 업종코드 수집 (실패해도 배치 계속)
        fundamentals = await self._fetch_fundamentals(list(volumes.keys()))
        logger.info("indicator.fundamentals_batch_done", count=len(fundamentals))

        # 업종명 업데이트 (stocks 테이블) — integration API에서 함께 수집한 industryCode 활용
        if self._stock_repo is not None and fundamentals:
            from app.service.collect_service import _WICS_CODE_MAP
            sector_map = {
                t: _WICS_CODE_MAP.get(data.get("industryCode", ""))
                for t, data in fundamentals.items()
                if _WICS_CODE_MAP.get(data.get("industryCode", ""))
            }
            updated = await self._stock_repo.batch_update_sectors(sector_map)
            logger.info("indicator.sectors_updated", count=updated)

        upsert_rows = []
        for ticker in volumes.keys():
            prices = await self._price_repo.get_by_ticker(ticker, start_date, trade_date)
            if len(prices) < MIN_BARS_MA_LONG:
                # 데이터 부족 종목도 volume_rank는 저장 (거래량 조건 정확성 보장)
                fund = fundamentals.get(ticker, {})
                upsert_rows.append({
                    "ticker":       ticker,
                    "trade_date":   trade_date,
                    "ma5":          None, "ma20":  None,
                    "ma60":         None, "ma120": None,
                    "rsi14":        None,
                    "macd":         None, "macd_signal": None, "macd_hist": None,
                    "atr14":        None,
                    "bb_upper":     None, "bb_mid": None, "bb_lower": None,
                    "obv":          None, "volume_ma20": None,
                    "prev_high":    None,
                    "per":          fund.get("per"),
                    "pbr":          fund.get("pbr"),
                    "volume_rank":  volume_rank.get(ticker),
                })
                continue
            price_df = pd.DataFrame(
                [{"close": p.close, "high": p.high, "low": p.low, "volume": p.volume} for p in prices],
                index=[p.trade_date for p in prices],
            )
            indicators = self._compute_for_ticker(price_df)
            fund = fundamentals.get(ticker, {})
            upsert_rows.append({
                "ticker":       ticker,
                "trade_date":   trade_date,
                "ma5":          indicators["ma5"],
                "ma20":         indicators["ma20"],
                "ma60":         indicators["ma60"],
                "ma120":        indicators["ma120"],
                "rsi14":        indicators["rsi14"],
                "macd":         indicators["macd"],
                "macd_signal":  indicators["macd_signal"],
                "macd_hist":    indicators["macd_hist"],
                "atr14":        indicators["atr14"],
                "bb_upper":     indicators["bb_upper"],
                "bb_mid":       indicators["bb_mid"],
                "bb_lower":     indicators["bb_lower"],
                "obv":          indicators["obv"],
                "volume_ma20":  indicators["volume_ma20"],
                "prev_high":    indicators["prev_high"],
                "per":          fund.get("per"),
                "pbr":          fund.get("pbr"),
                "volume_rank":  volume_rank.get(ticker),
            })

        saved = await self._indicator_repo.upsert_many(upsert_rows)
        logger.info("indicator.calculated", trade_date=str(trade_date), count=saved)
        return {"calculated": saved}

    # ── 온디맨드: 단일 종목 조회 (없으면 수집 후 계산) ──────────────────────────

    async def get_or_fetch_for_ticker_date(
        self, ticker: str, trade_date: date
    ) -> dict[str, Any] | None:
        """
        1. DB에 지표 있으면 즉시 반환
        2. 없으면 provider에서 과거 데이터 수집 → 지표 계산 → 저장 → 반환
        """
        # 1) DB 조회
        snap = await self._indicator_repo.get_by_ticker_date(ticker, trade_date)
        if snap:
            return self._snap_to_dict(snap)

        # 2) provider 없으면 None 반환
        if self._provider is None:
            return None

        logger.info("indicator.on_demand_fetch", ticker=ticker, date=str(trade_date))

        # 3) 과거 데이터 수집
        lookback = settings.default_lookback_days + 10
        start_date = trade_date - timedelta(days=lookback)
        try:
            df = await self._provider.get_ohlcv_by_ticker(ticker, start_date, trade_date)
        except Exception as exc:
            logger.error("indicator.on_demand_fetch_failed", ticker=ticker, error=str(exc))
            return None

        if df is None or df.empty:
            return None

        # 4) DB 저장
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
        await self._price_repo.upsert_many(rows)

        # 5) 지표 계산
        price_df = pd.DataFrame(
            [{"close": r["close"], "high": r["high"], "volume": r["volume"]} for r in rows],
            index=[r["trade_date"] for r in rows],
        ).sort_index()

        if len(price_df) < MIN_BARS_MA_LONG:
            logger.warning("indicator.insufficient_bars", ticker=ticker, bars=len(price_df))
            return None

        indicators = self._compute_for_ticker(price_df)
        upsert_row = {
            "ticker": ticker,
            "trade_date": trade_date,
            "ma5":         indicators["ma5"],
            "ma20":        indicators["ma20"],
            "rsi14":       indicators["rsi14"],
            "macd":        indicators["macd"],
            "macd_signal": indicators["macd_signal"],
            "prev_high":   indicators["prev_high"],
            "volume_rank": None,  # 온디맨드는 전종목 비교 불가
        }
        await self._indicator_repo.upsert_many([upsert_row])
        logger.info("indicator.on_demand_done", ticker=ticker, date=str(trade_date))

        return {
            "ticker": ticker,
            "trade_date": trade_date,
            **indicators,
            "volume_rank": None,
        }

    # ── 기존 단순 조회 ──────────────────────────────────────────────────────────

    async def get_for_ticker_date(
        self, ticker: str, trade_date: date
    ) -> dict[str, Any] | None:
        snap = await self._indicator_repo.get_by_ticker_date(ticker, trade_date)
        if snap is None:
            return None
        return self._snap_to_dict(snap)

    @staticmethod
    def _snap_to_dict(snap) -> dict[str, Any]:
        return {
            "ticker": snap.ticker,
            "trade_date": snap.trade_date,
            "ma5": snap.ma5,
            "ma20": snap.ma20,
            "rsi14": snap.rsi14,
            "macd": snap.macd,
            "macd_signal": snap.macd_signal,
            "prev_high": snap.prev_high,
            "per": snap.per,
            "pbr": snap.pbr,
            "volume_rank": snap.volume_rank,
        }
