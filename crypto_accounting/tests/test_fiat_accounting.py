"""
Tests for fiat exchange accounting:
  - Transaction model fiat fields and new types
  - FiatAccountTracker balance computation
  - TaxEngine uses fiat_amount * fx_rate for cost basis / proceeds
"""

import unittest
from datetime import datetime
from decimal import Decimal

from ..models.transaction import Transaction, TransactionType, FIAT_ONLY_TYPES
from ..engine.transaction_store import TransactionStore
from ..engine.fiat_account import FiatAccountTracker
from ..engine.tax_engine import TaxEngine, CostBasisMethod


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _store(*txns):
    s = TransactionStore()
    for t in txns:
        s.add(t)
    return s


def _buy_with_fiat(date, asset, qty, fiat_currency, fiat_amount, fx_rate, fee_usd=None):
    """Buy crypto using a non-USD fiat currency."""
    return Transaction(
        type=TransactionType.BUY,
        date=date,
        asset=asset,
        quantity=Decimal(str(qty)),
        fiat_currency=fiat_currency,
        fiat_amount=Decimal(str(fiat_amount)),
        fx_rate_to_usd=Decimal(str(fx_rate)),
        fee_usd=Decimal(str(fee_usd)) if fee_usd else None,
        wallet="Binance",
    )


def _sell_for_fiat(date, asset, qty, fiat_currency, fiat_amount, fx_rate, fee_usd=None):
    """Sell crypto receiving non-USD fiat."""
    return Transaction(
        type=TransactionType.SELL,
        date=date,
        asset=asset,
        quantity=Decimal(str(qty)),
        fiat_currency=fiat_currency,
        fiat_amount=Decimal(str(fiat_amount)),
        fx_rate_to_usd=Decimal(str(fx_rate)),
        fee_usd=Decimal(str(fee_usd)) if fee_usd else None,
        wallet="Binance",
    )


def _deposit(date, currency, amount, wallet="Binance"):
    return Transaction(
        type=TransactionType.FIAT_DEPOSIT,
        date=date,
        asset="FIAT",
        quantity=Decimal("0"),
        fiat_currency=currency,
        fiat_amount=Decimal(str(amount)),
        wallet=wallet,
    )


def _withdraw(date, currency, amount, wallet="Binance"):
    return Transaction(
        type=TransactionType.FIAT_WITHDRAWAL,
        date=date,
        asset="FIAT",
        quantity=Decimal("0"),
        fiat_currency=currency,
        fiat_amount=Decimal(str(amount)),
        wallet=wallet,
    )


# ------------------------------------------------------------------ #
# Transaction model tests
# ------------------------------------------------------------------ #

class TestTransactionFiatFields(unittest.TestCase):

    def test_total_usd_derived_from_fiat_amount_and_fx_rate(self):
        """total_usd = fiat_amount * fx_rate_to_usd when total_usd not given."""
        t = Transaction(
            type=TransactionType.BUY,
            date=datetime(2024, 1, 1),
            asset="BTC",
            quantity=Decimal("0.5"),
            fiat_currency="EUR",
            fiat_amount=Decimal("23000"),
            fx_rate_to_usd=Decimal("1.09"),
        )
        self.assertAlmostEqual(float(t.total_usd), 23000 * 1.09, places=2)

    def test_explicit_total_usd_takes_priority_over_fiat(self):
        """If total_usd is provided directly, do not override it."""
        t = Transaction(
            type=TransactionType.BUY,
            date=datetime(2024, 1, 1),
            asset="BTC",
            quantity=Decimal("1"),
            total_usd=Decimal("50000"),
            fiat_currency="EUR",
            fiat_amount=Decimal("45000"),
            fx_rate_to_usd=Decimal("1.09"),
        )
        self.assertEqual(t.total_usd, Decimal("50000"))

    def test_fiat_display(self):
        t = Transaction(
            type=TransactionType.SELL,
            date=datetime(2024, 3, 1),
            asset="ETH",
            quantity=Decimal("2"),
            fiat_currency="GBP",
            fiat_amount=Decimal("5400"),
            fx_rate_to_usd=Decimal("1.27"),
        )
        self.assertIn("GBP", t.fiat_display)
        self.assertIn("5,400", t.fiat_display)

    def test_fiat_deposit_is_fiat_only(self):
        t = _deposit(datetime(2024, 1, 1), "EUR", 10000)
        self.assertTrue(t.is_fiat_only)
        self.assertFalse(t.is_acquisition)
        self.assertFalse(t.is_disposal)

    def test_fiat_withdrawal_is_fiat_only(self):
        t = _withdraw(datetime(2024, 1, 1), "USD", 5000)
        self.assertTrue(t.is_fiat_only)

    def test_fiat_types_in_constant(self):
        self.assertIn(TransactionType.FIAT_DEPOSIT, FIAT_ONLY_TYPES)
        self.assertIn(TransactionType.FIAT_WITHDRAWAL, FIAT_ONLY_TYPES)

    def test_csv_round_trip_preserves_fiat_fields(self):
        import tempfile, os
        t = _buy_with_fiat(datetime(2024, 1, 1), "BTC", "0.5", "EUR", "23000", "1.09")
        store = _store(t)
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            path = f.name
        try:
            store.save_csv(path)
            loaded = TransactionStore.load_csv(path)
            txn = loaded.all()[0]
            self.assertEqual(txn.fiat_currency, "EUR")
            self.assertEqual(txn.fiat_amount, Decimal("23000"))
            self.assertEqual(txn.fx_rate_to_usd, Decimal("1.09"))
        finally:
            os.unlink(path)


# ------------------------------------------------------------------ #
# FiatAccountTracker tests
# ------------------------------------------------------------------ #

class TestFiatAccountTracker(unittest.TestCase):

    def test_deposit_increases_balance(self):
        store = _store(_deposit(datetime(2024, 1, 1), "EUR", "10000"))
        tracker = FiatAccountTracker.from_store(store)
        acc = tracker.account("EUR")
        self.assertIsNotNone(acc)
        self.assertEqual(acc.balance, Decimal("10000"))
        self.assertEqual(acc.total_deposited, Decimal("10000"))

    def test_withdrawal_decreases_balance(self):
        store = _store(
            _deposit(datetime(2024, 1, 1), "EUR", "10000"),
            _withdraw(datetime(2024, 2, 1), "EUR", "3000"),
        )
        tracker = FiatAccountTracker.from_store(store)
        acc = tracker.account("EUR")
        self.assertEqual(acc.balance, Decimal("7000"))

    def test_buy_reduces_fiat_balance(self):
        store = _store(
            _deposit(datetime(2024, 1, 1), "EUR", "10000"),
            _buy_with_fiat(datetime(2024, 1, 10), "BTC", "0.1", "EUR", "5000", "1.09"),
        )
        tracker = FiatAccountTracker.from_store(store)
        acc = tracker.account("EUR")
        self.assertEqual(acc.balance, Decimal("5000"))
        self.assertEqual(acc.total_spent_on_buys, Decimal("5000"))
        self.assertEqual(acc.num_buys, 1)

    def test_sell_increases_fiat_balance(self):
        store = _store(
            _sell_for_fiat(datetime(2024, 6, 1), "ETH", "2", "EUR", "6000", "1.09"),
        )
        tracker = FiatAccountTracker.from_store(store)
        acc = tracker.account("EUR")
        self.assertEqual(acc.balance, Decimal("6000"))
        self.assertEqual(acc.total_received_from_sells, Decimal("6000"))
        self.assertEqual(acc.num_sells, 1)

    def test_realised_fiat_pnl(self):
        """P&L = received from sells - spent on buys."""
        store = _store(
            _deposit(datetime(2024, 1, 1), "EUR", "20000"),
            _buy_with_fiat(datetime(2024, 1, 5), "BTC", "0.3", "EUR", "12000", "1.09"),
            _sell_for_fiat(datetime(2024, 8, 1), "BTC", "0.3", "EUR", "15000", "1.10"),
        )
        tracker = FiatAccountTracker.from_store(store)
        acc = tracker.account("EUR")
        self.assertEqual(acc.realised_fiat_pnl, Decimal("3000"))

    def test_multiple_currencies(self):
        store = _store(
            _deposit(datetime(2024, 1, 1), "EUR", "5000"),
            _deposit(datetime(2024, 1, 2), "GBP", "4000"),
            _deposit(datetime(2024, 1, 3), "USD", "3000"),
        )
        tracker = FiatAccountTracker.from_store(store)
        currencies = tracker.currencies()
        self.assertIn("EUR", currencies)
        self.assertIn("GBP", currencies)
        self.assertIn("USD", currencies)

    def test_ledger_order(self):
        store = _store(
            _deposit(datetime(2024, 1, 1), "EUR", "10000"),
            _buy_with_fiat(datetime(2024, 2, 1), "BTC", "0.1", "EUR", "4000", "1.08"),
        )
        tracker = FiatAccountTracker.from_store(store)
        entries = tracker.ledger("EUR")
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].txn_type, TransactionType.FIAT_DEPOSIT)
        self.assertEqual(entries[1].txn_type, TransactionType.BUY)

    def test_running_balance_in_ledger(self):
        store = _store(
            _deposit(datetime(2024, 1, 1), "USD", "10000"),
            _buy_with_fiat(datetime(2024, 2, 1), "ETH", "2", "USD", "3000", "1"),
        )
        tracker = FiatAccountTracker.from_store(store)
        entries = tracker.ledger("USD")
        self.assertEqual(entries[0].running_balance, Decimal("10000"))
        self.assertEqual(entries[1].running_balance, Decimal("7000"))

    def test_no_fiat_currency_on_transaction_is_ignored(self):
        """Transactions without fiat_currency should not create fiat entries."""
        store = _store(
            Transaction(
                type=TransactionType.BUY,
                date=datetime(2024, 1, 1),
                asset="BTC",
                quantity=Decimal("1"),
                price_usd=Decimal("40000"),
            )
        )
        tracker = FiatAccountTracker.from_store(store)
        self.assertEqual(tracker.currencies(), [])


# ------------------------------------------------------------------ #
# TaxEngine with fiat transactions
# ------------------------------------------------------------------ #

class TestTaxEngineFiat(unittest.TestCase):

    def test_buy_with_eur_derives_cost_basis(self):
        """Cost basis for a EUR buy = fiat_amount * fx_rate (+ fees)."""
        store = _store(
            _buy_with_fiat(datetime(2022, 1, 1), "BTC", "1", "EUR", "30000", "1.10"),
            Transaction(
                type=TransactionType.SELL,
                date=datetime(2023, 6, 1),
                asset="BTC",
                quantity=Decimal("1"),
                total_usd=Decimal("50000"),
            ),
        )
        engine = TaxEngine(store, CostBasisMethod.FIFO)
        records = engine.compute()
        self.assertEqual(len(records), 1)
        r = records[0]
        # Cost basis = 30000 EUR * 1.10 = 33000 USD
        self.assertEqual(r.cost_basis_usd, Decimal("33000.00"))
        self.assertEqual(r.gain_loss_usd, Decimal("17000.00"))

    def test_sell_for_eur_derives_proceeds(self):
        """Proceeds for an EUR sell = fiat_amount * fx_rate."""
        store = _store(
            Transaction(
                type=TransactionType.BUY,
                date=datetime(2022, 1, 1),
                asset="ETH",
                quantity=Decimal("2"),
                total_usd=Decimal("4000"),
            ),
            _sell_for_fiat(datetime(2023, 6, 1), "ETH", "2", "EUR", "6000", "1.10"),
        )
        engine = TaxEngine(store, CostBasisMethod.FIFO)
        records = engine.compute()
        r = records[0]
        # Proceeds = 6000 EUR * 1.10 = 6600 USD
        self.assertEqual(r.proceeds_usd, Decimal("6600.00"))
        self.assertEqual(r.gain_loss_usd, Decimal("2600.00"))

    def test_fiat_deposit_not_in_gains(self):
        """FIAT_DEPOSIT must not appear as a gain record."""
        store = _store(
            _deposit(datetime(2024, 1, 1), "EUR", "10000"),
            _deposit(datetime(2024, 2, 1), "USD", "5000"),
        )
        engine = TaxEngine(store, CostBasisMethod.FIFO)
        records = engine.compute()
        self.assertEqual(records, [])

    def test_fiat_withdrawal_not_in_gains(self):
        store = _store(_withdraw(datetime(2024, 1, 1), "EUR", "5000"))
        engine = TaxEngine(store, CostBasisMethod.FIFO)
        records = engine.compute()
        self.assertEqual(records, [])

    def test_mixed_usd_and_eur_buys(self):
        """Mix of USD-priced and EUR-priced acquisitions works correctly."""
        store = _store(
            Transaction(
                type=TransactionType.BUY,
                date=datetime(2021, 1, 1),
                asset="BTC",
                quantity=Decimal("0.5"),
                total_usd=Decimal("15000"),
            ),
            _buy_with_fiat(datetime(2022, 1, 1), "BTC", "0.5", "EUR", "18000", "1.08"),
            Transaction(
                type=TransactionType.SELL,
                date=datetime(2023, 6, 1),
                asset="BTC",
                quantity=Decimal("1"),
                total_usd=Decimal("40000"),
            ),
        )
        engine = TaxEngine(store, CostBasisMethod.FIFO)
        records = engine.compute()
        self.assertEqual(len(records), 1)
        # FIFO: first lot = $15000, second lot = 18000*1.08 = $19440
        expected_basis = Decimal("15000") + Decimal("18000") * Decimal("1.08")
        self.assertEqual(records[0].cost_basis_usd, expected_basis.quantize(Decimal("0.01")))


if __name__ == "__main__":
    unittest.main()
