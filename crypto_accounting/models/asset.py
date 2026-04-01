"""
Asset model – metadata about a cryptocurrency.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Asset:
    symbol: str           # e.g. "BTC"
    name: str             # e.g. "Bitcoin"
    decimals: int = 8     # precision used for display
    coingecko_id: Optional[str] = None  # for price lookups
    tags: list = field(default_factory=list)  # e.g. ["defi", "l2"]

    def __str__(self) -> str:
        return f"{self.name} ({self.symbol})"


# Built-in registry of common assets
COMMON_ASSETS: dict[str, Asset] = {
    "BTC":  Asset("BTC",  "Bitcoin",         8, "bitcoin"),
    "ETH":  Asset("ETH",  "Ethereum",        18, "ethereum"),
    "BNB":  Asset("BNB",  "BNB",             18, "binancecoin"),
    "SOL":  Asset("SOL",  "Solana",           9, "solana"),
    "ADA":  Asset("ADA",  "Cardano",          6, "cardano"),
    "XRP":  Asset("XRP",  "XRP",              6, "ripple"),
    "DOT":  Asset("DOT",  "Polkadot",        10, "polkadot"),
    "DOGE": Asset("DOGE", "Dogecoin",         8, "dogecoin"),
    "AVAX": Asset("AVAX", "Avalanche",       18, "avalanche-2"),
    "MATIC":Asset("MATIC","Polygon",         18, "matic-network"),
    "LINK": Asset("LINK", "Chainlink",       18, "chainlink"),
    "UNI":  Asset("UNI",  "Uniswap",         18, "uniswap"),
    "USDT": Asset("USDT", "Tether",           6, "tether",      ["stablecoin"]),
    "USDC": Asset("USDC", "USD Coin",         6, "usd-coin",    ["stablecoin"]),
    "DAI":  Asset("DAI",  "Dai",             18, "dai",         ["stablecoin"]),
}
