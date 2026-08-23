from __future__ import annotations
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import yaml
from src.prices.service import fetch as fetch_price
from src.qa import run as run_qa
from src.output.excel import build as build_excel
from src.output.json_export import write as write_json
from src.universe import tradingview

PRICE_FIELDS = {
    "price", "previous_close", "price_change", "price_change_pct",
    "price_date", "previous_trading_date", "calendar_days_elapsed",
    "volume", "price_source", "price_observed_at", "last_checked_at",
    "market_session", "data_status", "price_trade_date_source",
    "price_bar_time", "price_bar_update_time",
    "raw_previous_close", "raw_close_change_pct", "corporate_action_adjusted",
    "source_change_origin", "comparison_base_source",
}

CLOSED_GLOBAL_SESSION_STATES = {
    "out_of_session", "post_market", "pre_market", "holiday", "night"
}


def load_rows(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def row_key(row: dict) -> tuple[str, str, str]:
    return (
        str(row.get("country") or "").upper(),
        str(row.get("exchange") or "").upper(),
        str(row.get("ticker") or "").upper(),
    )


def load_previous(path: str) -> dict[tuple[str, str, str], dict]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
        return {row_key(r): r for r in payload.get("rows", [])}
    except Exception:
        return {}


def copy_previous_price(row: dict, previous: dict | None) -> bool:
    if not previous:
        return False
    copied = False
    for field in PRICE_FIELDS:
        if field in previous:
            row[field] = previous.get(field)
            copied = True
    return copied


def safe_global_snapshot_value(snapshot: dict | None) -> bool:
    if not snapshot:
        return False
    session = str(snapshot.get("market_session") or "").strip().lower()
    return session in CLOSED_GLOBAL_SESSION_STATES


def _completed_snapshot_status(row: dict) -> str:
    """Classify a completed overseas quote without inventing a prior reference.

    Newly listed securities can have a valid completed close while TradingView
    does not yet provide a previous-close comparison. In that case the close is
    publishable, but day change fields must remain blank and the UI should say so.
    """
    if row.get("previous_close") is None or row.get("price_change_pct") is None:
        return "COMPLETED_NO_COMPARISON_REFERENCE"
    return "REFRESHED_COMPLETED_SESSION"


def main():
    settings = yaml.safe_load(Path("config/settings.yml").read_text(encoding="utf-8"))
    upath = settings["project"]["universe_csv"]
    if not Path(upath).exists():
        raise SystemExit(f"Universe missing: {upath}. Run: python -m src.universe.build")

    scope = os.getenv("UPDATE_SCOPE", "ALL").strip().upper()
    if scope not in {"ALL", "SAFE_REFRESH"}:
        raise SystemExit(f"Unsupported UPDATE_SCOPE={scope}")

    rows = load_rows(upath)
    previous_map = load_previous(settings["project"]["output_json"])
    checked_at = datetime.now(timezone.utc).isoformat()

    try:
        global_snapshot = tradingview.fetch_price_snapshot(
            settings.get("global_discovery_industries", [])
        )
    except Exception as exc:
        print(f"Global snapshot unavailable; safe previous values will be preserved: {exc}")
        global_snapshot = {}

    enriched, fetch_errors = [], []
    refreshed_global = 0
    preserved_global = 0

    for source_row in rows:
        if str(source_row.get("active", "")).upper() not in ("TRUE", "1", "YES"):
            continue
        row = dict(source_row)
        country = str(row.get("country") or "").upper()
        previous = previous_map.get(row_key(row))

        if country != "KR":
            key = (
                str(row.get("exchange") or "").upper(),
                str(row.get("ticker") or "").upper(),
            )
            snap = global_snapshot.get(key)
            if safe_global_snapshot_value(snap):
                row.update(snap)
                row["last_checked_at"] = checked_at
                row["data_status"] = _completed_snapshot_status(row)
                refreshed_global += 1
            else:
                if copy_previous_price(row, previous):
                    if snap:
                        row["market_session"] = snap.get("market_session")
                        row["price_observed_at"] = snap.get("price_observed_at")
                    row["last_checked_at"] = checked_at
                    row["data_status"] = "PRESERVED_OPEN_OR_UNKNOWN"
                    preserved_global += 1
                else:
                    try:
                        row.update(fetch_price(row, global_snapshot=None))
                        row["last_checked_at"] = checked_at
                        row["data_status"] = (
                            "COMPLETED_NO_COMPARISON_REFERENCE"
                            if row.get("previous_close") is None or row.get("price_change_pct") is None
                            else "COMPLETED_HISTORICAL_FALLBACK"
                        )
                        refreshed_global += 1
                    except Exception as exc:
                        row.update({
                            "price": None,
                            "previous_close": None,
                            "price_change": None,
                            "price_change_pct": None,
                            "price_date": None,
                            "previous_trading_date": None,
                            "calendar_days_elapsed": None,
                            "price_source": None,
                        })
                        row["last_checked_at"] = checked_at
                        row["data_status"] = "FETCH_ERROR"
                        fetch_errors.append(f"{row.get('company_name')} ({row.get('ticker')}): {exc}")
            enriched.append(row)
            continue

        try:
            row.update(fetch_price(row, global_snapshot=global_snapshot))
            row["last_checked_at"] = checked_at
            row["data_status"] = "COMPLETED_DAILY_QUOTE"
            tp = row.get("target_price")
            if tp not in (None, ""):
                try:
                    row["target_price"] = float(str(tp).replace(",", ""))
                except ValueError:
                    pass
        except Exception as exc:
            if not copy_previous_price(row, previous):
                row.update({
                    "price": None,
                    "previous_close": None,
                    "price_change": None,
                    "price_change_pct": None,
                    "price_date": None,
                    "previous_trading_date": None,
                    "calendar_days_elapsed": None,
                    "price_source": None,
                })
            row["last_checked_at"] = checked_at
            row["data_status"] = "PRESERVED_AFTER_FETCH_ERROR" if previous else "FETCH_ERROR"
            fetch_errors.append(f"{row.get('company_name')} ({row.get('ticker')}): {exc}")
        enriched.append(row)

    qa = run_qa(enriched, settings)
    qa["fetch_error_count"] = len(fetch_errors)
    qa["fetch_errors"] = fetch_errors[:200]
    qa["global_snapshot_count"] = len(global_snapshot)
    qa["update_scope"] = scope
    qa["refreshed_completed_global_count"] = refreshed_global
    qa["preserved_open_or_unknown_global_count"] = preserved_global

    global_rows = [r for r in enriched if str(r.get("country") or "").upper() != "KR"]
    qa["global_price_date_count"] = sum(1 for r in global_rows if r.get("price_date"))
    qa["global_price_date_missing_count"] = len(global_rows) - qa["global_price_date_count"]
    date_counts = {}
    for r in global_rows:
        d = r.get("price_date") or "UNKNOWN"
        date_counts[d] = date_counts.get(d, 0) + 1
    qa["global_price_date_distribution"] = dict(sorted(date_counts.items()))

    qpath = Path(settings["project"]["qa_json"])
    qpath.parent.mkdir(parents=True, exist_ok=True)
    qpath.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")

    if qa["status"] == "FAIL" and os.getenv("ALLOW_FAILED_PUBLISH") != "1":
        print(json.dumps(qa, ensure_ascii=False, indent=2))
        raise SystemExit(2)

    write_json(enriched, qa, settings["project"]["output_json"])
    build_excel(enriched, qa, settings["project"]["output_excel"])
    print(json.dumps(qa, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
