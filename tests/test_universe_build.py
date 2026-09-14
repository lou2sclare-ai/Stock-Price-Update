import unittest

from src.universe.build import merge_with_existing, validate_fresh_universe


def settings():
    return {
        "qa": {
            "minimum_domestic_universe": 1,
            "minimum_total_universe": 2,
        },
        "universe_refresh": {"minimum_retained_ratio": 0.60},
        "research_sectors": {
            "SHIPBUILDING": {"naver_industries": ["조선"]},
        },
        "global_discovery_industries": ["Aerospace & Defense"],
    }


class UniverseBuildTests(unittest.TestCase):
    def test_partial_refresh_is_rejected_before_mass_removal(self):
        existing = {}
        for i in range(10):
            existing[("KR", "KRX", f"{i:06d}")] = {
                "country": "KR",
                "exchange": "KRX",
                "ticker": f"{i:06d}",
                "active": "TRUE",
            }
        existing[("US", "NYSE", "AAA")] = {
            "country": "US",
            "exchange": "NYSE",
            "ticker": "AAA",
            "active": "TRUE",
        }

        fresh = [
            {
                "country": "KR",
                "exchange": "KRX",
                "ticker": "000000",
                "active": "TRUE",
                "source_industry": "조선",
            },
            {
                "country": "US",
                "exchange": "NYSE",
                "ticker": "AAA",
                "active": "TRUE",
                "source_industry": "Aerospace & Defense",
            },
        ]

        with self.assertRaisesRegex(RuntimeError, "domestic count collapsed"):
            validate_fresh_universe(fresh, existing, settings())

    def test_already_removed_row_does_not_accumulate_duplicate_removal_notes(self):
        key = ("US", "NYSE", "OLD")
        existing = {
            key: {
                "country": "US",
                "exchange": "NYSE",
                "ticker": "OLD",
                "company_name": "Old Co",
                "active": "FALSE",
                "source_status": "REMOVED",
                "review_note": "Removed from source universe previously; review before deletion.",
            }
        }

        rows, changes = merge_with_existing([], existing)

        self.assertEqual(changes["removed_count"], 0)
        self.assertEqual(rows[0]["review_note"], existing[key]["review_note"])


if __name__ == "__main__":
    unittest.main()
