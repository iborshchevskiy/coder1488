"""
BlockchainImporter – fetches transaction history from public blockchain addresses.

Supported chains / APIs (all free, no API key required for basic use)
----------------------------------------------------------------------
- Tron  (TRC20 tokens + native TRX)  via Tronscan API
- Ethereum  (ERC20 tokens + native ETH)  via Etherscan API  (key optional)
- Bitcoin  via Blockstream.info API

Usage::

    importer = BlockchainImporter()

    # TRC20 USDT on Tron
    txns = importer.from_tron("TYour...Address", tokens=["USDT"])

    # Ethereum address
    txns = importer.from_ethereum("0xYour...Address", etherscan_key="optional")

    # Bitcoin
    txns = importer.from_bitcoin("bc1q...")
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError
from urllib.parse import urlencode

from ..models.transaction import Transaction, TransactionType

log = logging.getLogger(__name__)

# Known TRC20 token contracts → symbol
_TRC20_TOKENS: Dict[str, str] = {
    "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t": "USDT",   # Tether TRC20
    "TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8": "USDC",
    "TAFjULxiVgT4qWk6UZwjqwZXTSaGaqnVp4": "BTT",
    "TLa2f6VPqDgRE67v1736s7bJ8Ray5wYjU7": "WIN",
    "TCFLL5dx5ZJdKnWuesXxi1VPwjLVmWZkyd": "JST",
    "TKfjV9RNKJJCqPvBtK8L7Knykh7DNWvnYt": "WBTC",
}

# Known ERC20 token contracts → symbol
_ERC20_TOKENS: Dict[str, str] = {
    "0xdac17f958d2ee523a2206206994597c13d831ec7": "USDT",
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC",
    "0x6b175474e89094c44da98b954eedeac495271d0f": "DAI",
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": "WBTC",
    "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984": "UNI",
    "0x514910771af9ca656af840dff83e8264ecf986ca": "LINK",
    "0x7d1afa7b718fb893db30a3abc0cfc608aacfebb0": "MATIC",
}

_PAGE_SIZE = 50


class BlockchainImporter:

    def __init__(self, etherscan_api_key: Optional[str] = None) -> None:
        self._etherscan_key = etherscan_api_key or "YourApiKeyToken"
        self._session_headers = {"User-Agent": "crypto-accounting/1.0"}

    # ------------------------------------------------------------------ #
    # Tron / TRC20
    # ------------------------------------------------------------------ #

    def from_tron(
        self,
        address: str,
        tokens: Optional[List[str]] = None,
        include_trx: bool = True,
        max_pages: int = 20,
    ) -> List[Transaction]:
        """
        Fetch TRX and/or TRC20 token transactions for a Tron address.

        Args:
            address:     Tron base58 address (starts with T)
            tokens:      filter to specific symbols, e.g. ["USDT"] — None = all
            include_trx: also fetch native TRX transfers
            max_pages:   safety cap on API pagination
        """
        txns: List[Transaction] = []
        token_filter = {t.upper() for t in tokens} if tokens else None

        # --- TRC20 token transfers ---
        trc20 = self._fetch_trc20_transfers(address, max_pages)
        for raw in trc20:
            txn = self._parse_trc20_transfer(raw, address, token_filter)
            if txn:
                txns.append(txn)

        # --- Native TRX transfers ---
        if include_trx and (token_filter is None or "TRX" in token_filter):
            trx = self._fetch_trx_transfers(address, max_pages)
            for raw in trx:
                txn = self._parse_trx_transfer(raw, address)
                if txn:
                    txns.append(txn)

        txns.sort(key=lambda t: t.date)
        log.info("Tron import: %d transactions for %s", len(txns), address[:10] + "...")
        return txns

    def _fetch_trc20_transfers(self, address: str, max_pages: int) -> List[dict]:
        records = []
        for page in range(max_pages):
            params = urlencode({
                "relatedAddress": address,
                "limit": _PAGE_SIZE,
                "start": page * _PAGE_SIZE,
            })
            url = f"https://apilist.tronscanapi.com/api/token_trc20/transfers?{params}"
            data = self._get_json(url)
            if not data:
                break
            batch = data.get("token_transfers", [])
            records.extend(batch)
            if len(batch) < _PAGE_SIZE:
                break
            time.sleep(0.3)  # rate-limit courtesy
        return records

    def _parse_trc20_transfer(
        self, raw: dict, my_address: str, token_filter: Optional[set]
    ) -> Optional[Transaction]:
        contract = raw.get("contract_address", "")
        symbol = _TRC20_TOKENS.get(contract, raw.get("tokenInfo", {}).get("tokenAbbr", "")).upper()
        if not symbol:
            return None
        if token_filter and symbol not in token_filter:
            return None

        from_addr = raw.get("from_address", "")
        to_addr = raw.get("to_address", "")
        amount_raw = raw.get("quant", "0")
        decimals = int(raw.get("tokenInfo", {}).get("tokenDecimal", 6))
        amount = Decimal(str(amount_raw)) / (10 ** decimals)
        ts = int(raw.get("block_ts", 0)) / 1000
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
        tx_hash = raw.get("transaction_id", "")

        is_incoming = to_addr.lower() == my_address.lower()
        txn_type = TransactionType.TRANSFER_IN if is_incoming else TransactionType.TRANSFER_OUT

        return Transaction(
            type=txn_type,
            date=dt,
            asset=symbol,
            quantity=amount,
            wallet=f"Tron:{my_address[:8]}",
            tx_hash=tx_hash,
            notes=f"TRC20 {'receive' if is_incoming else 'send'} from {from_addr[:8]}…",
        )

    def _fetch_trx_transfers(self, address: str, max_pages: int) -> List[dict]:
        records = []
        for page in range(max_pages):
            params = urlencode({
                "address": address,
                "limit": _PAGE_SIZE,
                "start": page * _PAGE_SIZE,
            })
            url = f"https://apilist.tronscanapi.com/api/transaction?{params}"
            data = self._get_json(url)
            if not data:
                break
            batch = data.get("data", [])
            records.extend(batch)
            if len(batch) < _PAGE_SIZE:
                break
            time.sleep(0.3)
        return records

    def _parse_trx_transfer(self, raw: dict, my_address: str) -> Optional[Transaction]:
        contracts = raw.get("contractData", {})
        amount_sun = Decimal(str(contracts.get("amount", 0)))
        amount_trx = amount_sun / Decimal("1_000_000")
        if amount_trx <= 0:
            return None

        from_addr = contracts.get("owner_address", "")
        to_addr = contracts.get("to_address", "")
        ts = int(raw.get("timestamp", 0)) / 1000
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
        tx_hash = raw.get("hash", "")
        is_incoming = to_addr.lower() == my_address.lower()
        txn_type = TransactionType.TRANSFER_IN if is_incoming else TransactionType.TRANSFER_OUT

        return Transaction(
            type=txn_type,
            date=dt,
            asset="TRX",
            quantity=amount_trx,
            wallet=f"Tron:{my_address[:8]}",
            tx_hash=tx_hash,
        )

    # ------------------------------------------------------------------ #
    # Ethereum / ERC20
    # ------------------------------------------------------------------ #

    def from_ethereum(
        self,
        address: str,
        tokens: Optional[List[str]] = None,
        include_eth: bool = True,
        etherscan_key: Optional[str] = None,
    ) -> List[Transaction]:
        """
        Fetch ETH and ERC20 transactions for an Ethereum address via Etherscan.

        A free Etherscan API key is recommended but not strictly required for small queries.
        """
        key = etherscan_key or self._etherscan_key
        token_filter = {t.upper() for t in tokens} if tokens else None
        txns: List[Transaction] = []

        # --- ERC20 transfers ---
        erc20_raw = self._fetch_etherscan(
            action="tokentx", address=address, api_key=key
        )
        for raw in erc20_raw:
            txn = self._parse_erc20_transfer(raw, address, token_filter)
            if txn:
                txns.append(txn)

        # --- Native ETH transfers ---
        if include_eth and (token_filter is None or "ETH" in token_filter):
            eth_raw = self._fetch_etherscan(
                action="txlist", address=address, api_key=key
            )
            for raw in eth_raw:
                txn = self._parse_eth_transfer(raw, address)
                if txn:
                    txns.append(txn)

        txns.sort(key=lambda t: t.date)
        log.info("Ethereum import: %d transactions for %s", len(txns), address[:10] + "...")
        return txns

    def _fetch_etherscan(self, action: str, address: str, api_key: str) -> List[dict]:
        params = urlencode({
            "module": "account",
            "action": action,
            "address": address,
            "sort": "asc",
            "apikey": api_key,
        })
        url = f"https://api.etherscan.io/api?{params}"
        data = self._get_json(url)
        if data and data.get("status") == "1":
            return data.get("result", [])
        return []

    def _parse_erc20_transfer(
        self, raw: dict, my_address: str, token_filter: Optional[set]
    ) -> Optional[Transaction]:
        symbol = raw.get("tokenSymbol", "").upper()
        if token_filter and symbol not in token_filter:
            return None

        decimals = int(raw.get("tokenDecimal", 18))
        amount = Decimal(raw.get("value", "0")) / (10 ** decimals)
        if amount <= 0:
            return None

        from_addr = raw.get("from", "").lower()
        to_addr = raw.get("to", "").lower()
        dt = datetime.utcfromtimestamp(int(raw.get("timeStamp", 0)))
        tx_hash = raw.get("hash", "")
        is_incoming = to_addr == my_address.lower()
        txn_type = TransactionType.TRANSFER_IN if is_incoming else TransactionType.TRANSFER_OUT

        gas_price = Decimal(raw.get("gasPrice", "0"))
        gas_used = Decimal(raw.get("gasUsed", "0"))
        fee_eth = (gas_price * gas_used) / Decimal("1e18")

        return Transaction(
            type=txn_type,
            date=dt,
            asset=symbol,
            quantity=amount,
            fee_quantity=fee_eth if fee_eth > 0 else None,
            fee_asset="ETH" if fee_eth > 0 else None,
            wallet=f"ETH:{my_address[:8]}",
            tx_hash=tx_hash,
        )

    def _parse_eth_transfer(self, raw: dict, my_address: str) -> Optional[Transaction]:
        amount = Decimal(raw.get("value", "0")) / Decimal("1e18")
        if amount <= 0:
            return None

        from_addr = raw.get("from", "").lower()
        to_addr = raw.get("to", "").lower()
        dt = datetime.utcfromtimestamp(int(raw.get("timeStamp", 0)))
        tx_hash = raw.get("hash", "")
        is_incoming = to_addr == my_address.lower()
        txn_type = TransactionType.TRANSFER_IN if is_incoming else TransactionType.TRANSFER_OUT

        gas = Decimal(raw.get("gasUsed", raw.get("gas", "0")))
        gas_price = Decimal(raw.get("gasPrice", "0"))
        fee_eth = (gas * gas_price) / Decimal("1e18")

        return Transaction(
            type=txn_type,
            date=dt,
            asset="ETH",
            quantity=amount,
            fee_quantity=fee_eth if fee_eth > 0 else None,
            fee_asset="ETH" if fee_eth > 0 else None,
            wallet=f"ETH:{my_address[:8]}",
            tx_hash=tx_hash,
        )

    # ------------------------------------------------------------------ #
    # Bitcoin
    # ------------------------------------------------------------------ #

    def from_bitcoin(self, address: str) -> List[Transaction]:
        """
        Fetch Bitcoin transactions for an address via Blockstream.info (free, no key).
        """
        txns: List[Transaction] = []
        url = f"https://blockstream.info/api/address/{address}/txs"
        data = self._get_json(url, is_list=True)
        if not data:
            return txns

        for raw in data:
            txn = self._parse_btc_tx(raw, address)
            if txn:
                txns.append(txn)

        txns.sort(key=lambda t: t.date)
        log.info("Bitcoin import: %d transactions for %s", len(txns), address[:10] + "...")
        return txns

    def _parse_btc_tx(self, raw: dict, my_address: str) -> Optional[Transaction]:
        status = raw.get("status", {})
        if not status.get("confirmed"):
            return None  # skip unconfirmed

        ts = status.get("block_time", 0)
        dt = datetime.utcfromtimestamp(ts)
        tx_hash = raw.get("txid", "")

        # Calculate net flow for our address
        net_sats = 0
        for inp in raw.get("vin", []):
            prev = inp.get("prevout", {})
            if prev.get("scriptpubkey_address") == my_address:
                net_sats -= prev.get("value", 0)
        for out in raw.get("vout", []):
            if out.get("scriptpubkey_address") == my_address:
                net_sats += out.get("value", 0)

        if net_sats == 0:
            return None

        amount = abs(Decimal(net_sats)) / Decimal("100_000_000")  # satoshis to BTC
        # Estimate fee in BTC
        fee_sats = raw.get("fee", 0)
        fee_btc = Decimal(fee_sats) / Decimal("100_000_000") if fee_sats else None

        is_incoming = net_sats > 0
        txn_type = TransactionType.TRANSFER_IN if is_incoming else TransactionType.TRANSFER_OUT

        return Transaction(
            type=txn_type,
            date=dt,
            asset="BTC",
            quantity=amount,
            fee_quantity=fee_btc,
            fee_asset="BTC" if fee_btc else None,
            wallet=f"BTC:{my_address[:8]}",
            tx_hash=tx_hash,
        )

    # ------------------------------------------------------------------ #
    # Shared HTTP helper
    # ------------------------------------------------------------------ #

    def _get_json(self, url: str, is_list: bool = False):
        try:
            req = Request(url, headers=self._session_headers)
            with urlopen(req, timeout=10) as resp:
                raw = resp.read()
            return json.loads(raw)
        except (URLError, json.JSONDecodeError, Exception) as e:
            log.warning("HTTP error fetching %s: %s", url[:80], e)
            return [] if is_list else None
