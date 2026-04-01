"""
Authentication utilities for the Crypto Accounting System.

Supports two registration modes:
  classic   – username + strong password; seed phrase is a recovery key
  anonymous – seed phrase is the sole credential (no username/password)

Uses only Python stdlib – no extra dependencies.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import os
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional, Tuple

# ------------------------------------------------------------------ #
# Seed-phrase word list (256 words → 8 bits per word, 96-bit entropy
# for a 12-word phrase – comparable to a 128-bit AES key after removal
# of bias).  Words taken from the first 256 entries of BIP-39 English.
# ------------------------------------------------------------------ #

_WORDS: list[str] = [
    "abandon","ability","able","about","above","absent","absorb","abstract",
    "absurd","abuse","access","accident","account","accuse","achieve","acid",
    "acoustic","acquire","across","act","action","actor","actress","actual",
    "adapt","add","addict","address","adjust","admit","adult","advance",
    "advice","aerobic","afford","afraid","again","age","agent","agree",
    "ahead","aim","air","airport","aisle","alarm","album","alcohol",
    "alert","alien","all","alley","allow","almost","alone","alpha",
    "already","also","alter","always","amateur","amazing","among","amount",
    "amused","analyst","anchor","ancient","anger","angle","angry","animal",
    "ankle","announce","annual","another","answer","antenna","antique","anxiety",
    "any","apart","apology","appear","apple","approve","april","arch",
    "arctic","area","arena","argue","arm","armed","armor","army",
    "around","arrange","arrest","arrive","arrow","art","artefact","artist",
    "artwork","ask","aspect","assault","asset","assist","assume","asthma",
    "athlete","atom","attack","attend","attitude","attract","auction","audit",
    "august","aunt","author","auto","autumn","average","avocado","avoid",
    "awake","aware","away","awesome","awful","awkward","axis","baby",
    "balance","bamboo","banana","banner","barely","bargain","barrel","base",
    "basic","basket","battle","beach","bean","beauty","because","become",
    "beef","before","begin","behave","behind","believe","below","belt",
    "bench","benefit","best","betray","better","between","beyond","bicycle",
    "bid","bike","bind","biology","bird","birth","bitter","black",
    "blade","blame","blanket","blast","bleak","bless","blind","blood",
    "blossom","blouse","blue","blur","blush","board","boat","body",
    "boil","bomb","bone","book","boost","border","boring","borrow",
    "boss","bottom","bounce","box","boy","bracket","brain","brand",
    "brave","breeze","brick","bridge","brief","bright","bring","brisk",
    "broccoli","broken","bronze","broom","brother","brown","brush","bubble",
    "buddy","budget","buffalo","build","bulb","bulk","bullet","bundle",
    "bunker","burden","burger","burst","bus","business","busy","butter",
    "buyer","buzz","cabbage","cabin","cable","cactus","cage","cake",
    "call","calm","camera","camp","can","canal","cancel","candy",
]

assert len(_WORDS) == 256, f"Word list must have exactly 256 words, got {len(_WORDS)}"


def generate_seed_phrase(num_words: int = 12) -> str:
    """Return a space-separated, cryptographically random seed phrase."""
    return " ".join(secrets.choice(_WORDS) for _ in range(num_words))


# ------------------------------------------------------------------ #
# Password hashing (PBKDF2-HMAC-SHA-256)
# ------------------------------------------------------------------ #

_PBKDF2_ITERATIONS = 260_000


def hash_password(password: str) -> Tuple[str, str]:
    """Hash *password*.  Returns (hex_hash, hex_salt)."""
    salt = secrets.token_bytes(32)
    key = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return key.hex(), salt.hex()


def verify_password(password: str, stored_hash: str, stored_salt: str) -> bool:
    salt = bytes.fromhex(stored_salt)
    key = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return _hmac.compare_digest(key.hex(), stored_hash)


# ------------------------------------------------------------------ #
# Seed-phrase hashing (for storage and anonymous login verification)
# ------------------------------------------------------------------ #

def hash_seed(seed_phrase: str) -> str:
    """Return a hex SHA-256 digest of the normalised seed phrase."""
    normalised = " ".join(seed_phrase.strip().lower().split())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def verify_seed(seed_phrase: str, stored_hash: str) -> bool:
    return _hmac.compare_digest(hash_seed(seed_phrase), stored_hash)


# ------------------------------------------------------------------ #
# Password-strength checker
# ------------------------------------------------------------------ #

_SPECIAL = set("!@#$%^&*()_+-=[]{}|;':\",./<>?")


def check_password_strength(password: str) -> Tuple[bool, str]:
    """Return (is_strong, message)."""
    if len(password) < 12:
        return False, "At least 12 characters required"
    if not any(c.isupper() for c in password):
        return False, "Must contain at least one uppercase letter"
    if not any(c.islower() for c in password):
        return False, "Must contain at least one lowercase letter"
    if not any(c.isdigit() for c in password):
        return False, "Must contain at least one digit"
    if not any(c in _SPECIAL for c in password):
        return False, "Must contain at least one special character (!@#$%…)"
    return True, "Strong"


# ------------------------------------------------------------------ #
# User account model
# ------------------------------------------------------------------ #

@dataclass
class UserAccount:
    account_type: str           # "classic" | "anonymous"
    username: Optional[str]     # None for anonymous
    password_hash: Optional[str]
    password_salt: Optional[str]
    seed_hash: str              # SHA-256(seed phrase) – always stored
    recovery_email: Optional[str] = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "UserAccount":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ------------------------------------------------------------------ #
# Session tokens (HMAC-SHA-256, no external deps)
# Token format:  <unix_ts>:<random_hex_nonce>:<hmac_hex_signature>
# ------------------------------------------------------------------ #

TOKEN_TTL_SECONDS = 30 * 24 * 3600   # 30 days
_SECRET_KEY: Optional[bytes] = None


def init_secret_key(data_dir: Path) -> None:
    """Load (or generate and persist) the HMAC signing key."""
    global _SECRET_KEY
    key_path = data_dir / "auth_secret.bin"
    if key_path.exists():
        _SECRET_KEY = key_path.read_bytes()
    else:
        _SECRET_KEY = secrets.token_bytes(32)
        key_path.write_bytes(_SECRET_KEY)


def _require_key() -> bytes:
    if _SECRET_KEY is None:
        raise RuntimeError("Auth secret key not initialised — call init_secret_key() first")
    return _SECRET_KEY


def create_session_token() -> str:
    key = _require_key()
    ts = str(int(time.time()))
    nonce = secrets.token_hex(8)
    payload = f"{ts}:{nonce}"
    sig = _hmac.new(key, payload.encode("utf-8"), "sha256").hexdigest()
    return f"{payload}:{sig}"


def verify_session_token(token: str) -> bool:
    """Return True iff the token is well-formed, signed, and not expired."""
    key = _require_key()
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return False
        ts_str, nonce, sig = parts
        ts = int(ts_str)
        if time.time() - ts > TOKEN_TTL_SECONDS:
            return False
        payload = f"{ts_str}:{nonce}"
        expected = _hmac.new(key, payload.encode("utf-8"), "sha256").hexdigest()
        return _hmac.compare_digest(expected, sig)
    except Exception:
        return False
