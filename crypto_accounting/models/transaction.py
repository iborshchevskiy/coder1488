"""
Transaction model for the crypto accounting system.
Represents a single event affecting crypto holdings.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional


class TransactionType(str, Enum):
    BUY = "buy"
    SELL = "sell"
    RECEIVE = "receive"          # gift / airdrop / fork received
    SEND = "send"                # gift / donation sent
    TRANSFER_IN = "transfer_in"  # move between own wallets (incoming)
    TRANSFER_OUT = "transfer_out"  # move between own wallets (outgoing)
    MINING = "mining"            # block reward / staking reward
    INCOME = "income"            # payment for services in crypto
    SWAP = "swap"                # one coin directly exchanged for another
    FEE = "fee"                  # standalone fee transaction


# Transaction types that are taxable disposal events
DISPOSAL_TYPES = {TransactionType.SELL, TransactionType.SEND, TransactionType.SWAP}

# Transaction types that create a new cost-basis lot
ACQUISITION_TYPES = {
    TransactionType.BUY,
    TransactionType.RECEIVE,
    TransactionType.TRANSFER_IN,
    TransactionType.MINING,
    TransactionType.INCOME,
    TransactionType.SWAP,
}


@dataclass
class Transaction:
    """A single crypto transaction."""

    type: TransactionType
    date: datetime
    asset: str                        # e.g. "BTC", "ETH"
    quantity: Decimal                 # amount of the primary asset

    # Optional fields
    price_usd: Optional[Decimal] = None    # price per unit in USD at the time
    total_usd: Optional[Decimal] = None    # total value in USD (auto-computed if missing)
    fee_usd: Optional[Decimal] = None      # trading / network fee in USD
    fee_asset: Optional[str] = None        # asset the fee was paid in
    fee_quantity: Optional[Decimal] = None # amount of fee_asset spent on fees

    # For SWAPs: the asset and quantity received
    swap_asset: Optional[str] = None
    swap_quantity: Optional[Decimal] = None

    wallet: Optional[str] = None          # wallet / exchange name
    notes: Optional[str] = None
    tx_hash: Optional[str] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        # Coerce numeric types to Decimal for precision
        for attr in ("quantity", "price_usd", "total_usd", "fee_usd",
                     "fee_quantity", "swap_quantity"):
            val = getattr(self, attr)
            if val is not None and not isinstance(val, Decimal):
                setattr(self, attr, Decimal(str(val)))

        # Compute total_usd from quantity * price_usd when not provided
        if self.total_usd is None and self.price_usd is not None:
            self.total_usd = (self.quantity * self.price_usd).quantize(Decimal("0.01"))

    @property
    def is_disposal(self) -> bool:
        return self.type in DISPOSAL_TYPES

    @property
    def is_acquisition(self) -> bool:
        return self.type in ACQUISITION_TYPES

    @property
    def cost_basis_usd(self) -> Optional[Decimal]:
        """Cost basis for an acquisition (total paid, including fees)."""
        if not self.is_acquisition:
            return None
        base = self.total_usd or Decimal("0")
        fee = self.fee_usd or Decimal("0")
        return base + fee

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "date": self.date.isoformat(),
            "asset": self.asset,
            "quantity": str(self.quantity),
            "price_usd": str(self.price_usd) if self.price_usd is not None else "",
            "total_usd": str(self.total_usd) if self.total_usd is not None else "",
            "fee_usd": str(self.fee_usd) if self.fee_usd is not None else "",
            "fee_asset": self.fee_asset or "",
            "fee_quantity": str(self.fee_quantity) if self.fee_quantity is not None else "",
            "swap_asset": self.swap_asset or "",
            "swap_quantity": str(self.swap_quantity) if self.swap_quantity is not None else "",
            "wallet": self.wallet or "",
            "notes": self.notes or "",
            "tx_hash": self.tx_hash or "",
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Transaction":
        def _dec(v: str) -> Optional[Decimal]:
            return Decimal(v) if v else None

        return cls(
            id=data.get("id", str(uuid.uuid4())),
            type=TransactionType(data["type"]),
            date=datetime.fromisoformat(data["date"]),
            asset=data["asset"],
            quantity=Decimal(data["quantity"]),
            price_usd=_dec(data.get("price_usd", "")),
            total_usd=_dec(data.get("total_usd", "")),
            fee_usd=_dec(data.get("fee_usd", "")),
            fee_asset=data.get("fee_asset") or None,
            fee_quantity=_dec(data.get("fee_quantity", "")),
            swap_asset=data.get("swap_asset") or None,
            swap_quantity=_dec(data.get("swap_quantity", "")),
            wallet=data.get("wallet") or None,
            notes=data.get("notes") or None,
            tx_hash=data.get("tx_hash") or None,
        )

    def __repr__(self) -> str:
        return (
            f"Transaction({self.type.value} {self.quantity} {self.asset} "
            f"@ {self.date.date()} total={self.total_usd} USD)"
        )
