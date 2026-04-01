"""
Lot model – a parcel of cryptocurrency acquired at a specific cost basis.
Used by the tax engine to match disposals against acquisitions.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional


@dataclass
class Lot:
    """An acquired parcel of a single asset."""

    asset: str
    quantity: Decimal           # original quantity
    remaining: Decimal          # quantity not yet disposed of
    cost_basis_usd: Decimal     # total cost in USD for original quantity
    acquired_date: datetime
    acquisition_tx_id: str
    wallet: Optional[str] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        for attr in ("quantity", "remaining", "cost_basis_usd"):
            val = getattr(self, attr)
            if not isinstance(val, Decimal):
                setattr(self, attr, Decimal(str(val)))

    @property
    def cost_per_unit(self) -> Decimal:
        if self.quantity == 0:
            return Decimal("0")
        return self.cost_basis_usd / self.quantity

    @property
    def remaining_cost_basis(self) -> Decimal:
        return self.remaining * self.cost_per_unit

    @property
    def is_exhausted(self) -> bool:
        return self.remaining <= Decimal("0")

    def consume(self, amount: Decimal) -> Decimal:
        """
        Consume *amount* from this lot.
        Returns the actual amount consumed (may be less than requested).
        """
        consumed = min(self.remaining, amount)
        self.remaining -= consumed
        return consumed

    def __repr__(self) -> str:
        return (
            f"Lot({self.asset} qty={self.quantity} rem={self.remaining} "
            f"basis={self.cost_basis_usd:.2f} USD acquired={self.acquired_date.date()})"
        )
