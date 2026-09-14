from __future__ import annotations
import re
from dataclasses import dataclass, asdict
from functools import lru_cache
from urllib.parse import urljoin, urlparse, parse_qs
from bs4 import BeautifulSoup
from src.utils.http import get

BASE = "https://finance.naver.com"
GROUP_URL = f"{BASE}/sise/sise_group.naver?type=upjong"

# Stable fallback ids for the research industries used by this project.
# NAVER sometimes changes query-parameter order or serves a simplified page to
# cloud runners, so the group-list page must not be a single point of failure.
FALLBACK_INDUSTRY_NOS = {
    "우주항공과국방": "284",
    "전기제품": "283",
    "조선": "291",
    "기계": "299",
    "전기장비": "306",
}


@dataclass
class NaverStock:
    company_name: str
    ticker: str
    source_sector: str
    source: str = "NAVER_FINANCE"
    country: str = "KR"
    exchange: str = "KRX"
    currency: str = "KRW"


def _text(node) -> str:
    return " ".join(node.get_text(" ", strip=True).split())


def _decode_response(response) -> str:
    raw = response.content
    declared = str(response.encoding or "").strip()
    candidates = []
    if declared and declared.lower() not in {"iso-8859-1", "latin-1"}:
        candidates.append(declared)
    candidates.extend(["euc-kr", "cp949", "utf-8"])
    seen = set()
    for encoding in candidates:
        key = encoding.lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def _industry_links_from_html(html: str) -> dict[str, str]:
    """Parse NAVER industry links without depending on query-parameter order."""
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        absolute = urljoin(BASE, a.get("href", ""))
        parsed = urlparse(absolute)
        if not parsed.path.endswith("sise_group_detail.naver"):
            continue
        qs = parse_qs(parsed.query)
        if "upjong" not in [str(v).lower() for v in qs.get("type", [])]:
            continue
        name = _text(a)
        if name:
            out[name] = absolute
    return out


def _fallback_industry_links() -> dict[str, str]:
    return {
        name: f"{BASE}/sise/sise_group_detail.naver?no={no}&type=upjong"
        for name, no in FALLBACK_INDUSTRY_NOS.items()
    }


@lru_cache(maxsize=1)
def list_industries() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        response = get(GROUP_URL, timeout=15, retries=4)
        out.update(_industry_links_from_html(_decode_response(response)))
    except Exception as exc:
        print(f"NAVER industry list request unavailable; using configured fallbacks: {exc}")

    # Always supply known research industries even if NAVER changes the list page
    # markup, parameter order, or returns an anti-bot/simplified response.
    for name, href in _fallback_industry_links().items():
        out.setdefault(name, href)

    if not out:
        raise RuntimeError("NAVER industry list parsing returned zero industries")
    return out


def _stocks_from_html(html: str, industry_name: str) -> list[dict]:
    """Parse stock links without depending on query-parameter order."""
    soup = BeautifulSoup(html, "lxml")
    rows = []
    seen = set()
    for a in soup.find_all("a", href=True):
        absolute = urljoin(BASE, a.get("href", ""))
        parsed = urlparse(absolute)
        if not parsed.path.endswith("/item/main.naver"):
            continue
        qs = parse_qs(parsed.query)
        ticker = (qs.get("code") or [""])[0]
        name = _text(a)
        if re.fullmatch(r"\d{6}", ticker) and name and ticker not in seen:
            seen.add(ticker)
            rows.append(asdict(NaverStock(name, ticker, industry_name)))
    return rows


def fetch_industry(industry_name: str) -> list[dict]:
    industries = list_industries()
    if industry_name not in industries:
        choices = ", ".join(sorted(industries)[:30])
        raise KeyError(f"NAVER industry not found: {industry_name}. Examples: {choices}")

    response = get(industries[industry_name], timeout=15, retries=4)
    rows = _stocks_from_html(_decode_response(response), industry_name)
    if not rows:
        raise RuntimeError(f"NAVER industry parsing returned zero stocks: {industry_name}")
    return rows
