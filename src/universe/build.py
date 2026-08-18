from __future__ import annotations
import csv
import json
import re
from datetime import date
from pathlib import Path
import yaml
from src.universe import naver, tradingview

FIELDS = [
    "company_name", "ticker", "country", "exchange", "currency",
    "source", "source_sector", "source_industry", "research_sector",
    "market_cap", "research_status", "target_price", "target_currency",
    "last_report_date", "active", "source_status", "first_seen", "last_seen",
    "review_note",
]

SHIP_WORDS = re.compile(
    r"\b(ship|shipyard|shipbuilding|dockyard|marine|naval|zosen|offshore|fincantieri)\b",
    re.I,
)
CONSTRUCTION_WORDS = re.compile(
    r"\b(caterpillar|komatsu|deere|construction machinery|heavy equipment|excavator|loader|earthmoving)\b",
    re.I,
)
KOREA_CONSTRUCTION_WORDS = re.compile(
    r"(건설기계|건설장비|굴삭기|굴착기|휠로더|로더|두산밥캣|대모|진성티이씨|디와이파워|대창단조|동일금속)",
    re.I,
)
PRESERVE_FIELDS = {
    "research_status", "target_price", "target_currency", "last_report_date",
    "active", "first_seen",
}


def load_settings(path="config/settings.yml"):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def key(row: dict) -> tuple[str, str, str]:
    return (
        str(row.get("country") or "").upper(),
        str(row.get("exchange") or "").upper(),
        str(row.get("ticker") or "").upper(),
    )


def load_existing(path: str) -> dict[tuple[str, str, str], dict]:
    p = Path(path)
    if not p.exists():
        return {}
    with p.open(encoding="utf-8-sig", newline="") as f:
        return {key(r): r for r in csv.DictReader(f)}


def classify_domestic(industry: str, company_name: str) -> tuple[str, str]:
    if industry == "조선":
        return "SHIPBUILDING", ""
    if industry == "우주항공과국방":
        return "DEFENSE", ""
    if industry in ("전기장비", "전기제품"):
        return "POWER_EQUIPMENT", ""
    if industry == "기계":
        if KOREA_CONSTRUCTION_WORDS.search(company_name or ""):
            return "CONSTRUCTION_EQUIPMENT", "Auto-classified from NAVER machinery by company-name keyword; review once."
        return "MACHINERY", "NAVER 기계 업종 기본 분류. 건설장비 여부는 별도 검토 가능."
    return "MACHINERY", "Unmapped NAVER industry; review."


def build_domestic(settings: dict) -> list[dict]:
    by_ticker: dict[str, dict] = {}
    industries = []
    for cfg in settings["research_sectors"].values():
        for industry in cfg.get("naver_industries", []):
            if industry not in industries:
                industries.append(industry)
    for industry in industries:
        for raw in naver.fetch_industry(industry):
            ticker = raw["ticker"]
            sector, note = classify_domestic(industry, raw.get("company_name") or "")
            row = {
                **raw,
                "source_industry": industry,
                "research_sector": sector,
                "market_cap": "",
                "research_status": "UNDEFINED",
                "target_price": "",
                "target_currency": "KRW",
                "last_report_date": "",
                "active": "TRUE",
                "source_status": "PRESENT",
                "review_note": note,
            }
            by_ticker.setdefault(ticker, row)
    return list(by_ticker.values())


def classify_global(row: dict) -> tuple[str, str]:
    industry = (row.get("source_industry") or "").strip()
    name = row.get("company_name") or ""
    if industry == "Aerospace & Defense":
        return "DEFENSE", ""
    if industry == "Electrical Products":
        return "POWER_EQUIPMENT", "Broad industry; power-equipment relevance can be overridden."
    if industry == "Industrial Machinery":
        return "MACHINERY", ""
    if industry == "Trucks/Construction/Farm Machinery":
        if SHIP_WORDS.search(name):
            return "SHIPBUILDING", "Auto-classified by company-name keyword; review once."
        if CONSTRUCTION_WORDS.search(name):
            return "CONSTRUCTION_EQUIPMENT", "Auto-classified by company-name keyword; review once."
        return "MACHINERY", "Broad industry; review for shipbuilding/construction-equipment."
    return "MACHINERY", "Unmapped TradingView industry; review."


def build_global(settings: dict) -> list[dict]:
    raw_rows = tradingview.fetch_industries(settings.get("global_discovery_industries", []))
    out = []
    for raw in raw_rows:
        sector, note = classify_global(raw)
        out.append({
            **raw,
            "research_sector": sector,
            "research_status": "UNDEFINED",
            "target_price": "",
            "target_currency": raw.get("currency") or "",
            "last_report_date": "",
            "active": "TRUE",
            "source_status": "PRESENT",
            "review_note": note,
        })
    return out


def dedupe(rows: list[dict]) -> list[dict]:
    exact: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        k = key(row)
        existing = exact.get(k)
        if existing is None or float(row.get("market_cap") or 0) > float(existing.get("market_cap") or 0):
            exact[k] = row

    domestic = [r for r in exact.values() if str(r.get("country") or "").upper() == "KR"]
    global_rows = [r for r in exact.values() if str(r.get("country") or "").upper() != "KR"]
    by_name: dict[str, dict] = {}
    for row in global_rows:
        nk = re.sub(r"[^a-z0-9]+", "", str(row.get("company_name") or "").lower())
        if not nk:
            nk = "|".join(key(row))
        existing = by_name.get(nk)
        if existing is None or float(row.get("market_cap") or 0) > float(existing.get("market_cap") or 0):
            by_name[nk] = row
    return domestic + list(by_name.values())


def apply_overrides(rows: list[dict], settings: dict) -> list[dict]:
    overrides = settings.get("manual_overrides", {}) or {}
    for row in rows:
        keys = [str(row.get("ticker", "")), f"{row.get('exchange','')}:{row.get('ticker','')}"]
        for candidate in keys:
            if candidate in overrides:
                row.update(overrides[candidate])
    return rows


def merge_with_existing(current: list[dict], existing: dict) -> tuple[list[dict], dict]:
    today = date.today().isoformat()
    current_map = {key(r): r for r in current}
    added, removed = [], []

    for k, row in current_map.items():
        old = existing.get(k)
        if old:
            for field in PRESERVE_FIELDS:
                if old.get(field) not in (None, ""):
                    row[field] = old[field]
            row["first_seen"] = old.get("first_seen") or today
        else:
            row["first_seen"] = today
            added.append({"key": list(k), "company_name": row.get("company_name"), "research_sector": row.get("research_sector")})
        row["last_seen"] = today
        row["source_status"] = "PRESENT"

    for k, old in existing.items():
        if k in current_map:
            continue
        old = dict(old)
        old["active"] = "FALSE"
        old["source_status"] = "REMOVED"
        note = str(old.get("review_note") or "").strip()
        marker = f"Removed from source universe on {today}; review before deletion."
        old["review_note"] = f"{note} | {marker}".strip(" |")
        current_map[k] = old
        removed.append({"key": list(k), "company_name": old.get("company_name"), "research_sector": old.get("research_sector")})

    changes = {
        "as_of": today,
        "added_count": len(added),
        "removed_count": len(removed),
        "added": added,
        "removed": removed,
    }
    return list(current_map.values()), changes


def write_universe(rows: list[dict], path: str):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for row in sorted(
            rows,
            key=lambda x: (
                str(x.get("research_sector") or ""),
                -float(x.get("market_cap") or 0),
                str(x.get("company_name") or ""),
            ),
        ):
            w.writerow({k: row.get(k, "") for k in FIELDS})


def main():
    s = load_settings()
    universe_path = s["project"]["universe_csv"]
    existing = load_existing(universe_path)
    domestic = build_domestic(s)
    global_rows = build_global(s)
    fresh = apply_overrides(dedupe(domestic + global_rows), s)
    rows, changes = merge_with_existing(fresh, existing)
    write_universe(rows, universe_path)
    cp = Path(s["project"]["universe_changes_json"])
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(changes, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Universe: domestic={len(domestic)}, global={len(global_rows)}, "
        f"total={len(rows)}, added={changes['added_count']}, removed={changes['removed_count']}"
    )


if __name__ == "__main__":
    main()
