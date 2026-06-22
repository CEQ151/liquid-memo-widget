"""Authenticated surprise-payload encryption and Windows-user-bound key storage."""
from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


AAD = b"DesktopMemo_Pro/surprise/v1"
DEFAULT_PAYLOAD_PATH = Path(__file__).with_name("surprise.enc")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


def derive_key(passphrase: str, salt: bytes, n: int = 32768, r: int = 8, p: int = 1) -> bytes:
    if not passphrase:
        raise ValueError("empty passphrase")
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(passphrase.encode("utf-8"))


def encrypt_payload(payload: dict, passphrase: str) -> bytes:
    salt, nonce = os.urandom(16), os.urandom(12)
    key = derive_key(passphrase, salt)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encrypted = AESGCM(key).encrypt(nonce, raw, AAD)
    envelope = {
        "version": 1,
        "kdf": {"name": "scrypt", "n": 32768, "r": 8, "p": 1, "salt": _b64(salt)},
        "cipher": {"name": "AES-256-GCM", "nonce": _b64(nonce), "data": _b64(encrypted)},
    }
    return json.dumps(envelope, separators=(",", ":")).encode("ascii")


def read_envelope(path: Path = DEFAULT_PAYLOAD_PATH) -> dict:
    envelope = json.loads(path.read_text(encoding="ascii"))
    if envelope.get("version") != 1 or envelope.get("kdf", {}).get("name") != "scrypt":
        raise ValueError("unsupported surprise payload")
    if envelope.get("cipher", {}).get("name") != "AES-256-GCM":
        raise ValueError("unsupported surprise cipher")
    kdf = envelope["kdf"]
    if (int(kdf.get("n", 0)), int(kdf.get("r", 0)), int(kdf.get("p", 0))) != (32768, 8, 1):
        raise ValueError("unsupported surprise KDF parameters")
    return envelope


def key_from_passphrase(passphrase: str, envelope: dict) -> bytes:
    kdf = envelope["kdf"]
    return derive_key(passphrase, _unb64(kdf["salt"]), int(kdf["n"]), int(kdf["r"]), int(kdf["p"]))


def decrypt_with_key(envelope: dict, key: bytes) -> dict:
    if len(key) != 32:
        raise ValueError("invalid surprise key")
    cipher = envelope["cipher"]
    raw = AESGCM(key).decrypt(_unb64(cipher["nonce"]), _unb64(cipher["data"]), AAD)
    payload = json.loads(raw.decode("utf-8"))
    text_fields = {"pendingText", "completedText", "deadlineText", "drawText", "reviewText"}
    if not text_fields.issubset(payload) or not all(isinstance(payload[key], str) for key in text_fields):
        raise ValueError("invalid surprise content")
    if not isinstance(payload.get("notes"), list) or not payload["notes"]:
        raise ValueError("invalid surprise content")
    if not all(isinstance(note, str) and note.strip() for note in payload["notes"]):
        raise ValueError("invalid surprise content")
    return payload


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data: bytes) -> tuple[_DATA_BLOB, object]:
    buffer = ctypes.create_string_buffer(data)
    return _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def protect_key(key: bytes) -> str:
    source, keepalive = _blob(key)
    output = _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source), "DesktopMemo surprise", None, None, None, 0, ctypes.byref(output)
    ):
        raise ctypes.WinError()
    try:
        return _b64(ctypes.string_at(output.pbData, output.cbData))
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


def unprotect_key(encoded: str) -> bytes:
    source, keepalive = _blob(_unb64(encoded))
    output = _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)
