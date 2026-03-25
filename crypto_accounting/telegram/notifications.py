"""
Transaction notification formatter and dispatcher.

Called after any transaction is saved — checks subscriptions and
fires Telegram messages to relevant subscribers.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import List, Optional

from ..models.transaction import Transaction, TransactionType
from .bot import TelegramBot
from .tg_store import TelegramStore, TelegramUser

log = logging.getLogger(__name__)

# Icons per transaction type
_TYPE_ICON = {
    TransactionType.BUY:              "🟢 Buy",
    TransactionType.SELL:             "🔴 Sell",
    TransactionType.RECEIVE:          "📥 Received",
    TransactionType.SEND:             "📤 Sent",
    TransactionType.TRANSFER_IN:      "↙️ Transfer In",
    TransactionType.TRANSFER_OUT:     "↗️ Transfer Out",
    TransactionType.MINING:           "⛏️ Mining",
    TransactionType.INCOME:           "💰 Income",
    TransactionType.SWAP:             "🔄 Swap",
    TransactionType.FEE:              "💸 Fee",
    TransactionType.FIAT_DEPOSIT:     "🏦 Fiat Deposit",
    TransactionType.FIAT_WITHDRAWAL:  "🏧 Fiat Withdrawal",
}

_INBOUND = {
    TransactionType.BUY,
    TransactionType.RECEIVE,
    TransactionType.TRANSFER_IN,
    TransactionType.MINING,
    TransactionType.INCOME,
    TransactionType.FIAT_DEPOSIT,
}


def _fmt(value: Optional[Decimal], decimals: int = 6) -> str:
    if value is None:
        return "—"
    # Trim trailing zeros but keep minimum decimals
    s = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return s


def _truncate_hash(h: str, n: int = 12) -> str:
    if not h or len(h) <= n * 2 + 3:
        return h
    return f"{h[:n]}…{h[-n:]}"


def format_transaction_notification(txn: Transaction) -> str:
    """Build a human-readable Telegram HTML notification for a transaction."""
    label = _TYPE_ICON.get(txn.type, str(txn.type.value))
    direction = "+" if txn.type in _INBOUND else "-"
    amount_line = f"{direction}{_fmt(txn.quantity)} {txn.asset}"

    lines = [
        f"<b>{label}</b>",
        "",
        f"💱 <b>{amount_line}</b>",
    ]

    if txn.price_usd:
        lines.append(f"💵 Price: ${_fmt(txn.price_usd, 4)}/unit")

    if txn.total_usd:
        lines.append(f"💵 Total: ${_fmt(txn.total_usd, 2)}")
    elif txn.fiat_amount and txn.fiat_currency:
        lines.append(f"💵 Total: {_fmt(txn.fiat_amount, 2)} {txn.fiat_currency}")

    if txn.fee_usd:
        lines.append(f"🔧 Fee: ${_fmt(txn.fee_usd, 4)}")

    if txn.wallet:
        lines.append(f"👛 Wallet: <code>{txn.wallet}</code>")

    lines.append(f"📅 {txn.date.strftime('%Y-%m-%d %H:%M UTC')}")

    if txn.tx_hash:
        lines.append(f"🔗 TX: <code>{_truncate_hash(txn.tx_hash)}</code>")

    if txn.notes:
        lines.append(f"📝 {txn.notes}")

    # Swap details
    if txn.type == TransactionType.SWAP and txn.swap_asset:
        lines.append(f"↔️ Swapped to: {_fmt(txn.swap_quantity)} {txn.swap_asset}")

    return "\n".join(lines)


def format_summary_notification(txns: List[Transaction], imported: int, skipped: int) -> str:
    """Brief summary after a bulk import."""
    lines = [
        f"📊 <b>Import Complete</b>",
        f"✅ {imported} new transactions added",
    ]
    if skipped:
        lines.append(f"⏭️ {skipped} duplicates skipped")
    if txns:
        assets = list({t.asset for t in txns})[:5]
        lines.append(f"💱 Assets: {', '.join(assets)}")
    return "\n".join(lines)


class NotificationDispatcher:
    """
    Sends Telegram notifications to subscribers whose wallet appears
    in a transaction's wallet field or tx_hash.
    """

    def __init__(self, bot: TelegramBot, tg_store: TelegramStore) -> None:
        self.bot = bot
        self.tg_store = tg_store

    def notify_transaction(self, txn: Transaction) -> int:
        """
        Send notification for a single transaction.
        Matches against txn.wallet.
        Returns number of notifications sent.
        """
        if not self.tg_store.config.notifications_enabled:
            return 0
        if not txn.wallet:
            return 0

        subscribers = self.tg_store.subscribers_for_wallet(txn.wallet)
        if not subscribers:
            # Also try lowercase
            subscribers = self.tg_store.subscribers_for_wallet(txn.wallet.lower())

        if not subscribers:
            return 0

        text = format_transaction_notification(txn)
        sent = 0
        for chat_id in subscribers:
            user = self.tg_store.get_user(chat_id)
            if user and not user.notifications_enabled:
                continue
            result = self.bot.send_message(chat_id, text)
            if result.get("ok"):
                sent += 1
            else:
                log.warning("Failed to notify %s: %s", chat_id, result.get("description"))
        return sent

    def notify_transactions(self, txns: List[Transaction]) -> int:
        """Notify for a list of transactions (e.g. after bulk import)."""
        total = 0
        for txn in txns:
            total += self.notify_transaction(txn)
        return total

    def notify_import_summary(
        self,
        admin_chat_ids: List[int],
        txns: List[Transaction],
        imported: int,
        skipped: int,
    ) -> None:
        """Send import summary to admin chat IDs."""
        if not admin_chat_ids:
            return
        text = format_summary_notification(txns, imported, skipped)
        for cid in admin_chat_ids:
            self.bot.send_message(cid, text)
