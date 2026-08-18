from __future__ import annotations
from collections import Counter
from datetime import date

OFFICIAL_KRX_CHANGE_ORIGIN = "KRX_GET_MARKET_OHLCV_BY_TICKER"


def run(rows: list[dict], settings: dict) -> dict:
    errors, warnings = [], []
    qa_cfg = settings.get("qa", {})
    keys = [(r.get("country"), r.get("exchange"), r.get("ticker")) for r in rows]
    dupes = [k for k, n in Counter(keys).items() if n > 1]
    if dupes and qa_cfg.get("hard_fail_on_duplicate_primary_key", True):
        errors.append(f"Duplicate primary keys: {dupes[:10]}")

    domestic_count = sum(1 for r in rows if str(r.get("country") or "").upper() == "KR")
    if domestic_count < int(qa_cfg.get("minimum_domestic_universe", 1)):
        errors.append(f"Domestic universe unexpectedly small: {domestic_count}")
    if len(rows) < int(qa_cfg.get("minimum_total_universe", 1)):
        errors.append(f"Total universe unexpectedly small: {len(rows)}")

    max_move = float(qa_cfg.get("max_abs_daily_change_pct", 40.0))
    missing_prices = 0
    corporate_action_adjustments = []
    official_kr_count = 0

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

        if str(r.get("country") or "").upper() == "KR" and p is not None and p > 0:
            origin = str(r.get("source_change_origin") or "")
            base_source = str(r.get("comparison_base_source") or "")
            if origin != OFFICIAL_KRX_CHANGE_ORIGIN:
                errors.append(f"KR daily return is not from official KRX cross-sectional quote: {ident}")
            elif base_source != "KRX_official_change_implied_base":
                errors.append(f"KR comparison base is not derived from official KRX daily return: {ident}")
            else:
                official_kr_count += 1

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
        if pct is not None and abs(pct) >= max_move:
            warnings.append(f"Large official daily move {pct:.1f}%: {ident}")
        if r.get("research_status") == "COVERAGE" and not r.get("target_price"):
            warnings.append(f"Coverage without TP: {ident}")
        if r.get("research_status") == "NR" and r.get("target_price"):
            errors.append(f"NR has TP: {ident}")
        if r.get("target_price") and r.get("target_currency") and r.get("currency") and r.get("target_currency") != r.get("currency"):
            errors.append(f"TP currency mismatch: {ident}")

    if official_kr_count != domestic_count:
        errors.append(
            f"Official KRX daily-return coverage incomplete: {official_kr_count}/{domestic_count}"
        )

    return {
        "status": "FAIL" if errors else ("REVIEW" if warnings else "PASS"),
        "errors": errors,
        "warnings": warnings,
        "row_count": len(rows),
        "domestic_count": domestic_count,
        "official_kr_return_count": official_kr_count,
        "missing_price_count": missing_prices,
        "corporate_action_adjustment_count": len(corporate_action_adjustments),
        "corporate_action_adjustments": corporate_action_adjustments[:100],
        "checked_on": date.today().isoformat(),
    }
