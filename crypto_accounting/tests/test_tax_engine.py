"""Tests for the tax engine (FIFO, LIFO, HIFO)."""

import unittest
from datetime import datetime
from decimal import Decimal

from ..models.transaction import Transaction, TransactionType
from ..engine.transaction_store import TransactionStore
from ..engine.tax_engine import TaxEngine, CostBasisMethod


def _store(*txns):
    store = TransactionStore()
    for t in txns:
        store.add(t)
    return store


def _buy(date, asset, qty, price, fee=None, wallet=None):
    return Transaction(
        type=TransactionType.BUY,
        date=date,
        asset=asset,
        quantity=Decimal(str(qty)),
        price_usd=Decimal(str(price)),
        fee_usd=Decimal(str(fee)) if fee else None,
        wallet=wallet,
    )


def _sell(date, asset, qty, price, fee=None):
    return Transaction(
        type=TransactionType.SELL,
        date=date,
        asset=asset,
        quantity=Decimal(str(qty)),
        price_usd=Decimal(str(price)),
        fee_usd=Decimal(str(fee)) if fee else None,
    )


class TestFIFO(unittest.TestCase):

    def test_simple_gain(self):
        store = _store(
            _buy(datetime(2022, 1, 1), "BTC", "1", "30000"),
            _sell(datetime(2023, 6, 1), "BTC", "1", "50000"),
        )
        engine = TaxEngine(store, CostBasisMethod.FIFO)
        records = engine.compute()
        self.assertEqual(len(records), 1)
        r = records[0]
        self.assertEqual(r.proceeds_usd, Decimal("50000"))
        self.assertEqual(r.cost_basis_usd, Decimal("30000"))
        self.assertEqual(r.gain_loss_usd, Decimal("20000"))
        self.assertTrue(r.is_long_term)

    def test_simple_loss(self):
        store = _store(
            _buy(datetime(2022, 1, 1), "BTC", "1", "50000"),
            _sell(datetime(2022, 6, 1), "BTC", "1", "30000"),
        )
        engine = TaxEngine(store, CostBasisMethod.FIFO)
        records = engine.compute()
        r = records[0]
        self.assertEqual(r.gain_loss_usd, Decimal("-20000"))
        self.assertFalse(r.is_long_term)

    def test_partial_sell(self):
        store = _store(
            _buy(datetime(2022, 1, 1), "BTC", "2", "30000"),
            _sell(datetime(2022, 6, 1), "BTC", "1", "40000"),
        )
        engine = TaxEngine(store, CostBasisMethod.FIFO)
        records = engine.compute()
        r = records[0]
        # Cost basis for 1 BTC from 2 BTC lot costing 60000 total = 30000
        self.assertEqual(r.cost_basis_usd, Decimal("30000"))
        self.assertEqual(r.gain_loss_usd, Decimal("10000"))

    def test_fifo_order_two_lots(self):
        """FIFO should consume the earlier lot first."""
        store = _store(
            _buy(datetime(2022, 1, 1), "ETH", "1", "1000"),  # lot 1: cheap
            _buy(datetime(2022, 6, 1), "ETH", "1", "2000"),  # lot 2: expensive
            _sell(datetime(2023, 1, 1), "ETH", "1", "3000"),
        )
        engine = TaxEngine(store, CostBasisMethod.FIFO)
        records = engine.compute()
        r = records[0]
        # FIFO uses lot 1 first (cost 1000)
        self.assertEqual(r.cost_basis_usd, Decimal("1000"))
        self.assertEqual(r.gain_loss_usd, Decimal("2000"))

    def test_fee_reduces_gain(self):
        store = _store(
            _buy(datetime(2022, 1, 1), "BTC", "1", "30000", fee="100"),
            _sell(datetime(2023, 1, 1), "BTC", "1", "50000", fee="200"),
        )
        engine = TaxEngine(store, CostBasisMethod.FIFO)
        records = engine.compute()
        r = records[0]
        # basis = 30000 + 100 buy fee = 30100; gain = 50000 - 30100 - 200 = 19700
        self.assertEqual(r.cost_basis_usd, Decimal("30100"))
        self.assertEqual(r.gain_loss_usd, Decimal("19700"))

    def test_multiple_disposals(self):
        store = _store(
            _buy(datetime(2022, 1, 1), "BTC", "3", "20000"),
            _sell(datetime(2022, 6, 1), "BTC", "1", "25000"),
            _sell(datetime(2023, 3, 1), "BTC", "1", "30000"),
        )
        engine = TaxEngine(store, CostBasisMethod.FIFO)
        records = engine.compute()
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].gain_loss_usd, Decimal("5000"))
        self.assertEqual(records[1].gain_loss_usd, Decimal("10000"))

    def test_engine_summary(self):
        store = _store(
            _buy(datetime(2022, 1, 1), "BTC", "1", "30000"),
            _sell(datetime(2023, 6, 1), "BTC", "1", "50000"),
        )
        engine = TaxEngine(store, CostBasisMethod.FIFO)
        summary = engine.summary()
        self.assertEqual(summary["total_gain_loss_usd"], Decimal("20000"))
        self.assertEqual(summary["num_disposals"], 1)


class TestLIFO(unittest.TestCase):

    def test_lifo_order(self):
        """LIFO should consume the latest lot first."""
        store = _store(
            _buy(datetime(2022, 1, 1), "ETH", "1", "1000"),  # lot 1
            _buy(datetime(2022, 6, 1), "ETH", "1", "2000"),  # lot 2 (most recent)
            _sell(datetime(2022, 9, 1), "ETH", "1", "3000"),
        )
        engine = TaxEngine(store, CostBasisMethod.LIFO)
        records = engine.compute()
        r = records[0]
        # LIFO uses lot 2 first (cost 2000)
        self.assertEqual(r.cost_basis_usd, Decimal("2000"))
        self.assertEqual(r.gain_loss_usd, Decimal("1000"))


class TestHIFO(unittest.TestCase):

    def test_hifo_order(self):
        """HIFO should consume the highest-cost lot first (minimises gains)."""
        store = _store(
            _buy(datetime(2022, 1, 1), "ETH", "1", "1000"),  # cheap
            _buy(datetime(2022, 6, 1), "ETH", "1", "2000"),  # expensive
            _sell(datetime(2022, 9, 1), "ETH", "1", "2500"),
        )
        engine = TaxEngine(store, CostBasisMethod.HIFO)
        records = engine.compute()
        r = records[0]
        # HIFO uses the expensive lot (cost 2000) → gain = 500 (not 1500)
        self.assertEqual(r.cost_basis_usd, Decimal("2000"))
        self.assertEqual(r.gain_loss_usd, Decimal("500"))


class TestMiningAndSwap(unittest.TestCase):

    def test_mining_opens_lot(self):
        store = _store(
            Transaction(
                type=TransactionType.MINING,
                date=datetime(2022, 1, 1),
                asset="ETH",
                quantity=Decimal("1"),
                price_usd=Decimal("2000"),
            ),
            _sell(datetime(2023, 6, 1), "ETH", "1", "3000"),
        )
        engine = TaxEngine(store, CostBasisMethod.FIFO)
        records = engine.compute()
        r = records[0]
        self.assertEqual(r.cost_basis_usd, Decimal("2000"))
        self.assertEqual(r.gain_loss_usd, Decimal("1000"))

    def test_swap_creates_disposal_and_lot(self):
        store = _store(
            _buy(datetime(2022, 1, 1), "ETH", "1", "1000"),
            Transaction(
                type=TransactionType.SWAP,
                date=datetime(2023, 1, 1),
                asset="ETH",
                quantity=Decimal("1"),
                price_usd=Decimal("2000"),
                total_usd=Decimal("2000"),
                swap_asset="SOL",
                swap_quantity=Decimal("20"),
            ),
            _sell(datetime(2023, 6, 1), "SOL", "10", "120"),
        )
        engine = TaxEngine(store, CostBasisMethod.FIFO)
        records = engine.compute()
        # Two disposals: ETH swap + SOL sell
        self.assertEqual(len(records), 2)
        eth_record = records[0]
        self.assertEqual(eth_record.asset, "ETH")
        self.assertEqual(eth_record.gain_loss_usd, Decimal("1000"))


class TestYearFilter(unittest.TestCase):

    def test_filter_by_year(self):
        store = _store(
            _buy(datetime(2021, 1, 1), "BTC", "1", "30000"),
            _sell(datetime(2021, 6, 1), "BTC", "0.5", "40000"),
            _buy(datetime(2022, 1, 1), "BTC", "1", "45000"),
            _sell(datetime(2022, 8, 1), "BTC", "0.5", "50000"),
        )
        engine = TaxEngine(store, CostBasisMethod.FIFO)
        engine.compute()
        records_2021 = engine.gains(year=2021)
        records_2022 = engine.gains(year=2022)
        self.assertEqual(len(records_2021), 1)
        self.assertEqual(len(records_2022), 1)


if __name__ == "__main__":
    unittest.main()
