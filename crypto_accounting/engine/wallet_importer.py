"""
WalletImporter – parses CSV exports from major exchanges and wallets
into Transaction objects.

Supported formats
-----------------
- Coinbase           (Advanced Trade CSV / standard CSV)
- Binance            (Trade History & Transaction History CSV)
- Kraken             (Ledger CSV)
- Crypto.com         (App transaction CSV)
- Generic CSV        (configurable column mapping)

Usage::

    importer = WalletImporter()
    transactions = importer.from_coinbase_csv("coinbase_export.csv")
    transactions = importer.from_binance_csv("binance_export.csv")
    transactions = importer.from_generic_csv("my_data.csv", column_map={...})
    transactions = importer.detect_and_import("unknown_export.csv")
"""

from __future__ import annotations

import csv
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Dict, List, Optional

from ..models.transaction import Transaction, TransactionType

log = logging.getLogger(__name__)


def _dec(value: str) -> Optional[Decimal]:
    if not value or value.strip() in ("-", "", "N/A", "n/a"):
        return None
    cleaned = re.sub(r"[,$€£ ]", "", value.strip())
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _parse_date(value: str, fmt: str) -> Optional[datetime]:
    try:
        return datetime.strptime(value.strip(), fmt)
    except (ValueError, AttributeError):
        return None


# ------------------------------------------------------------------ #
# Format detection
# ------------------------------------------------------------------ #

def _detect_format(headers: List[str]) -> Optional[str]:
    h = {h.lower().strip() for h in headers}
    if "transaction type" in h and "asset" in h and "quantity transacted" in h:
        return "coinbase"
    if "order type" in h and "pair" in h and "price" in h and "fee" in h and "vol" in h:
        return "kraken"
    if "side" in h and "executed qty" in h and "avg price" in h:
        return "binance"
    if "transaction description" in h and "transaction kind" in h:
        return "crypto_com"
    return None


# ------------------------------------------------------------------ #
# Main importer class
# ------------------------------------------------------------------ #

class WalletImporter:

    def detect_and_import(self, path: str | Path) -> List[Transaction]:
        """Auto-detect the CSV format and import."""
        path = Path(path)
        with path.open(encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            fmt = _detect_format(reader.fieldnames or [])

        if fmt == "coinbase":
            return self.from_coinbase_csv(path)
        elif fmt == "kraken":
            return self.from_kraken_csv(path)
        elif fmt == "binance":
            return self.from_binance_csv(path)
        elif fmt == "crypto_com":
            return self.from_crypto_com_csv(path)
        else:
            raise ValueError(
                f"Could not detect CSV format. Headers: {reader.fieldnames}\n"
                "Use from_generic_csv() with a column_map instead."
            )

    # ------------------------------------------------------------------ #
    # Coinbase
    # ------------------------------------------------------------------ #

    def from_coinbase_csv(self, path: str | Path) -> List[Transaction]:
        """
        Parse a Coinbase Advanced Trade or standard transaction history CSV.

        Expected columns (Advanced Trade):
          Timestamp, Transaction Type, Asset, Quantity Transacted,
          Price Currency, Price at Transaction, Subtotal, Total (inclusive of fees and/or spread),
          Fees and/or Spread, Notes
        """
        path = Path(path)
        txns: List[Transaction] = []

        with path.open(encoding="utf-8-sig") as fh:
            # Skip preamble lines until header row
            lines = fh.readlines()

        header_idx = 0
        for i, line in enumerate(lines):
            if "Timestamp" in line or "timestamp" in line:
                header_idx = i
                break

        import io
        reader = csv.DictReader(io.StringIO("".join(lines[header_idx:])))

        type_map = {
            "Buy": TransactionType.BUY,
            "Sell": TransactionType.SELL,
            "Receive": TransactionType.RECEIVE,
            "Send": TransactionType.SEND,
            "Rewards Income": TransactionType.INCOME,
            "Staking Income": TransactionType.INCOME,
            "Learning Reward": TransactionType.INCOME,
            "Coinbase Earn": TransactionType.INCOME,
            "Convert": TransactionType.SWAP,
        }

        for row in reader:
            raw_type = row.get("Transaction Type", "").strip()
            txn_type = type_map.get(raw_type)
            if txn_type is None:
                log.warning("Coinbase: skipping unknown type %r", raw_type)
                continue

            date_str = row.get("Timestamp", "").strip()
            dt = (
                _parse_date(date_str, "%Y-%m-%dT%H:%M:%SZ")
                or _parse_date(date_str, "%Y-%m-%d %H:%M:%S %Z")
                or _parse_date(date_str, "%m/%d/%Y")
            )
            if dt is None:
                log.warning("Coinbase: skipping row with bad date %r", date_str)
                continue

            asset = row.get("Asset", "").strip().upper()
            qty = _dec(row.get("Quantity Transacted", ""))
            price = _dec(row.get("Price at Transaction", ""))
            subtotal = _dec(row.get("Subtotal", ""))
            total = _dec(row.get("Total (inclusive of fees and/or spread)", "") or
                         row.get("Total", ""))
            fees = _dec(row.get("Fees and/or Spread", "") or row.get("Fees", ""))
            notes = row.get("Notes", "").strip()

            if not asset or qty is None:
                continue

            txn = Transaction(
                type=txn_type,
                date=dt,
                asset=asset,
                quantity=qty,
                price_usd=price,
                total_usd=subtotal or total,
                fee_usd=fees,
                wallet="Coinbase",
                notes=notes,
            )
            txns.append(txn)

        log.info("Coinbase import: %d transactions from %s", len(txns), path.name)
        return txns

    # ------------------------------------------------------------------ #
    # Binance
    # ------------------------------------------------------------------ #

    def from_binance_csv(self, path: str | Path) -> List[Transaction]:
        """
        Parse a Binance Trade History CSV.

        Expected columns:
          Date(UTC), Pair, Side, Price, Executed, Amount, Fee
        """
        path = Path(path)
        txns: List[Transaction] = []

        with path.open(encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)

            for row in reader:
                date_str = row.get("Date(UTC)", "").strip()
                dt = (
                    _parse_date(date_str, "%Y-%m-%d %H:%M:%S")
                    or _parse_date(date_str, "%Y-%m-%d %H:%M")
                )
                if dt is None:
                    continue

                pair = row.get("Pair", "").strip().upper()   # e.g. "BTCUSDT"
                side = row.get("Side", "").strip().upper()
                txn_type = TransactionType.BUY if side == "BUY" else TransactionType.SELL

                # Parse base/quote from pair
                executed_str = row.get("Executed", "").strip()  # e.g. "0.5BTC"
                amount_str = row.get("Amount", "").strip()       # e.g. "15000USDT"
                fee_str = row.get("Fee", "").strip()             # e.g. "15BNB"

                # Extract numeric and asset parts
                def split_num_asset(s: str):
                    m = re.match(r"([\d.,]+)\s*([A-Z]+)", s.replace(",", ""))
                    if m:
                        return _dec(m.group(1)), m.group(2)
                    return None, None

                qty, base_asset = split_num_asset(executed_str)
                total, quote_asset = split_num_asset(amount_str)
                fee_qty, fee_asset = split_num_asset(fee_str)
                price = _dec(row.get("Price", ""))

                if not base_asset or qty is None:
                    continue

                txn = Transaction(
                    type=txn_type,
                    date=dt,
                    asset=base_asset,
                    quantity=qty,
                    price_usd=price,
                    total_usd=total if quote_asset in ("USDT", "BUSD", "USD") else None,
                    fee_quantity=fee_qty,
                    fee_asset=fee_asset,
                    wallet="Binance",
                )
                txns.append(txn)

        log.info("Binance import: %d transactions from %s", len(txns), path.name)
        return txns

    # ------------------------------------------------------------------ #
    # Kraken
    # ------------------------------------------------------------------ #

    def from_kraken_csv(self, path: str | Path) -> List[Transaction]:
        """
        Parse a Kraken Ledger CSV.

        Expected columns:
          txid, refid, time, type, subtype, aclass, asset, amount, fee, balance
        """
        path = Path(path)
        txns: List[Transaction] = []

        type_map = {
            "buy": TransactionType.BUY,
            "sell": TransactionType.SELL,
            "deposit": TransactionType.TRANSFER_IN,
            "withdrawal": TransactionType.TRANSFER_OUT,
            "receive": TransactionType.RECEIVE,
            "spend": TransactionType.SEND,
            "staking": TransactionType.INCOME,
        }

        with path.open(encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                raw_type = row.get("type", "").strip().lower()
                txn_type = type_map.get(raw_type)
                if txn_type is None:
                    continue

                date_str = row.get("time", "").strip()
                dt = (
                    _parse_date(date_str, "%Y-%m-%d %H:%M:%S")
                    or _parse_date(date_str, "%Y-%m-%dT%H:%M:%S")
                )
                if dt is None:
                    continue

                raw_asset = row.get("asset", "").strip().upper()
                # Kraken uses XXBT, XETH, ZUSD etc.
                asset = _normalize_kraken_asset(raw_asset)
                if asset in ("USD", "EUR", "GBP", "CAD", "AUD", "CHF", "JPY"):
                    continue  # skip fiat ledger entries

                amount = _dec(row.get("amount", ""))
                fee = _dec(row.get("fee", ""))
                tx_hash = row.get("txid", "").strip()

                if amount is None:
                    continue

                qty = abs(amount)
                if qty == 0:
                    continue

                txn = Transaction(
                    type=txn_type,
                    date=dt,
                    asset=asset,
                    quantity=qty,
                    fee_usd=fee,
                    tx_hash=tx_hash or None,
                    wallet="Kraken",
                )
                txns.append(txn)

        log.info("Kraken import: %d transactions from %s", len(txns), path.name)
        return txns

    # ------------------------------------------------------------------ #
    # Crypto.com
    # ------------------------------------------------------------------ #

    def from_crypto_com_csv(self, path: str | Path) -> List[Transaction]:
        """
        Parse a Crypto.com App transaction history CSV.

        Expected columns:
          Timestamp (UTC), Transaction Description, Currency, Amount,
          To Currency, To Amount, Native Currency, Native Amount,
          Native Amount (in USD), Transaction Kind
        """
        path = Path(path)
        txns: List[Transaction] = []

        kind_map = {
            "crypto_purchase": TransactionType.BUY,
            "crypto_exchange": TransactionType.SWAP,
            "viban_purchase": TransactionType.BUY,
            "crypto_withdrawal": TransactionType.TRANSFER_OUT,
            "crypto_deposit": TransactionType.TRANSFER_IN,
            "referral_gift": TransactionType.RECEIVE,
            "mco_stake_reward": TransactionType.INCOME,
            "crypto_earn_interest_paid": TransactionType.INCOME,
            "rewards_platform_deposit_credited": TransactionType.INCOME,
            "supercharger_reward_to_app_credited": TransactionType.INCOME,
            "crypto_earn_program_created": TransactionType.TRANSFER_OUT,
            "crypto_earn_program_withdrawn": TransactionType.TRANSFER_IN,
            "card_cashback_revard": TransactionType.INCOME,
        }

        with path.open(encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                kind = row.get("Transaction Kind", "").strip().lower()
                txn_type = kind_map.get(kind)
                if txn_type is None:
                    log.debug("Crypto.com: skipping kind %r", kind)
                    continue

                date_str = row.get("Timestamp (UTC)", "").strip()
                dt = (
                    _parse_date(date_str, "%Y-%m-%d %H:%M:%S")
                    or _parse_date(date_str, "%Y-%m-%dT%H:%M:%SZ")
                )
                if dt is None:
                    continue

                asset = row.get("Currency", "").strip().upper()
                amount = _dec(row.get("Amount", ""))
                native_usd = _dec(row.get("Native Amount (in USD)", ""))

                if not asset or amount is None:
                    continue

                qty = abs(amount)
                swap_asset = row.get("To Currency", "").strip().upper() or None
                swap_qty = _dec(row.get("To Amount", ""))

                txn = Transaction(
                    type=txn_type,
                    date=dt,
                    asset=asset,
                    quantity=qty,
                    total_usd=native_usd,
                    swap_asset=swap_asset if txn_type == TransactionType.SWAP else None,
                    swap_quantity=swap_qty if txn_type == TransactionType.SWAP else None,
                    wallet="Crypto.com",
                    notes=row.get("Transaction Description", "").strip(),
                )
                txns.append(txn)

        log.info("Crypto.com import: %d transactions from %s", len(txns), path.name)
        return txns

    # ------------------------------------------------------------------ #
    # Generic CSV with column mapping
    # ------------------------------------------------------------------ #

    def from_generic_csv(
        self,
        path: str | Path,
        column_map: Dict[str, str],
        date_format: str = "%Y-%m-%d",
        wallet_name: str = "Import",
        type_map: Optional[Dict[str, TransactionType]] = None,
        default_type: TransactionType = TransactionType.BUY,
    ) -> List[Transaction]:
        """
        Import from any CSV using a column mapping.

        column_map keys (all optional except date, asset, quantity):
          date, type, asset, quantity, price_usd, total_usd,
          fee_usd, fee_asset, fee_quantity, wallet, notes, tx_hash

        Example::

            importer.from_generic_csv("trades.csv", column_map={
                "date": "Trade Date",
                "asset": "Coin",
                "quantity": "Amount",
                "total_usd": "USD Value",
                "type": "Action",
            }, type_map={"Bought": TransactionType.BUY, "Sold": TransactionType.SELL})
        """
        path = Path(path)
        txns: List[Transaction] = []
        _type_map = type_map or {}

        with path.open(encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                def col(key: str) -> str:
                    mapped = column_map.get(key)
                    if not mapped:
                        return ""
                    return row.get(mapped, "").strip()

                date_str = col("date")
                dt = _parse_date(date_str, date_format)
                if dt is None:
                    continue

                asset = col("asset").upper()
                qty = _dec(col("quantity"))
                if not asset or qty is None:
                    continue

                raw_type = col("type")
                txn_type = _type_map.get(raw_type, default_type)

                txn = Transaction(
                    type=txn_type,
                    date=dt,
                    asset=asset,
                    quantity=abs(qty),
                    price_usd=_dec(col("price_usd")),
                    total_usd=_dec(col("total_usd")),
                    fee_usd=_dec(col("fee_usd")),
                    fee_asset=col("fee_asset") or None,
                    fee_quantity=_dec(col("fee_quantity")),
                    wallet=col("wallet") or wallet_name,
                    notes=col("notes") or None,
                    tx_hash=col("tx_hash") or None,
                )
                txns.append(txn)

        log.info("Generic import: %d transactions from %s", len(txns), path.name)
        return txns


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _normalize_kraken_asset(asset: str) -> str:
    """Map Kraken internal asset names to standard symbols."""
    mapping = {
        "XXBT": "BTC", "XBT": "BTC",
        "XETH": "ETH", "ETH": "ETH",
        "XXRP": "XRP", "XRP": "XRP",
        "XLTC": "LTC", "LTC": "LTC",
        "ZUSD": "USD", "ZEUR": "EUR",
        "ZGBP": "GBP", "ZCAD": "CAD",
        "ZAUD": "AUD", "ZJPY": "JPY",
        "XDOT": "DOT",
    }
    return mapping.get(asset, asset.lstrip("XZ"))
