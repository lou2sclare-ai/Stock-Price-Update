from __future__ import annotations
from collections import Counter
from datetime import date


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
        pct = r.get("price_change_pct")
        if pct is not None and abs(pct) >= max_move:
            warnings.append(f"Large daily move {pct:.1f}%: {ident}")
        if r.get("research_status") == "COVERAGE" and not r.get("target_price"):
            warnings.append(f"Coverage without TP: {ident}")
        if r.get("research_status") == "NR" and r.get("target_price"):
            errors.append(f"NR has TP: {ident}")
        if r.get("target_price") and r.get("target_currency") and r.get("currency") and r.get("target_currency") != r.get("currency"):
            errors.append(f"TP currency mismatch: {ident}")

    return {
        "status": "FAIL" if errors else ("REVIEW" if warnings else "PASS"),
        "errors": errors,
        "warnings": warnings,
        "row_count": len(rows),
        "domestic_count": domestic_count,
        "missing_price_count": missing_prices,
        "checked_on": date.today().isoformat(),
    }
