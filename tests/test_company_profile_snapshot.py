"""Сохранение неизвестности и точности самостоятельного профиля."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from procurement.domain.company_profile_snapshot import (
    CRITICAL_PATHS,
    CompanyProfileSnapshot,
    ProfileFactInput,
    ProfilePolicyConfirmation,
    ProfileSaveCommand,
    new_snapshot,
    validate_profile_value,
)


def test_partial_snapshot_roundtrip_keeps_unknown_and_sources() -> None:
    command = ProfileSaveCommand(
        expected_version=0,
        changes={
            "identity.name": ProfileFactInput(knowledge="KNOWN", value="ООО Пример"),
            "geography.all_russia": ProfileFactInput(knowledge="KNOWN", value=False),
            "supplied_goods": ProfileFactInput(knowledge="KNOWN", value=()),
        },
    )
    snapshot = new_snapshot("synthetic", "operator", command, None, "audit1")
    restored = CompanyProfileSnapshot.model_validate_json(snapshot.model_dump_json())
    assert restored == snapshot
    assert restored.facts["identity.name"].sources[0].recorded_by == "operator"
    assert restored.facts["identity.inn"].knowledge == "UNKNOWN"
    assert restored.facts["finance.min_contract_amount"].value is None
    assert restored.facts["geography.all_russia"].value is False
    assert restored.facts["supplied_goods"].value == ()


@pytest.mark.parametrize("value", [1.1, True, "NaN", "Infinity", "-Infinity"])
def test_money_rejects_inexact_values(value: object) -> None:
    with pytest.raises((ValueError, ValidationError)):
        validate_profile_value("finance.min_contract_amount", value)  # type: ignore[arg-type]


def test_money_reuses_decimal_limits_and_preserves_kopecks() -> None:
    assert validate_profile_value("finance.min_contract_amount", "123456789012345.67") == Decimal(
        "123456789012345.67"
    )
    assert validate_profile_value("finance.min_contract_amount", "0") == Decimal("0")
    assert validate_profile_value("geography.max_distance_km", "100.50") == Decimal("100.5")
    with pytest.raises(ValidationError):
        validate_profile_value("finance.min_margin", "1.1")


def test_commands_do_not_coerce_boolean_or_null() -> None:
    with pytest.raises(ValidationError):
        ProfileSaveCommand(
            expected_version=0,
            changes={"geography.all_russia": {"knowledge": "KNOWN", "value": "false"}},
        )
    with pytest.raises(ValidationError):
        ProfileSaveCommand(expected_version=True, changes={})
    with pytest.raises(ValidationError):
        ProfileSaveCommand(
            expected_version=0, changes={"identity.name": {"knowledge": "KNOWN", "value": None}}
        )
    with pytest.raises(ValidationError):
        ProfileSaveCommand(
            expected_version=0,
            changes={"finance.min_margin": {"knowledge": "NOT_APPLICABLE", "reason": "нет"}},
        )


def test_changed_field_preserves_other_sources_and_does_not_modify_previous() -> None:
    first = new_snapshot(
        "synthetic",
        "a",
        ProfileSaveCommand(
            expected_version=0,
            changes={"identity.name": ProfileFactInput(knowledge="KNOWN", value="Первое")},
        ),
        None,
        "audit1",
    )
    second = new_snapshot(
        "synthetic",
        "b",
        ProfileSaveCommand(
            expected_version=1,
            changes={"identity.inn": ProfileFactInput(knowledge="KNOWN", value="1650000000")},
        ),
        first,
        "audit2",
    )
    assert second.facts["identity.name"] == first.facts["identity.name"]
    assert first.facts["identity.inn"].knowledge == "UNKNOWN"
    assert second.version == 2 and second.parent_version == 1


def test_digest_detects_tampered_snapshot() -> None:
    snapshot = new_snapshot(
        "synthetic", "a", ProfileSaveCommand(expected_version=0, changes={}), None, "audit1"
    )
    payload = snapshot.model_dump(mode="json")
    payload["facts"]["identity.inn"]["reason"] = "tampered"
    with pytest.raises(ValidationError, match="snapshot_digest_mismatch"):
        CompanyProfileSnapshot.model_validate(payload)


def test_owner_confirmation_binds_tenant_actor_version_and_normalized_changes() -> None:
    command = ProfileSaveCommand(
        expected_version=3,
        changes={"finance.min_contract_amount": ProfileFactInput(knowledge="KNOWN", value="1.00")},
    )
    digest = command.confirmation_digest("tenant-a", "owner-a")
    assert digest != command.confirmation_digest("tenant-b", "owner-a")
    assert digest != command.confirmation_digest("tenant-a", "owner-b")
    assert digest != ProfileSaveCommand(
        expected_version=4,
        changes={"finance.min_contract_amount": ProfileFactInput(knowledge="KNOWN", value="1.00")},
    ).confirmation_digest("tenant-a", "owner-a")
    snapshot = new_snapshot(
        "tenant-a",
        "owner-a",
        command,
        None,
        "audit-owner",
        ProfilePolicyConfirmation(
            command_sha256=command.digest(),
            confirmation_sha256=digest,
            confirmed_by="owner-a",
            confirmed_at=datetime.now(UTC),
            changed_paths=("finance.min_contract_amount",),
        ),
    )
    assert snapshot.critical_settings_status == "OWNER_AUTHORIZED"
    assert snapshot.policy_confirmation is not None
    assert CompanyProfileSnapshot.model_validate_json(snapshot.model_dump_json()) == snapshot


@pytest.mark.parametrize("name", ["unknown", "supplier-partial", "explicit-empty-and-false"])
def test_synthetic_handoff_has_exact_refs_and_manual_command_sources(name: str) -> None:
    folder = Path(__file__).parent / "fixtures" / "company_profile"
    handoff = json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))
    snapshot = CompanyProfileSnapshot.model_validate(handoff["profile_snapshot"])
    command = ProfileSaveCommand.model_validate_json(
        (folder / f"{name}.command.json").read_text(encoding="utf-8")
    )
    assert handoff["profile_ref"] == handoff["selection"]["profile_ref"]
    assert handoff["profile_ref"]["snapshot_sha256"] == snapshot.snapshot_sha256
    assert all(snapshot.facts[path].knowledge == "UNKNOWN" for path in CRITICAL_PATHS)
    for path, fact in snapshot.facts.items():
        for source in fact.sources:
            assert source.source_sha256 == command.digest()
            assert source.provenance.locator == path
