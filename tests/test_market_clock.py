import unittest
from datetime import datetime, timezone

from src.market_clock import (
    completed_snapshot_decision,
    historical_exclusive_cutoff,
)


UTC = timezone.utc


class MarketClockTests(unittest.TestCase):
    def test_taiwan_out_of_session_label_before_open_is_not_completed(self):
        snapshot = {
            "price": 331.5,
            "price_date": "2026-09-21",
            "market_session": "out_of_session",
            "snapshot_exchange": "TPEX",
        }

        safe, reason = completed_snapshot_decision(
            snapshot,
            now=datetime(2026, 9, 20, 23, 32, tzinfo=UTC),
        )

        self.assertFalse(safe)
        self.assertEqual(reason, "official_session_not_closed")

    def test_taiwan_same_day_bar_is_completed_after_official_close(self):
        snapshot = {
            "price": 331.5,
            "price_date": "2026-09-21",
            "market_session": "out_of_session",
            "snapshot_exchange": "TPEX",
        }

        safe, reason = completed_snapshot_decision(
            snapshot,
            now=datetime(2026, 9, 21, 6, 0, tzinfo=UTC),
        )

        self.assertTrue(safe)
        self.assertEqual(reason, "official_session_closed")

    def test_official_non_session_date_is_rejected(self):
        snapshot = {
            "price": 100.0,
            "price_date": "2026-09-21",
            "market_session": "out_of_session",
            "snapshot_exchange": "TASE",
        }

        safe, reason = completed_snapshot_decision(
            snapshot,
            now=datetime(2026, 9, 21, 20, 0, tzinfo=UTC),
        )

        self.assertFalse(safe)
        self.assertEqual(reason, "non_session_market_date")

    def test_prior_official_session_stays_safe_during_current_market(self):
        snapshot = {
            "price": 100.0,
            "price_date": "2026-09-18",
            "market_session": "market",
            "snapshot_exchange": "TPEX",
        }

        safe, reason = completed_snapshot_decision(
            snapshot,
            now=datetime(2026, 9, 21, 2, 0, tzinfo=UTC),
        )

        self.assertTrue(safe)
        self.assertEqual(reason, "official_prior_session_closed")

    def test_historical_cutoff_changes_only_after_market_close(self):
        row = {"exchange": "TPEX"}
        self.assertEqual(
            historical_exclusive_cutoff(
                row,
                now=datetime(2026, 9, 20, 23, 32, tzinfo=UTC),
            ),
            "2026-09-21",
        )
        self.assertEqual(
            historical_exclusive_cutoff(
                row,
                now=datetime(2026, 9, 21, 6, 0, tzinfo=UTC),
            ),
            "2026-09-22",
        )


if __name__ == "__main__":
    unittest.main()
