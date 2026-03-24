"""
Tax Engine – computes capital gains/losses using FIFO, LIFO, or HIFO.

Terminology
-----------
- Lot            : a parcel of acquired crypto with a known cost basis
- Disposal       : a sell, send, or swap event
- Short-term     : held ≤ 365 days (taxed as ordinary income in the US)
- Long-term      : held > 365 days (preferential rate in the US)
- GainRecord     : the result of matching a disposal against one or more lots
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional

from ..models.transaction import Transaction, TransactionType
from ..models.lot import Lot
from .transaction_store import TransactionStore


LONG_TERM_THRESHOLD = timedelta(days=365)


class CostBasisMethod(str, Enum):
    FIFO = "fifo"   # First In, First Out
    LIFO = "lifo"   # Last In, First Out
    HIFO = "hifo"   # Highest Cost, First Out (minimises gains)


@dataclass
class GainRecord:
    """Realised gain or loss from a single disposal event."""

    disposal_tx_id: str
    disposal_date: datetime
    asset: str
    quantity_disposed: Decimal

    proceeds_usd: Decimal           # what was received
    cost_basis_usd: Decimal         # original cost of the disposed lot(s)
    fee_usd: Decimal                # fees attributable to this disposal
    gain_loss_usd: Decimal          # proceeds - cost_basis - fees

    is_long_term: bool              # held > 365 days
    method: CostBasisMethod

    # Detail on which lots were consumed
    lots_used: List[dict] = field(default_factory=list)

    @property
    def term(self) -> str:
        return "long-term" if self.is_long_term else "short-term"

    def to_dict(self) -> dict:
        return {
            "disposal_tx_id": self.disposal_tx_id,
            "disposal_date": self.disposal_date.isoformat(),
            "asset": self.asset,
            "quantity": str(self.quantity_disposed),
            "proceeds_usd": str(self.proceeds_usd),
            "cost_basis_usd": str(self.cost_basis_usd),
            "fee_usd": str(self.fee_usd),
            "gain_loss_usd": str(self.gain_loss_usd),
            "term": self.term,
            "method": self.method.value,
        }


class TaxEngine:
    """
    Computes realised capital gains by replaying all transactions.

    The engine maintains a pool of open lots (per asset) and matches
    disposal events against them according to the chosen cost-basis method.
    """

    def __init__(
        self,
        store: TransactionStore,
        method: CostBasisMethod = CostBasisMethod.FIFO,
    ) -> None:
        self._store = store
        self.method = method
        self._lots: Dict[str, List[Lot]] = {}
        self._gain_records: List[GainRecord] = []
        self._computed = False

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def compute(self) -> List[GainRecord]:
        """Run the engine over all transactions and return gain records."""
        self._lots = {}
        self._gain_records = []

        for txn in self._store.all():
            self._process(txn)

        self._computed = True
        return self._gain_records

    def gains(self, year: Optional[int] = None) -> List[GainRecord]:
        if not self._computed:
            self.compute()
        records = self._gain_records
        if year is not None:
            records = [r for r in records if r.disposal_date.year == year]
        return records

    def summary(self, year: Optional[int] = None) -> dict:
        records = self.gains(year)
        total = sum(r.gain_loss_usd for r in records)
        lt = sum(r.gain_loss_usd for r in records if r.is_long_term)
        st = sum(r.gain_loss_usd for r in records if not r.is_long_term)
        return {
            "year": year or "all",
            "method": self.method.value,
            "total_gain_loss_usd": total,
            "long_term_gain_loss_usd": lt,
            "short_term_gain_loss_usd": st,
            "num_disposals": len(records),
        }

    def open_lots(self, asset: Optional[str] = None) -> Dict[str, List[Lot]]:
        """Return currently open (unconsumed) lots, optionally filtered by asset."""
        if not self._computed:
            self.compute()
        if asset:
            return {asset.upper(): self._lots.get(asset.upper(), [])}
        return {k: v for k, v in self._lots.items() if v}

    # ------------------------------------------------------------------ #
    # Internal processing
    # ------------------------------------------------------------------ #

    def _process(self, txn: Transaction) -> None:
        asset = txn.asset.upper()

        if txn.is_acquisition:
            self._open_lot(asset, txn)

        if txn.is_disposal:
            record = self._match_disposal(asset, txn)
            if record:
                self._gain_records.append(record)

        # SWAP: open a lot for the received asset
        if txn.type == TransactionType.SWAP and txn.swap_asset and txn.swap_quantity:
            recv_asset = txn.swap_asset.upper()
            basis = txn.total_usd or Decimal("0")
            lot = Lot(
                asset=recv_asset,
                quantity=txn.swap_quantity,
                remaining=txn.swap_quantity,
                cost_basis_usd=basis,
                acquired_date=txn.date,
                acquisition_tx_id=txn.id,
            )
            self._lots.setdefault(recv_asset, []).append(lot)

    def _open_lot(self, asset: str, txn: Transaction) -> None:
        basis = txn.cost_basis_usd or Decimal("0")
        lot = Lot(
            asset=asset,
            quantity=txn.quantity,
            remaining=txn.quantity,
            cost_basis_usd=basis,
            acquired_date=txn.date,
            acquisition_tx_id=txn.id,
            wallet=txn.wallet,
        )
        self._lots.setdefault(asset, []).append(lot)

    def _match_disposal(
        self, asset: str, txn: Transaction
    ) -> Optional[GainRecord]:
        lots = self._lots.get(asset, [])
        open_lots = [l for l in lots if not l.is_exhausted]

        if not open_lots and txn.quantity > 0:
            # No lots to match – record with zero cost basis (unknown)
            open_lots = []

        ordered = self._order_lots(open_lots)
        quantity_to_match = txn.quantity
        total_basis = Decimal("0")
        lots_used = []
        is_long_term = True  # will be refined below

        any_lt = False
        any_st = False

        for lot in ordered:
            if quantity_to_match <= 0:
                break
            consumed = lot.consume(quantity_to_match)
            lot_basis = consumed * lot.cost_per_unit
            total_basis += lot_basis
            quantity_to_match -= consumed
            held = txn.date - lot.acquired_date
            lt = held > LONG_TERM_THRESHOLD
            if lt:
                any_lt = True
            else:
                any_st = True
            lots_used.append({
                "lot_id": lot.id,
                "acquired_date": lot.acquired_date.isoformat(),
                "consumed": str(consumed),
                "basis": str(lot_basis.quantize(Decimal("0.01"))),
                "long_term": lt,
            })

        # Mixed holding periods: conservative = short-term
        if any_lt and not any_st:
            is_long_term = True
        else:
            is_long_term = False

        proceeds = txn.total_usd or Decimal("0")
        fee = txn.fee_usd or Decimal("0")
        gain = proceeds - total_basis - fee

        return GainRecord(
            disposal_tx_id=txn.id,
            disposal_date=txn.date,
            asset=asset,
            quantity_disposed=txn.quantity,
            proceeds_usd=proceeds,
            cost_basis_usd=total_basis.quantize(Decimal("0.01")),
            fee_usd=fee,
            gain_loss_usd=gain.quantize(Decimal("0.01")),
            is_long_term=is_long_term,
            method=self.method,
            lots_used=lots_used,
        )

    def _order_lots(self, lots: List[Lot]) -> List[Lot]:
        if self.method == CostBasisMethod.FIFO:
            return sorted(lots, key=lambda l: l.acquired_date)
        elif self.method == CostBasisMethod.LIFO:
            return sorted(lots, key=lambda l: l.acquired_date, reverse=True)
        elif self.method == CostBasisMethod.HIFO:
            return sorted(lots, key=lambda l: l.cost_per_unit, reverse=True)
        return lots
