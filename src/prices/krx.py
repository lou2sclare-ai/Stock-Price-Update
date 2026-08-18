from __future__ import annotations
from datetime import datetime, timedelta
from functools import lru_cache
from math import isfinite
from zoneinfo import ZoneInfo
from pykrx import stock

KST = ZoneInfo("Asia/Seoul")
OFFICIAL_CHANGE_ORIGIN = "KRX_GET_MARKET_OHLCV_BY_TICKER"


def _completed_end_date():
    """Return the latest date that can safely contain a completed KRX session."""
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


@lru_cache(maxsize=8)
def _official_market_snapshot(trading_day: str):
    """Fetch the KRX all-stock daily quote table once per trading day.

    This endpoint is the source of truth for the exchange-published `등락률`.
    The date-range endpoint is intentionally not used for daily return because
    PyKRX defaults that path to adjusted NAVER history and it is not equivalent
    to KRX's official one-day comparison basis around corporate actions.
    """
    df = stock.get_market_ohlcv_by_ticker(trading_day, market="ALL")
    if df is None or df.empty:
        raise RuntimeError(f"No official KRX market snapshot: {trading_day}")
    return df


def fetch_daily_close(ticker: str, lookback_days: int = 24) -> list[dict]:
    end = _completed_end_date()
    end_ymd = end.strftime("%Y%m%d")
    trading_day = stock.get_nearest_business_day_in_a_week(end_ymd, prev=True)
    start = end - timedelta(days=lookback_days)

    # Raw KRX history is retained only to identify preceding trading dates and
    # raw prior closes for QA/corporate-action diagnostics.
    hist = stock.get_market_ohlcv_by_date(
        start.strftime("%Y%m%d"),
        trading_day,
        ticker,
        adjusted=False,
    )
    if hist is None or hist.empty:
        raise RuntimeError(f"No completed KRX history: {ticker}")

    snapshot = _official_market_snapshot(trading_day)
    ticker_key = str(ticker).zfill(6)
    if ticker_key not in snapshot.index:
        raise RuntimeError(f"Ticker missing from official KRX snapshot: {ticker_key} {trading_day}")

    official = snapshot.loc[ticker_key]
    official_close = _number(official.get("종가"))
    official_pct = _number(official.get("등락률"))
    official_volume = _number(official.get("거래량"))
    if official_close is None or official_close <= 0:
        raise RuntimeError(f"Official KRX close unavailable/invalid: {ticker_key} {trading_day}")
    if official_pct is None or official_pct <= -100:
        raise RuntimeError(f"Official KRX daily change unavailable/invalid: {ticker_key} {trading_day}")

    out = []
    for idx, row in hist.tail(8).iterrows():
        item = {
            "date": idx.date().isoformat(),
            "close": _number(row.get("종가")),
            "volume": _number(row.get("거래량")),
        }
        if idx.strftime("%Y%m%d") == trading_day:
            item.update({
                "close": official_close,
                "volume": official_volume,
                "source_change_pct": official_pct,
                "source_change_origin": OFFICIAL_CHANGE_ORIGIN,
            })
        out.append(item)

    # If the historical endpoint omitted the current trading day for any reason,
    # append the official KRX row rather than silently falling back to old data.
    if not out or out[-1]["date"] != datetime.strptime(trading_day, "%Y%m%d").date().isoformat():
        out.append({
            "date": datetime.strptime(trading_day, "%Y%m%d").date().isoformat(),
            "close": official_close,
            "volume": official_volume,
            "source_change_pct": official_pct,
            "source_change_origin": OFFICIAL_CHANGE_ORIGIN,
        })

    if len([x for x in out if x.get("close") is not None]) < 2:
        raise RuntimeError(f"Need at least 2 completed KRX rows: {ticker_key}")
    return out
