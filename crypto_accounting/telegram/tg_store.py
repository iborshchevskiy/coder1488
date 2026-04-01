"""
Telegram-specific data storage.

Stored under these keys (both FileStorage and VercelKV):
  tg:config         – {"token": str, "admin_chat_ids": [int, ...], "webhook_url": str}
  tg:users          – {str(chat_id): UserRecord dict, ...}
  tg:subscriptions  – {wallet_address_lower: [chat_id, ...], ...}
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Any


# ------------------------------------------------------------------ #
# Data models
# ------------------------------------------------------------------ #

@dataclass
class TelegramUser:
    chat_id: int
    username: str = ""
    first_name: str = ""
    language_code: str = "en"
    wallets: List[str] = field(default_factory=list)       # subscribed wallet addresses
    notifications_enabled: bool = True
    is_admin: bool = False
    registered_at: str = ""   # ISO datetime string

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "TelegramUser":
        return cls(
            chat_id=int(d["chat_id"]),
            username=d.get("username", ""),
            first_name=d.get("first_name", ""),
            language_code=d.get("language_code", "en"),
            wallets=d.get("wallets", []),
            notifications_enabled=d.get("notifications_enabled", True),
            is_admin=d.get("is_admin", False),
            registered_at=d.get("registered_at", ""),
        )


@dataclass
class TelegramConfig:
    token: str = ""
    admin_chat_ids: List[int] = field(default_factory=list)
    webhook_url: str = ""
    webhook_secret: str = ""
    notifications_enabled: bool = True

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "TelegramConfig":
        return cls(
            token=d.get("token", os.environ.get("TELEGRAM_BOT_TOKEN", "")),
            admin_chat_ids=[int(x) for x in d.get("admin_chat_ids", [])],
            webhook_url=d.get("webhook_url", ""),
            webhook_secret=d.get("webhook_secret", ""),
            notifications_enabled=d.get("notifications_enabled", True),
        )

    @classmethod
    def default(cls) -> "TelegramConfig":
        return cls(token=os.environ.get("TELEGRAM_BOT_TOKEN", ""))


# ------------------------------------------------------------------ #
# Storage backend (file-based)
# ------------------------------------------------------------------ #

class TelegramFileStore:
    """Persists Telegram data to JSON files in data_dir."""

    def __init__(self, data_dir: Path) -> None:
        self._dir = data_dir / "telegram"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cfg_path = self._dir / "config.json"
        self._users_path = self._dir / "users.json"
        self._subs_path = self._dir / "subscriptions.json"

    # -- Config --------------------------------------------------------

    def load_config(self) -> TelegramConfig:
        if self._cfg_path.exists():
            try:
                return TelegramConfig.from_dict(json.loads(self._cfg_path.read_text()))
            except Exception:
                pass
        return TelegramConfig.default()

    def save_config(self, cfg: TelegramConfig) -> None:
        self._cfg_path.write_text(json.dumps(cfg.to_dict(), indent=2))

    # -- Users ---------------------------------------------------------

    def load_users(self) -> Dict[int, TelegramUser]:
        if self._users_path.exists():
            try:
                raw = json.loads(self._users_path.read_text())
                return {int(k): TelegramUser.from_dict(v) for k, v in raw.items()}
            except Exception:
                pass
        return {}

    def save_users(self, users: Dict[int, TelegramUser]) -> None:
        self._users_path.write_text(
            json.dumps({str(k): v.to_dict() for k, v in users.items()}, indent=2)
        )

    # -- Subscriptions -------------------------------------------------

    def load_subscriptions(self) -> Dict[str, List[int]]:
        """Returns {wallet_address: [chat_id, ...]}"""
        if self._subs_path.exists():
            try:
                return json.loads(self._subs_path.read_text())
            except Exception:
                pass
        return {}

    def save_subscriptions(self, subs: Dict[str, List[int]]) -> None:
        self._subs_path.write_text(json.dumps(subs, indent=2))


# ------------------------------------------------------------------ #
# Storage backend (Vercel KV)
# ------------------------------------------------------------------ #

class TelegramKVStore:
    """Persists Telegram data in Vercel KV."""

    _KEY_CFG = "tg:config"
    _KEY_USERS = "tg:users"
    _KEY_SUBS = "tg:subscriptions"

    def __init__(self) -> None:
        self._url = os.environ["KV_REST_API_URL"].rstrip("/")
        self._token = os.environ["KV_REST_API_TOKEN"]

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    def _get(self, key: str) -> Optional[str]:
        import urllib.request
        req = urllib.request.Request(
            f"{self._url}/get/{key}",
            headers=self._headers(),
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read()).get("result")
        except Exception:
            return None

    def _set(self, key: str, value: str) -> None:
        import urllib.request
        payload = json.dumps({"value": value}).encode()
        req = urllib.request.Request(
            f"{self._url}/set/{key}",
            data=payload,
            headers={**self._headers(), "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()

    def load_config(self) -> TelegramConfig:
        raw = self._get(self._KEY_CFG)
        if raw:
            try:
                return TelegramConfig.from_dict(json.loads(raw))
            except Exception:
                pass
        return TelegramConfig.default()

    def save_config(self, cfg: TelegramConfig) -> None:
        self._set(self._KEY_CFG, json.dumps(cfg.to_dict()))

    def load_users(self) -> Dict[int, TelegramUser]:
        raw = self._get(self._KEY_USERS)
        if raw:
            try:
                data = json.loads(raw)
                return {int(k): TelegramUser.from_dict(v) for k, v in data.items()}
            except Exception:
                pass
        return {}

    def save_users(self, users: Dict[int, TelegramUser]) -> None:
        self._set(self._KEY_USERS, json.dumps({str(k): v.to_dict() for k, v in users.items()}))

    def load_subscriptions(self) -> Dict[str, List[int]]:
        raw = self._get(self._KEY_SUBS)
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return {}

    def save_subscriptions(self, subs: Dict[str, List[int]]) -> None:
        self._set(self._KEY_SUBS, json.dumps(subs))


# ------------------------------------------------------------------ #
# High-level manager
# ------------------------------------------------------------------ #

class TelegramStore:
    """
    High-level Telegram data manager.
    Wraps either TelegramFileStore or TelegramKVStore.
    """

    def __init__(self, backend) -> None:
        self._b = backend
        self._users: Optional[Dict[int, TelegramUser]] = None
        self._subs: Optional[Dict[str, List[int]]] = None
        self._cfg: Optional[TelegramConfig] = None

    # -- Config --------------------------------------------------------

    @property
    def config(self) -> TelegramConfig:
        if self._cfg is None:
            self._cfg = self._b.load_config()
        return self._cfg

    def save_config(self, cfg: TelegramConfig) -> None:
        self._cfg = cfg
        self._b.save_config(cfg)

    # -- Users ---------------------------------------------------------

    @property
    def users(self) -> Dict[int, TelegramUser]:
        if self._users is None:
            self._users = self._b.load_users()
        return self._users

    def get_user(self, chat_id: int) -> Optional[TelegramUser]:
        return self.users.get(chat_id)

    def upsert_user(self, user: TelegramUser) -> None:
        self.users[user.chat_id] = user
        self._b.save_users(self.users)

    def delete_user(self, chat_id: int) -> None:
        self.users.pop(chat_id, None)
        self._b.save_users(self.users)

    # -- Subscriptions -------------------------------------------------

    @property
    def subscriptions(self) -> Dict[str, List[int]]:
        if self._subs is None:
            self._subs = self._b.load_subscriptions()
        return self._subs

    def subscribers_for_wallet(self, address: str) -> List[int]:
        return self.subscriptions.get(address.lower(), [])

    def add_wallet_subscription(self, chat_id: int, address: str) -> None:
        addr = address.lower()
        subs = self.subscriptions
        if addr not in subs:
            subs[addr] = []
        if chat_id not in subs[addr]:
            subs[addr].append(chat_id)
        # Update user's wallet list too
        user = self.get_user(chat_id)
        if user and address not in user.wallets:
            user.wallets.append(address)
            self._b.save_users(self.users)
        self._b.save_subscriptions(subs)

    def remove_wallet_subscription(self, chat_id: int, address: str) -> bool:
        addr = address.lower()
        subs = self.subscriptions
        removed = False
        if addr in subs and chat_id in subs[addr]:
            subs[addr].remove(chat_id)
            removed = True
            if not subs[addr]:
                del subs[addr]
        user = self.get_user(chat_id)
        if user and address in user.wallets:
            user.wallets.remove(address)
            self._b.save_users(self.users)
        if removed:
            self._b.save_subscriptions(subs)
        return removed

    def wallets_for_user(self, chat_id: int) -> List[str]:
        user = self.get_user(chat_id)
        return user.wallets if user else []

    # -- Factory -------------------------------------------------------

    @classmethod
    def from_data_dir(cls, data_dir: Path) -> "TelegramStore":
        return cls(TelegramFileStore(data_dir))

    @classmethod
    def from_kv(cls) -> "TelegramStore":
        return cls(TelegramKVStore())

    @classmethod
    def auto(cls, data_dir: Optional[Path] = None) -> "TelegramStore":
        if os.environ.get("KV_REST_API_URL") and os.environ.get("KV_REST_API_TOKEN"):
            return cls.from_kv()
        if data_dir is None:
            data_dir = Path.home() / ".crypto_accounting"
        return cls.from_data_dir(data_dir)
