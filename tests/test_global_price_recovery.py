import unittest
from unittest.mock import patch

from src import main as stock_main
from src.prices import global_yahoo
from src.universe import tradingview


class GlobalPriceRecoveryTests(unittest.TestCase):
    def test_targeted_tradingview_symbol_recovers_exact_key(self):
        row = {col: None for col in tradingview.PRICE_COLUMNS}
        row.update({
            "name": "SHR",
            "description": "Schindler Holding Ltd.",
            "exchange": "BX",
            "country": "Switzerland",
            "type": "stock",
            "close": 260.0,
            "change": 1.0,
            "change_abs": 2.5,
            "volume": 1000,
            "current_session": "out_of_session",
            "time_business_day": 20260914,
        })
        item = {"s": "BX:SHR", "d": [row.get(col) for col in tradingview.PRICE_COLUMNS]}

        with patch.object(
            tradingview,
            "_symbol_price_rows",
            return_value=([item], tradingview.PRICE_COLUMNS),
        ):
            snapshots = tradingview.fetch_symbol_price_snapshots([("BX", "SHR")])

        self.assertIn(("BX", "SHR"), snapshots)
        self.assertEqual(snapshots[("BX", "SHR")]["price_date"], "2026-09-14")
        self.assertEqual(snapshots[("BX", "SHR")]["market_session"], "out_of_session")
        self.assertTrue(stock_main.safe_global_snapshot_value(snapshots[("BX", "SHR")]))

    def test_yahoo_exchange_symbols_are_explicit(self):
        self.assertEqual(global_yahoo.yahoo_symbol("VISDEM", "NSE"), "VISDEM.NS")
        self.assertEqual(global_yahoo.yahoo_symbol("MHEL", "BSE"), "MHEL.BO")
        self.assertEqual(global_yahoo.yahoo_symbol("AUSA-M", "TASE"), "AUSA-M.TA")
        self.assertEqual(global_yahoo.yahoo_symbol("1909", "TSE"), "1909.T")
        self.assertEqual(global_yahoo.yahoo_symbol("SHR", "BX"), "SHR.SW")

    def test_unknown_exchange_never_queries_ambiguous_raw_ticker(self):
        with self.assertRaises(RuntimeError):
            global_yahoo.yahoo_symbol("ABC", "UNKNOWN_EXCHANGE")

    def test_recovery_requires_newer_date(self):
        old = {"price_date": "2026-09-04"}
        self.assertTrue(stock_main._price_date_newer({"price_date": "2026-09-14"}, old))
        self.assertFalse(stock_main._price_date_newer({"price_date": "2026-09-04"}, old))
        self.assertFalse(stock_main._price_date_newer({"price_date": "2026-09-03"}, old))

    def test_completed_snapshot_never_regresses_date(self):
        old = {"price_date": "2026-09-11"}
        self.assertTrue(stock_main._price_date_not_older({"price_date": "2026-09-11"}, old))
        self.assertTrue(stock_main._price_date_not_older({"price_date": "2026-09-14"}, old))
        self.assertFalse(stock_main._price_date_not_older({"price_date": "2026-09-10"}, old))


if __name__ == "__main__":
    unittest.main()
