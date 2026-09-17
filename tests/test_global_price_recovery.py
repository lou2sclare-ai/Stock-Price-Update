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
        self.assertEqual(global_yahoo.yahoo_symbol("42", "HKEX"), "0042.HK")
        self.assertEqual(global_yahoo.yahoo_symbol("301699", "SZSE"), "301699.SZ")
        self.assertEqual(global_yahoo.yahoo_symbol("603448", "SSE"), "603448.SS")
        self.assertEqual(global_yahoo.yahoo_symbol("7934", "TPEX"), "7934.TWO")

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

    def test_empty_previous_row_is_not_preserved(self):
        row = {}
        previous = {"price": None, "price_date": None, "data_status": "FETCH_ERROR"}
        self.assertFalse(stock_main.copy_previous_price(row, previous))

    def test_live_quote_without_completed_session_is_pending(self):
        self.assertTrue(stock_main.awaiting_first_completed_close({
            "price": 10.0,
            "price_date": "2026-09-17",
            "market_session": "market",
        }))
        self.assertFalse(stock_main.awaiting_first_completed_close({
            "price": 10.0,
            "price_date": "2026-09-17",
            "market_session": "post_market",
        }))

    def test_exchange_lagging_snapshot_is_eligible_for_newer_history(self):
        snapshot = {"price_date": "2026-09-04", "market_session": "out_of_session"}
        previous = {"price_date": "2026-09-04"}
        exchange_target = "2026-09-16"

        snap_is_safe = (
            stock_main.safe_global_snapshot_value(snapshot)
            and stock_main._price_date_not_older(snapshot, previous)
        )
        snap_lags_exchange = bool(
            snap_is_safe and snapshot["price_date"] < exchange_target
        )

        self.assertTrue(snap_lags_exchange)
        self.assertTrue(stock_main._price_date_newer(
            {"price_date": "2026-09-15"}, snapshot
        ))

    def test_domestic_batch_collects_results_and_errors(self):
        rows = [
            {"active": "TRUE", "country": "KR", "exchange": "KRX", "ticker": "000001"},
            {"active": "TRUE", "country": "KR", "exchange": "KRX", "ticker": "000002"},
            {"active": "TRUE", "country": "US", "exchange": "NYSE", "ticker": "AAA"},
        ]

        def fake_fetch(row, global_snapshot=None):
            if row["ticker"] == "000002":
                raise RuntimeError("source unavailable")
            return {"price": 100.0, "price_date": "2026-09-16"}

        with patch.object(stock_main, "fetch_price", side_effect=fake_fetch):
            results = stock_main._fetch_domestic_batch(rows, {}, max_workers=2)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[("KR", "KRX", "000001")][0]["price"], 100.0)
        self.assertIsInstance(results[("KR", "KRX", "000002")][1], RuntimeError)


if __name__ == "__main__":
    unittest.main()
