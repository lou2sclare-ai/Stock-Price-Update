from __future__ import annotations
import csv
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
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
KST = ZoneInfo("Asia/Seoul")


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
    # A prior output row may exist without ever obtaining a completed close.
    # Copying that empty row would turn a FETCH_ERROR into a misleading
    # PRESERVED state forever, so preserve only an actually publishable value.
    if not previous or not previous.get("price_date") or previous.get("price") is None:
        return False
    try:
        if float(previous.get("price") or 0) <= 0:
            return False
    except (TypeError, ValueError):
        return False
    copied = False
    for field in PRICE_FIELDS:
        if field in previous:
            row[field] = previous.get(field)
            copied = True
    return copied


def safe_global_snapshot_value(snapshot: dict | None) -> bool:
    if not snapshot or not snapshot.get("price_date"):
        return False
    session = str(snapshot.get("market_session") or "").strip().lower()
    return session in CLOSED_GLOBAL_SESSION_STATES


def awaiting_first_completed_close(snapshot: dict | None) -> bool:
    """Return whether a live quote exists but its session is not complete."""
    if not snapshot or not snapshot.get("price_date"):
        return False
    try:
        if float(snapshot.get("price") or 0) <= 0:
            return False
    except (TypeError, ValueError):
        return False
    session = str(snapshot.get("market_session") or "").strip().lower()
    return bool(session and session not in CLOSED_GLOBAL_SESSION_STATES)


def _price_date_not_older(candidate: dict | None, previous: dict | None) -> bool:
    if not candidate or not candidate.get("price_date"):
        return False
    if not previous or not previous.get("price_date"):
        return True
    return str(candidate["price_date"]) >= str(previous["price_date"])


def _price_date_newer(candidate: dict | None, previous: dict | None) -> bool:
    if not candidate or not candidate.get("price_date"):
        return False
    if not previous or not previous.get("price_date"):
        return True
    return str(candidate["price_date"]) > str(previous["price_date"])


def _completed_snapshot_status(row: dict) -> str:
    """Classify a completed overseas quote without inventing a prior reference."""
    if row.get("previous_close") is None or row.get("price_change_pct") is None:
        return "COMPLETED_NO_COMPARISON_REFERENCE"
    return "REFRESHED_COMPLETED_SESSION"


def _priority_map(settings: dict) -> dict[str, dict]:
    out = {}
    for item in settings.get("priority_coverage", []) or []:
        ticker = str(item.get("ticker") or "").strip()
        if not ticker:
            continue
        out[ticker.zfill(6)] = item
    return out


def _apply_priority_metadata(row: dict, priority_map: dict[str, dict]):
    """Attach presentation priority without changing research_status semantics."""
    ticker = str(row.get("ticker") or "").strip().zfill(6)
    item = priority_map.get(ticker) if str(row.get("country") or "").upper() == "KR" else None
    if item:
        row["priority_coverage"] = True
        row["priority_coverage_rank"] = int(item.get("rank") or 999)
        row["priority_coverage_display_name"] = item.get("display_name") or row.get("company_name")
    else:
        row["priority_coverage"] = False
        row["priority_coverage_rank"] = None
        row["priority_coverage_display_name"] = None


def _global_key(row: dict) -> tuple[str, str]:
    return (
        str(row.get("exchange") or "").upper(),
        str(row.get("ticker") or "").upper(),
    )


def _active_global_keys(rows: list[dict]) -> list[tuple[str, str]]:
    out = []
    seen = set()
    for row in rows:
        if str(row.get("active", "")).upper() not in ("TRUE", "1", "YES"):
            continue
        if str(row.get("country") or "").upper() == "KR":
            continue
        key = _global_key(row)
        if not all(key) or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _exchange_completed_latest(snapshot: dict[tuple[str, str], dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for (exchange, _), value in snapshot.items():
        if not safe_global_snapshot_value(value):
            continue
        d = value.get("price_date")
        if d and (exchange not in out or str(d) > out[exchange]):
            out[exchange] = str(d)
    return out


def _fetch_domestic_batch(
    rows: list[dict],
    global_snapshot: dict,
    max_workers: int = 8,
) -> dict[tuple[str, str, str], tuple[dict | None, Exception | None]]:
    """Fetch independent Korean quotes concurrently with bounded fan-out."""
    domestic = [
        row for row in rows
        if str(row.get("active", "")).upper() in ("TRUE", "1", "YES")
        and str(row.get("country") or "").upper() == "KR"
    ]
    results: dict[tuple[str, str, str], tuple[dict | None, Exception | None]] = {}

    def one(row: dict) -> dict:
        return fetch_price(row, global_snapshot=global_snapshot)

    with ThreadPoolExecutor(max_workers=max(1, int(max_workers))) as pool:
        pending = {pool.submit(one, row): row_key(row) for row in domestic}
        for future in as_completed(pending):
            key = pending[future]
            try:
                results[key] = (future.result(), None)
            except Exception as exc:
                results[key] = (None, exc)
    return results


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
    priority_map = _priority_map(settings)
    checked_at = datetime.now(timezone.utc).isoformat()
    completed_before_date = datetime.now(KST).date().isoformat()

    try:
        global_snapshot = tradingview.fetch_price_snapshot(
            settings.get("global_discovery_industries", [])
        )
    except Exception as exc:
        print(f"Global industry snapshot unavailable; targeted/previous fallbacks will be used: {exc}")
        global_snapshot = {}

    # Industry scans occasionally omit illiquid symbols even though their
    # individual TradingView pages still have a valid quote. Recover those keys
    # with a targeted symbol query before falling back to historical providers.
    universe_global_keys = _active_global_keys(rows)
    missing_keys = [key for key in universe_global_keys if key not in global_snapshot]
    targeted_snapshot_count = 0
    targeted_snapshot_error = None
    if missing_keys and len(missing_keys) <= 500:
        try:
            targeted = tradingview.fetch_symbol_price_snapshots(missing_keys)
            targeted_snapshot_count = len(targeted)
            global_snapshot.update(targeted)
        except Exception as exc:
            targeted_snapshot_error = str(exc)
            print(f"Targeted TradingView recovery unavailable: {exc}")
    elif len(missing_keys) > 500:
        targeted_snapshot_error = f"skipped unusually large missing-key set: {len(missing_keys)}"
        print(f"Targeted TradingView recovery skipped for {len(missing_keys)} missing keys.")

    exchange_latest = _exchange_completed_latest(global_snapshot)
    domestic_workers = int(settings.get("price_fetch", {}).get("domestic_workers", 8))
    domestic_results = _fetch_domestic_batch(
        rows,
        global_snapshot,
        max_workers=domestic_workers,
    )

    enriched, fetch_errors = [], []
    refreshed_global = 0
    preserved_global = 0
    historical_recovery_attempted = 0
    historical_recovery_succeeded = 0
    checked_no_new_trade = 0
    awaiting_first_close = []

    for source_row in rows:
        if str(source_row.get("active", "")).upper() not in ("TRUE", "1", "YES"):
            continue
        row = dict(source_row)
        _apply_priority_metadata(row, priority_map)
        country = str(row.get("country") or "").upper()
        previous = previous_map.get(row_key(row))

        if country != "KR":
            key = _global_key(row)
            snap = global_snapshot.get(key)
            exchange_target = exchange_latest.get(key[0])
            snap_is_safe = (
                safe_global_snapshot_value(snap)
                and _price_date_not_older(snap, previous)
            )
            snap_date = str(snap.get("price_date") or "") if snap else ""
            snap_lags_exchange = bool(
                snap_is_safe and exchange_target and snap_date < exchange_target
            )

            if snap_is_safe and not snap_lags_exchange:
                row.update(snap)
                row["last_checked_at"] = checked_at
                row["data_status"] = _completed_snapshot_status(row)
                refreshed_global += 1
            else:
                # The old implementation copied the previous row immediately
                # whenever the broad TradingView scan missed a symbol. That made
                # a one-off omission permanent. If the same exchange has a newer
                # completed date, first try a completed historical quote.
                previous_date = str(previous.get("price_date") or "") if previous else ""
                needs_recovery = (
                    previous is None
                    or snap_lags_exchange
                    or (exchange_target and previous_date and previous_date < exchange_target)
                )
                recovered = None
                recovery_error = None
                if needs_recovery:
                    historical_recovery_attempted += 1
                    try:
                        recovered = fetch_price(
                            row,
                            global_snapshot=None,
                            before_date=completed_before_date,
                        )
                    except Exception as exc:
                        recovery_error = exc

                recovery_baseline = snap if snap_is_safe else previous
                if recovered and _price_date_newer(recovered, recovery_baseline):
                    row.update(recovered)
                    if snap:
                        row["market_session"] = snap.get("market_session")
                        row["price_observed_at"] = snap.get("price_observed_at")
                    row["last_checked_at"] = checked_at
                    row["data_status"] = (
                        "COMPLETED_NO_COMPARISON_REFERENCE"
                        if row.get("previous_close") is None or row.get("price_change_pct") is None
                        else "COMPLETED_HISTORICAL_FALLBACK"
                    )
                    refreshed_global += 1
                    historical_recovery_succeeded += 1
                elif snap_is_safe:
                    # The source was checked successfully, but this security has
                    # no newer completed trade than its exchange peers.  Keep the
                    # real last-traded date instead of fabricating an exchange date.
                    row.update(snap)
                    row["last_checked_at"] = checked_at
                    row["data_status"] = (
                        "CHECKED_NO_NEW_TRADE"
                        if snap_lags_exchange
                        else _completed_snapshot_status(row)
                    )
                    refreshed_global += 1
                    if snap_lags_exchange:
                        checked_no_new_trade += 1
                    if recovery_error is not None:
                        fetch_errors.append(
                            f"{row.get('company_name')} ({row.get('ticker')}) historical recovery: {recovery_error}"
                        )
                elif copy_previous_price(row, previous):
                    if snap:
                        row["market_session"] = snap.get("market_session")
                        row["price_observed_at"] = snap.get("price_observed_at")
                    row["last_checked_at"] = checked_at
                    row["data_status"] = "PRESERVED_OPEN_OR_UNKNOWN"
                    preserved_global += 1
                    if recovery_error is not None:
                        fetch_errors.append(
                            f"{row.get('company_name')} ({row.get('ticker')}) historical recovery: {recovery_error}"
                        )
                else:
                    # No prior safe value exists. Use only a historical close
                    # strictly before the current KST date, never an intraday bar.
                    try:
                        if recovered is None:
                            if recovery_error is not None:
                                raise recovery_error
                            recovered = fetch_price(
                                row,
                                global_snapshot=None,
                                before_date=completed_before_date,
                            )
                        row.update(recovered)
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
                        if awaiting_first_completed_close(snap):
                            # A real live quote exists, but this row entered the
                            # universe before a safely publishable close was
                            # stored. Retry after the exchange closes.
                            row["market_session"] = snap.get("market_session")
                            row["price_observed_at"] = snap.get("price_observed_at")
                            row["pending_trade_date"] = snap.get("price_date")
                            row["data_status"] = "AWAITING_FIRST_COMPLETED_CLOSE"
                            awaiting_first_close.append({
                                "company_name": row.get("company_name"),
                                "ticker": row.get("ticker"),
                                "exchange": row.get("exchange"),
                                "observed_trade_date": snap.get("price_date"),
                                "market_session": snap.get("market_session"),
                                "historical_fallback_error": str(exc),
                            })
                        else:
                            row["data_status"] = "FETCH_ERROR"
                            fetch_errors.append(f"{row.get('company_name')} ({row.get('ticker')}): {exc}")
            enriched.append(row)
            continue

        domestic_result, domestic_error = domestic_results.get(
            row_key(row),
            (None, RuntimeError("Domestic quote task missing")),
        )
        try:
            if domestic_error is not None:
                raise domestic_error
            row.update(domestic_result or {})
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
    qa["global_targeted_snapshot_count"] = targeted_snapshot_count
    qa["global_targeted_snapshot_error"] = targeted_snapshot_error
    qa["global_historical_recovery_attempted_count"] = historical_recovery_attempted
    qa["global_historical_recovery_succeeded_count"] = historical_recovery_succeeded
    qa["global_checked_no_new_trade_count"] = checked_no_new_trade
    qa["global_awaiting_first_completed_close_count"] = len(awaiting_first_close)
    qa["global_awaiting_first_completed_close"] = awaiting_first_close[:100]
    qa["update_scope"] = scope
    qa["refreshed_completed_global_count"] = refreshed_global
    qa["preserved_open_or_unknown_global_count"] = preserved_global
    qa["global_exchange_latest_completed_dates"] = dict(sorted(exchange_latest.items()))

    priority_rows = sorted(
        [r for r in enriched if r.get("priority_coverage")],
        key=lambda r: int(r.get("priority_coverage_rank") or 999),
    )
    expected_priority = sorted(priority_map.values(), key=lambda x: int(x.get("rank") or 999))
    present_tickers = {str(r.get("ticker") or "").zfill(6) for r in priority_rows}
    qa["priority_coverage_expected_count"] = len(expected_priority)
    qa["priority_coverage_present_count"] = len(priority_rows)
    qa["priority_coverage_missing"] = [
        {
            "rank": item.get("rank"),
            "ticker": str(item.get("ticker") or "").zfill(6),
            "display_name": item.get("display_name"),
        }
        for item in expected_priority
        if str(item.get("ticker") or "").zfill(6) not in present_tickers
    ]

    global_rows = [r for r in enriched if str(r.get("country") or "").upper() != "KR"]
    qa["global_price_date_count"] = sum(1 for r in global_rows if r.get("price_date"))
    qa["global_price_date_missing_count"] = len(global_rows) - qa["global_price_date_count"]
    date_counts = {}
    for r in global_rows:
        d = r.get("price_date") or (
            "첫 완료종가 대기"
            if r.get("data_status") == "AWAITING_FIRST_COMPLETED_CLOSE"
            else "UNKNOWN"
        )
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
