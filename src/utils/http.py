from __future__ import annotations
import time
import requests

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; StockSectorDashboard/1.0; research-use)",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

def get(url: str, *, params=None, timeout: int = 20, retries: int = 3) -> requests.Response:
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=DEFAULT_HEADERS, timeout=timeout)
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET failed after {retries} attempts: {url}: {last}")
