"""Локальные секреты приложения."""

from __future__ import annotations

import os
import secrets
import base64
import hashlib
import hmac
import json
from pathlib import Path


def load_or_create_app_secret(path: Path) -> bytes:
    """Возвращает постоянный локальный секрет, не печатая его в логах."""
    if path.exists():
        return path.read_bytes()
    secret = secrets.token_bytes(32)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        return path.read_bytes()
    with os.fdopen(descriptor, "wb") as secret_file:
        secret_file.write(secret)
    return secret


def hash_pin(pin: str) -> str:
    """Хеширует числовой PIN с солью; открытый PIN не сохраняется."""
    if not pin.isascii() or not pin.isdecimal() or not 4 <= len(pin) <= 12:
        raise ValueError("PIN должен состоять из 4–12 цифр.")
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(pin.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    encoded_salt = base64.urlsafe_b64encode(salt).decode("ascii")
    encoded_hash = base64.urlsafe_b64encode(derived).decode("ascii")
    return f"scrypt$16384$8$1${encoded_salt}${encoded_hash}"


def verify_pin(pin: str, stored_hash: str) -> bool:
    try:
        algorithm, raw_n, raw_r, raw_p, raw_salt, raw_hash = stored_hash.split("$", 5)
        if algorithm != "scrypt" or not pin.isascii() or not pin.isdecimal():
            return False
        salt = base64.urlsafe_b64decode(raw_salt.encode("ascii"))
        expected = base64.urlsafe_b64decode(raw_hash.encode("ascii"))
        actual = hashlib.scrypt(
            pin.encode("utf-8"), salt=salt, n=int(raw_n), r=int(raw_r), p=int(raw_p), dklen=len(expected)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, UnicodeError):
        return False


def sign_session(tournament_id: int, secret: bytes) -> str:
    payload = json.dumps({"tournament_id": tournament_id}, separators=(",", ":")).encode()
    signature = hmac.new(secret, payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload + b"." + signature).decode("ascii")


def read_session(value: str | None, secret: bytes) -> int | None:
    try:
        raw = base64.urlsafe_b64decode((value or "").encode("ascii"))
        # Подпись — ровно 32 байта и сама может содержать b".", поэтому делим по длине, а не по точке.
        signature_size = hashlib.sha256().digest_size
        if len(raw) <= signature_size + 1 or raw[-signature_size - 1 : -signature_size] != b".":
            return None
        payload, signature = raw[: -signature_size - 1], raw[-signature_size:]
        if not hmac.compare_digest(signature, hmac.new(secret, payload, hashlib.sha256).digest()):
            return None
        return int(json.loads(payload)["tournament_id"])
    except (ValueError, KeyError, TypeError, UnicodeError, json.JSONDecodeError):
        return None
