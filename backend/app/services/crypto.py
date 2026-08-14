"""Symmetric encryption for secrets that must be RECOVERABLE at rest.

Used for values the app has to read back in cleartext to function — currently the
TOTP shared secret, which pyotp needs verbatim to verify a code (so hashing, as we
do for passwords and reset/invite tokens, is not an option here).

Key material:
  * If ENCRYPTION_KEY is set it is used directly. It must be a urlsafe-base64
    32-byte Fernet key (generate: `python -c "from cryptography.fernet import
    Fernet; print(Fernet.generate_key().decode())"`).
  * Otherwise the key is DERIVED from JWT_SECRET_KEY. That secret is always
    present and already validated (>=32 chars, not a known placeholder) in
    production, so 2FA encryption works out of the box with no new required
    config. Setting ENCRYPTION_KEY explicitly is the way to rotate/separate it.

Rotating the key makes previously-encrypted values undecryptable; for TOTP that
means affected users must re-enroll 2FA. Document before rotating.

Backward compatibility: ciphertext is tagged with a version prefix. A stored
value WITHOUT the prefix is treated as legacy plaintext and returned unchanged, so
enabling this on a database that already has cleartext TOTP secrets does not break
existing 2FA — those rows are transparently re-encrypted next time they're written.
"""
import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

from app.config import settings

# Marks a value this module encrypted, so decryption can tell ciphertext from a
# legacy plaintext secret written before encryption was introduced.
_PREFIX = "enc:v1:"


def _fernet() -> Fernet:
    key = (settings.ENCRYPTION_KEY or "").strip()
    if key:
        # Trust an explicitly provided key as a real Fernet key.
        return Fernet(key.encode("utf-8"))
    # Derive a deterministic 32-byte key from JWT_SECRET_KEY. SHA-256 gives 32
    # bytes; Fernet wants urlsafe-base64 of those 32 bytes.
    digest = hashlib.sha256(settings.JWT_SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plaintext: Optional[str]) -> Optional[str]:
    if plaintext is None:
        return None
    token = _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")
    return _PREFIX + token


def decrypt(stored: Optional[str]) -> Optional[str]:
    if stored is None:
        return None
    if not stored.startswith(_PREFIX):
        # Legacy cleartext written before this module existed — return as-is.
        return stored
    token = stored[len(_PREFIX):]
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        # Wrong/rotated key. Surface as "no usable secret" rather than crashing;
        # for TOTP this fails the code check and the user re-enrolls.
        return None


class EncryptedString(TypeDecorator):
    """A String column whose value is encrypted at rest, transparently.

    Reads return cleartext; writes store ciphertext. Existing plaintext rows are
    passed through on read and upgraded to ciphertext on the next write.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):  # on write
        return encrypt(value)

    def process_result_value(self, value, dialect):  # on read
        return decrypt(value)
