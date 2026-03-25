"""
Storage abstraction for the Crypto Accounting System.

Two backends:
  - FileStorage   – local filesystem (CSV + JSON), default for development
  - VercelKVStorage – Vercel KV (Redis-backed REST API), used when
                      KV_REST_API_URL and KV_REST_API_TOKEN are set
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional

from .models.transaction import Transaction
from .engine.transaction_store import TransactionStore
from .config import Config


# ------------------------------------------------------------------ #
# Abstract interface
# ------------------------------------------------------------------ #

class Storage(ABC):
    """Minimal persistence interface used by the web app."""

    @abstractmethod
    def load_config(self) -> Config:
        ...

    @abstractmethod
    def save_config(self, cfg: Config) -> None:
        ...

    @abstractmethod
    def load_store(self) -> TransactionStore:
        ...

    @abstractmethod
    def save_store(self, store: TransactionStore) -> None:
        ...


# ------------------------------------------------------------------ #
# File-based backend (local dev / self-hosted)
# ------------------------------------------------------------------ #

class FileStorage(Storage):
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._config_path = data_dir / "config.json"
        self._ledger_path = data_dir / "ledger.csv"
        data_dir.mkdir(parents=True, exist_ok=True)

    def load_config(self) -> Config:
        return Config.load(self._config_path)

    def save_config(self, cfg: Config) -> None:
        cfg.save(self._config_path)

    def load_store(self) -> TransactionStore:
        if self._ledger_path.exists():
            return TransactionStore.load_csv(self._ledger_path)
        return TransactionStore()

    def save_store(self, store: TransactionStore) -> None:
        store.save_csv(self._ledger_path)

    @property
    def data_dir(self) -> Path:
        return self._data_dir


# ------------------------------------------------------------------ #
# Vercel KV backend (serverless – no persistent filesystem)
# ------------------------------------------------------------------ #

class VercelKVStorage(Storage):
    """
    Stores data in Vercel KV (Redis) via the REST API.
    Required env vars:
      KV_REST_API_URL   – e.g. https://xxx.kv.vercel-storage.com
      KV_REST_API_TOKEN – Bearer token
    Keys used:
      transactions  – JSON array of transaction dicts
      config        – JSON object of config dict
    """

    _KEY_TXN = "transactions"
    _KEY_CFG = "config"

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
                data = json.loads(resp.read())
                return data.get("result")
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

    # -- Config --------------------------------------------------------

    def load_config(self) -> Config:
        raw = self._get(self._KEY_CFG)
        if raw:
            try:
                return Config.from_dict(json.loads(raw))
            except Exception:
                pass
        return Config()

    def save_config(self, cfg: Config) -> None:
        self._set(self._KEY_CFG, json.dumps(cfg.to_dict()))

    # -- TransactionStore ----------------------------------------------

    def load_store(self) -> TransactionStore:
        raw = self._get(self._KEY_TXN)
        store = TransactionStore()
        if raw:
            try:
                items = json.loads(raw)
                for d in items:
                    store.add(Transaction.from_dict(d))
            except Exception:
                pass
        return store

    def save_store(self, store: TransactionStore) -> None:
        items = [t.to_dict() for t in store.all()]
        self._set(self._KEY_TXN, json.dumps(items, default=str))


# ------------------------------------------------------------------ #
# Factory
# ------------------------------------------------------------------ #

def get_storage(data_dir: Optional[Path] = None) -> Storage:
    """
    Return the appropriate storage backend:
    - VercelKVStorage if KV_REST_API_URL is set
    - FileStorage otherwise
    """
    if os.environ.get("KV_REST_API_URL") and os.environ.get("KV_REST_API_TOKEN"):
        return VercelKVStorage()
    if data_dir is None:
        data_dir = Path.home() / ".crypto_accounting"
    return FileStorage(data_dir)
