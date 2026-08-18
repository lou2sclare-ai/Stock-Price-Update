from __future__ import annotations
import yfinance as yf

EXCHANGE_SUFFIX = {
    "KRX": ".KS", "KOSDAQ": ".KQ", "TSE": ".T", "JPX": ".T",
    "LSE": ".L", "XETR": ".DE", "FWB": ".F", "SIX": ".SW",
    "MIL": ".MI", "EPA": ".PA", "STO": ".ST", "OSL": ".OL",
}

def yahoo_symbol(ticker: str, exchange: str | None) -> str:
    if not exchange or "." in ticker:
        return ticker
    return ticker + EXCHANGE_SUFFIX.get(exchange.upper(), "")


def fetch_daily_close(ticker: str, exchange: str | None = None) -> list[dict]:
    symbol = yahoo_symbol(ticker, exchange)
    df = yf.download(symbol, period="1mo", interval="1d", auto_adjust=False, progress=False, threads=False)
    if df is None or df.empty:
        raise RuntimeError(f"No Yahoo daily data: {symbol}")
    # yfinance may return multi-index columns. Normalize Close/Volume.
    close = df["Close"]
    volume = df["Volume"]
    if hasattr(close, "columns"):
        close = close.iloc[:, 0]
        volume = volume.iloc[:, 0]
    out = []
    for idx in df.tail(7).index:
        c = close.loc[idx]
        v = volume.loc[idx]
        if c is None or float(c) != float(c):
            continue
        out.append({"date": idx.date().isoformat(), "close": float(c), "volume": float(v or 0)})
    return out
