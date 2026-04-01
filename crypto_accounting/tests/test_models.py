"""Tests for core data models."""

import unittest
from datetime import datetime
from decimal import Decimal

from ..models.transaction import Transaction, TransactionType
from ..models.lot import Lot


class TestTransaction(unittest.TestCase):

    def _buy(self, qty="1", price="50000", fee=None):
        return Transaction(
            type=TransactionType.BUY,
            date=datetime(2023, 1, 1),
            asset="BTC",
            quantity=Decimal(qty),
            price_usd=Decimal(price),
            fee_usd=Decimal(fee) if fee else None,
        )

    def test_total_computed_from_price(self):
        t = self._buy()
        self.assertEqual(t.total_usd, Decimal("50000.00"))

    def test_cost_basis_includes_fee(self):
        t = self._buy(fee="25")
        self.assertEqual(t.cost_basis_usd, Decimal("50025.00"))

    def test_is_disposal_sell(self):
        t = Transaction(
            type=TransactionType.SELL,
            date=datetime(2023, 6, 1),
            asset="BTC",
            quantity=Decimal("0.5"),
            price_usd=Decimal("30000"),
        )
        self.assertTrue(t.is_disposal)
        self.assertFalse(t.is_acquisition)

    def test_is_acquisition_buy(self):
        t = self._buy()
        self.assertTrue(t.is_acquisition)
        self.assertFalse(t.is_disposal)

    def test_round_trip_dict(self):
        t = self._buy(fee="10")
        t2 = Transaction.from_dict(t.to_dict())
        self.assertEqual(t.id, t2.id)
        self.assertEqual(t.quantity, t2.quantity)
        self.assertEqual(t.price_usd, t2.price_usd)
        self.assertEqual(t.fee_usd, t2.fee_usd)

    def test_mining_is_not_disposal(self):
        t = Transaction(
            type=TransactionType.MINING,
            date=datetime(2023, 3, 1),
            asset="ETH",
            quantity=Decimal("0.1"),
            price_usd=Decimal("1800"),
        )
        self.assertFalse(t.is_disposal)
        self.assertTrue(t.is_acquisition)


class TestLot(unittest.TestCase):

    def _lot(self, qty="1", basis="40000"):
        return Lot(
            asset="BTC",
            quantity=Decimal(qty),
            remaining=Decimal(qty),
            cost_basis_usd=Decimal(basis),
            acquired_date=datetime(2023, 1, 1),
            acquisition_tx_id="tx-001",
        )

    def test_cost_per_unit(self):
        lot = self._lot("2", "80000")
        self.assertEqual(lot.cost_per_unit, Decimal("40000"))

    def test_consume_partial(self):
        lot = self._lot("1", "40000")
        consumed = lot.consume(Decimal("0.5"))
        self.assertEqual(consumed, Decimal("0.5"))
        self.assertEqual(lot.remaining, Decimal("0.5"))
        self.assertFalse(lot.is_exhausted)

    def test_consume_full(self):
        lot = self._lot("1", "40000")
        consumed = lot.consume(Decimal("1"))
        self.assertEqual(consumed, Decimal("1"))
        self.assertTrue(lot.is_exhausted)

    def test_consume_more_than_available(self):
        lot = self._lot("0.5", "20000")
        consumed = lot.consume(Decimal("1"))
        self.assertEqual(consumed, Decimal("0.5"))  # capped at remaining
        self.assertTrue(lot.is_exhausted)

    def test_remaining_cost_basis(self):
        lot = self._lot("2", "80000")
        lot.consume(Decimal("1"))
        self.assertEqual(lot.remaining_cost_basis, Decimal("40000"))


if __name__ == "__main__":
    unittest.main()
