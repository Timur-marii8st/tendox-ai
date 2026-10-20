from __future__ import annotations

import base64

import pytest

from procurement.documents.ai_transfer_keys import (
    AI_TRANSFER_RAW_KEK_ID_ENV,
    AI_TRANSFER_RAW_ROOT_KEK_B64_ENV,
    LocalPilotDerivedTenantKekProvider,
    LocalPilotTenantKekError,
    local_pilot_tenant_kek_provider_from_env,
)


def _root_b64() -> str:
    return base64.b64encode(bytes(range(32))).decode("ascii")


def _provider(*, key_id: str = "pilot-root-v1") -> LocalPilotDerivedTenantKekProvider:
    return LocalPilotDerivedTenantKekProvider(root_secret=bytes(range(32)), key_id=key_id)


def test_per_tenant_keks_cannot_unwrap_each_others_dek() -> None:
    provider = _provider()
    nonce = bytes(range(12))
    dek = bytes(reversed(range(32)))
    aad = b"exact-wrap-aad"

    company_one = provider.wrap_dek(
        company_id="company-1",
        key_id="pilot-root-v1",
        nonce=nonce,
        dek=dek,
        aad=aad,
    )
    company_two = provider.wrap_dek(
        company_id="company-2",
        key_id="pilot-root-v1",
        nonce=nonce,
        dek=dek,
        aad=aad,
    )

    assert company_one != company_two
    assert (
        provider.unwrap_dek(
            company_id="company-1",
            key_id="pilot-root-v1",
            nonce=nonce,
            wrapped_dek=company_one,
            aad=aad,
        )
        == dek
    )
    with pytest.raises(LocalPilotTenantKekError):
        provider.unwrap_dek(
            company_id="company-2",
            key_id="pilot-root-v1",
            nonce=nonce,
            wrapped_dek=company_one,
            aad=aad,
        )


@pytest.mark.parametrize(
    ("company_id", "key_id", "nonce", "dek", "aad"),
    [
        ("company-1", "wrong-key", bytes(range(12)), bytes(range(32)), b"aad"),
        (" company-1", "pilot-root-v1", bytes(range(12)), bytes(range(32)), b"aad"),
        ("company-1", "pilot-root-v1", b"short", bytes(range(32)), b"aad"),
        ("company-1", "pilot-root-v1", bytes(range(12)), b"short", b"aad"),
        ("company-1", "pilot-root-v1", bytearray(range(12)), bytes(range(32)), b"aad"),
    ],
)
def test_wrap_rejects_wrong_key_or_non_exact_immutable_inputs(
    company_id: str, key_id: str, nonce: bytes, dek: bytes, aad: bytes
) -> None:
    with pytest.raises(LocalPilotTenantKekError):
        _provider().wrap_dek(
            company_id=company_id,
            key_id=key_id,
            nonce=nonce,
            dek=dek,
            aad=aad,
        )


def test_unwrap_rejects_wrong_key_aad_and_tampered_ciphertext() -> None:
    provider = _provider()
    nonce = bytes(range(12))
    wrapped = provider.wrap_dek(
        company_id="company-1",
        key_id="pilot-root-v1",
        nonce=nonce,
        dek=bytes(range(32)),
        aad=b"bound-aad",
    )

    for kwargs in (
        {"key_id": "pilot-root-v2", "aad": b"bound-aad", "wrapped_dek": wrapped},
        {"key_id": "pilot-root-v1", "aad": b"other-aad", "wrapped_dek": wrapped},
        {
            "key_id": "pilot-root-v1",
            "aad": b"bound-aad",
            "wrapped_dek": wrapped[:-1] + bytes([wrapped[-1] ^ 1]),
        },
        {"key_id": "pilot-root-v1", "aad": b"bound-aad", "wrapped_dek": wrapped[:-1]},
    ):
        with pytest.raises(LocalPilotTenantKekError):
            provider.unwrap_dek(
                company_id="company-1",
                nonce=nonce,
                **kwargs,
            )


def test_env_factory_is_disabled_when_pair_is_absent_and_builds_valid_provider() -> None:
    assert local_pilot_tenant_kek_provider_from_env({}) is None

    provider = local_pilot_tenant_kek_provider_from_env(
        {
            AI_TRANSFER_RAW_ROOT_KEK_B64_ENV: _root_b64(),
            AI_TRANSFER_RAW_KEK_ID_ENV: "pilot-root-v1",
        }
    )

    assert isinstance(provider, LocalPilotDerivedTenantKekProvider)
    assert provider.active_key_id(company_id="company-1") == "pilot-root-v1"


@pytest.mark.parametrize(
    "environ",
    [
        {AI_TRANSFER_RAW_ROOT_KEK_B64_ENV: _root_b64()},
        {AI_TRANSFER_RAW_KEK_ID_ENV: "pilot-root-v1"},
        {
            AI_TRANSFER_RAW_ROOT_KEK_B64_ENV: "not base64!",
            AI_TRANSFER_RAW_KEK_ID_ENV: "pilot-root-v1",
        },
        {
            AI_TRANSFER_RAW_ROOT_KEK_B64_ENV: base64.b64encode(b"too short").decode("ascii"),
            AI_TRANSFER_RAW_KEK_ID_ENV: "pilot-root-v1",
        },
        {
            AI_TRANSFER_RAW_ROOT_KEK_B64_ENV: _root_b64(),
            AI_TRANSFER_RAW_KEK_ID_ENV: " invalid ",
        },
    ],
)
def test_env_factory_rejects_partial_or_malformed_values_without_echoing_them(
    environ: dict[str, str],
) -> None:
    with pytest.raises(RuntimeError) as raised:
        local_pilot_tenant_kek_provider_from_env(environ)

    assert "not base64" not in str(raised.value)
    assert " invalid " not in str(raised.value)
    assert _root_b64() not in str(raised.value)


def test_provider_repr_and_errors_do_not_disclose_root_secret() -> None:
    root_secret = b"s" * 32
    provider = LocalPilotDerivedTenantKekProvider(root_secret=root_secret, key_id="pilot-root-v1")

    assert root_secret.decode("ascii") not in repr(provider)
    with pytest.raises(LocalPilotTenantKekError) as raised:
        provider.wrap_dek(
            company_id="company-1",
            key_id="different-key",
            nonce=bytes(range(12)),
            dek=bytes(range(32)),
            aad=b"aad",
        )
    assert root_secret.decode("ascii") not in str(raised.value)


def test_runtime_injects_provider_only_when_complete_env_pair_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import procurement.api.runtime as runtime

    captured: list[object] = []

    class FakeStorage:
        def __init__(self, _engine: object, *, raw_key_provider: object) -> None:
            captured.append(raw_key_provider)

    monkeypatch.setenv("DATABASE_URL", "postgresql://not-used")
    monkeypatch.setattr(runtime, "create_engine", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(runtime, "PostgresStorage", FakeStorage)
    monkeypatch.setattr(runtime, "PostgresCaseService", lambda storage: storage)
    monkeypatch.setattr(runtime, "PostgresAuthenticator", lambda storage: storage)
    monkeypatch.setattr(runtime, "PaddleOcrRunner", lambda: object())
    monkeypatch.setattr(runtime, "create_app", lambda *_args, **_kwargs: object())

    monkeypatch.delenv(AI_TRANSFER_RAW_ROOT_KEK_B64_ENV, raising=False)
    monkeypatch.delenv(AI_TRANSFER_RAW_KEK_ID_ENV, raising=False)
    runtime.create_runtime_app()
    assert captured.pop() is None

    monkeypatch.setenv(AI_TRANSFER_RAW_ROOT_KEK_B64_ENV, _root_b64())
    monkeypatch.setenv(AI_TRANSFER_RAW_KEK_ID_ENV, "pilot-root-v1")
    runtime.create_runtime_app()
    assert isinstance(captured.pop(), LocalPilotDerivedTenantKekProvider)
