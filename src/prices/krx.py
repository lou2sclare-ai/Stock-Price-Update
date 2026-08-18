from __future__ import annotations
from datetime import datetime
from math import isfinite
from zoneinfo import ZoneInfo
from src.utils.http import get

KST = ZoneInfo("Asia/Seoul")
OFFICIAL_CHANGE_ORIGIN = "NAVER_KRX_MIRROR_DAILY_QUOTE"
COMPARISON_BASE_SOURCE = "source_change_implied_base"
PRICE_URL = "https://m.stock.naver.com/api/stock/{ticker}/price"
BASIC_URL = "https://m.stock.naver.com/api/stock/{ticker}/basic"


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


def _json_rows(ticker: str) -> list[dict]:
    url = PRICE_URL.format(ticker=str(ticker).zfill(6))
    payload = get(url, params={"pageSize": 5, "page": 1}, timeout=15, retries=3).json()
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("priceInfos", "prices", "stockPrices", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    raise RuntimeError(f"Unexpected NAVER price payload: {ticker}")


def _basic(ticker: str) -> dict:
    url = BASIC_URL.format(ticker=str(ticker).zfill(6))
    payload = get(url, timeout=15, retries=3).json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected NAVER basic payload: {ticker}")
    return payload


def _extract(row: dict) -> tuple[float, float, float | None, str | None]:
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
    return close, pct, volume, traded_at


def fetch_official_daily_quote(ticker: str) -> dict:
    """Return a completed Korean daily quote from NAVER's KRX-mirrored feed.

    GitHub-hosted jobs can be unreliable against the direct KRX endpoint. NAVER
    already mirrors the exchange comparison data used on its stock page, so the
    published close and daily percentage move are taken from that quote feed.
    We never recompute the percentage from two historical raw closes.
    """
    ticker_key = str(ticker).zfill(6)
    rows = []
    try:
        rows = _json_rows(ticker_key)
        current = rows[0] if rows else None
        if not current:
            raise RuntimeError("NAVER price rows empty")
        close, pct, volume, price_date = _extract(current)
    except Exception as first_exc:
        try:
            current = _basic(ticker_key)
            close, pct, volume, price_date = _extract(current)
        except Exception as second_exc:
            raise RuntimeError(
                f"NAVER KRX-mirrored quote failed: {ticker_key}; "
                f"price={first_exc}; basic={second_exc}"
            ) from second_exc

    previous_date = None
    raw_previous = None
    raw_pct = None
    if len(rows) >= 2:
        try:
            raw_previous, _, _, previous_date = _extract(rows[1])
            if raw_previous and raw_previous > 0:
                raw_pct = (close / raw_previous - 1.0) * 100.0
        except Exception:
            previous_date = _date(rows[1].get("localTradedAt") or rows[1].get("date"))
            raw_previous = _number(rows[1].get("closePrice") or rows[1].get("close"))
            if raw_previous and raw_previous > 0:
                raw_pct = (close / raw_previous - 1.0) * 100.0

    comparison_base = close / (1.0 + pct / 100.0)
    comparison_base = float(round(comparison_base))
    change = close - comparison_base
    corporate_action_adjusted = raw_pct is not None and abs(raw_pct - pct) >= 1.0

    elapsed = None
    if price_date and previous_date:
        try:
            elapsed = (
                datetime.strptime(price_date, "%Y-%m-%d").date()
                - datetime.strptime(previous_date, "%Y-%m-%d").date()
            ).days
        except ValueError:
            elapsed = None

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
