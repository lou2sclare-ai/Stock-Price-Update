from __future__ import annotations
import csv
import json
import os
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
    "volume", "price_source", "price_observed_at",
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


def main():
    settings = yaml.safe_load(Path("config/settings.yml").read_text(encoding="utf-8"))
    upath = settings["project"]["universe_csv"]
    if not Path(upath).exists():
        raise SystemExit(f"Universe missing: {upath}. Run: python -m src.universe.build")

    scope = os.getenv("UPDATE_SCOPE", "ALL").strip().upper()
    if scope not in {"ALL", "KR_ONLY"}:
        raise SystemExit(f"Unsupported UPDATE_SCOPE={scope}")

    rows = load_rows(upath)
    previous_map = load_previous(settings["project"]["output_json"])

    global_snapshot = {}
    if scope == "ALL":
        # ALL is intended for the 08:15 KST run, when US/Europe are closed and
        # Korea/Japan have not opened yet. At that time the screener snapshot is
        # a completed-session snapshot across the covered markets.
        try:
            global_snapshot = tradingview.fetch_price_snapshot(
                settings.get("global_discovery_industries", [])
            )
        except Exception as exc:
            print(f"Global snapshot unavailable; Yahoo fallback will be used: {exc}")
            global_snapshot = {}

    enriched, fetch_errors = [], []
    for source_row in rows:
        if str(source_row.get("active", "")).upper() not in ("TRUE", "1", "YES"):
            continue
        row = dict(source_row)
        country = str(row.get("country") or "").upper()

        # The afternoon job refreshes only Korea after KRX close. Overseas rows
        # retain the safe morning snapshot instead of being overwritten with
        # intraday European/US prices.
        if scope == "KR_ONLY" and country != "KR":
            if not copy_previous_price(row, previous_map.get(row_key(row))):
                fetch_errors.append(
                    f"{row.get('company_name')} ({row.get('ticker')}): "
                    "No previous safe global price to preserve"
                )
            enriched.append(row)
            continue

        try:
            row.update(fetch_price(row, global_snapshot=global_snapshot))
            tp = row.get("target_price")
            if tp not in (None, ""):
                try:
                    row["target_price"] = float(str(tp).replace(",", ""))
                except ValueError:
                    pass
        except Exception as exc:
            # If a source temporarily fails, preserve the previously published
            # price rather than replacing a good value with a blank.
            if not copy_previous_price(row, previous_map.get(row_key(row))):
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
            fetch_errors.append(f"{row.get('company_name')} ({row.get('ticker')}): {exc}")
        enriched.append(row)

    qa = run_qa(enriched, settings)
    qa["fetch_error_count"] = len(fetch_errors)
    qa["fetch_errors"] = fetch_errors[:200]
    qa["global_snapshot_count"] = len(global_snapshot)
    qa["update_scope"] = scope

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
