from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from procurement.access import AccessRole
from procurement.api import create_app
from procurement.api.contracts import InvalidRequirementSet, Principal, RequirementSetConflict
from procurement.documents import (
    ExecutableRequirementSelection,
    ExtractionResult,
    ExtractionStatus,
    RequirementEntryDisposition,
    RequirementSetCoverageAssessment,
    RequirementSetNormalizationAssessment,
    ReviewedRequirementEntry,
    ReviewedRequirementSetRecord,
    build_case_requirement_set_binding,
    build_requirement_set_materialization_preview,
    build_reviewed_requirement_set_decision,
    build_reviewed_requirement_set_proposal,
    materialize_reviewed_requirement_entries,
)
from procurement.documents.extraction import ExtractedBlock
from procurement.domain.compliance import Verdict
from procurement.domain.provenance import Extractor, Provenance
from procurement.domain.requirements import Operator, Requirement

TENANT = "tenant-a"
NOW = datetime(2026, 9, 20, 12, tzinfo=UTC)


class _Authenticator:
    async def authenticate(self, credential: str) -> Principal | None:
        return {
            "operator": Principal(
                company_id=TENANT,
                actor_id="operator-a",
                access_role=AccessRole.OPERATOR,
            ),
            "reviewer": Principal(
                company_id=TENANT,
                actor_id="reviewer-a",
                access_role=AccessRole.COMPLETENESS_REVIEWER,
            ),
            "auditor": Principal(
                company_id=TENANT,
                actor_id="auditor-a",
                access_role=AccessRole.AUDITOR,
            ),
        }.get(credential)


class _Service:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], ReviewedRequirementSetRecord] = {}
        self.bindings: dict[tuple[str, str], object] = {}
        self.receipts: dict[tuple[str, str], tuple[str, object]] = {}

    async def store_reviewed_requirement_set_proposal(self, **kwargs):
        key = (kwargs["company_id"], kwargs["idempotency_key"])
        existing = self.receipts.get(key)
        if existing is not None:
            if existing[0] != kwargs["request_digest"]:
                raise RequirementSetConflict
            return existing[1]
        proposal = build_reviewed_requirement_set_proposal(
            company_id=kwargs["company_id"],
            set_id=kwargs["set_id"],
            source_document_id=kwargs["source_document_id"],
            source_document_sha256=kwargs["source_document_sha256"],
            declared_scope=kwargs["declared_scope"],
            expected_entry_count=kwargs["expected_entry_count"],
            entries=kwargs["entries"],
            prepared_by=kwargs["actor_id"],
            prepared_at=NOW,
        )
        record = ReviewedRequirementSetRecord(proposal=proposal)
        self.records[(kwargs["company_id"], kwargs["set_id"])] = record
        self.receipts[key] = (kwargs["request_digest"], record)
        return record

    async def preview_reviewed_requirement_set_materialization(self, **kwargs):
        blocks = tuple(
            ExtractedBlock(
                text=text,
                provenance=Provenance(
                    document_id=kwargs["source_document_id"],
                    locator=(f"table 1 row 1 cell 1 nested table 1 row {ordinal} cell {cell}"),
                    extractor=Extractor.NATIVE_DOCX,
                ),
            )
            for ordinal, row in enumerate(
                (
                    ("Тип корпуса", "Rack", "Не изменять"),
                    ("Количество ядер", "Больше или равно 16 шт", "Указать"),
                ),
                start=1,
            )
            for cell, text in enumerate(row, start=1)
        )
        return build_requirement_set_materialization_preview(
            company_id=kwargs["company_id"],
            source_document_id=kwargs["source_document_id"],
            source_document_sha256=kwargs["source_document_sha256"],
            extraction=ExtractionResult(
                status=ExtractionStatus.PASS,
                blocks=blocks,
                source_units_total=len(blocks),
                source_units_extracted=len(blocks),
                characters_extracted=sum(len(item.text) for item in blocks),
            ),
            expected_entry_count=kwargs["expected_entry_count"],
        )

    async def materialize_reviewed_requirement_set_proposal(self, **kwargs):
        preview = await self.preview_reviewed_requirement_set_materialization(**kwargs)
        if preview.preview_sha256 != kwargs["preview_sha256"]:
            raise InvalidRequirementSet
        entries = materialize_reviewed_requirement_entries(preview, kwargs["selections"])
        return await self.store_reviewed_requirement_set_proposal(
            **kwargs,
            entries=entries,
        )

    async def get_reviewed_requirement_set(self, *, company_id: str, set_id: str):
        return self.records.get((company_id, set_id))

    async def decide_reviewed_requirement_set(self, **kwargs):
        record = self.records[(kwargs["company_id"], kwargs["set_id"])]
        if record.proposal.proposal_sha256 != kwargs["proposal_sha256"]:
            raise RequirementSetConflict
        decision = build_reviewed_requirement_set_decision(
            record.proposal,
            coverage_assessment=kwargs["coverage_assessment"],
            normalization_assessment=kwargs["normalization_assessment"],
            status=kwargs["status"],
            reason=kwargs["reason"],
            reviewed_by=kwargs["reviewer_id"],
            reviewed_at=NOW,
        )
        decided = ReviewedRequirementSetRecord(proposal=record.proposal, decision=decision)
        self.records[(kwargs["company_id"], kwargs["set_id"])] = decided
        return decided

    async def bind_reviewed_requirement_set_to_case(self, **kwargs):
        record = self.records[(kwargs["company_id"], kwargs["set_id"])]
        assert record.decision is not None
        binding = build_case_requirement_set_binding(
            record.proposal,
            record.decision,
            binding_id=kwargs["binding_id"],
            case_id=kwargs["case_id"],
            case_version=kwargs["case_version"],
            bound_by=kwargs["actor_id"],
            bound_at=NOW,
        )
        self.bindings[(kwargs["company_id"], binding.binding_id)] = binding
        return binding

    async def get_case_requirement_set_binding(self, *, company_id: str, binding_id: str):
        return self.bindings.get((company_id, binding_id))


def _call(app: object, method: str, url: str, **kwargs: object) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, url, **kwargs)

    return asyncio.run(send())


def _entry_payload() -> dict[str, object]:
    provenance = Provenance(
        document_id="tz-1",
        locator="table 1 row 1",
        extractor=Extractor.MANUAL,
    )
    entry = ReviewedRequirementEntry(
        ordinal=1,
        raw_name="Ядер на процессор",
        raw_value="Не менее 16",
        provenance=provenance,
        disposition=RequirementEntryDisposition.EXECUTABLE,
        requirement=Requirement(
            property="cpu_cores_each",
            operator=Operator.GE,
            value=Decimal(16),
            unit="шт",
            mandatory=True,
            raw_text="Не менее 16 ядер",
            provenance=provenance,
        ),
        review_note="Сверено",
    )
    return entry.model_dump(mode="json")


def test_exact_proposal_decision_and_case_binding_roundtrip() -> None:
    service = _Service()
    app = create_app(service, _Authenticator())
    proposal_response = _call(
        app,
        "POST",
        "/v1/reviewed-requirement-sets",
        headers={"Authorization": "Bearer operator", "Idempotency-Key": "prepare-1"},
        json={
            "source_document_id": "tz-1",
            "source_document_sha256": "a" * 64,
            "declared_scope": "Вся таблица технических требований",
            "expected_entry_count": 1,
            "entries": [_entry_payload()],
        },
    )
    assert proposal_response.status_code == 201, proposal_response.text
    proposal = proposal_response.json()["proposal"]

    decision_response = _call(
        app,
        "POST",
        f"/v1/reviewed-requirement-sets/{proposal['set_id']}/decision",
        headers={"Authorization": "Bearer reviewer", "Idempotency-Key": "decision-1"},
        json={
            "proposal_sha256": proposal["proposal_sha256"],
            "coverage_assessment": RequirementSetCoverageAssessment.CONFIRMED,
            "normalization_assessment": RequirementSetNormalizationAssessment.REVIEWED,
            "status": Verdict.PASS,
            "reason": "Строка сверена с источником",
        },
    )
    assert decision_response.status_code == 200, decision_response.text
    decision = decision_response.json()["decision"]

    binding_response = _call(
        app,
        "POST",
        "/v1/case-requirement-set-bindings",
        headers={"Authorization": "Bearer operator", "Idempotency-Key": "binding-1"},
        json={
            "case_id": "case-1",
            "case_version": 2,
            "set_id": proposal["set_id"],
            "proposal_sha256": proposal["proposal_sha256"],
            "decision_sha256": decision["decision_sha256"],
        },
    )
    assert binding_response.status_code == 201, binding_response.text
    binding = binding_response.json()
    assert binding["case_id"] == "case-1"
    assert binding["reviewed_by"] == "reviewer-a"
    assert binding["bound_by"] == "operator-a"

    loaded = _call(
        app,
        "GET",
        f"/v1/case-requirement-set-bindings/{binding['binding_id']}",
        headers={"Authorization": "Bearer auditor"},
    )
    assert loaded.status_code == 200
    assert loaded.json()["binding_sha256"] == binding["binding_sha256"]


def test_roles_and_strict_json_are_enforced() -> None:
    app = create_app(_Service(), _Authenticator())
    denied = _call(
        app,
        "POST",
        "/v1/reviewed-requirement-sets",
        headers={"Authorization": "Bearer reviewer", "Idempotency-Key": "prepare-1"},
        json={},
    )
    assert denied.status_code == 403

    operator_cannot_decide = _call(
        app,
        "POST",
        "/v1/reviewed-requirement-sets/set-1/decision",
        headers={"Authorization": "Bearer operator", "Idempotency-Key": "decision-denied"},
        json={},
    )
    assert operator_cannot_decide.status_code == 403

    reviewer_cannot_bind = _call(
        app,
        "POST",
        "/v1/case-requirement-set-bindings",
        headers={"Authorization": "Bearer reviewer", "Idempotency-Key": "binding-denied"},
        json={},
    )
    assert reviewer_cannot_bind.status_code == 403

    invalid = _call(
        app,
        "POST",
        "/v1/reviewed-requirement-sets",
        headers={"Authorization": "Bearer operator", "Idempotency-Key": "prepare-2"},
        json={"source_document_id": "tz-1"},
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "invalid_requirement_set"


def test_server_derived_preview_materializes_only_selected_hint() -> None:
    service = _Service()
    app = create_app(service, _Authenticator())
    headers = {"Authorization": "Bearer operator"}
    preview_response = _call(
        app,
        "POST",
        "/v1/documents/tz-1/reviewed-requirement-set-preview",
        headers=headers,
        json={"source_document_sha256": "a" * 64, "expected_entry_count": 2},
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["numeric_suggestion_count"] == 1
    assert [item["raw_name"] for item in preview["entries"]] == [
        "Тип корпуса",
        "Количество ядер",
    ]

    materialized = _call(
        app,
        "POST",
        "/v1/documents/tz-1/reviewed-requirement-set-materializations",
        headers={**headers, "Idempotency-Key": "materialize-1"},
        json={
            "source_document_sha256": "a" * 64,
            "expected_entry_count": 2,
            "preview_sha256": preview["preview_sha256"],
            "declared_scope": "all source table rows",
            "selections": [
                ExecutableRequirementSelection(
                    ordinal=2,
                    property="cpu_cores_each",
                    unit="шт",
                    mandatory=True,
                    review_note="operator checked both exact cells",
                ).model_dump(mode="json")
            ],
        },
    )
    assert materialized.status_code == 201, materialized.text
    entries = materialized.json()["proposal"]["entries"]
    assert entries[0]["disposition"] == "MANUAL_REVIEW_REQUIRED"
    assert entries[1]["disposition"] == "EXECUTABLE"
    assert entries[1]["requirement"]["property"] == "cpu_cores_each"


def test_materialization_rejects_stale_preview_digest() -> None:
    app = create_app(_Service(), _Authenticator())
    response = _call(
        app,
        "POST",
        "/v1/documents/tz-1/reviewed-requirement-set-materializations",
        headers={
            "Authorization": "Bearer operator",
            "Idempotency-Key": "materialize-stale",
        },
        json={
            "source_document_sha256": "a" * 64,
            "expected_entry_count": 2,
            "preview_sha256": "0" * 64,
            "declared_scope": "all source table rows",
            "selections": [],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_requirement_set"
