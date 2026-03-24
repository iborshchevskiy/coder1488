"""
Wallet model – represents an exchange account or on-chain address.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Wallet:
    name: str
    address: Optional[str] = None      # blockchain address
    exchange: Optional[str] = None     # e.g. "Coinbase", "Binance"
    chain: Optional[str] = None        # e.g. "Ethereum", "Bitcoin"
    notes: Optional[str] = None
    tags: list = field(default_factory=list)

    def __str__(self) -> str:
        parts = [self.name]
        if self.exchange:
            parts.append(f"({self.exchange})")
        if self.address:
            parts.append(self.address[:8] + "...")
        return " ".join(parts)
