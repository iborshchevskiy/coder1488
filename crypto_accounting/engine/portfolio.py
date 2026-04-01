"""
Portfolio – tracks current holdings and unrealised P&L.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional

from ..models.transaction import Transaction, TransactionType
from ..models.lot import Lot
from .transaction_store import TransactionStore


@dataclass
class HoldingSnapshot:
    """Aggregated view of a single asset's current position."""

    asset: str
    quantity: Decimal
    total_cost_basis: Decimal       # sum of cost bases of remaining lots
    num_lots: int
    current_price_usd: Optional[Decimal] = None

    @property
    def average_cost_usd(self) -> Decimal:
        if self.quantity == 0:
            return Decimal("0")
        return self.total_cost_basis / self.quantity

    @property
    def market_value_usd(self) -> Optional[Decimal]:
        if self.current_price_usd is None:
            return None
        return (self.quantity * self.current_price_usd).quantize(Decimal("0.01"))

    @property
    def unrealised_pnl_usd(self) -> Optional[Decimal]:
        mv = self.market_value_usd
        if mv is None:
            return None
        return mv - self.total_cost_basis

    @property
    def unrealised_pnl_pct(self) -> Optional[Decimal]:
        if self.total_cost_basis == 0 or self.unrealised_pnl_usd is None:
            return None
        return (self.unrealised_pnl_usd / self.total_cost_basis * 100).quantize(
            Decimal("0.01")
        )


class Portfolio:
    """
    Maintains the set of open lots and computes holding snapshots.

    The portfolio is built by replaying all transactions chronologically.
    """

    def __init__(self) -> None:
        self._lots: Dict[str, List[Lot]] = {}  # asset -> list of open lots

    # ------------------------------------------------------------------ #
    # Building from transactions
    # ------------------------------------------------------------------ #

    @classmethod
    def from_store(cls, store: TransactionStore) -> "Portfolio":
        portfolio = cls()
        for txn in store.all():
            portfolio.apply(txn)
        return portfolio

    def apply(self, txn: Transaction) -> None:
        """Apply a single transaction to the portfolio state."""
        asset = txn.asset.upper()

        if txn.is_acquisition:
            self._add_lot(asset, txn)

        elif txn.is_disposal:
            self._consume_lots(asset, txn.quantity)

        # For SWAP, also open a lot for the received asset
        if txn.type == TransactionType.SWAP and txn.swap_asset and txn.swap_quantity:
            received_asset = txn.swap_asset.upper()
            # Basis of received asset = fair value of what was given up
            basis = txn.total_usd or Decimal("0")
            lot = Lot(
                asset=received_asset,
                quantity=txn.swap_quantity,
                remaining=txn.swap_quantity,
                cost_basis_usd=basis,
                acquired_date=txn.date,
                acquisition_tx_id=txn.id,
                wallet=txn.wallet,
            )
            self._lots.setdefault(received_asset, []).append(lot)

    def _add_lot(self, asset: str, txn: Transaction) -> None:
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

    def _consume_lots(self, asset: str, quantity: Decimal) -> Decimal:
        """
        Consume *quantity* from existing lots (FIFO order).
        Returns the total cost basis consumed.
        """
        lots = self._lots.get(asset, [])
        remaining_to_consume = quantity
        total_basis_consumed = Decimal("0")

        for lot in lots:
            if lot.is_exhausted or remaining_to_consume <= 0:
                continue
            consumed = lot.consume(remaining_to_consume)
            total_basis_consumed += consumed * lot.cost_per_unit
            remaining_to_consume -= consumed

        # Prune exhausted lots
        self._lots[asset] = [l for l in lots if not l.is_exhausted]
        return total_basis_consumed

    # ------------------------------------------------------------------ #
    # Querying
    # ------------------------------------------------------------------ #

    def holdings(
        self, prices: Optional[Dict[str, Decimal]] = None
    ) -> List[HoldingSnapshot]:
        """
        Return a snapshot of all non-zero holdings.

        Args:
            prices: optional dict mapping asset symbol -> current USD price.
        """
        snapshots = []
        for asset, lots in self._lots.items():
            open_lots = [l for l in lots if not l.is_exhausted]
            if not open_lots:
                continue
            qty = sum(l.remaining for l in open_lots)
            basis = sum(l.remaining_cost_basis for l in open_lots)
            price = prices.get(asset) if prices else None
            snapshots.append(
                HoldingSnapshot(
                    asset=asset,
                    quantity=qty,
                    total_cost_basis=basis.quantize(Decimal("0.01")),
                    num_lots=len(open_lots),
                    current_price_usd=price,
                )
            )
        return sorted(snapshots, key=lambda s: s.asset)

    def holding(self, asset: str) -> Optional[HoldingSnapshot]:
        for h in self.holdings():
            if h.asset == asset.upper():
                return h
        return None

    def lots_for(self, asset: str) -> List[Lot]:
        return [l for l in self._lots.get(asset.upper(), []) if not l.is_exhausted]

    @property
    def total_cost_basis(self) -> Decimal:
        return sum(h.total_cost_basis for h in self.holdings())

    def total_market_value(self, prices: Dict[str, Decimal]) -> Optional[Decimal]:
        return sum(
            h.market_value_usd
            for h in self.holdings(prices)
            if h.market_value_usd is not None
        )
