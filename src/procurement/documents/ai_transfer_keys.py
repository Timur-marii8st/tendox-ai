"""Local pilot-only tenant KEK provider for encrypted AI-transfer captures.

This adapter deliberately derives an in-process tenant key from one supplied
root secret.  It is suitable only for a controlled pilot: it is not a KMS,
does not rotate keys, and must not be represented as a production key service.
"""

from __future__ import annotations

import base64
import binascii
import os
from collections.abc import Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

AI_TRANSFER_RAW_ROOT_KEK_B64_ENV = "AI_TRANSFER_RAW_ROOT_KEK_B64"
AI_TRANSFER_RAW_KEK_ID_ENV = "AI_TRANSFER_RAW_KEK_ID"

_AES_256_KEY_BYTES = 32
_AES_GCM_NONCE_BYTES = 12
_AES_GCM_TAG_BYTES = 16
_MAX_IDENTIFIER_LENGTH = 200
_HKDF_DOMAIN = b"syurai-procurement/ai-transfer-raw/local-pilot-tenant-kek/v1"
_ENV_CONFIGURATION_ERROR = "AI transfer raw local pilot KEK configuration is invalid"
_OPERATION_ERROR = "local pilot tenant KEK operation failed"


class LocalPilotTenantKekError(ValueError):
    """Fixed-message error that never includes root or derived key material."""

    def __init__(self) -> None:
        super().__init__(_OPERATION_ERROR)


class LocalPilotDerivedTenantKekProvider:
    """Single-version, HKDF-derived KEK provider for a non-production pilot.

    The root secret is a 32-byte immutable value.  A separate 32-byte KEK is
    derived for every exact ``(company_id, key_id)`` pair; neither the root nor
    a derived key is exposed by the public interface or object representation.
    """

    __slots__ = ("_key_id", "_root_secret")

    def __init__(self, *, root_secret: bytes, key_id: str) -> None:
        if type(root_secret) is not bytes or len(root_secret) != _AES_256_KEY_BYTES:
            raise LocalPilotTenantKekError()
        self._key_id = _require_identifier(key_id)
        self._root_secret = root_secret

    def __repr__(self) -> str:
        return f"{type(self).__name__}(key_id={self._key_id!r})"

    def active_key_id(self, *, company_id: str) -> str:
        """Return the configured key version after validating the tenant ID."""
        _require_identifier(company_id)
        return self._key_id

    def wrap_dek(
        self,
        *,
        company_id: str,
        key_id: str,
        nonce: bytes,
        dek: bytes,
        aad: bytes,
    ) -> bytes:
        """Wrap exactly one immutable 32-byte DEK under the derived tenant KEK."""
        tenant_kek = self._derive_tenant_kek(company_id=company_id, key_id=key_id)
        _require_exact_bytes(nonce, length=_AES_GCM_NONCE_BYTES)
        _require_exact_bytes(dek, length=_AES_256_KEY_BYTES)
        _require_exact_bytes(aad)
        try:
            wrapped = AESGCM(tenant_kek).encrypt(nonce, dek, aad)
        except (TypeError, ValueError):
            raise LocalPilotTenantKekError() from None
        if type(wrapped) is not bytes or len(wrapped) != _AES_256_KEY_BYTES + _AES_GCM_TAG_BYTES:
            raise LocalPilotTenantKekError()
        return wrapped

    def unwrap_dek(
        self,
        *,
        company_id: str,
        key_id: str,
        nonce: bytes,
        wrapped_dek: bytes,
        aad: bytes,
    ) -> bytes:
        """Authenticate and unwrap exactly one immutable 32-byte DEK."""
        tenant_kek = self._derive_tenant_kek(company_id=company_id, key_id=key_id)
        _require_exact_bytes(nonce, length=_AES_GCM_NONCE_BYTES)
        _require_exact_bytes(wrapped_dek, length=_AES_256_KEY_BYTES + _AES_GCM_TAG_BYTES)
        _require_exact_bytes(aad)
        try:
            dek = AESGCM(tenant_kek).decrypt(nonce, wrapped_dek, aad)
        except (InvalidTag, TypeError, ValueError):
            raise LocalPilotTenantKekError() from None
        if type(dek) is not bytes or len(dek) != _AES_256_KEY_BYTES:
            raise LocalPilotTenantKekError()
        return dek

    def _derive_tenant_kek(self, *, company_id: str, key_id: str) -> bytes:
        checked_company_id = _require_identifier(company_id)
        checked_key_id = _require_identifier(key_id)
        if checked_key_id != self._key_id:
            raise LocalPilotTenantKekError()
        try:
            return HKDF(
                algorithm=SHA256(),
                length=_AES_256_KEY_BYTES,
                salt=None,
                info=_derivation_info(company_id=checked_company_id, key_id=checked_key_id),
            ).derive(self._root_secret)
        except (TypeError, ValueError):
            raise LocalPilotTenantKekError() from None


def local_pilot_tenant_kek_provider_from_env(
    environ: Mapping[str, str] | None = None,
) -> LocalPilotDerivedTenantKekProvider | None:
    """Load the pilot adapter only when both explicit environment values exist.

    Both absent means raw-response storage remains disabled.  A partial or
    malformed pair is a fixed configuration error and deliberately never
    includes an environment value in its exception.
    """
    source = os.environ if environ is None else environ
    root_b64 = source.get(AI_TRANSFER_RAW_ROOT_KEK_B64_ENV)
    key_id = source.get(AI_TRANSFER_RAW_KEK_ID_ENV)
    if root_b64 is None and key_id is None:
        return None
    if type(root_b64) is not str or type(key_id) is not str:
        raise RuntimeError(_ENV_CONFIGURATION_ERROR)
    try:
        root_secret = base64.b64decode(root_b64.encode("ascii"), validate=True)
        return LocalPilotDerivedTenantKekProvider(root_secret=root_secret, key_id=key_id)
    except (UnicodeEncodeError, binascii.Error, LocalPilotTenantKekError, ValueError):
        raise RuntimeError(_ENV_CONFIGURATION_ERROR) from None


def _derivation_info(*, company_id: str, key_id: str) -> bytes:
    """Encode unambiguous domain-separated HKDF context."""
    company = company_id.encode("utf-8")
    version = key_id.encode("utf-8")
    return (
        _HKDF_DOMAIN
        + len(version).to_bytes(2, "big")
        + version
        + len(company).to_bytes(2, "big")
        + company
    )


def _require_identifier(value: str) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > _MAX_IDENTIFIER_LENGTH
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise LocalPilotTenantKekError()
    return value


def _require_exact_bytes(value: bytes, *, length: int | None = None) -> bytes:
    if type(value) is not bytes or (length is not None and len(value) != length):
        raise LocalPilotTenantKekError()
    return value


__all__ = [
    "AI_TRANSFER_RAW_KEK_ID_ENV",
    "AI_TRANSFER_RAW_ROOT_KEK_B64_ENV",
    "LocalPilotDerivedTenantKekProvider",
    "LocalPilotTenantKekError",
    "local_pilot_tenant_kek_provider_from_env",
]
