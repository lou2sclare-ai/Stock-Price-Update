from __future__ import annotations
from datetime import datetime, timedelta
from math import isfinite
from zoneinfo import ZoneInfo
from pykrx import stock

KST = ZoneInfo("Asia/Seoul")
OFFICIAL_CHANGE_ORIGIN = "KRX_UNADJUSTED_FLUC_RT"


def _completed_end_date():
    """Return the latest date that can safely contain a completed KRX session.

    PyKRX can expose today's in-progress quote while the Korean market is open.
    Before 16:00 KST we therefore stop at yesterday; weekends/holidays are
    naturally skipped by the returned exchange data.
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

    # CRITICAL: adjusted=False forces PyKRX to use KRX's unadjusted daily data.
    # The default adjusted=True path uses adjusted historical data and its
    # return series can be unsuitable for the exchange's official one-day
    # comparison basis around capital reductions, splits/consolidations,
    # relistings and other reference-price resets.
    df = stock.get_market_ohlcv_by_date(
        start.strftime("%Y%m%d"),
        end.strftime("%Y%m%d"),
        ticker,
        adjusted=False,
    )
    if df is None or df.empty:
        raise RuntimeError(f"No completed official KRX OHLCV data: {ticker}")

    out = []
    for idx, row in df.tail(8).iterrows():
        close = _number(row.get("종가"))
        official_pct = _number(row.get("등락률"))
        if close is None or close <= 0:
            continue
        if official_pct is None or official_pct <= -100:
            raise RuntimeError(
                f"Official KRX daily change unavailable/invalid: {ticker} {idx.date()}"
            )
        out.append({
            "date": idx.date().isoformat(),
            "close": close,
            "volume": _number(row.get("거래량")),
            "source_change_pct": official_pct,
            "source_change_origin": OFFICIAL_CHANGE_ORIGIN,
        })

    if len(out) < 2:
        raise RuntimeError(f"Need at least 2 official KRX daily rows: {ticker}")
    return out
