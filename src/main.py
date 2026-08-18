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


def load_rows(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main():
    settings = yaml.safe_load(Path("config/settings.yml").read_text(encoding="utf-8"))
    upath = settings["project"]["universe_csv"]
    if not Path(upath).exists():
        raise SystemExit(f"Universe missing: {upath}. Run: python -m src.universe.build")

    rows = load_rows(upath)
    enriched, fetch_errors = [], []
    for source_row in rows:
        if str(source_row.get("active", "")).upper() not in ("TRUE", "1", "YES"):
            continue
        row = dict(source_row)
        try:
            row.update(fetch_price(row))
            tp = row.get("target_price")
            if tp not in (None, ""):
                try:
                    row["target_price"] = float(str(tp).replace(",", ""))
                except ValueError:
                    pass
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
            fetch_errors.append(f"{row.get('company_name')} ({row.get('ticker')}): {exc}")
        enriched.append(row)

    qa = run_qa(enriched, settings)
    # Fetch failures are already represented as missing-price warnings/errors by QA.
    qa["fetch_error_count"] = len(fetch_errors)
    qa["fetch_errors"] = fetch_errors[:200]

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
