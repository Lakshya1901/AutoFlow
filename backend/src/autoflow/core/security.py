"""
AutoFlow Security
API key validation, credential encryption, and CORS setup.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from autoflow.core.config import get_settings
from autoflow.core.logging import get_logger

logger = get_logger(__name__)

# ─── API Key Authentication ───────────────────────────────────────────────────

_api_key_header = APIKeyHeader(
    name="X-AutoFlow-API-Key",
    auto_error=False,
    description="API key for authenticating the Chrome Extension and external clients",
)


async def require_api_key(
    api_key: str | None = Security(_api_key_header),
) -> str:
    """
    FastAPI dependency to validate the API key from the request header.

    Usage:
        @router.post("/endpoint", dependencies=[Depends(require_api_key)])
        async def my_endpoint():
            ...
    """
    settings = get_settings()

    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key is required. Include X-AutoFlow-API-Key header.",
        )

    # Constant-time comparison to prevent timing attacks
    is_valid = hmac.compare_digest(
        api_key.encode("utf-8"),
        settings.extension_api_key.encode("utf-8"),
    )

    if not is_valid:
        logger.warning("Invalid API key attempt", key_prefix=api_key[:8] + "...")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
        )

    return api_key


# Optional auth for development — skips key check if dev mode
async def optional_api_key(
    api_key: str | None = Security(_api_key_header),
) -> str | None:
    """
    In development, API key is optional (to simplify testing).
    In production, this behaves the same as require_api_key.
    """
    settings = get_settings()
    if settings.is_development:
        return api_key or "dev-bypass"
    return await require_api_key(api_key)


# ─── Credential Encryption ────────────────────────────────────────────────────

class CredentialVault:
    """
    Encrypt and decrypt sensitive connector credentials using Fernet symmetric encryption.

    Credentials (API keys, OAuth tokens, passwords) are encrypted at rest
    using the CREDENTIAL_ENCRYPTION_KEY environment variable.
    """

    def __init__(self) -> None:
        settings = get_settings()
        key = settings.credential_encryption_key
        if not key:
            raise ValueError("CREDENTIAL_ENCRYPTION_KEY is not set")
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a credential value. Returns a base64-encoded encrypted string."""
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a credential value. Raises InvalidToken if tampered."""
        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken as e:
            logger.error("Failed to decrypt credential — possible tampering")
            raise ValueError("Credential decryption failed") from e

    def is_encrypted(self, value: str) -> bool:
        """Check if a value looks like it was encrypted by this vault."""
        try:
            self._fernet.decrypt(value.encode("utf-8"))
            return True
        except (InvalidToken, Exception):
            return False


# Singleton vault — instantiated lazily
_vault: CredentialVault | None = None


def get_vault() -> CredentialVault:
    """Get the global credential vault instance."""
    global _vault
    if _vault is None:
        _vault = CredentialVault()
    return _vault


# ─── Token Generation ─────────────────────────────────────────────────────────

def generate_api_key() -> str:
    """Generate a cryptographically secure API key."""
    return f"af_{secrets.token_urlsafe(32)}"


def generate_session_token() -> str:
    """Generate a secure session token for recording sessions."""
    return secrets.token_hex(24)


def hash_value(value: str) -> str:
    """SHA-256 hash a value (for storing non-decryptable hashes)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
