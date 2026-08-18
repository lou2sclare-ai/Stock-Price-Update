from __future__ import annotations
from dataclasses import dataclass, asdict
import requests

SCAN_URL = "https://scanner.tradingview.com/global/scan"

# TradingView's public screener endpoint is used as a discovery source, not a price source.
# The dashboard keeps source classification and our research classification separately.
COLUMNS = [
    "name", "description", "exchange", "country", "sector", "industry",
    "market_cap_basic", "currency", "type", "subtype",
]

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


def _scan(industry: str, limit: int = 10000) -> list[dict]:
    payload = {
        "filter": [
            {"left": "type", "operation": "equal", "right": "stock"},
            {"left": "industry", "operation": "equal", "right": industry},
        ],
        "options": {"lang": "en"},
        "markets": [],
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": COLUMNS,
        "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
        "range": [0, limit],
    }
    r = requests.post(SCAN_URL, json=payload, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.json().get("data", [])


def fetch_industries(industry_names: list[str]) -> list[dict]:
    out = []
    seen = set()
    for industry in industry_names:
        for item in _scan(industry):
            s = item.get("s", "")
            values = item.get("d", [])
            row = dict(zip(COLUMNS, values))
            # symbol is generally EXCHANGE:TICKER; preserve exchange and ticker separately.
            ticker = row.get("name") or (s.split(":", 1)[-1] if ":" in s else s)
            key = (row.get("exchange"), ticker)
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
