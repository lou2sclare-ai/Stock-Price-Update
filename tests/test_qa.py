import unittest

from src.qa import OFFICIAL_KR_BASE_SOURCE, OFFICIAL_KR_CHANGE_ORIGIN, run


def settings():
    return {
        "qa": {
            "max_abs_daily_change_pct": 40,
            "stale_price_days_warning": 7,
            "minimum_domestic_universe": 0,
            "minimum_total_universe": 1,
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


class QaTests(unittest.TestCase):
    def test_pass(self):
        self.assertEqual(run([valid_kr_row()], settings())["status"], "PASS")

    def test_duplicate_fails(self):
        row = valid_kr_row()
        self.assertEqual(run([row, row.copy()], settings())["status"], "FAIL")

    def test_exchange_wide_stale_dates_are_detected_even_when_relative_lag_is_zero(self):
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

        self.assertEqual(qa["global_lagging_price_date_count"], 0)
        self.assertEqual(qa["global_absolute_stale_price_date_count"], 2)
        self.assertEqual(qa["global_preserved_absolute_stale_count"], 2)
        self.assertEqual(qa["status"], "REVIEW")
        self.assertTrue(any("완료거래일 절대 지연 검토" in message for message in qa["warnings"]))


if __name__ == "__main__":
    unittest.main()
