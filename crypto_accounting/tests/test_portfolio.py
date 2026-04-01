"""Tests for the Portfolio tracker."""

import unittest
from datetime import datetime
from decimal import Decimal

from ..models.transaction import Transaction, TransactionType
from ..engine.transaction_store import TransactionStore
from ..engine.portfolio import Portfolio


def _store(*txns):
    s = TransactionStore()
    for t in txns:
        s.add(t)
    return s


class TestPortfolio(unittest.TestCase):

    def test_single_buy(self):
        store = _store(
            Transaction(
                type=TransactionType.BUY,
                date=datetime(2023, 1, 1),
                asset="BTC",
                quantity=Decimal("1"),
                price_usd=Decimal("30000"),
                fee_usd=Decimal("100"),
            )
        )
        portfolio = Portfolio.from_store(store)
        holdings = portfolio.holdings()
        self.assertEqual(len(holdings), 1)
        h = holdings[0]
        self.assertEqual(h.asset, "BTC")
        self.assertEqual(h.quantity, Decimal("1"))
        # cost basis includes buy fee
        self.assertEqual(h.total_cost_basis, Decimal("30100"))

    def test_buy_then_sell_reduces_holding(self):
        store = _store(
            Transaction(
                type=TransactionType.BUY,
                date=datetime(2023, 1, 1),
                asset="BTC",
                quantity=Decimal("2"),
                price_usd=Decimal("30000"),
            ),
            Transaction(
                type=TransactionType.SELL,
                date=datetime(2023, 6, 1),
                asset="BTC",
                quantity=Decimal("1"),
                price_usd=Decimal("40000"),
            ),
        )
        portfolio = Portfolio.from_store(store)
        holdings = portfolio.holdings()
        self.assertEqual(len(holdings), 1)
        self.assertEqual(holdings[0].quantity, Decimal("1"))

    def test_full_sell_removes_holding(self):
        store = _store(
            Transaction(
                type=TransactionType.BUY,
                date=datetime(2023, 1, 1),
                asset="BTC",
                quantity=Decimal("1"),
                price_usd=Decimal("30000"),
            ),
            Transaction(
                type=TransactionType.SELL,
                date=datetime(2023, 6, 1),
                asset="BTC",
                quantity=Decimal("1"),
                price_usd=Decimal("40000"),
            ),
        )
        portfolio = Portfolio.from_store(store)
        holdings = portfolio.holdings()
        self.assertEqual(len(holdings), 0)

    def test_multiple_assets(self):
        store = _store(
            Transaction(
                type=TransactionType.BUY,
                date=datetime(2023, 1, 1),
                asset="BTC",
                quantity=Decimal("1"),
                price_usd=Decimal("30000"),
            ),
            Transaction(
                type=TransactionType.BUY,
                date=datetime(2023, 1, 2),
                asset="ETH",
                quantity=Decimal("5"),
                price_usd=Decimal("2000"),
            ),
        )
        portfolio = Portfolio.from_store(store)
        assets = {h.asset for h in portfolio.holdings()}
        self.assertIn("BTC", assets)
        self.assertIn("ETH", assets)

    def test_unrealised_pnl_with_prices(self):
        store = _store(
            Transaction(
                type=TransactionType.BUY,
                date=datetime(2023, 1, 1),
                asset="BTC",
                quantity=Decimal("1"),
                price_usd=Decimal("30000"),
            ),
        )
        portfolio = Portfolio.from_store(store)
        holdings = portfolio.holdings(prices={"BTC": Decimal("60000")})
        h = holdings[0]
        self.assertEqual(h.market_value_usd, Decimal("60000"))
        self.assertEqual(h.unrealised_pnl_usd, Decimal("30000"))

    def test_average_cost_multiple_lots(self):
        store = _store(
            Transaction(
                type=TransactionType.BUY,
                date=datetime(2023, 1, 1),
                asset="ETH",
                quantity=Decimal("2"),
                price_usd=Decimal("1000"),
            ),
            Transaction(
                type=TransactionType.BUY,
                date=datetime(2023, 6, 1),
                asset="ETH",
                quantity=Decimal("2"),
                price_usd=Decimal("2000"),
            ),
        )
        portfolio = Portfolio.from_store(store)
        h = portfolio.holding("ETH")
        self.assertIsNotNone(h)
        self.assertEqual(h.quantity, Decimal("4"))
        self.assertEqual(h.total_cost_basis, Decimal("6000"))
        self.assertEqual(h.average_cost_usd, Decimal("1500"))


class TestTransactionStore(unittest.TestCase):

    def test_csv_round_trip(self):
        import tempfile, os
        store = _store(
            Transaction(
                type=TransactionType.BUY,
                date=datetime(2023, 1, 1),
                asset="BTC",
                quantity=Decimal("0.5"),
                price_usd=Decimal("40000"),
                fee_usd=Decimal("20"),
                wallet="Coinbase",
                notes="Test buy",
            )
        )
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            path = f.name
        try:
            store.save_csv(path)
            loaded = TransactionStore.load_csv(path)
            self.assertEqual(len(loaded), 1)
            t = loaded.all()[0]
            self.assertEqual(t.asset, "BTC")
            self.assertEqual(t.quantity, Decimal("0.5"))
            self.assertEqual(t.fee_usd, Decimal("20"))
        finally:
            os.unlink(path)

    def test_by_asset_filter(self):
        store = _store(
            Transaction(
                type=TransactionType.BUY,
                date=datetime(2023, 1, 1),
                asset="BTC",
                quantity=Decimal("1"),
                price_usd=Decimal("30000"),
            ),
            Transaction(
                type=TransactionType.BUY,
                date=datetime(2023, 1, 2),
                asset="ETH",
                quantity=Decimal("2"),
                price_usd=Decimal("2000"),
            ),
        )
        btc_txns = store.by_asset("BTC")
        self.assertEqual(len(btc_txns), 1)
        self.assertEqual(btc_txns[0].asset, "BTC")

    def test_summary(self):
        store = _store(
            Transaction(
                type=TransactionType.BUY,
                date=datetime(2023, 1, 1),
                asset="BTC",
                quantity=Decimal("1"),
                price_usd=Decimal("30000"),
            ),
            Transaction(
                type=TransactionType.SELL,
                date=datetime(2023, 6, 1),
                asset="BTC",
                quantity=Decimal("0.5"),
                price_usd=Decimal("40000"),
            ),
        )
        s = store.summary()
        self.assertEqual(s["total_transactions"], 2)
        self.assertIn("BTC", s["assets"])
        self.assertEqual(s["by_type"].get("buy"), 1)
        self.assertEqual(s["by_type"].get("sell"), 1)


if __name__ == "__main__":
    unittest.main()
