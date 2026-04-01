"""
FiatAccountTracker – aggregates fiat currency balances from transactions.

A "fiat account" represents the running cash balance of a single fiat
currency on a single exchange/wallet.  It is updated by:

  FIAT_DEPOSIT       → +fiat_amount  (cash added to the exchange)
  BUY                → -fiat_amount  (cash spent on crypto)
  SELL               → +fiat_amount  (cash received from crypto sale)
  FIAT_WITHDRAWAL    → -fiat_amount  (cash taken off the exchange)
  FEE (fiat)         → -fiat_amount  (fee paid in fiat)

Usage::

    tracker = FiatAccountTracker.from_store(store)
    accounts = tracker.accounts()   # list of FiatAccount snapshots

    # Drill into a specific currency
    account = tracker.account("EUR")

    # Ledger of all fiat movements for EUR
    entries = tracker.ledger("EUR")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from ..models.transaction import Transaction, TransactionType
from .transaction_store import TransactionStore


# ------------------------------------------------------------------ #
# Data structures
# ------------------------------------------------------------------ #

@dataclass
class FiatEntry:
    """One line in a fiat account ledger."""
    date: datetime
    txn_type: TransactionType
    fiat_currency: str
    amount: Decimal          # positive = inflow, negative = outflow
    running_balance: Decimal
    asset: str               # crypto asset involved (or "—" for pure fiat)
    crypto_quantity: Decimal
    fx_rate_to_usd: Optional[Decimal]
    wallet: Optional[str]
    notes: Optional[str]
    txn_id: str

    @property
    def amount_usd(self) -> Optional[Decimal]:
        if self.fx_rate_to_usd:
            return (self.amount * self.fx_rate_to_usd).quantize(Decimal("0.01"))
        return None

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "type": self.txn_type.value,
            "currency": self.fiat_currency,
            "amount": str(self.amount),
            "running_balance": str(self.running_balance),
            "amount_usd": str(self.amount_usd) if self.amount_usd else "",
            "asset": self.asset,
            "crypto_quantity": str(self.crypto_quantity),
            "fx_rate_to_usd": str(self.fx_rate_to_usd) if self.fx_rate_to_usd else "",
            "wallet": self.wallet or "",
            "notes": self.notes or "",
            "txn_id": self.txn_id,
        }


@dataclass
class FiatAccount:
    """Snapshot of a single fiat currency's position (optionally per wallet)."""
    currency: str
    wallet: Optional[str]          # None = aggregate across all wallets
    balance: Decimal               # current balance (positive = held)
    total_deposited: Decimal       # total cash deposits
    total_withdrawn: Decimal       # total cash withdrawals
    total_spent_on_buys: Decimal   # total fiat spent buying crypto
    total_received_from_sells: Decimal  # total fiat received from selling crypto
    total_fees_fiat: Decimal       # fees paid in this fiat currency
    num_buys: int
    num_sells: int

    @property
    def net_flow(self) -> Decimal:
        return self.total_deposited - self.total_withdrawn

    @property
    def realised_fiat_pnl(self) -> Decimal:
        """Total fiat received from sells minus total fiat spent on buys."""
        return self.total_received_from_sells - self.total_spent_on_buys

    def to_dict(self) -> dict:
        return {
            "currency": self.currency,
            "wallet": self.wallet,
            "balance": str(self.balance.quantize(Decimal("0.01"))),
            "total_deposited": str(self.total_deposited.quantize(Decimal("0.01"))),
            "total_withdrawn": str(self.total_withdrawn.quantize(Decimal("0.01"))),
            "total_spent_on_buys": str(self.total_spent_on_buys.quantize(Decimal("0.01"))),
            "total_received_from_sells": str(self.total_received_from_sells.quantize(Decimal("0.01"))),
            "total_fees_fiat": str(self.total_fees_fiat.quantize(Decimal("0.01"))),
            "realised_fiat_pnl": str(self.realised_fiat_pnl.quantize(Decimal("0.01"))),
            "net_flow": str(self.net_flow.quantize(Decimal("0.01"))),
            "num_buys": self.num_buys,
            "num_sells": self.num_sells,
        }


# ------------------------------------------------------------------ #
# Tracker
# ------------------------------------------------------------------ #

class FiatAccountTracker:
    """
    Replay all transactions and maintain per-currency fiat ledgers.

    A key is (currency, wallet) – one ledger per currency per exchange.
    Calling accounts() returns aggregated snapshots (wallet=None totals).
    """

    def __init__(self) -> None:
        # (currency, wallet) → running balance
        self._balances: Dict[Tuple[str, str], Decimal] = {}
        # (currency, wallet) → list of FiatEntry
        self._ledgers: Dict[Tuple[str, str], List[FiatEntry]] = {}
        # (currency, wallet) → counters
        self._stats: Dict[Tuple[str, str], dict] = {}

    # ------------------------------------------------------------------ #
    # Factory
    # ------------------------------------------------------------------ #

    @classmethod
    def from_store(cls, store: TransactionStore) -> "FiatAccountTracker":
        tracker = cls()
        for txn in store.all():
            tracker.apply(txn)
        return tracker

    # ------------------------------------------------------------------ #
    # Applying transactions
    # ------------------------------------------------------------------ #

    def apply(self, txn: Transaction) -> None:
        # Only process transactions that have a fiat side
        currency = txn.fiat_currency
        if not currency:
            return

        currency = currency.upper()
        wallet = txn.wallet or "_global"
        key = (currency, wallet)

        self._balances.setdefault(key, Decimal("0"))
        self._ledgers.setdefault(key, [])
        self._stats.setdefault(key, {
            "deposited": Decimal("0"),
            "withdrawn": Decimal("0"),
            "spent_buys": Decimal("0"),
            "received_sells": Decimal("0"),
            "fees": Decimal("0"),
            "num_buys": 0,
            "num_sells": 0,
        })

        amount = txn.fiat_amount or Decimal("0")
        delta = Decimal("0")
        s = self._stats[key]

        if txn.type == TransactionType.FIAT_DEPOSIT:
            delta = amount
            s["deposited"] += amount

        elif txn.type == TransactionType.FIAT_WITHDRAWAL:
            delta = -amount
            s["withdrawn"] += amount

        elif txn.type == TransactionType.BUY:
            delta = -amount        # fiat leaves account, crypto arrives
            s["spent_buys"] += amount
            s["num_buys"] += 1

        elif txn.type == TransactionType.SELL:
            delta = amount         # fiat arrives, crypto leaves
            s["received_sells"] += amount
            s["num_sells"] += 1

        elif txn.type == TransactionType.FEE:
            delta = -amount
            s["fees"] += amount

        else:
            return  # no fiat movement for other types

        self._balances[key] += delta

        entry = FiatEntry(
            date=txn.date,
            txn_type=txn.type,
            fiat_currency=currency,
            amount=delta,
            running_balance=self._balances[key],
            asset=txn.asset,
            crypto_quantity=txn.quantity,
            fx_rate_to_usd=txn.fx_rate_to_usd,
            wallet=txn.wallet,
            notes=txn.notes,
            txn_id=txn.id,
        )
        self._ledgers[key].append(entry)

    # ------------------------------------------------------------------ #
    # Querying
    # ------------------------------------------------------------------ #

    def accounts(self, include_zero: bool = True) -> List[FiatAccount]:
        """Return aggregate snapshots (per currency, all wallets combined)."""
        currency_totals: Dict[str, dict] = {}

        for (currency, wallet), stats in self._stats.items():
            if currency not in currency_totals:
                currency_totals[currency] = {
                    "balance": Decimal("0"),
                    "deposited": Decimal("0"),
                    "withdrawn": Decimal("0"),
                    "spent_buys": Decimal("0"),
                    "received_sells": Decimal("0"),
                    "fees": Decimal("0"),
                    "num_buys": 0,
                    "num_sells": 0,
                }
            t = currency_totals[currency]
            t["balance"] += self._balances.get((currency, wallet), Decimal("0"))
            t["deposited"] += stats["deposited"]
            t["withdrawn"] += stats["withdrawn"]
            t["spent_buys"] += stats["spent_buys"]
            t["received_sells"] += stats["received_sells"]
            t["fees"] += stats["fees"]
            t["num_buys"] += stats["num_buys"]
            t["num_sells"] += stats["num_sells"]

        results = []
        for currency, t in sorted(currency_totals.items()):
            if not include_zero and t["balance"] == 0:
                continue
            results.append(FiatAccount(
                currency=currency,
                wallet=None,
                balance=t["balance"],
                total_deposited=t["deposited"],
                total_withdrawn=t["withdrawn"],
                total_spent_on_buys=t["spent_buys"],
                total_received_from_sells=t["received_sells"],
                total_fees_fiat=t["fees"],
                num_buys=t["num_buys"],
                num_sells=t["num_sells"],
            ))
        return results

    def account(self, currency: str) -> Optional[FiatAccount]:
        for acc in self.accounts():
            if acc.currency == currency.upper():
                return acc
        return None

    def accounts_by_wallet(self) -> List[FiatAccount]:
        """Return one snapshot per (currency, wallet) pair."""
        results = []
        for (currency, wallet), stats in sorted(self._stats.items()):
            balance = self._balances.get((currency, wallet), Decimal("0"))
            results.append(FiatAccount(
                currency=currency,
                wallet=wallet if wallet != "_global" else None,
                balance=balance,
                total_deposited=stats["deposited"],
                total_withdrawn=stats["withdrawn"],
                total_spent_on_buys=stats["spent_buys"],
                total_received_from_sells=stats["received_sells"],
                total_fees_fiat=stats["fees"],
                num_buys=stats["num_buys"],
                num_sells=stats["num_sells"],
            ))
        return results

    def ledger(self, currency: str, wallet: Optional[str] = None) -> List[FiatEntry]:
        """Return all fiat entries for a given currency (and optionally wallet)."""
        currency = currency.upper()
        if wallet:
            return list(self._ledgers.get((currency, wallet), []))
        # Merge all wallets for this currency
        all_entries = []
        for (cur, w), entries in self._ledgers.items():
            if cur == currency:
                all_entries.extend(entries)
        return sorted(all_entries, key=lambda e: e.date)

    def currencies(self) -> List[str]:
        return sorted({c for (c, _) in self._balances})
