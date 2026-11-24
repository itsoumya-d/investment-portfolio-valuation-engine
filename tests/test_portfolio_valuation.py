import unittest
from src.portfolio_valuation import (
    BreakType,
    MarketQuote,
    PortfolioValuationEngine,
    TradeType,
    Transaction,
)


class TestPortfolioValuationEngine(unittest.TestCase):
    def setUp(self):
        self.engine = PortfolioValuationEngine(base_currency="GBP")
        self.fx_rates = {
            "USD/GBP": 0.80,
            "GBP/USD": 1.25,
            "EUR/GBP": 0.85,
            "GBP/EUR": 1.17647,
        }

    def test_buy_transactions_aggregate_cost_basis(self):
        # 100 shares @ $150
        tx1 = Transaction("AAPL", "Equity", TradeType.BUY, 100.0, 150.0, "USD")
        # 100 shares @ $170
        tx2 = Transaction("AAPL", "Equity", TradeType.BUY, 100.0, 170.0, "USD")

        self.engine.record_transaction(tx1)
        self.engine.record_transaction(tx2)

        pos = self.engine.positions["AAPL"]
        self.assertEqual(pos.quantity, 200.0)
        self.assertEqual(pos.cost_basis, 32000.0)
        self.assertEqual(pos.unit_cost_basis, 160.0)

    def test_partial_sell_realized_pnl(self):
        # Buy 100 @ 100 GBP
        self.engine.record_transaction(
            Transaction("VOD.L", "Equity", TradeType.BUY, 100.0, 100.0, "GBP")
        )
        # Sell 40 @ 120 GBP -> Realized P&L = 40 * (120 - 100) = 800 GBP
        self.engine.record_transaction(
            Transaction("VOD.L", "Equity", TradeType.SELL, 40.0, 120.0, "GBP")
        )

        pos = self.engine.positions["VOD.L"]
        self.assertEqual(pos.quantity, 60.0)
        self.assertEqual(pos.cost_basis, 6000.0)
        self.assertEqual(pos.unit_cost_basis, 100.0)
        self.assertEqual(self.engine.realized_pnl, 800.0)

    def test_sell_more_than_held_raises_error(self):
        self.engine.record_transaction(
            Transaction("TSLA", "Equity", TradeType.BUY, 10.0, 200.0, "USD")
        )
        with self.assertRaises(ValueError):
            self.engine.record_transaction(
                Transaction("TSLA", "Equity", TradeType.SELL, 15.0, 210.0, "USD")
            )

    def test_multi_currency_valuation(self):
        # BP in GBP: 1000 shares @ 4.50 GBP
        self.engine.record_transaction(
            Transaction("BP.L", "Equity", TradeType.BUY, 1000.0, 4.50, "GBP")
        )
        # MSFT in USD: 50 shares @ 400.00 USD
        self.engine.record_transaction(
            Transaction("MSFT", "Equity", TradeType.BUY, 50.0, 400.00, "USD")
        )

        quotes = {
            "BP.L": MarketQuote("BP.L", 5.00, "GBP"),      # MV = 5000 GBP, cost = 4500 GBP
            "MSFT": MarketQuote("MSFT", 420.00, "USD"),    # MV = 21000 USD * 0.80 = 16800 GBP
        }                                                  # Cost = 20000 USD * 0.80 = 16000 GBP

        summary = self.engine.value_portfolio(quotes, self.fx_rates)

        self.assertEqual(summary.base_currency, "GBP")
        self.assertEqual(summary.total_market_value, 5000.0 + 16800.0)
        self.assertEqual(summary.total_cost_basis, 4500.0 + 16000.0)
        self.assertEqual(summary.total_unrealized_pnl, 500.0 + 800.0)

        msft_item = summary.items["MSFT"]
        self.assertEqual(msft_item.local_market_value, 21000.0)
        self.assertEqual(msft_item.base_market_value, 16800.0)
        self.assertEqual(msft_item.unrealized_pnl_base, 800.0)

    def test_reconciliation_detects_breaks(self):
        # Internal: BP.L (1000), MSFT (50)
        self.engine.record_transaction(
            Transaction("BP.L", "Equity", TradeType.BUY, 1000.0, 5.0, "GBP")
        )
        self.engine.record_transaction(
            Transaction("MSFT", "Equity", TradeType.BUY, 50.0, 400.0, "USD")
        )

        quotes = {
            "BP.L": MarketQuote("BP.L", 5.0, "GBP"),
            "MSFT": MarketQuote("MSFT", 400.0, "USD"),
            "GOOGL": MarketQuote("GOOGL", 180.0, "USD"),
        }

        # Custodian reports:
        # BP.L: 950 (quantity mismatch)
        # MSFT: missing from custodian feed
        # GOOGL: 20 (missing from internal)
        custodian_records = {
            "BP.L": {"quantity": 950.0, "market_value_base": 4750.0},
            "GOOGL": {"quantity": 20.0, "market_value_base": 2880.0},
        }

        breaks = self.engine.reconcile_with_custodian(custodian_records, quotes, self.fx_rates)

        break_types = {b.break_type for b in breaks}
        self.assertIn(BreakType.QUANTITY_MISMATCH, break_types)
        self.assertIn(BreakType.MISSING_CUSTODIAN, break_types)
        self.assertIn(BreakType.MISSING_INTERNAL, break_types)

        bp_break = next(b for b in breaks if b.instrument_id == "BP.L" and b.break_type == BreakType.QUANTITY_MISMATCH)
        self.assertEqual(bp_break.variance, 50.0)

        msft_break = next(b for b in breaks if b.instrument_id == "MSFT")
        self.assertEqual(msft_break.break_type, BreakType.MISSING_CUSTODIAN)

        googl_break = next(b for b in breaks if b.instrument_id == "GOOGL")
        self.assertEqual(googl_break.break_type, BreakType.MISSING_INTERNAL)

    def test_full_liquidation_removes_from_active_positions(self):
        self.engine.record_transaction(
            Transaction("NVDA", "Equity", TradeType.BUY, 10.0, 100.0, "USD")
        )
        self.assertEqual(len(self.engine.positions), 1)

        self.engine.record_transaction(
            Transaction("NVDA", "Equity", TradeType.SELL, 10.0, 150.0, "USD")
        )
        self.assertEqual(len(self.engine.positions), 0)


if __name__ == "__main__":
    unittest.main()
