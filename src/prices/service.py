from __future__ import annotations
from datetime import date
from src.prices import krx, global_yahoo


def _finalize(series: list[dict]) -> dict:
    clean = [x for x in series if x.get("close") is not None]
    if len(clean) < 2:
        raise RuntimeError("Need at least 2 completed daily closes")
    current, previous = clean[-1], clean[-2]
    change = current["close"] - previous["close"]
    pct = (current["close"] / previous["close"] - 1.0) * 100 if previous["close"] else None
    d0 = date.fromisoformat(previous["date"])
    d1 = date.fromisoformat(current["date"])
    return {
        "price": current["close"],
        "previous_close": previous["close"],
        "price_change": change,
        "price_change_pct": pct,
        "price_date": current["date"],
        "previous_trading_date": previous["date"],
        "calendar_days_elapsed": (d1 - d0).days,
        "volume": current.get("volume"),
    }


def fetch(row: dict, global_snapshot: dict | None = None) -> dict:
    country = (row.get("country") or "").upper()
    if country == "KR":
        result = _finalize(krx.fetch_daily_close(row["ticker"]))
        result["price_source"] = "KRX/PyKRX"
        return result

    key = (
        str(row.get("exchange") or "").upper(),
        str(row.get("ticker") or "").upper(),
    )
    if global_snapshot and key in global_snapshot:
        result = dict(global_snapshot[key])
        # TradingView's change is calculated against the prior regular close.
        # Exact exchange session dates will be added in the calendar QA layer;
        # until then do not invent dates for global markets.
        result.setdefault("price_date", None)
        result.setdefault("previous_trading_date", None)
        result.setdefault("calendar_days_elapsed", None)
        return result

    # Fallback only: useful for manually overridden tickers that map cleanly.
    result = _finalize(global_yahoo.fetch_daily_close(row["ticker"], row.get("exchange")))
    result["price_source"] = "Yahoo Finance/yfinance fallback"
    return result
