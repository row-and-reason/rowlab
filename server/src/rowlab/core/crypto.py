"""Saved keys (OpenRouter, S3) encrypted at rest with `ROWLAB_SECRET_KEY`, when it is set.

Encrypted values are stored as `enc:<token>`; anything else is a key saved before there was a secret
key, read as it is.
"""

import base64
import hashlib
from typing import Any

from rowlab.core.config import config

PREFIX = "enc:"


def encrypt(value: str) -> str:
    if not config().secret_key:
        return value
    return PREFIX + _fernet().encrypt(value.encode()).decode()


def decrypt(stored: str) -> str:
    if not stored.startswith(PREFIX):
        return stored
    if not config().secret_key:
        raise RuntimeError("A saved key is encrypted, but ROWLAB_SECRET_KEY isn't set.")
    return _fernet().decrypt(stored.removeprefix(PREFIX).encode()).decode()


def _fernet() -> Any:
    # Only needed with a secret key, which hosted setups have: `pip install rowlab[hosted]`.
    from cryptography.fernet import Fernet

    # Any string works as the secret key: it is stretched to the 32 bytes Fernet needs.
    digest = hashlib.sha256(config().secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))
