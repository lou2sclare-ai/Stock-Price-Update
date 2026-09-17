from __future__ import annotations
from datetime import date
import yfinance as yf

# Yahoo Finance exchange suffixes used by the global research universe.
# Unknown non-US exchanges must not silently fall back to the raw ticker because
# that can resolve to a completely different security on another market.
EXCHANGE_SUFFIX = {
    "KRX": ".KS",
    "KOSDAQ": ".KQ",
    "TSE": ".T",
    "JPX": ".T",
    "LSE": ".L",
    "XETR": ".DE",
    "FWB": ".F",
    "SIX": ".SW",
    "BX": ".SW",
    "MIL": ".MI",
    "EPA": ".PA",
    "STO": ".ST",
    "OMXSTO": ".ST",
    "OSL": ".OL",
    "OMXHEX": ".HE",
    "NSE": ".NS",
    "BSE": ".BO",
    "TASE": ".TA",
    "TSX": ".TO",
    "TSXV": ".V",
    "ASX": ".AX",
    "HKEX": ".HK",
    "SSE": ".SS",
    "SZSE": ".SZ",
    "TPEX": ".TWO",
    "SET": ".BK",
    "SGX": ".SI",
    "IDX": ".JK",
    "KLSE": ".KL",
}

NO_SUFFIX_EXCHANGES = {
    "NASDAQ", "NYSE", "NYSEARCA", "NYSEMKT", "AMEX", "CBOE", "BATS",
}


def yahoo_symbol(ticker: str, exchange: str | None) -> str:
    ticker = str(ticker or "").strip()
    exchange = str(exchange or "").strip().upper()
    if not ticker:
        raise RuntimeError("Yahoo fallback requires a ticker")
    # Yahoo uses four-digit Hong Kong symbols even when TradingView exposes a
    # shorter numeric ticker (for example HKEX:42 -> 0042.HK).
    if exchange == "HKEX" and ticker.isdigit():
        ticker = ticker.zfill(4)
    if "." in ticker:
        return ticker
    if not exchange or exchange in NO_SUFFIX_EXCHANGES:
        return ticker
    suffix = EXCHANGE_SUFFIX.get(exchange)
    if suffix is None:
        raise RuntimeError(
            f"Yahoo fallback disabled for unmapped exchange {exchange}: "
            "using the raw ticker could resolve to the wrong security"
        )
    return ticker + suffix


def fetch_daily_close(
    ticker: str,
    exchange: str | None = None,
    *,
    before_date: str | date | None = None,
) -> list[dict]:
    symbol = yahoo_symbol(ticker, exchange)
    df = yf.download(
        symbol,
        period="1mo",
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if df is None or df.empty:
        raise RuntimeError(f"No Yahoo daily data: {symbol}")

    cutoff = None
    if before_date:
        cutoff = (
            before_date
            if isinstance(before_date, date)
            else date.fromisoformat(str(before_date))
        )

    # yfinance may return multi-index columns. Normalize Close/Volume.
    close = df["Close"]
    volume = df["Volume"]
    if hasattr(close, "columns"):
        close = close.iloc[:, 0]
        volume = volume.iloc[:, 0]

    out = []
    for idx in df.index:
        d = idx.date()
        if cutoff is not None and d >= cutoff:
            # An ALL run can happen while some overseas market is already open.
            # Historical fallback must never turn the current intraday bar into a
            # completed close, so keep only bars strictly before the KST run date.
            continue
        c = close.loc[idx]
        v = volume.loc[idx]
        if c is None or float(c) != float(c):
            continue
        out.append({
            "date": d.isoformat(),
            "close": float(c),
            "volume": float(v or 0),
        })
    return out[-7:]
