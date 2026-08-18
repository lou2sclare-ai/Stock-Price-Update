from __future__ import annotations
from datetime import datetime, timedelta
from math import isfinite
from zoneinfo import ZoneInfo
from pykrx import stock

KST = ZoneInfo("Asia/Seoul")


def _completed_end_date():
    """Return the latest date that can safely contain a completed KRX session.

    PyKRX may expose today's in-progress OHLCV while the Korean market is open.
    Before 16:00 KST we therefore stop at yesterday; weekends/holidays are
    naturally skipped by the returned trading-day index.
    """
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


def fetch_daily_close(ticker: str, lookback_days: int = 24) -> list[dict]:
    end = _completed_end_date()
    start = end - timedelta(days=lookback_days)
    df = stock.get_market_ohlcv_by_date(
        start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), ticker
    )
    if df is None or df.empty:
        raise RuntimeError(f"No completed KRX OHLCV data: {ticker}")

    # PyKRX/KRX daily OHLCV includes the exchange's official daily change rate.
    # Keep it. Comparing the last two raw closes is wrong across capital
    # reductions, stock splits/consolidations, relistings, or reference-price
    # resets because the prior raw close is not necessarily today's comparison
    # base price.
    out = []
    for idx, row in df.tail(8).iterrows():
        out.append({
            "date": idx.date().isoformat(),
            "close": _number(row.get("종가")),
            "volume": _number(row.get("거래량")),
            "source_change_pct": _number(row.get("등락률")),
        })
    return out
