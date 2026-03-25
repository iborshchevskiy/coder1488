"""
Telegram bot command handlers.

Supported commands (user):
  /start              – register & welcome
  /help               – list commands
  /addwallet <addr>   – subscribe to wallet notifications
  /removewallet <addr>– unsubscribe from wallet
  /wallets            – list subscribed wallets
  /notifications on|off – toggle notifications

Supported commands (admin only):
  /admin users        – list all registered users
  /admin broadcast <msg> – send message to all users
  /admin setwebook <url> – configure webhook
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from .bot import TelegramBot, build_keyboard
from .tg_store import TelegramStore, TelegramUser

log = logging.getLogger(__name__)

_USER_KEYBOARD = [
    ["/wallets", "/help"],
]

_WELCOME = (
    "👋 <b>Welcome to Crypto Accounting Bot!</b>\n\n"
    "I'll send you real-time notifications for transactions on your watched wallets.\n\n"
    "<b>Commands:</b>\n"
    "• /addwallet <code>&lt;address&gt;</code> — track a wallet\n"
    "• /removewallet <code>&lt;address&gt;</code> — stop tracking\n"
    "• /wallets — list your wallets\n"
    "• /notifications on|off — pause/resume alerts\n"
    "• /help — show this message"
)


class BotHandlers:
    def __init__(self, bot: TelegramBot, store: TelegramStore) -> None:
        self.bot = bot
        self.store = store

    # ------------------------------------------------------------------ #
    # Entry point
    # ------------------------------------------------------------------ #

    def handle_update(self, update: Dict[str, Any]) -> None:
        """Route an incoming Telegram update."""
        msg = update.get("message")
        if not msg:
            return
        text: str = msg.get("text", "").strip()
        chat = msg.get("chat", {})
        chat_id: int = chat["id"]
        from_user = msg.get("from", {})

        # Ensure user exists
        user = self._ensure_user(chat_id, from_user)

        if not text.startswith("/"):
            return

        parts = text.split(None, 2)
        cmd = parts[0].lower().split("@")[0]  # strip @botname
        args = parts[1:] if len(parts) > 1 else []

        if cmd == "/start":
            self._cmd_start(user)
        elif cmd == "/help":
            self._cmd_help(user)
        elif cmd == "/addwallet":
            self._cmd_addwallet(user, args)
        elif cmd == "/removewallet":
            self._cmd_removewallet(user, args)
        elif cmd == "/wallets":
            self._cmd_wallets(user)
        elif cmd == "/notifications":
            self._cmd_notifications(user, args)
        elif cmd == "/admin":
            self._cmd_admin(user, args)
        else:
            self.bot.send_message(chat_id, "Unknown command. Try /help")

    # ------------------------------------------------------------------ #
    # User helpers
    # ------------------------------------------------------------------ #

    def _ensure_user(self, chat_id: int, from_user: Dict) -> TelegramUser:
        user = self.store.get_user(chat_id)
        if user is None:
            cfg = self.store.config
            user = TelegramUser(
                chat_id=chat_id,
                username=from_user.get("username", ""),
                first_name=from_user.get("first_name", ""),
                language_code=from_user.get("language_code", "en"),
                is_admin=(chat_id in cfg.admin_chat_ids),
                registered_at=datetime.now(timezone.utc).isoformat(),
            )
            self.store.upsert_user(user)
        return user

    # ------------------------------------------------------------------ #
    # Commands – regular users
    # ------------------------------------------------------------------ #

    def _cmd_start(self, user: TelegramUser) -> None:
        self.bot.send_message(
            user.chat_id,
            _WELCOME,
            reply_markup=build_keyboard(_USER_KEYBOARD),
        )

    def _cmd_help(self, user: TelegramUser) -> None:
        self.bot.send_message(user.chat_id, _WELCOME)

    def _cmd_addwallet(self, user: TelegramUser, args) -> None:
        if not args:
            self.bot.send_message(
                user.chat_id,
                "Usage: /addwallet <code>&lt;wallet_address&gt;</code>\n"
                "Example: <code>/addwallet TRxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx</code>",
            )
            return
        address = args[0].strip()
        if len(address) < 10:
            self.bot.send_message(user.chat_id, "⚠️ That doesn't look like a valid wallet address.")
            return
        if address in user.wallets:
            self.bot.send_message(user.chat_id, f"ℹ️ You're already tracking <code>{address}</code>.")
            return
        if len(user.wallets) >= 20:
            self.bot.send_message(user.chat_id, "⚠️ You can track a maximum of 20 wallets.")
            return
        self.store.add_wallet_subscription(user.chat_id, address)
        self.bot.send_message(
            user.chat_id,
            f"✅ Now tracking wallet:\n<code>{address}</code>\n\n"
            "You'll receive notifications for all incoming and outgoing transactions.",
        )

    def _cmd_removewallet(self, user: TelegramUser, args) -> None:
        if not args:
            self.bot.send_message(
                user.chat_id,
                "Usage: /removewallet <code>&lt;wallet_address&gt;</code>",
            )
            return
        address = args[0].strip()
        removed = self.store.remove_wallet_subscription(user.chat_id, address)
        if removed:
            self.bot.send_message(
                user.chat_id,
                f"🗑️ Stopped tracking:\n<code>{address}</code>",
            )
        else:
            self.bot.send_message(
                user.chat_id,
                f"ℹ️ You weren't tracking <code>{address}</code>.",
            )

    def _cmd_wallets(self, user: TelegramUser) -> None:
        wallets = self.store.wallets_for_user(user.chat_id)
        if not wallets:
            self.bot.send_message(
                user.chat_id,
                "You have no wallets tracked yet.\n"
                "Use /addwallet &lt;address&gt; to start.",
            )
            return
        lines = [f"<b>Your tracked wallets ({len(wallets)}):</b>"]
        for i, addr in enumerate(wallets, 1):
            lines.append(f"{i}. <code>{addr}</code>")
        notif = "🔔 ON" if user.notifications_enabled else "🔕 OFF"
        lines.append(f"\nNotifications: {notif}")
        self.bot.send_message(user.chat_id, "\n".join(lines))

    def _cmd_notifications(self, user: TelegramUser, args) -> None:
        if not args:
            state = "ON 🔔" if user.notifications_enabled else "OFF 🔕"
            self.bot.send_message(
                user.chat_id,
                f"Notifications are currently <b>{state}</b>.\n"
                "Use /notifications on or /notifications off to change.",
            )
            return
        flag = args[0].lower()
        if flag == "on":
            user.notifications_enabled = True
            self.store.upsert_user(user)
            self.bot.send_message(user.chat_id, "🔔 Notifications <b>enabled</b>.")
        elif flag == "off":
            user.notifications_enabled = False
            self.store.upsert_user(user)
            self.bot.send_message(user.chat_id, "🔕 Notifications <b>disabled</b>.")
        else:
            self.bot.send_message(user.chat_id, "Usage: /notifications on|off")

    # ------------------------------------------------------------------ #
    # Commands – admin only
    # ------------------------------------------------------------------ #

    def _cmd_admin(self, user: TelegramUser, args) -> None:
        if not user.is_admin:
            self.bot.send_message(user.chat_id, "⛔ Admin access required.")
            return
        if not args:
            self.bot.send_message(
                user.chat_id,
                "<b>Admin commands:</b>\n"
                "/admin users — list all users\n"
                "/admin broadcast &lt;message&gt; — message all users\n"
                "/admin setwebhook &lt;url&gt; — configure webhook",
            )
            return
        sub = args[0].lower()
        rest = args[1] if len(args) > 1 else ""

        if sub == "users":
            self._admin_users(user)
        elif sub == "broadcast":
            self._admin_broadcast(user, rest)
        elif sub == "setwebhook":
            self._admin_setwebhook(user, rest)
        else:
            self.bot.send_message(user.chat_id, f"Unknown admin sub-command: {sub}")

    def _admin_users(self, admin: TelegramUser) -> None:
        users = list(self.store.users.values())
        if not users:
            self.bot.send_message(admin.chat_id, "No registered users yet.")
            return
        lines = [f"<b>Registered users ({len(users)}):</b>"]
        for u in users:
            name = u.username or u.first_name or str(u.chat_id)
            wallets = len(u.wallets)
            notif = "🔔" if u.notifications_enabled else "🔕"
            admin_tag = " 👑" if u.is_admin else ""
            lines.append(f"• @{name}{admin_tag} — {wallets} wallet(s) {notif}")
        self.bot.send_message(admin.chat_id, "\n".join(lines))

    def _admin_broadcast(self, admin: TelegramUser, message: str) -> None:
        if not message:
            self.bot.send_message(admin.chat_id, "Usage: /admin broadcast &lt;message&gt;")
            return
        users = list(self.store.users.values())
        sent = 0
        for u in users:
            result = self.bot.send_message(u.chat_id, f"📢 {message}")
            if result.get("ok"):
                sent += 1
        self.bot.send_message(admin.chat_id, f"✅ Broadcast sent to {sent}/{len(users)} users.")

    def _admin_setwebhook(self, admin: TelegramUser, url: str) -> None:
        if not url:
            self.bot.send_message(admin.chat_id, "Usage: /admin setwebhook &lt;https://your-app.vercel.app/api/telegram/webhook&gt;")
            return
        cfg = self.store.config
        result = self.bot.set_webhook(url, secret_token=cfg.webhook_secret or None)
        if result.get("ok"):
            cfg.webhook_url = url
            self.store.save_config(cfg)
            self.bot.send_message(admin.chat_id, f"✅ Webhook set to:\n<code>{url}</code>")
        else:
            self.bot.send_message(admin.chat_id, f"❌ Failed: {result.get('description')}")
