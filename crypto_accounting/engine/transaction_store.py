"""
TransactionStore – persists and retrieves transactions from CSV or JSON files.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterator, List, Optional

from ..models.transaction import Transaction, TransactionType


_CSV_FIELDS = [
    "id", "type", "date", "asset", "quantity",
    "price_usd", "total_usd", "fee_usd", "fee_asset", "fee_quantity",
    "fiat_currency", "fiat_amount", "fx_rate_to_usd",
    "swap_asset", "swap_quantity", "wallet", "notes", "tx_hash",
]


class TransactionStore:
    """
    In-memory collection of transactions with CSV / JSON persistence.

    Usage::

        store = TransactionStore()
        store.add(Transaction(...))
        store.save_csv("ledger.csv")

        store2 = TransactionStore.load_csv("ledger.csv")
    """

    def __init__(self, transactions: Optional[List[Transaction]] = None) -> None:
        self._txns: List[Transaction] = list(transactions or [])

    # ------------------------------------------------------------------ #
    # Mutation
    # ------------------------------------------------------------------ #

    def add(self, txn: Transaction) -> None:
        self._txns.append(txn)

    def remove(self, txn_id: str) -> bool:
        before = len(self._txns)
        self._txns = [t for t in self._txns if t.id != txn_id]
        return len(self._txns) < before

    def clear(self) -> None:
        self._txns.clear()

    # ------------------------------------------------------------------ #
    # Querying
    # ------------------------------------------------------------------ #

    def all(self) -> List[Transaction]:
        return sorted(self._txns, key=lambda t: t.date)

    def __len__(self) -> int:
        return len(self._txns)

    def __iter__(self) -> Iterator[Transaction]:
        return iter(self.all())

    def by_asset(self, symbol: str) -> List[Transaction]:
        s = symbol.upper()
        return [t for t in self.all() if t.asset.upper() == s]

    def by_type(self, *types: TransactionType) -> List[Transaction]:
        return [t for t in self.all() if t.type in types]

    def by_wallet(self, wallet: str) -> List[Transaction]:
        return [t for t in self.all() if t.wallet == wallet]

    def by_date_range(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> List[Transaction]:
        txns = self.all()
        if start:
            txns = [t for t in txns if t.date >= start]
        if end:
            txns = [t for t in txns if t.date <= end]
        return txns

    def assets(self) -> set[str]:
        """Return the set of unique asset symbols in the store."""
        return {t.asset.upper() for t in self._txns}

    def get(self, txn_id: str) -> Optional[Transaction]:
        for t in self._txns:
            if t.id == txn_id:
                return t
        return None

    # ------------------------------------------------------------------ #
    # CSV persistence
    # ------------------------------------------------------------------ #

    def save_csv(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            for txn in self.all():
                writer.writerow(txn.to_dict())

    @classmethod
    def load_csv(cls, path: str | Path) -> "TransactionStore":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {path}")
        txns: List[Transaction] = []
        with path.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                txns.append(Transaction.from_dict(row))
        return cls(txns)

    # ------------------------------------------------------------------ #
    # JSON persistence
    # ------------------------------------------------------------------ #

    def save_json(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump([t.to_dict() for t in self.all()], fh, indent=2)

    @classmethod
    def load_json(cls, path: str | Path) -> "TransactionStore":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"JSON file not found: {path}")
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return cls([Transaction.from_dict(d) for d in data])

    # ------------------------------------------------------------------ #
    # Summary stats
    # ------------------------------------------------------------------ #

    def summary(self) -> dict:
        txns = self.all()
        return {
            "total_transactions": len(txns),
            "assets": sorted(self.assets()),
            "date_range": (
                (txns[0].date.date(), txns[-1].date.date()) if txns else None
            ),
            "by_type": {
                t.value: sum(1 for x in txns if x.type == t)
                for t in TransactionType
                if any(x.type == t for x in txns)
            },
        }
