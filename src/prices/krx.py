from __future__ import annotations
from datetime import datetime, timedelta
from math import isfinite
from zoneinfo import ZoneInfo
from src.utils.http import get

KST = ZoneInfo("Asia/Seoul")
OFFICIAL_CHANGE_ORIGIN = "NAVER_KRX_MIRROR_DAILY_QUOTE"
COMPARISON_BASE_SOURCE = "source_exact_absolute_change"
PRICE_URL = "https://m.stock.naver.com/api/stock/{ticker}/price"


def _number(value):
    if value is None:
        return None
    try:
        text = str(value).replace(",", "").replace("%", "").replace("+", "").strip()
        x = float(text)
        return x if isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _date(value):
    if not value:
        return None
    text = str(value).strip().replace(".", "-").replace("/", "-")
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    if len(text) >= 8 and text[:8].isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return None


def _completed_cutoff_date() -> str:
    """Latest calendar date allowed to be published as a completed KRX close."""
    now = datetime.now(KST)
    cutoff = now.date() if now.hour >= 16 else now.date() - timedelta(days=1)
    return cutoff.isoformat()


def _json_rows(ticker: str) -> list[dict]:
    url = PRICE_URL.format(ticker=str(ticker).zfill(6))
    payload = get(url, params={"pageSize": 7, "page": 1}, timeout=15, retries=3).json()
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("priceInfos", "prices", "stockPrices", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    raise RuntimeError(f"Unexpected NAVER price payload: {ticker}")


def _signed_source_change(row: dict, pct: float) -> float:
    """Read NAVER's exact absolute day change and apply the sign from its return."""
    delta = _number(row.get("compareToPreviousClosePrice"))
    if delta is None:
        raise RuntimeError("NAVER/KRX-mirrored exact daily price change unavailable")
    if abs(pct) < 1e-12 or abs(delta) < 1e-12:
        return 0.0
    return abs(delta) if pct > 0 else -abs(delta)


def _extract(row: dict) -> tuple[float, float, float | None, str, float]:
    close = _number(row.get("closePrice") or row.get("close") or row.get("nowVal"))
    pct = _number(
        row.get("fluctuationsRatio")
        or row.get("changeRate")
        or row.get("fluctuationRate")
        or row.get("rate")
    )
    volume = _number(
        row.get("accumulatedTradingVolume")
        or row.get("tradingVolume")
        or row.get("volume")
    )
    traded_at = _date(
        row.get("localTradedAt")
        or row.get("tradedAt")
        or row.get("date")
    )
    if close is None or close <= 0:
        raise RuntimeError("NAVER/KRX-mirrored close unavailable")
    if pct is None or pct <= -100:
        raise RuntimeError("NAVER/KRX-mirrored daily return unavailable")
    if not traded_at:
        raise RuntimeError("NAVER/KRX-mirrored trade date unavailable")
    change = _signed_source_change(row, pct)
    return close, pct, volume, traded_at, change


def _completed_rows(rows: list[dict]) -> list[tuple[float, float, float | None, str, float]]:
    cutoff = _completed_cutoff_date()
    parsed = []
    for row in rows:
        try:
            item = _extract(row)
        except Exception:
            continue
        if item[3] <= cutoff:
            parsed.append(item)
    parsed.sort(key=lambda x: x[3], reverse=True)
    return parsed


def fetch_official_daily_quote(ticker: str) -> dict:
    """Return the latest completed Korean quote using NAVER's exact day change.

    Before 16:00 KST NAVER may expose a same-day pre-open placeholder using the
    prior close with a 0.0% move. Rows newer than the completed-close cutoff are
    discarded. For the selected completed row, both the percentage move and the
    exact absolute change come directly from the source instead of reconstructing
    a comparison price from a rounded percentage.
    """
    ticker_key = str(ticker).zfill(6)
    rows = _json_rows(ticker_key)
    completed = _completed_rows(rows)
    if not completed:
        raise RuntimeError(
            f"No completed NAVER/KRX-mirrored daily quote: {ticker_key}; "
            f"cutoff={_completed_cutoff_date()}"
        )

    close, pct, volume, price_date, change = completed[0]
    comparison_base = close - change
    if comparison_base <= 0:
        raise RuntimeError("NAVER/KRX-mirrored comparison base is invalid")

    previous_date = None
    raw_previous = None
    raw_pct = None
    if len(completed) >= 2:
        raw_previous, _, _, previous_date, _ = completed[1]
        if raw_previous and raw_previous > 0:
            raw_pct = (close / raw_previous - 1.0) * 100.0

    corporate_action_adjusted = raw_pct is not None and abs(raw_pct - pct) >= 1.0

    elapsed = None
    if price_date and previous_date:
        elapsed = (
            datetime.strptime(price_date, "%Y-%m-%d").date()
            - datetime.strptime(previous_date, "%Y-%m-%d").date()
        ).days

    return {
        "price": close,
        "previous_close": comparison_base,
        "price_change": change,
        "price_change_pct": float(pct),
        "price_date": price_date,
        "previous_trading_date": previous_date,
        "calendar_days_elapsed": elapsed,
        "volume": volume,
        "raw_previous_close": raw_previous,
        "raw_close_change_pct": raw_pct,
        "corporate_action_adjusted": corporate_action_adjusted,
        "comparison_base_source": COMPARISON_BASE_SOURCE,
        "source_change_origin": OFFICIAL_CHANGE_ORIGIN,
        "price_source": "NAVER Finance KRX-mirrored daily quote",
    }
