from __future__ import annotations
from datetime import datetime, timedelta
from functools import lru_cache
from math import isfinite
from zoneinfo import ZoneInfo
from pykrx import stock

KST = ZoneInfo("Asia/Seoul")
OFFICIAL_CHANGE_ORIGIN = "KRX_GET_MARKET_OHLCV_BY_TICKER"
COMPARISON_BASE_SOURCE = "KRX_official_change_implied_base"


def _completed_end_date():
    now = datetime.now(KST)
    if now.hour < 16:
        return now.date() - timedelta(days=1)
    return now.date()


def _number(value):
    try:
        x = float(value)
        return x if isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _nearest_business_day(day) -> str:
    return stock.get_nearest_business_day_in_a_week(day.strftime("%Y%m%d"), prev=True)


def _previous_business_day(trading_day: str) -> str:
    d = datetime.strptime(trading_day, "%Y%m%d").date() - timedelta(days=1)
    return _nearest_business_day(d)


@lru_cache(maxsize=8)
def _official_market_snapshot(trading_day: str):
    """Official KRX all-stock quote table for one completed trading day."""
    df = stock.get_market_ohlcv_by_ticker(trading_day, market="ALL")
    if df is None or df.empty:
        raise RuntimeError(f"No official KRX market snapshot: {trading_day}")
    return df


def fetch_official_daily_quote(ticker: str) -> dict:
    """Return a finalized daily KRX quote using the exchange-published return.

    The current close and daily return both come from KRX's cross-sectional
    daily snapshot. The last raw close is used only as a diagnostic comparison,
    never as the published return basis. This avoids false moves around capital
    reductions, splits/consolidations, relistings and reference-price resets.
    """
    trading_day = _nearest_business_day(_completed_end_date())
    previous_day = _previous_business_day(trading_day)
    ticker_key = str(ticker).zfill(6)

    current_snapshot = _official_market_snapshot(trading_day)
    if ticker_key not in current_snapshot.index:
        raise RuntimeError(f"Ticker missing from official KRX snapshot: {ticker_key} {trading_day}")

    current = current_snapshot.loc[ticker_key]
    close = _number(current.get("종가"))
    pct = _number(current.get("등락률"))
    volume = _number(current.get("거래량"))
    if close is None or close <= 0:
        raise RuntimeError(f"Official KRX close unavailable/invalid: {ticker_key} {trading_day}")
    if pct is None or pct <= -100:
        raise RuntimeError(f"Official KRX daily change unavailable/invalid: {ticker_key} {trading_day}")

    # The exchange's daily percentage move defines the correct comparison base.
    comparison_base = close / (1.0 + pct / 100.0)
    comparison_base = float(round(comparison_base))
    change = close - comparison_base

    raw_previous = None
    raw_pct = None
    try:
        previous_snapshot = _official_market_snapshot(previous_day)
        if ticker_key in previous_snapshot.index:
            raw_previous = _number(previous_snapshot.loc[ticker_key].get("종가"))
            if raw_previous and raw_previous > 0:
                raw_pct = (close / raw_previous - 1.0) * 100.0
    except Exception:
        # Previous raw close is diagnostic only. It must never block publication
        # when today's official KRX close/return are available.
        raw_previous = None
        raw_pct = None

    corporate_action_adjusted = (
        raw_pct is not None and abs(raw_pct - pct) >= 1.0
    )

    d0 = datetime.strptime(previous_day, "%Y%m%d").date()
    d1 = datetime.strptime(trading_day, "%Y%m%d").date()
    return {
        "price": close,
        "previous_close": comparison_base,
        "price_change": change,
        "price_change_pct": float(pct),
        "price_date": d1.isoformat(),
        "previous_trading_date": d0.isoformat(),
        "calendar_days_elapsed": (d1 - d0).days,
        "volume": volume,
        "raw_previous_close": raw_previous,
        "raw_close_change_pct": raw_pct,
        "corporate_action_adjusted": corporate_action_adjusted,
        "comparison_base_source": COMPARISON_BASE_SOURCE,
        "source_change_origin": OFFICIAL_CHANGE_ORIGIN,
        "price_source": "KRX/PyKRX official cross-sectional daily quote",
    }
