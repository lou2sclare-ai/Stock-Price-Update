from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

KST = ZoneInfo("Asia/Seoul")


def _key(row: dict) -> tuple[str, str, str]:
    return (
        str(row.get("country") or "").strip().upper(),
        str(row.get("exchange") or "").strip().upper(),
        str(row.get("ticker") or "").strip().upper(),
    )


def active_inactive_overrides(settings: dict, today: str | None = None) -> dict[tuple[str, str, str], dict]:
    today = today or datetime.now(KST).date().isoformat()
    out = {}
    for item in settings.get("inactive_listings", []) or []:
        effective = str(item.get("effective_date") or "").strip()
        if not effective or effective > today:
            continue
        key = _key(item)
        if all(key):
            out[key] = item
    return out


def apply_inactive_listings(
    universe_path: str,
    settings: dict,
    *,
    today: str | None = None,
) -> int:
    p = Path(universe_path)
    if not p.exists():
        return 0

    with p.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    overrides = active_inactive_overrides(settings, today=today)
    changed = 0
    for row in rows:
        item = overrides.get(_key(row))
        if not item:
            continue
        was_active = str(row.get("active") or "").upper() in {"TRUE", "1", "YES"}
        row["active"] = "FALSE"
        row["source_status"] = "CONFIRMED_INACTIVE"
        reason = str(item.get("reason") or "Confirmed inactive listing").strip()
        effective = str(item.get("effective_date") or "").strip()
        marker = f"Inactive from {effective}: {reason}"
        note = str(row.get("review_note") or "").strip()
        if marker not in note:
            row["review_note"] = f"{note} | {marker}".strip(" |")
        if was_active:
            changed += 1

    if changed or overrides:
        with p.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    return changed


def main():
    settings = yaml.safe_load(Path("config/settings.yml").read_text(encoding="utf-8"))
    universe_path = settings["project"]["universe_csv"]
    changed = apply_inactive_listings(universe_path, settings)
    print(f"Confirmed inactive listings applied: newly deactivated={changed}")


if __name__ == "__main__":
    main()
