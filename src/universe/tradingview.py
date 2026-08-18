from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import requests

SCAN_URL = "https://scanner.tradingview.com/global/scan"

# TradingView is the global universe source. We keep primary common-share
# listings only to avoid duplicate overseas listings, preferred shares and
# depositary clutter. Price snapshots come from the same screener universe.
COLUMNS = [
    "name", "description", "exchange", "country", "sector", "industry",
    "market_cap_basic", "currency", "type", "subtype", "typespecs",
]
PRICE_COLUMNS = COLUMNS + ["close", "change", "change_abs", "volume"]


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


def fetch_industries(industry_names: list[str]) -> list[dict]:
    out = []
    seen = set()
    for industry in industry_names:
        for item in _scan(industry):
            values = item.get("d", [])
            row = dict(zip(COLUMNS, values))
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
    """Return latest regular-session price data keyed by (exchange, ticker).

    The screener's `change` field is percentage change from the previous regular
    close. We derive previous_close from close and change so every row is
    internally consistent even when an absolute-change field is unavailable.
    """
    out: dict[tuple[str, str], dict] = {}
    observed_at = datetime.now(timezone.utc).isoformat()
    for industry in industry_names:
        for item in _scan(industry, PRICE_COLUMNS):
            values = item.get("d", [])
            row = dict(zip(PRICE_COLUMNS, values))
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
            out[(exchange, str(ticker).upper())] = {
                "price": close,
                "previous_close": previous,
                "price_change": change_abs,
                "price_change_pct": pct,
                "volume": volume,
                "price_source": "TradingView Screener",
                "price_observed_at": observed_at,
            }
    return out
