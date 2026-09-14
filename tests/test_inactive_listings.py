import csv
import tempfile
import unittest
from pathlib import Path

from src.universe.inactive import active_inactive_overrides, apply_inactive_listings


class InactiveListingTests(unittest.TestCase):
    def settings(self):
        return {
            "inactive_listings": [
                {
                    "country": "Japan",
                    "exchange": "TSE",
                    "ticker": "1909",
                    "effective_date": "2026-09-14",
                    "reason": "JPX delisting effective 2026-09-14",
                }
            ]
        }

    def test_effective_date_controls_override(self):
        self.assertEqual(active_inactive_overrides(self.settings(), today="2026-09-13"), {})
        active = active_inactive_overrides(self.settings(), today="2026-09-14")
        self.assertIn(("JAPAN", "TSE", "1909"), active)

    def test_apply_marks_listing_inactive_without_touching_others(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "universe.csv"
            fieldnames = [
                "company_name", "ticker", "country", "exchange", "active",
                "source_status", "review_note",
            ]
            rows = [
                {
                    "company_name": "Nippon Dry-Chemical",
                    "ticker": "1909",
                    "country": "Japan",
                    "exchange": "TSE",
                    "active": "TRUE",
                    "source_status": "PRESENT",
                    "review_note": "",
                },
                {
                    "company_name": "Other",
                    "ticker": "7265",
                    "country": "Japan",
                    "exchange": "TSE",
                    "active": "TRUE",
                    "source_status": "PRESENT",
                    "review_note": "",
                },
            ]
            with path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            changed = apply_inactive_listings(str(path), self.settings(), today="2026-09-14")
            self.assertEqual(changed, 1)

            with path.open(encoding="utf-8-sig", newline="") as f:
                got = list(csv.DictReader(f))
            self.assertEqual(got[0]["active"], "FALSE")
            self.assertEqual(got[0]["source_status"], "CONFIRMED_INACTIVE")
            self.assertIn("JPX delisting effective 2026-09-14", got[0]["review_note"])
            self.assertEqual(got[1]["active"], "TRUE")


if __name__ == "__main__":
    unittest.main()
