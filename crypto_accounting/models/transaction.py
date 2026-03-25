"""
Transaction model for the crypto accounting system.
Represents a single event affecting crypto or fiat holdings.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional


class TransactionType(str, Enum):
    BUY = "buy"                        # fiat → crypto (acquisition)
    SELL = "sell"                      # crypto → fiat (disposal)
    RECEIVE = "receive"                # gift / airdrop / fork received
    SEND = "send"                      # gift / donation sent
    TRANSFER_IN = "transfer_in"        # move between own wallets (incoming)
    TRANSFER_OUT = "transfer_out"      # move between own wallets (outgoing)
    MINING = "mining"                  # block reward / staking reward
    INCOME = "income"                  # payment for services in crypto
    SWAP = "swap"                      # crypto ↔ crypto exchange
    FEE = "fee"                        # standalone network/trading fee
    FIAT_DEPOSIT = "fiat_deposit"      # fiat deposited to exchange (not taxable)
    FIAT_WITHDRAWAL = "fiat_withdrawal"# fiat withdrawn from exchange (not taxable)


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

# Fiat-only transaction types (no crypto asset involved)
FIAT_ONLY_TYPES = {TransactionType.FIAT_DEPOSIT, TransactionType.FIAT_WITHDRAWAL}


@dataclass
class Transaction:
    """A single crypto or fiat transaction."""

    type: TransactionType
    date: datetime
    asset: str                         # crypto symbol or "FIAT" for pure fiat events
    quantity: Decimal                  # amount of the primary asset

    # USD equivalents (used for tax calculations and reporting)
    price_usd: Optional[Decimal] = None    # price per crypto unit in USD at the time
    total_usd: Optional[Decimal] = None    # total value in USD (auto-computed if missing)
    fee_usd: Optional[Decimal] = None      # trading / network fee in USD

    # Fee paid in a different asset
    fee_asset: Optional[str] = None
    fee_quantity: Optional[Decimal] = None

    # Fiat side of a BUY or SELL
    # e.g. "bought 0.5 BTC for 23 000 EUR" → fiat_currency="EUR", fiat_amount=23000
    fiat_currency: Optional[str] = None   # ISO 4217 code, e.g. "EUR", "GBP"
    fiat_amount: Optional[Decimal] = None # amount of fiat spent (BUY) or received (SELL)
    # Exchange rate at execution time: 1 fiat_currency = fx_rate_to_usd USD
    # Used to derive total_usd when it is not provided directly.
    fx_rate_to_usd: Optional[Decimal] = None

    # For SWAP: the asset and quantity received
    swap_asset: Optional[str] = None
    swap_quantity: Optional[Decimal] = None

    wallet: Optional[str] = None          # wallet / exchange name
    notes: Optional[str] = None
    tx_hash: Optional[str] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        _decimal_fields = (
            "quantity", "price_usd", "total_usd", "fee_usd",
            "fee_quantity", "swap_quantity", "fiat_amount", "fx_rate_to_usd",
        )
        for attr in _decimal_fields:
            val = getattr(self, attr)
            if val is not None and not isinstance(val, Decimal):
                setattr(self, attr, Decimal(str(val)))

        # Derive total_usd from fiat_amount * fx_rate_to_usd if available
        if self.total_usd is None and self.fiat_amount is not None and self.fx_rate_to_usd is not None:
            self.total_usd = (self.fiat_amount * self.fx_rate_to_usd).quantize(Decimal("0.01"))

        # Fall back to quantity * price_usd
        if self.total_usd is None and self.price_usd is not None:
            self.total_usd = (self.quantity * self.price_usd).quantize(Decimal("0.01"))

    # ------------------------------------------------------------------ #
    # Convenience properties
    # ------------------------------------------------------------------ #

    @property
    def is_disposal(self) -> bool:
        return self.type in DISPOSAL_TYPES

    @property
    def is_acquisition(self) -> bool:
        return self.type in ACQUISITION_TYPES

    @property
    def is_fiat_only(self) -> bool:
        """True for pure fiat movements (deposit / withdrawal) — no crypto involved."""
        return self.type in FIAT_ONLY_TYPES

    @property
    def cost_basis_usd(self) -> Optional[Decimal]:
        """Cost basis for an acquisition (total paid, including buy-side fees)."""
        if not self.is_acquisition:
            return None
        base = self.total_usd or Decimal("0")
        fee = self.fee_usd or Decimal("0")
        return base + fee

    @property
    def proceeds_usd(self) -> Optional[Decimal]:
        """Net proceeds for a disposal (total received minus sell-side fees)."""
        if not self.is_disposal:
            return None
        base = self.total_usd or Decimal("0")
        fee = self.fee_usd or Decimal("0")
        return base - fee

    @property
    def fiat_display(self) -> Optional[str]:
        """Human-readable fiat side, e.g. '23,000.00 EUR'."""
        if self.fiat_currency and self.fiat_amount is not None:
            return f"{self.fiat_amount:,.2f} {self.fiat_currency}"
        return None

    # ------------------------------------------------------------------ #
    # Serialisation
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict:
        def _s(v) -> str:
            return str(v) if v is not None else ""

        return {
            "id": self.id,
            "type": self.type.value,
            "date": self.date.isoformat(),
            "asset": self.asset,
            "quantity": str(self.quantity),
            "price_usd": _s(self.price_usd),
            "total_usd": _s(self.total_usd),
            "fee_usd": _s(self.fee_usd),
            "fee_asset": self.fee_asset or "",
            "fee_quantity": _s(self.fee_quantity),
            "fiat_currency": self.fiat_currency or "",
            "fiat_amount": _s(self.fiat_amount),
            "fx_rate_to_usd": _s(self.fx_rate_to_usd),
            "swap_asset": self.swap_asset or "",
            "swap_quantity": _s(self.swap_quantity),
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
            fiat_currency=data.get("fiat_currency") or None,
            fiat_amount=_dec(data.get("fiat_amount", "")),
            fx_rate_to_usd=_dec(data.get("fx_rate_to_usd", "")),
            swap_asset=data.get("swap_asset") or None,
            swap_quantity=_dec(data.get("swap_quantity", "")),
            wallet=data.get("wallet") or None,
            notes=data.get("notes") or None,
            tx_hash=data.get("tx_hash") or None,
        )

    def __repr__(self) -> str:
        fiat_part = f" ({self.fiat_display})" if self.fiat_display else ""
        return (
            f"Transaction({self.type.value} {self.quantity} {self.asset}"
            f"{fiat_part} @ {self.date.date()} total_usd={self.total_usd})"
        )
