"""
System configuration – base currency, display preferences, data paths.
Persisted as JSON so the web UI can read/write it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

_DEFAULT_CONFIG_PATH = Path.home() / ".crypto_accounting" / "config.json"

# Supported fiat base currencies
SUPPORTED_FIAT = {
    "USD": "US Dollar",
    "EUR": "Euro",
    "GBP": "British Pound",
    "JPY": "Japanese Yen",
    "CAD": "Canadian Dollar",
    "AUD": "Australian Dollar",
    "CHF": "Swiss Franc",
    "CNY": "Chinese Yuan",
    "SEK": "Swedish Krona",
    "NOK": "Norwegian Krone",
    "DKK": "Danish Krone",
    "NZD": "New Zealand Dollar",
    "SGD": "Singapore Dollar",
    "HKD": "Hong Kong Dollar",
    "KRW": "South Korean Won",
    "BRL": "Brazilian Real",
    "INR": "Indian Rupee",
    "MXN": "Mexican Peso",
    "PLN": "Polish Zloty",
    "ZAR": "South African Rand",
}

# Fiat currency symbols for display
FIAT_SYMBOLS = {
    "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥",
    "CAD": "CA$", "AUD": "A$", "CHF": "CHF", "CNY": "¥",
    "SEK": "kr", "NOK": "kr", "DKK": "kr", "NZD": "NZ$",
    "SGD": "S$", "HKD": "HK$", "KRW": "₩", "BRL": "R$",
    "INR": "₹", "MXN": "$", "PLN": "zł", "ZAR": "R",
}


@dataclass
class Config:
    base_currency: str = "USD"
    ledger_path: str = "ledger.csv"
    cost_basis_method: str = "fifo"       # fifo | lifo | hifo
    tax_year_start_month: int = 1         # 1 = January (US/EU), 4 = April (UK)
    include_fees_in_basis: bool = True
    rate_provider: str = "ecb"            # ecb | exchangerate-api | manual
    rate_api_key: Optional[str] = None    # for exchangerate-api
    # Manual override rates: { "EURUSD": 1.08, ... } key = from+to
    manual_rates: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # Derived helpers
    # ------------------------------------------------------------------ #

    @property
    def currency_symbol(self) -> str:
        return FIAT_SYMBOLS.get(self.base_currency, self.base_currency + " ")

    def format_amount(self, amount, decimals: int = 2) -> str:
        sym = self.currency_symbol
        formatted = f"{amount:,.{decimals}f}"
        # Place symbol before or after based on convention
        if self.base_currency in ("SEK", "NOK", "DKK", "PLN"):
            return f"{formatted} {sym}"
        return f"{sym}{formatted}"

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #

    def save(self, path: str | Path = _DEFAULT_CONFIG_PATH) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as fh:
            json.dump(asdict(self), fh, indent=2)

    @classmethod
    def load(cls, path: str | Path = _DEFAULT_CONFIG_PATH) -> "Config":
        path = Path(path)
        if not path.exists():
            return cls()
        with path.open() as fh:
            data = json.load(fh)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
