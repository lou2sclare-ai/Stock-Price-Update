from __future__ import annotations
from datetime import datetime, timedelta
from pykrx import stock


def fetch_daily_close(ticker: str, lookback_days: int = 20) -> list[dict]:
    end = datetime.now().date()
    start = end - timedelta(days=lookback_days)
    df = stock.get_market_ohlcv_by_date(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), ticker)
    if df is None or df.empty:
        raise RuntimeError(f"No KRX OHLCV data: {ticker}")
    out = []
    for idx, row in df.tail(5).iterrows():
        out.append({
            "date": idx.date().isoformat(),
            "close": float(row["종가"]),
            "volume": float(row["거래량"]),
        })
    return out
