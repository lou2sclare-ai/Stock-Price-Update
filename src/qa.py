from __future__ import annotations
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
OFFICIAL_KR_CHANGE_ORIGIN = "NAVER_KRX_MIRROR_DAILY_QUOTE"
OFFICIAL_KR_BASE_SOURCE = "source_exact_absolute_change"


def _completed_kr_cutoff() -> str:
    now = datetime.now(KST)
    cutoff = now.date() if now.hour >= 16 else now.date() - timedelta(days=1)
    return cutoff.isoformat()


def run(rows: list[dict], settings: dict) -> dict:
    errors, warnings = [], []
    qa_cfg = settings.get("qa", {})
    keys = [(r.get("country"), r.get("exchange"), r.get("ticker")) for r in rows]
    dupes = [k for k, n in Counter(keys).items() if n > 1]
    if dupes and qa_cfg.get("hard_fail_on_duplicate_primary_key", True):
        errors.append(f"Duplicate primary keys: {dupes[:10]}")

    domestic = [r for r in rows if str(r.get("country") or "").upper() == "KR"]
    domestic_count = len(domestic)
    if domestic_count < int(qa_cfg.get("minimum_domestic_universe", 1)):
        errors.append(f"Domestic universe unexpectedly small: {domestic_count}")
    if len(rows) < int(qa_cfg.get("minimum_total_universe", 1)):
        errors.append(f"Total universe unexpectedly small: {len(rows)}")

    max_move = float(qa_cfg.get("max_abs_daily_change_pct", 40.0))
    missing_prices = 0
    corporate_action_adjustments = []
    official_kr_count = 0
    kr_zero_return_count = 0
    kr_future_date_count = 0
    kr_inexact_change_count = 0
    unsafe_open_global_count = 0
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
            if session == "regular" and not status.startswith("PRESERVED"):
                unsafe_open_global_count += 1

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

    if official_kr_count != domestic_count:
        errors.append(f"Official Korean daily-return coverage incomplete: {official_kr_count}/{domestic_count}")
    if kr_future_date_count:
        errors.append(f"Korean price date exceeds completed-session cutoff {kr_cutoff}: {kr_future_date_count}/{domestic_count}")
    if domestic_count and kr_zero_return_count / domestic_count >= 0.50:
        errors.append(f"Suspicious Korean zero-return concentration: {kr_zero_return_count}/{domestic_count}")
    if kr_inexact_change_count:
        errors.append(f"Korean exact price-change arithmetic mismatch: {kr_inexact_change_count}/{domestic_count}")
    if unsafe_open_global_count:
        errors.append(f"Open global regular-session prices would be published: {unsafe_open_global_count}")

    return {
        "status": "FAIL" if errors else ("REVIEW" if warnings else "PASS"),
        "errors": errors,
        "warnings": warnings,
        "row_count": len(rows),
        "domestic_count": domestic_count,
        "official_kr_return_count": official_kr_count,
        "kr_completed_cutoff": kr_cutoff,
        "kr_zero_return_count": kr_zero_return_count,
        "kr_future_date_count": kr_future_date_count,
        "kr_inexact_change_count": kr_inexact_change_count,
        "unsafe_open_global_count": unsafe_open_global_count,
        "missing_price_count": missing_prices,
        "corporate_action_adjustment_count": len(corporate_action_adjustments),
        "corporate_action_adjustments": corporate_action_adjustments[:100],
        "checked_on": datetime.now(KST).date().isoformat(),
    }
