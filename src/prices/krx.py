from __future__ import annotations
from datetime import datetime, timedelta
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


def fetch_daily_close(ticker: str, lookback_days: int = 24) -> list[dict]:
    end = _completed_end_date()
    start = end - timedelta(days=lookback_days)
    df = stock.get_market_ohlcv_by_date(
        start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), ticker
    )
    if df is None or df.empty:
        raise RuntimeError(f"No completed KRX OHLCV data: {ticker}")
    out = []
    for idx, row in df.tail(5).iterrows():
        out.append({
            "date": idx.date().isoformat(),
            "close": float(row["종가"]),
            "volume": float(row["거래량"]),
        })
    return out
