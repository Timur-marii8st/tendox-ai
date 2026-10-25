"""Реальный DTO профиля и saved-case HTTP boundary, без выдуманных допусков."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from procurement.access import AccessRole
from procurement.api.comparison import comparison_router
from procurement.api.comparison_demo import ContractExamplesAdapter
from procurement.api.contracts import Principal
from procurement.comparison.profile_adapter import validate_example_snapshot
from procurement.comparison.service import CaseRef, SelectedCase, compare_selected
from procurement.domain.cases import case_input_digest
from procurement.domain.company_profile_snapshot import (
    CompanyProfileSnapshot,
    ProfileFactInput,
    ProfilePolicyConfirmation,
    ProfileSaveCommand,
    ProfileSelection,
    new_snapshot,
)
from procurement.domain.decisions import GateStatus
from procurement.storage.company_profile import ProfileNotFound

FIXTURES = Path(__file__).parent / "fixtures" / "company_profile"


def test_owner_authorized_snapshot_remains_a_valid_comparison_input() -> None:
    command = ProfileSaveCommand(
        expected_version=0,
        changes={"finance.min_contract_amount": ProfileFactInput(knowledge="KNOWN", value="0")},
    )
    confirmation = command.confirmation_digest("owner-profile", "owner")
    snapshot = new_snapshot(
        "owner-profile",
        "owner",
        command,
        None,
        "owner-audit",
        ProfilePolicyConfirmation(
            command_sha256=command.digest(),
            confirmation_sha256=confirmation,
            confirmed_by="owner",
            confirmed_at=datetime.now(UTC),
            changed_paths=("finance.min_contract_amount",),
        ),
    )
    rendered = snapshot.model_dump(mode="json")
    assert validate_example_snapshot(rendered, "owner-profile") == rendered


@pytest.mark.parametrize("name", ["unknown", "supplier-partial", "explicit-empty-and-false"])
def test_all_actual_profile_handoffs_compare_without_fake_policy(name):
    handoff = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    raw = handoff["profile_snapshot"]
    company = raw["company_id"]
    snapshot = validate_example_snapshot(raw, company)
    assert snapshot == raw
    assert "policy_confirmation" not in snapshot
    adapter = ContractExamplesAdapter()
    cases = tuple(
        SelectedCase(
            item.case.model_copy(
                update={
                    "company_id": company,
                    "selected_quote": None,
                    "profile": item.case.profile.model_copy(update={"company_id": company}),
                }
            )
        )
        for item in adapter._cases[:2]
    )
    report = compare_selected(company, snapshot, cases, at=datetime.now(UTC))
    assert report.profile_ref.snapshot_sha256 == raw["snapshot_sha256"]
    for row in report.rows:
        checks = {check.check_id: check for check in row.checks}
        assert checks["geography"].status == GateStatus.UNKNOWN
        assert not any(
            check.status == GateStatus.PASS
            for check in row.checks
            if check.check_id.startswith("finance")
        )
        assert row.economics == ()
    with pytest.raises(LookupError):
        validate_example_snapshot(raw, "foreign")


def test_saved_api_exact_selection_survives_new_latest_and_checks_tenant(monkeypatch):
    import procurement.api.comparison as boundary

    handoff = json.loads((FIXTURES / "supplier-partial.json").read_text(encoding="utf-8"))
    snapshot = CompanyProfileSnapshot.model_validate(handoff["profile_snapshot"])
    selection = ProfileSelection.model_validate(handoff["selection"])
    company = snapshot.company_id
    adapter = ContractExamplesAdapter()
    cases = [
        item.case.model_copy(
            update={
                "company_id": company,
                "selected_quote": None,
                "profile": item.case.profile.model_copy(update={"company_id": company}),
            }
        )
        for item in adapter._cases[:2]
    ]
    reads = []

    def read_selection(storage, tenant, selection_id=None):
        if tenant != company or selection_id not in (None, selection.selection_id):
            raise ProfileNotFound("not found")
        return selection

    def read_profile(storage, tenant, version=None):
        reads.append((tenant, version))
        assert version == snapshot.version  # Never latest, even after a new version exists.
        return snapshot

    class Repository:
        def list_cases(self, tenant, limit, cursor=None):
            from types import SimpleNamespace

            return SimpleNamespace(items=cases if tenant == company else (), next_cursor=None)

        def get_case(self, tenant, case_id, version):
            return next(
                (
                    case
                    for case in cases
                    if (case.company_id, case.case_id, case.version) == (tenant, case_id, version)
                ),
                None,
            )

    monkeypatch.setattr(boundary, "read_selection", read_selection)
    monkeypatch.setattr(boundary, "read_profile", read_profile)
    principal = Principal(company_id=company, actor_id="operator")

    async def authenticate():
        return principal

    app = FastAPI()
    app.include_router(comparison_router(Repository(), authenticate))
    client = TestClient(app)
    catalog = client.get("/v1/procurement-comparison/catalog")
    assert catalog.status_code == 200
    assert catalog.headers["cache-control"] == "no-store"
    command = {
        "selection_id": selection.selection_id,
        "profile_ref": {"version": snapshot.version, "snapshot_sha256": snapshot.snapshot_sha256},
        "case_refs": [
            CaseRef(
                case_id=case.case_id, version=case.version, input_sha256=case_input_digest(case)
            ).model_dump()
            for case in cases
        ],
    }
    result = client.post("/v1/procurement-comparison", json=command)
    assert result.status_code == 200, result.text
    assert result.json()["persistence"] == "EPHEMERAL"
    assert result.json()["audit_event_id"] is None
    assert reads and all(version == snapshot.version for _, version in reads)
    command["profile_ref"]["snapshot_sha256"] = "0" * 64
    assert client.post("/v1/procurement-comparison", json=command).status_code == 409
    command["selection_id"] = str(uuid4())
    assert client.post("/v1/procurement-comparison", json=command).status_code == 404
    principal = Principal(company_id="foreign", actor_id="operator")
    assert client.get("/v1/procurement-comparison/catalog").status_code == 404
    principal = Principal(company_id=company, actor_id="auditor", access_role=AccessRole.AUDITOR)
    assert client.post("/v1/procurement-comparison", json=command).status_code == 403
