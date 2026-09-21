from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo
import exchange_calendars as xcals


UTC = timezone.utc
KST = ZoneInfo("Asia/Seoul")
FINALIZATION_GRACE = timedelta(minutes=20)
SAME_DAY_COMPLETED_SESSIONS = {
    "out_of_session", "post_market", "night", "historical_fallback"
}


@dataclass(frozen=True)
class MarketClock:
    timezone_name: str
    regular_close: time


def _clock(timezone_name: str, hour: int, minute: int = 0) -> MarketClock:
    return MarketClock(timezone_name, time(hour, minute))


# This monitor deliberately uses a conservative regular-session close.  The
# mapping is only needed to accept a bar on the same local calendar date; an
# unmapped exchange is still safe on the next KST day.  ZoneInfo handles DST.
EXCHANGE_CLOCKS = {
    # Korea / Asia-Pacific
    "KRX": _clock("Asia/Seoul", 15, 30),
    "KOSDAQ": _clock("Asia/Seoul", 15, 30),
    "TSE": _clock("Asia/Tokyo", 15, 30),
    "JPX": _clock("Asia/Tokyo", 15, 30),
    "NAG": _clock("Asia/Tokyo", 15, 30),
    "HKEX": _clock("Asia/Hong_Kong", 16, 0),
    "SSE": _clock("Asia/Shanghai", 15, 0),
    "SZSE": _clock("Asia/Shanghai", 15, 0),
    "TWSE": _clock("Asia/Taipei", 13, 30),
    "TPEX": _clock("Asia/Taipei", 13, 30),
    "SGX": _clock("Asia/Singapore", 17, 0),
    "NSE": _clock("Asia/Kolkata", 15, 30),
    "BSE": _clock("Asia/Kolkata", 15, 30),
    "SET": _clock("Asia/Bangkok", 16, 30),
    "IDX": _clock("Asia/Jakarta", 16, 0),
    "MYX": _clock("Asia/Kuala_Lumpur", 17, 0),
    "HOSE": _clock("Asia/Ho_Chi_Minh", 15, 0),
    "HNX": _clock("Asia/Ho_Chi_Minh", 15, 0),
    "UPCOM": _clock("Asia/Ho_Chi_Minh", 15, 0),
    "PSE": _clock("Asia/Manila", 15, 0),
    "PSX": _clock("Asia/Karachi", 15, 30),
    "DSEBD": _clock("Asia/Dhaka", 14, 30),
    "CSELK": _clock("Asia/Colombo", 14, 30),
    "ASX": _clock("Australia/Sydney", 16, 0),
    "NZX": _clock("Pacific/Auckland", 16, 45),
    # Middle East / Africa
    "ADX": _clock("Asia/Dubai", 15, 0),
    "DFM": _clock("Asia/Dubai", 15, 0),
    "TADAWUL": _clock("Asia/Riyadh", 15, 0),
    "KSE": _clock("Asia/Kuwait", 13, 0),
    "TASE": _clock("Asia/Jerusalem", 17, 25),
    "EGX": _clock("Africa/Cairo", 14, 30),
    "JSE": _clock("Africa/Johannesburg", 17, 0),
    "NSEKE": _clock("Africa/Nairobi", 15, 0),
    "NSENG": _clock("Africa/Lagos", 14, 30),
    "CSEMA": _clock("Africa/Casablanca", 15, 30),
    "BVMT": _clock("Africa/Tunis", 14, 10),
    # Europe
    "LSE": _clock("Europe/London", 16, 30),
    "AQUIS": _clock("Europe/London", 16, 30),
    "XETR": _clock("Europe/Berlin", 17, 30),
    "FWB": _clock("Europe/Berlin", 17, 30),
    "EURONEXT": _clock("Europe/Paris", 17, 30),
    "EPA": _clock("Europe/Paris", 17, 30),
    "MIL": _clock("Europe/Rome", 17, 30),
    "BME": _clock("Europe/Madrid", 17, 30),
    "SIX": _clock("Europe/Zurich", 17, 30),
    "BX": _clock("Europe/Zurich", 17, 30),
    "OMXSTO": _clock("Europe/Stockholm", 17, 30),
    "STO": _clock("Europe/Stockholm", 17, 30),
    "NGM": _clock("Europe/Stockholm", 17, 30),
    "OMXCOP": _clock("Europe/Copenhagen", 17, 0),
    "OMXHEX": _clock("Europe/Helsinki", 18, 30),
    "OMXTSE": _clock("Europe/Tallinn", 16, 0),
    "OSL": _clock("Europe/Oslo", 16, 20),
    "GPW": _clock("Europe/Warsaw", 17, 0),
    "NEWCONNECT": _clock("Europe/Warsaw", 17, 0),
    "VIE": _clock("Europe/Vienna", 17, 30),
    "ATHEX": _clock("Europe/Athens", 17, 20),
    "BIST": _clock("Europe/Istanbul", 18, 10),
    "BVB": _clock("Europe/Bucharest", 17, 45),
    "BSESOF": _clock("Europe/Sofia", 17, 10),
    "PSECZ": _clock("Europe/Prague", 16, 20),
    "BET": _clock("Europe/Budapest", 17, 0),
    "ZSE": _clock("Europe/Zagreb", 16, 0),
    "RUS": _clock("Europe/Moscow", 19, 0),
    # Americas
    "NASDAQ": _clock("America/New_York", 16, 0),
    "NYSE": _clock("America/New_York", 16, 0),
    "AMEX": _clock("America/New_York", 16, 0),
    "NYSEARCA": _clock("America/New_York", 16, 0),
    "NYSEMKT": _clock("America/New_York", 16, 0),
    "CBOE": _clock("America/New_York", 16, 0),
    "BATS": _clock("America/New_York", 16, 0),
    "TSX": _clock("America/Toronto", 16, 0),
    "TSXV": _clock("America/Toronto", 16, 0),
    "CSE": _clock("America/Toronto", 16, 0),
    "NEO": _clock("America/Toronto", 16, 0),
    "BMFBOVESPA": _clock("America/Sao_Paulo", 17, 0),
    "BCBA": _clock("America/Argentina/Buenos_Aires", 17, 0),
}


# TradingView exchange codes to exchange_calendars identifiers.  Calendar
# validation takes priority over the fallback clocks above because it includes
# holidays, shortened sessions and daylight-saving changes.
EXCHANGE_CALENDARS = {
    "KRX": "XKRX",
    "KOSDAQ": "XKRX",
    "TSE": "JPX",
    "JPX": "JPX",
    "NAG": "JPX",
    "HKEX": "XHKG",
    "SSE": "XSHG",
    "SZSE": "XSHG",
    "TWSE": "XTAI",
    "TPEX": "XTAI",
    "SGX": "XSES",
    "NSE": "XBOM",
    "BSE": "XBOM",
    "SET": "XBKK",
    "IDX": "XIDX",
    "MYX": "XKLS",
    "PSE": "XPHS",
    "ASX": "XASX",
    "NZX": "XNZE",
    "TADAWUL": "XSAU",
    "TASE": "XTAE",
    "JSE": "XJSE",
    "LSE": "XLON",
    "AQUIS": "XLON",
    "XETR": "XETR",
    "FWB": "XFRA",
    "EURONEXT": "XPAR",
    "EPA": "XPAR",
    "MIL": "XMIL",
    "BME": "XMAD",
    "SIX": "XSWX",
    "BX": "XSWX",
    "OMXSTO": "XSTO",
    "STO": "XSTO",
    "NGM": "XSTO",
    "OMXHEX": "XHEL",
    "OMXTSE": "XEEE",
    "OSL": "XOSL",
    "GPW": "XWAR",
    "NEWCONNECT": "XWAR",
    "VIE": "XWBO",
    "ATHEX": "ASEX",
    "BIST": "XIST",
    "BVB": "BVB",
    "PSECZ": "XPRA",
    "BET": "XBUD",
    # RUS is intentionally left on the fallback clock. Moscow weekend trading
    # expanded after the bundled XMOS calendar rules and valid Sunday bars can
    # otherwise be rejected as non-sessions.
    "NASDAQ": "XNAS",
    "NYSE": "XNYS",
    "AMEX": "XASE",
    "NYSEARCA": "ARCX",
    "NYSEMKT": "XASE",
    "CBOE": "BATS",
    "BATS": "BATS",
    "TSX": "XTSX",
    "TSXV": "XTSX",
    "CSE": "XCSE",
    "NEO": "XTSX",
    "BMFBOVESPA": "BVMF",
    "BCBA": "XBUE",
}


@lru_cache(maxsize=None)
def _calendar(name: str):
    return xcals.get_calendar(name)


@lru_cache(maxsize=1024)
def _calendar_close(exchange: str, session_date: date) -> tuple[bool, datetime | None]:
    """Return (calendar usable, close UTC); close None means a non-session."""
    name = EXCHANGE_CALENDARS.get(exchange)
    if not name:
        return False, None
    try:
        calendar = _calendar(name)
        session = session_date.isoformat()
        if not calendar.is_session(session):
            return True, None
        close = calendar.session_close(session).to_pydatetime()
        if close.tzinfo is None:
            close = close.replace(tzinfo=UTC)
        return True, close.astimezone(UTC)
    except Exception:
        # A few bundled calendars have a shorter supported date range. Falling
        # back is safer than making the whole daily update fail.
        return False, None


def _parse_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _aware_utc(now: datetime | None) -> datetime:
    value = now or datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _close_boundary(clock: MarketClock, local_day: date) -> datetime:
    tz = ZoneInfo(clock.timezone_name)
    return datetime.combine(local_day, clock.regular_close, tzinfo=tz) + FINALIZATION_GRACE


def completed_snapshot_decision(
    snapshot: dict | None,
    *,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Conservatively decide whether a TradingView daily bar is completed."""
    if not snapshot:
        return False, "snapshot_missing"
    trade_date = _parse_date(snapshot.get("price_date"))
    if trade_date is None:
        return False, "trade_date_missing_or_invalid"
    try:
        if float(snapshot.get("price") or 0) <= 0:
            return False, "price_missing_or_invalid"
    except (TypeError, ValueError):
        return False, "price_missing_or_invalid"

    current_utc = _aware_utc(now)
    exchange = str(
        snapshot.get("snapshot_exchange") or snapshot.get("exchange") or ""
    ).strip().upper()
    clock = EXCHANGE_CLOCKS.get(exchange)

    calendar_usable, calendar_close = _calendar_close(exchange, trade_date)
    if calendar_usable:
        if calendar_close is None:
            return False, "non_session_market_date"
        if current_utc < calendar_close + FINALIZATION_GRACE:
            return False, "official_session_not_closed"
        if clock is not None:
            local_now = current_utc.astimezone(ZoneInfo(clock.timezone_name))
            if trade_date < local_now.date():
                return True, "official_prior_session_closed"
        session = str(snapshot.get("market_session") or "").strip().lower()
        if session not in SAME_DAY_COMPLETED_SESSIONS:
            return False, f"session_not_completed:{session or 'unknown'}"
        return True, "official_session_closed"

    if clock is None:
        # Unknown markets never publish a same-KST-day bar.  They become safe on
        # the next KST day, which is slower but cannot leak a live daily bar.
        kst_today = current_utc.astimezone(KST).date()
        if trade_date < kst_today:
            return True, "prior_kst_date_unmapped_exchange"
        return False, "unmapped_exchange_same_or_future_kst_date"

    local_now = current_utc.astimezone(ZoneInfo(clock.timezone_name))
    if trade_date < local_now.date():
        return True, "prior_local_market_date"
    if trade_date > local_now.date():
        return False, "future_local_market_date"

    session = str(snapshot.get("market_session") or "").strip().lower()
    if session not in SAME_DAY_COMPLETED_SESSIONS:
        return False, f"same_day_session_not_completed:{session or 'unknown'}"
    if local_now < _close_boundary(clock, trade_date):
        return False, "same_day_before_regular_close"
    return True, "same_day_after_close"


def historical_exclusive_cutoff(
    row: dict,
    *,
    now: datetime | None = None,
) -> str:
    """Return the first local date that a historical fallback must exclude."""
    current_utc = _aware_utc(now)
    exchange = str(row.get("exchange") or "").strip().upper()
    clock = EXCHANGE_CLOCKS.get(exchange)
    if clock is None:
        return current_utc.astimezone(KST).date().isoformat()

    local_now = current_utc.astimezone(ZoneInfo(clock.timezone_name))
    calendar_usable, calendar_close = _calendar_close(exchange, local_now.date())
    if calendar_usable:
        if calendar_close is None or current_utc >= calendar_close + FINALIZATION_GRACE:
            cutoff = local_now.date() + timedelta(days=1)
        else:
            cutoff = local_now.date()
        return cutoff.isoformat()

    cutoff = local_now.date()
    if local_now >= _close_boundary(clock, cutoff):
        cutoff += timedelta(days=1)
    return cutoff.isoformat()


def published_date_violation(
    row: dict,
    *,
    now: datetime | None = None,
) -> str | None:
    """Return a reason when a published completed date is not yet publishable."""
    if not row.get("price_date"):
        return None
    probe = dict(row)
    probe.setdefault("snapshot_exchange", row.get("exchange"))
    probe.setdefault("price", row.get("price"))
    safe, reason = completed_snapshot_decision(probe, now=now)
    return None if safe else reason
