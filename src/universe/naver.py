from __future__ import annotations
import re
from dataclasses import dataclass, asdict
from urllib.parse import urljoin, urlparse, parse_qs
from bs4 import BeautifulSoup
from src.utils.http import get

BASE = "https://finance.naver.com"
GROUP_URL = f"{BASE}/sise/sise_group.naver?type=upjong"

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


def list_industries() -> dict[str, str]:
    html = get(GROUP_URL).content.decode("euc-kr", errors="replace")
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, str] = {}
    for a in soup.select('a[href*="sise_group_detail.naver?type=upjong"]'):
        name = _text(a)
        href = urljoin(BASE, a.get("href", ""))
        if name and href:
            out[name] = href
    if not out:
        raise RuntimeError("NAVER industry list parsing returned zero industries")
    return out


def fetch_industry(industry_name: str) -> list[dict]:
    industries = list_industries()
    if industry_name not in industries:
        choices = ", ".join(sorted(industries)[:30])
        raise KeyError(f"NAVER industry not found: {industry_name}. Examples: {choices}")
    html = get(industries[industry_name]).content.decode("euc-kr", errors="replace")
    soup = BeautifulSoup(html, "lxml")
    rows = []
    seen = set()
    for a in soup.select('a[href*="/item/main.naver?code="]'):
        href = a.get("href", "")
        qs = parse_qs(urlparse(href).query)
        ticker = (qs.get("code") or [""])[0]
        name = _text(a)
        if re.fullmatch(r"\d{6}", ticker) and name and ticker not in seen:
            seen.add(ticker)
            rows.append(asdict(NaverStock(name, ticker, industry_name)))
    if not rows:
        raise RuntimeError(f"NAVER industry parsing returned zero stocks: {industry_name}")
    return rows
