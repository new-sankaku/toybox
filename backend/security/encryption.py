"""APIキー暗号化モジュール"""

import os
import base64
from typing import Optional

_encryption_key: Optional[bytes] = None


def _get_encryption_key() -> bytes:
    global _encryption_key
    if _encryption_key is None:
        key_str = os.environ.get("ENCRYPTION_KEY")
        if key_str:
            _encryption_key = base64.urlsafe_b64decode(key_str.encode())
        else:
            _encryption_key = _generate_default_key()
    return _encryption_key


def _generate_default_key() -> bytes:
    import hashlib

    seed = "toybox-default-encryption-key-2024"
    return hashlib.sha256(seed.encode()).digest()


def _get_fernet():
    try:
        from cryptography.fernet import Fernet

        key = _get_encryption_key()
        fernet_key = base64.urlsafe_b64encode(key[:32])
        return Fernet(fernet_key)
    except ImportError:
        return None


def encrypt_api_key(api_key: str) -> str:
    fernet = _get_fernet()
    if fernet:
        encrypted = fernet.encrypt(api_key.encode())
        return base64.urlsafe_b64encode(encrypted).decode()
    return _simple_encrypt(api_key)


def decrypt_api_key(encrypted_key: str) -> str:
    fernet = _get_fernet()
    if fernet:
        try:
            encrypted = base64.urlsafe_b64decode(encrypted_key.encode())
            decrypted = fernet.decrypt(encrypted)
            return decrypted.decode()
        except Exception:
            return _simple_decrypt(encrypted_key)
    return _simple_decrypt(encrypted_key)


def _simple_encrypt(text: str) -> str:
    key = _get_encryption_key()
    result = []
    for i, char in enumerate(text):
        key_byte = key[i % len(key)]
        result.append(chr(ord(char) ^ key_byte))
    return base64.urlsafe_b64encode("".join(result).encode("utf-8", "surrogateescape")).decode()


def _simple_decrypt(encrypted: str) -> str:
    key = _get_encryption_key()
    try:
        decoded = base64.urlsafe_b64decode(encrypted.encode()).decode("utf-8", "surrogateescape")
        result = []
        for i, char in enumerate(decoded):
            key_byte = key[i % len(key)]
            result.append(chr(ord(char) ^ key_byte))
        return "".join(result)
    except Exception:
        return ""


def generate_key_hint(api_key: str) -> str:
    if len(api_key) <= 8:
        return "***"
    return f"{api_key[:3]}...{api_key[-3:]}"
