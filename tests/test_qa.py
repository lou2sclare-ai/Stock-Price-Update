from src.qa import OFFICIAL_KR_BASE_SOURCE, OFFICIAL_KR_CHANGE_ORIGIN, run


def settings():
    return {
        "qa": {
            "max_abs_daily_change_pct": 40,
            "stale_price_days_warning": 7,
        }
    }


def valid_kr_row():
    return {
        "country": "KR",
        "exchange": "KRX",
        "ticker": "000001",
        "company_name": "A",
        "price": 100.0,
        "previous_close": 99.0,
        "price_change": 1.0,
        "price_change_pct": 1.2,
        "research_status": "UNDEFINED",
        "source_change_origin": OFFICIAL_KR_CHANGE_ORIGIN,
        "comparison_base_source": OFFICIAL_KR_BASE_SOURCE,
    }


def test_pass():
    assert run([valid_kr_row()], settings())["status"] == "PASS"


def test_duplicate_fails():
    row = valid_kr_row()
    assert run([row, row.copy()], settings())["status"] == "FAIL"


def test_exchange_wide_stale_dates_are_detected_even_when_relative_lag_is_zero():
    rows = [
        {
            "country": "Sweden",
            "exchange": "OMXSTO",
            "ticker": ticker,
            "company_name": name,
            "price": 100.0,
            "previous_close": 99.0,
            "price_change": 1.0,
            "price_change_pct": 1.0,
            "price_date": "2000-01-01",
            "market_session": "market",
            "data_status": "PRESERVED_OPEN_OR_UNKNOWN",
            "research_status": "UNDEFINED",
        }
        for ticker, name in [("AAA", "A"), ("BBB", "B")]
    ]

    qa = run(rows, settings())

    # Both rows share the same old date, so the original same-exchange check
    # cannot see any relative lag. The new absolute-age check still catches it.
    assert qa["global_lagging_price_date_count"] == 0
    assert qa["global_absolute_stale_price_date_count"] == 2
    assert qa["global_preserved_absolute_stale_count"] == 2
    assert qa["status"] == "REVIEW"
    assert any("완료거래일 절대 지연 검토" in message for message in qa["warnings"])
