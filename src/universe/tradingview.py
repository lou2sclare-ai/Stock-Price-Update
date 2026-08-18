from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import requests

SCAN_URL = "https://scanner.tradingview.com/global/scan"

COLUMNS = [
    "name", "description", "exchange", "country", "sector", "industry",
    "market_cap_basic", "currency", "type", "subtype", "typespecs",
]
# TradingView exposes the daily bar timestamp as well as the current session.
# Together they let us attach an actual trading date to each accepted completed
# regular-session snapshot rather than showing only the collection timestamp.
PRICE_COLUMNS = COLUMNS + [
    "close", "change", "change_abs", "volume", "current_session",
    "daily-bar.time", "time_business_day", "last_bar_update_time",
]

KOREA_NAMES = {"KR", "KOREA", "SOUTH KOREA", "REPUBLIC OF KOREA"}
OTC_EXCHANGES = {"OTC", "OTCQX", "OTCQB", "OTCPK", "PINK", "GREY"}

# Used only to convert TradingView's daily-bar UNIX time to the exchange-local
# calendar date. time_business_day is preferred when TradingView supplies it.
EXCHANGE_TZ = {
    "NASDAQ": "America/New_York", "NYSE": "America/New_York", "AMEX": "America/New_York",
    "NEO": "America/Toronto", "TSX": "America/Toronto", "TSXV": "America/Toronto",
    "BMFBOVESPA": "America/Sao_Paulo",
    "LSE": "Europe/London", "XETR": "Europe/Berlin", "FWB": "Europe/Berlin",
    "EURONEXT": "Europe/Paris", "MIL": "Europe/Rome", "BME": "Europe/Madrid",
    "SIX": "Europe/Zurich", "OSL": "Europe/Oslo", "OMXSTO": "Europe/Stockholm",
    "NGM": "Europe/Stockholm", "OMXHEL": "Europe/Helsinki", "OMXHEX": "Europe/Helsinki",
    "OMXCOP": "Europe/Copenhagen", "GPW": "Europe/Warsaw", "NEWCONNECT": "Europe/Warsaw",
    "BVB": "Europe/Bucharest", "VIE": "Europe/Vienna", "PSECZ": "Europe/Prague",
    "BIST": "Europe/Istanbul", "RUS": "Europe/Moscow", "OMXTSE": "Europe/Tallinn",
    "ZSE": "Europe/Zagreb", "BSESOF": "Europe/Sofia",
    "TSE": "Asia/Tokyo", "NAG": "Asia/Tokyo", "SSE": "Asia/Shanghai", "SZSE": "Asia/Shanghai",
    "HKEX": "Asia/Hong_Kong", "TPEX": "Asia/Taipei", "NSE": "Asia/Kolkata", "BSE": "Asia/Kolkata",
    "SET": "Asia/Bangkok", "IDX": "Asia/Jakarta", "TASE": "Asia/Jerusalem",
    "TADAWUL": "Asia/Riyadh", "PSX": "Asia/Karachi", "PSE": "Asia/Manila",
    "HOSE": "Asia/Ho_Chi_Minh", "HNX": "Asia/Ho_Chi_Minh", "UPCOM": "Asia/Ho_Chi_Minh",
    "CSELK": "Asia/Colombo", "DSEBD": "Asia/Dhaka", "ADX": "Asia/Dubai",
    "ASX": "Australia/Sydney", "JSE": "Africa/Johannesburg", "EGX": "Africa/Cairo",
    "NSEKE": "Africa/Nairobi", "CSEMA": "Africa/Casablanca", "NSENG": "Africa/Lagos",
    "KRX": "Asia/Seoul",
}


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
    business_day = row.get("time_business_day")
    try:
        n = int(float(business_day))
    except (TypeError, ValueError):
        n = 0
    if 19000101 <= n <= 21001231:
        text = str(n)
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}", "TradingView time_business_day"

    ts = _epoch_seconds(row.get("daily-bar.time"))
    if ts is None:
        return None, None
    exchange = str(row.get("exchange") or "").upper()
    tz_name = EXCHANGE_TZ.get(exchange)
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    if tz_name:
        dt = dt.astimezone(ZoneInfo(tz_name))
        return dt.date().isoformat(), "TradingView daily-bar.time exchange-local"
    return dt.date().isoformat(), "TradingView daily-bar.time UTC fallback"


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


def fetch_price_snapshot(industry_names: list[str]) -> dict[tuple[str, str], dict]:
    """Return quote data keyed by (exchange, ticker), including bar date/session.

    A caller must publish the snapshot only when market_session is not regular.
    The attached price_date is the TradingView daily bar's own trading date.
    """
    out: dict[tuple[str, str], dict] = {}
    observed_at = datetime.now(timezone.utc).isoformat()
    for industry in industry_names:
        for item in _scan(industry, PRICE_COLUMNS):
            values = item.get("d", [])
            row = dict(zip(PRICE_COLUMNS, values))
            if not _keep_listing(row):
                continue
            ticker = _ticker(item, row)
            exchange = str(row.get("exchange") or "").upper()
            if not ticker or not exchange:
                continue
            close = row.get("close")
            pct = row.get("change")
            try:
                close = float(close)
            except (TypeError, ValueError):
                continue
            if close <= 0:
                continue
            try:
                pct = float(pct) if pct is not None else None
            except (TypeError, ValueError):
                pct = None
            previous = None
            if pct is not None and pct > -100:
                previous = close / (1.0 + pct / 100.0)
            change_abs = row.get("change_abs")
            try:
                change_abs = float(change_abs) if change_abs is not None else None
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
