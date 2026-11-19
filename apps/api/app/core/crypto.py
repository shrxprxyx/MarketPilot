"""Fernet encryption for stored secrets (SRS §11). Keys come from FERNET_KEYS
(comma-separated): the first encrypts, all decrypt, so keys can be rotated."""
from cryptography.fernet import Fernet, MultiFernet

from app.config import settings


def _fernet() -> MultiFernet:
    keys = [k.strip() for k in settings.fernet_keys.split(",") if k.strip()]
    return MultiFernet([Fernet(k) for k in keys])


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
