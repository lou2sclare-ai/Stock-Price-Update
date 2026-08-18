from __future__ import annotations
from datetime import date
from src.prices import krx, global_yahoo


def _finalize(series: list[dict], prefer_source_change: bool = False) -> dict:
    clean = [x for x in series if x.get("close") is not None]
    if len(clean) < 2:
        raise RuntimeError("Need at least 2 completed daily closes")
    current, previous = clean[-1], clean[-2]
    raw_previous = previous["close"]
    raw_pct = (current["close"] / raw_previous - 1.0) * 100 if raw_previous else None

    pct = raw_pct
    comparison_base = raw_previous
    corporate_action_adjusted = False

    # KRX publishes the official daily return against the exchange's comparison
    # base price. After a split/consolidation, capital reduction, relisting, etc.
    # that base can differ materially from the last raw close before suspension.
    source_pct = current.get("source_change_pct")
    if prefer_source_change and source_pct is not None and source_pct > -100:
        pct = float(source_pct)
        comparison_base = current["close"] / (1.0 + pct / 100.0) if pct != -100 else None
        if raw_pct is not None and abs(raw_pct - pct) >= 1.0:
            corporate_action_adjusted = True

    change = current["close"] - comparison_base if comparison_base is not None else None
    d0 = date.fromisoformat(previous["date"])
    d1 = date.fromisoformat(current["date"])
    return {
        "price": current["close"],
        "previous_close": comparison_base,
        "price_change": change,
        "price_change_pct": pct,
        "price_date": current["date"],
        "previous_trading_date": previous["date"],
        "calendar_days_elapsed": (d1 - d0).days,
        "volume": current.get("volume"),
        "raw_previous_close": raw_previous,
        "raw_close_change_pct": raw_pct,
        "corporate_action_adjusted": corporate_action_adjusted,
    }


def fetch(row: dict, global_snapshot: dict | None = None) -> dict:
    country = (row.get("country") or "").upper()
    if country == "KR":
        result = _finalize(krx.fetch_daily_close(row["ticker"]), prefer_source_change=True)
        result["price_source"] = "KRX/PyKRX official change basis"
        return result

    key = (
        str(row.get("exchange") or "").upper(),
        str(row.get("ticker") or "").upper(),
    )
    if global_snapshot and key in global_snapshot:
        result = dict(global_snapshot[key])
        result.setdefault("price_date", None)
        result.setdefault("previous_trading_date", None)
        result.setdefault("calendar_days_elapsed", None)
        return result

    result = _finalize(global_yahoo.fetch_daily_close(row["ticker"], row.get("exchange")))
    result["price_source"] = "Yahoo Finance/yfinance fallback"
    return result
