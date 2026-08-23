from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
OFFICIAL_KR_CHANGE_ORIGIN = "NAVER_KRX_MIRROR_DAILY_QUOTE"
OFFICIAL_KR_BASE_SOURCE = "source_exact_absolute_change"
CLOSED_GLOBAL_SESSION_STATES = {
    "out_of_session", "post_market", "pre_market", "holiday", "night"
}


def _completed_kr_cutoff() -> str:
    now = datetime.now(KST)
    cutoff = now.date() if now.hour >= 16 else now.date() - timedelta(days=1)
    return cutoff.isoformat()


def _parse_date(value):
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def run(rows: list[dict], settings: dict) -> dict:
    errors, warnings = [], []
    qa_cfg = settings.get("qa", {})
    keys = [(r.get("country"), r.get("exchange"), r.get("ticker")) for r in rows]
    dupes = [k for k, n in Counter(keys).items() if n > 1]
    if dupes and qa_cfg.get("hard_fail_on_duplicate_primary_key", True):
        errors.append(f"Duplicate primary keys: {dupes[:10]}")

    domestic = [r for r in rows if str(r.get("country") or "").upper() == "KR"]
    global_rows = [r for r in rows if str(r.get("country") or "").upper() != "KR"]
    domestic_count = len(domestic)
    if domestic_count < int(qa_cfg.get("minimum_domestic_universe", 1)):
        errors.append(f"Domestic universe unexpectedly small: {domestic_count}")
    if len(rows) < int(qa_cfg.get("minimum_total_universe", 1)):
        errors.append(f"Total universe unexpectedly small: {len(rows)}")

    max_move = float(qa_cfg.get("max_abs_daily_change_pct", 40.0))
    missing_prices = 0
    corporate_action_adjustments = []
    official_kr_count = 0
    kr_priced_count = 0
    kr_zero_return_count = 0
    kr_future_date_count = 0
    kr_inexact_change_count = 0
    unsafe_open_global_count = 0
    unknown_global_session_count = 0
    no_comparison_reference = []
    kr_cutoff = _completed_kr_cutoff()

    for r in rows:
        ident = f"{r.get('company_name')} ({r.get('ticker')})"
        p = r.get("price")
        if p is None or p <= 0:
            missing_prices += 1
            msg = f"Missing/invalid price: {ident}"
            if qa_cfg.get("hard_fail_on_missing_price", False):
                errors.append(msg)
            else:
                warnings.append(msg)

        country = str(r.get("country") or "").upper()
        if country == "KR" and p is not None and p > 0:
            # Only Korean rows that actually have a publishable completed close
            # are expected to carry the official daily-return provenance fields.
            # A newly listed/security-discovery row can legitimately exist before
            # its first completed session; that case is already handled by the
            # missing-price QA policy above and must not become a contradictory
            # hard failure when hard_fail_on_missing_price is false.
            kr_priced_count += 1
            origin = str(r.get("source_change_origin") or "")
            base_source = str(r.get("comparison_base_source") or "")
            if origin != OFFICIAL_KR_CHANGE_ORIGIN:
                errors.append(f"KR daily return source is invalid: {ident} ({origin})")
            elif base_source != OFFICIAL_KR_BASE_SOURCE:
                errors.append(f"KR comparison base source is invalid: {ident} ({base_source})")
            else:
                official_kr_count += 1

            pct = r.get("price_change_pct")
            if pct is not None and abs(float(pct)) < 1e-12:
                kr_zero_return_count += 1
            price_date = str(r.get("price_date") or "")
            if price_date and price_date > kr_cutoff:
                kr_future_date_count += 1

            prev = r.get("previous_close")
            chg = r.get("price_change")
            if prev is not None and chg is not None:
                if abs((float(p) - float(prev)) - float(chg)) > 1e-6:
                    kr_inexact_change_count += 1
        elif country != "KR":
            session = str(r.get("market_session") or "").strip().lower()
            status = str(r.get("data_status") or "")
            if not session:
                unknown_global_session_count += 1
                if not status.startswith("PRESERVED") and status not in {
                    "COMPLETED_HISTORICAL_FALLBACK", "COMPLETED_NO_COMPARISON_REFERENCE"
                }:
                    unsafe_open_global_count += 1
            elif session not in CLOSED_GLOBAL_SESSION_STATES and not status.startswith("PRESERVED"):
                unsafe_open_global_count += 1

            if p is not None and p > 0 and (
                r.get("previous_close") is None
                or r.get("price_change") is None
                or r.get("price_change_pct") is None
            ):
                no_comparison_reference.append({
                    "company_name": r.get("company_name"),
                    "ticker": r.get("ticker"),
                    "exchange": r.get("exchange"),
                    "price_date": r.get("price_date"),
                    "data_status": r.get("data_status"),
                })

        if r.get("corporate_action_adjusted"):
            corporate_action_adjustments.append({
                "company_name": r.get("company_name"),
                "ticker": r.get("ticker"),
                "raw_previous_close": r.get("raw_previous_close"),
                "official_comparison_base": r.get("previous_close"),
                "raw_close_change_pct": r.get("raw_close_change_pct"),
                "official_change_pct": r.get("price_change_pct"),
            })

        pct = r.get("price_change_pct")
        if pct is not None and abs(float(pct)) >= max_move:
            warnings.append(f"Large daily move {float(pct):.1f}%: {ident}")
        if r.get("research_status") == "COVERAGE" and not r.get("target_price"):
            warnings.append(f"Coverage without TP: {ident}")
        if r.get("research_status") == "NR" and r.get("target_price"):
            errors.append(f"NR has TP: {ident}")
        if r.get("target_price") and r.get("target_currency") and r.get("currency") and r.get("target_currency") != r.get("currency"):
            errors.append(f"TP currency mismatch: {ident}")

    if official_kr_count != kr_priced_count:
        errors.append(f"Official Korean daily-return coverage incomplete: {official_kr_count}/{kr_priced_count} priced Korean securities")
    if kr_future_date_count:
        errors.append(f"Korean price date exceeds completed-session cutoff {kr_cutoff}: {kr_future_date_count}/{domestic_count}")
    if domestic_count and kr_zero_return_count / domestic_count >= 0.50:
        errors.append(f"Suspicious Korean zero-return concentration: {kr_zero_return_count}/{domestic_count}")
    if kr_inexact_change_count:
        errors.append(f"Korean exact price-change arithmetic mismatch: {kr_inexact_change_count}/{domestic_count}")
    if unsafe_open_global_count:
        errors.append(f"Unsafe/unknown global session prices would be published: {unsafe_open_global_count}")

    # Freshness diagnostics. Compare stocks only with other stocks on the same
    # exchange so weekends, national holidays and time zones do not create false
    # alarms. A lag is informational; only a >=7 calendar-day lag is REVIEW.
    exchange_latest = {}
    for r in global_rows:
        ex = str(r.get("exchange") or "").upper()
        d = _parse_date(r.get("price_date"))
        if ex and d and (ex not in exchange_latest or d > exchange_latest[ex]):
            exchange_latest[ex] = d

    lagging_global = []
    severe_lagging_global = []
    for r in global_rows:
        ex = str(r.get("exchange") or "").upper()
        d = _parse_date(r.get("price_date"))
        latest = exchange_latest.get(ex)
        if not d or not latest or d >= latest:
            continue
        lag_days = (latest - d).days
        entry = {
            "company_name": r.get("company_name"),
            "ticker": r.get("ticker"),
            "exchange": ex,
            "price_date": d.isoformat(),
            "exchange_latest_date": latest.isoformat(),
            "lag_calendar_days": lag_days,
            "data_status": r.get("data_status"),
        }
        lagging_global.append(entry)
        if lag_days >= 7 and not str(r.get("data_status") or "").startswith("PRESERVED"):
            severe_lagging_global.append(entry)

    if severe_lagging_global:
        sample = severe_lagging_global[:5]
        warnings.append(
            f"Global price-date freshness review: {len(severe_lagging_global)} securities lag their exchange by >=7 days; sample={sample}"
        )

    kr_dates = [_parse_date(r.get("price_date")) for r in domestic]
    kr_dates = [d for d in kr_dates if d]
    kr_latest = max(kr_dates) if kr_dates else None
    kr_latest_count = sum(1 for d in kr_dates if d == kr_latest) if kr_latest else 0

    return {
        "status": "FAIL" if errors else ("REVIEW" if warnings else "PASS"),
        "errors": errors,
        "warnings": warnings,
        "row_count": len(rows),
        "domestic_count": domestic_count,
        "kr_priced_count": kr_priced_count,
        "official_kr_return_count": official_kr_count,
        "kr_completed_cutoff": kr_cutoff,
        "kr_latest_price_date": kr_latest.isoformat() if kr_latest else None,
        "kr_latest_price_date_count": kr_latest_count,
        "kr_zero_return_count": kr_zero_return_count,
        "kr_future_date_count": kr_future_date_count,
        "kr_inexact_change_count": kr_inexact_change_count,
        "unsafe_open_global_count": unsafe_open_global_count,
        "unknown_global_session_count": unknown_global_session_count,
        "missing_price_count": missing_prices,
        "missing_return_reference_count": len(no_comparison_reference),
        "missing_return_references": no_comparison_reference[:100],
        "global_lagging_price_date_count": len(lagging_global),
        "global_lagging_price_dates": lagging_global[:100],
        "global_severe_lagging_price_date_count": len(severe_lagging_global),
        "corporate_action_adjustment_count": len(corporate_action_adjustments),
        "corporate_action_adjustments": corporate_action_adjustments[:100],
        "checked_on": datetime.now(KST).date().isoformat(),
    }
