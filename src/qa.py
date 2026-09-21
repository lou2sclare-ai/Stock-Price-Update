from __future__ import annotations
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from src.market_clock import published_date_violation

KST = ZoneInfo("Asia/Seoul")
OFFICIAL_KR_CHANGE_ORIGIN = "NAVER_KRX_MIRROR_DAILY_QUOTE"
OFFICIAL_KR_BASE_SOURCE = "source_exact_absolute_change"


def _completed_kr_cutoff(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local_now = current.astimezone(KST)
    cutoff = local_now.date() if local_now.hour >= 16 else local_now.date() - timedelta(days=1)
    return cutoff.isoformat()


def _parse_date(value):
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _exchange_reference_dates(rows: list[dict]) -> dict[str, date]:
    """Return each exchange's modal date, breaking ties toward the newer date."""
    counts: dict[str, Counter] = {}
    for row in rows:
        exchange = str(row.get("exchange") or "").upper()
        trade_date = _parse_date(row.get("price_date"))
        if exchange and trade_date:
            counts.setdefault(exchange, Counter())[trade_date] += 1
    return {
        exchange: max(date_counts, key=lambda d: (date_counts[d], d))
        for exchange, date_counts in counts.items()
    }


def run(
    rows: list[dict],
    settings: dict,
    *,
    now: datetime | None = None,
) -> dict:
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
    stale_days_warning = int(qa_cfg.get("stale_price_days_warning", 7))
    missing_prices = 0
    corporate_action_adjustments = []
    official_kr_count = 0
    kr_priced_count = 0
    kr_zero_return_count = 0
    kr_future_date_count = 0
    kr_inexact_change_count = 0
    kr_fetch_error_count = 0
    unsafe_open_global_count = 0
    unknown_global_session_count = 0
    no_comparison_reference = []
    awaiting_first_close = []
    invalid_completed_dates = []
    current_utc = now or datetime.now(timezone.utc)
    if current_utc.tzinfo is None:
        current_utc = current_utc.replace(tzinfo=timezone.utc)
    kr_cutoff = _completed_kr_cutoff(current_utc)

    for r in rows:
        ident = f"{r.get('company_name')} ({r.get('ticker')})"
        p = r.get("price")
        if p is None or p <= 0:
            missing_prices += 1
            if str(r.get("data_status") or "") == "AWAITING_FIRST_COMPLETED_CLOSE":
                awaiting_first_close.append({
                    "company_name": r.get("company_name"),
                    "ticker": r.get("ticker"),
                    "exchange": r.get("exchange"),
                    "observed_trade_date": r.get("pending_trade_date"),
                    "market_session": r.get("market_session"),
                })
            else:
                msg = (
                    f"완료 종가 미확보: {ident} — 아직 완료 거래일 시세가 없거나 수집하지 못한 종목입니다. "
                    f"신규상장·첫 거래 전·거래정지 등의 경우 정상일 수 있으며, 해당 종목만 가격을 비워 둡니다."
                )
                if qa_cfg.get("hard_fail_on_missing_price", False):
                    errors.append(msg)
                else:
                    warnings.append(msg)

        country = str(r.get("country") or "").upper()
        if country == "KR" and p is not None and p > 0:
            if str(r.get("data_status") or "") == "PRESERVED_AFTER_FETCH_ERROR":
                kr_fetch_error_count += 1
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
            date_violation = published_date_violation(r, now=current_utc)
            if date_violation:
                invalid_completed_dates.append({
                    "company_name": r.get("company_name"),
                    "ticker": r.get("ticker"),
                    "exchange": r.get("exchange"),
                    "price_date": r.get("price_date"),
                    "market_session": r.get("market_session"),
                    "reason": date_violation,
                })
            session = str(r.get("market_session") or "").strip().lower()
            if not session:
                unknown_global_session_count += 1
            # The exchange-calendar verdict is authoritative. A market can be
            # open now while the row safely publishes an older completed bar.
            if date_violation and p is not None and p > 0:
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
            warnings.append(
                f"급등락 검토 {float(pct):+.1f}%: {ident} — 원천 시세가 제공한 등락률을 그대로 사용한 값입니다. "
                f"계산 오류를 뜻하는 경고가 아니라 큰 변동폭을 한 번 더 확인하기 위한 REVIEW 항목입니다."
            )
        if r.get("research_status") == "COVERAGE" and not r.get("target_price"):
            warnings.append(f"Coverage without TP: {ident} — Coverage 상태이지만 목표주가가 없어 확인이 필요합니다.")
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
    if domestic_count and kr_fetch_error_count >= max(10, int(domestic_count * 0.25)):
        errors.append(
            f"Korean quote source failure concentration: {kr_fetch_error_count}/{domestic_count}; "
            "publication blocked so stale domestic prices are not presented as a fresh update"
        )
    if invalid_completed_dates:
        errors.append(
            "미완료·미래 해외 거래일 발행 차단: "
            f"{len(invalid_completed_dates)}개 종목의 가격 거래일이 해당 거래소 현지 마감 기준으로 "
            f"아직 완료되지 않았습니다. sample={invalid_completed_dates[:5]}"
        )

    # Relative freshness diagnostics. Compare stocks with other stocks on the
    # same exchange so ordinary weekends, holidays and time zones do not create
    # false alarms. This catches individual laggards, but it cannot detect an
    # entire exchange whose rows all stopped refreshing on the same old date.
    exchange_latest = _exchange_reference_dates(global_rows)

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
        if lag_days >= stale_days_warning:
            severe_lagging_global.append(entry)

    if severe_lagging_global:
        sample = severe_lagging_global[:5]
        warnings.append(
            f"거래소 내 거래일 지연 검토: {len(severe_lagging_global)}개 종목이 동일 거래소 최신 거래일보다 "
            f"{stale_days_warning}일 이상 늦습니다. 휴장·거래정지·저유동성 여부를 확인할 REVIEW 항목입니다. "
            f"sample={sample}"
        )

    # Absolute freshness diagnostics. This is deliberately separate from the
    # same-exchange comparison above: if a scheduled morning refresh disappears,
    # every stock on an exchange can remain on the same stale date and relative
    # comparison reports no lag at all. Calendar-day age is only a REVIEW signal,
    # not a hard failure, because long holidays and suspensions are legitimate.
    today = current_utc.astimezone(KST).date()
    absolute_stale_global = []
    preserved_absolute_stale_global = []
    for r in global_rows:
        d = _parse_date(r.get("price_date"))
        if not d:
            continue
        age_days = (today - d).days
        if age_days < stale_days_warning:
            continue
        entry = {
            "company_name": r.get("company_name"),
            "ticker": r.get("ticker"),
            "exchange": str(r.get("exchange") or "").upper(),
            "price_date": d.isoformat(),
            "age_calendar_days": age_days,
            "market_session": r.get("market_session"),
            "data_status": r.get("data_status"),
        }
        absolute_stale_global.append(entry)
        if str(r.get("data_status") or "").startswith("PRESERVED"):
            preserved_absolute_stale_global.append(entry)

    if absolute_stale_global:
        sample = absolute_stale_global[:5]
        warnings.append(
            f"완료거래일 절대 지연 검토: {len(absolute_stale_global)}개 해외 종목의 완료거래일이 오늘보다 "
            f"{stale_days_warning}일 이상 오래되었습니다. 동일 거래소 전체가 함께 멈춘 경우도 잡는 REVIEW 항목입니다. "
            f"이 중 PRESERVED 상태는 {len(preserved_absolute_stale_global)}개입니다. sample={sample}"
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
        "kr_fetch_error_count": kr_fetch_error_count,
        "unsafe_open_global_count": unsafe_open_global_count,
        "invalid_completed_date_count": len(invalid_completed_dates),
        "invalid_completed_dates": invalid_completed_dates[:100],
        "unknown_global_session_count": unknown_global_session_count,
        "missing_price_count": missing_prices,
        "awaiting_first_completed_close_count": len(awaiting_first_close),
        "awaiting_first_completed_close": awaiting_first_close[:100],
        "missing_return_reference_count": len(no_comparison_reference),
        "missing_return_references": no_comparison_reference[:100],
        "global_lagging_price_date_count": len(lagging_global),
        "global_lagging_price_dates": lagging_global[:100],
        "global_severe_lagging_price_date_count": len(severe_lagging_global),
        "global_absolute_stale_price_date_count": len(absolute_stale_global),
        "global_absolute_stale_price_dates": absolute_stale_global[:100],
        "global_preserved_absolute_stale_count": len(preserved_absolute_stale_global),
        "corporate_action_adjustment_count": len(corporate_action_adjustments),
        "corporate_action_adjustments": corporate_action_adjustments[:100],
        "checked_on": today.isoformat(),
    }
