from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import requests

SCAN_URL = "https://scanner.tradingview.com/global/scan"

COLUMNS = [
    "name", "description", "exchange", "country", "sector", "industry",
    "market_cap_basic", "currency", "type", "subtype", "typespecs",
]
BASE_PRICE_COLUMNS = COLUMNS + [
    "close", "change", "change_abs", "volume", "current_session",
]
PRICE_COLUMNS = BASE_PRICE_COLUMNS + [
    "daily-bar.time", "time_business_day", "last_bar_update_time",
]

KOREA_NAMES = {"KR", "KOREA", "SOUTH KOREA", "REPUBLIC OF KOREA"}
OTC_EXCHANGES = {"OTC", "OTCQX", "OTCQB", "OTCPK", "PINK", "GREY"}


@dataclass
class GlobalStock:
    company_name: str
    ticker: str
    source_sector: str
    source_industry: str
    source: str = "TRADINGVIEW_SCREENER"
    country: str | None = None
    exchange: str | None = None
    currency: str | None = None
    market_cap: float | None = None


def _scan(industry: str, columns: list[str] | None = None, limit: int = 10000) -> list[dict]:
    columns = columns or COLUMNS
    payload = {
        "filter": [
            {"left": "type", "operation": "equal", "right": "stock"},
            {"left": "is_primary", "operation": "equal", "right": True},
            {"left": "typespecs", "operation": "has", "right": "common"},
            {"left": "industry", "operation": "equal", "right": industry},
        ],
        "options": {"lang": "en", "active_symbols_only": True},
        "markets": [],
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": columns,
        "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
        "range": [0, limit],
    }
    r = requests.post(
        SCAN_URL,
        json=payload,
        timeout=45,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    r.raise_for_status()
    return r.json().get("data", [])


def _ticker(item: dict, row: dict) -> str:
    s = item.get("s", "")
    return row.get("name") or (s.split(":", 1)[-1] if ":" in s else s)


def _keep_listing(row: dict) -> bool:
    country = str(row.get("country") or "").strip().upper()
    exchange = str(row.get("exchange") or "").strip().upper()
    if country in KOREA_NAMES:
        return False
    if exchange in OTC_EXCHANGES or exchange.startswith("OTC"):
        return False
    return True


def _epoch_seconds(value) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if x > 10_000_000_000:
        x /= 1000.0
    return x if 100_000_000 <= x <= 10_000_000_000 else None


def _price_date(row: dict) -> tuple[str | None, str | None]:
    # TradingView's explicit business-day field is the preferred source.
    business_day = row.get("time_business_day")
    try:
        n = int(float(business_day))
    except (TypeError, ValueError):
        n = 0
    if 19000101 <= n <= 21001231:
        text = str(n)
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}", "TradingView time_business_day"

    # daily-bar.time is a bar identifier timestamp, not an exchange-local wall
    # clock. Converting it into America/New_York previously shifted US bars one
    # calendar day backward (e.g. an Aug-18 close displayed as Aug-17). Use the
    # timestamp's UTC calendar date as the fallback instead.
    ts = _epoch_seconds(row.get("daily-bar.time"))
    if ts is None:
        return None, None
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.date().isoformat(), "TradingView daily-bar.time UTC bar date"


def fetch_industries(industry_names: list[str]) -> list[dict]:
    out = []
    seen = set()
    for industry in industry_names:
        for item in _scan(industry):
            values = item.get("d", [])
            row = dict(zip(COLUMNS, values))
            if not _keep_listing(row):
                continue
            ticker = _ticker(item, row)
            key = (str(row.get("exchange") or "").upper(), str(ticker or "").upper())
            if not ticker or key in seen:
                continue
            seen.add(key)
            out.append(asdict(GlobalStock(
                company_name=row.get("description") or ticker,
                ticker=ticker,
                source_sector=row.get("sector") or "",
                source_industry=row.get("industry") or industry,
                country=row.get("country"),
                exchange=row.get("exchange"),
                currency=row.get("currency"),
                market_cap=row.get("market_cap_basic"),
            )))
    return out


def _industry_price_rows(industry: str) -> tuple[list[dict], list[str]]:
    try:
        return _scan(industry, PRICE_COLUMNS), PRICE_COLUMNS
    except requests.RequestException:
        # Never break the daily update just because an optional TradingView date
        # column is unavailable. Price/session safety still works with the base
        # columns; the UI will explicitly mark the trade date as unavailable.
        return _scan(industry, BASE_PRICE_COLUMNS), BASE_PRICE_COLUMNS


def fetch_price_snapshot(industry_names: list[str]) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    observed_at = datetime.now(timezone.utc).isoformat()
    for industry in industry_names:
        items, columns = _industry_price_rows(industry)
        for item in items:
            values = item.get("d", [])
            row = dict(zip(columns, values))
            if not _keep_listing(row):
                continue
            ticker = _ticker(item, row)
            exchange = str(row.get("exchange") or "").upper()
            if not ticker or not exchange:
                continue
            try:
                close = float(row.get("close"))
            except (TypeError, ValueError):
                continue
            if close <= 0:
                continue
            try:
                pct = float(row.get("change")) if row.get("change") is not None else None
            except (TypeError, ValueError):
                pct = None
            previous = close / (1.0 + pct / 100.0) if pct is not None and pct > -100 else None
            try:
                change_abs = float(row.get("change_abs")) if row.get("change_abs") is not None else None
            except (TypeError, ValueError):
                change_abs = None
            if change_abs is None and previous is not None:
                change_abs = close - previous
            try:
                volume = float(row.get("volume")) if row.get("volume") is not None else None
            except (TypeError, ValueError):
                volume = None
            price_date, date_source = _price_date(row)
            out[(exchange, str(ticker).upper())] = {
                "price": close,
                "previous_close": previous,
                "price_change": change_abs,
                "price_change_pct": pct,
                "price_date": price_date,
                "previous_trading_date": None,
                "calendar_days_elapsed": None,
                "volume": volume,
                "price_source": "TradingView Screener",
                "price_observed_at": observed_at,
                "last_checked_at": observed_at,
                "market_session": str(row.get("current_session") or "").strip().lower(),
                "price_trade_date_source": date_source,
                "price_bar_time": row.get("daily-bar.time"),
                "price_bar_update_time": row.get("last_bar_update_time"),
                "data_status": "COMPLETED_SESSION_SNAPSHOT",
            }
    return out
