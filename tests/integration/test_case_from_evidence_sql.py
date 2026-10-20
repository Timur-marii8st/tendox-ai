"""PostgreSQL invariants for creating a case version from exact document evidence."""

from __future__ import annotations

import json
import os
import uuid
from io import BytesIO
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from docx import Document
from sqlalchemy import create_engine, select
from sqlalchemy.exc import DBAPIError

from procurement.documents import (
    CompletenessStatus,
    ConstituentDecisionRef,
    DocumentInput,
    DocumentRole,
    DocumentSetCrossAssessment,
    DocumentSetInventoryAssessment,
    DocumentSetMemberAssessment,
    DocumentSetMemberAttestation,
    extract_document,
)
from procurement.domain.cases import GateCheck, GateKind, ProcurementCase, case_input_digest
from procurement.domain.decisions import GateStatus
from procurement.domain.provenance import Extractor, Provenance
from procurement.storage import (
    CaseEvidenceNotFound,
    CaseEvidenceSourceMismatch,
    CaseVersionConflict,
    IdempotencyConflict,
    PostgresStorage,
)
from procurement.storage.models import audit_events

PAPER_CASE = Path(__file__).parent.parent.parent / "examples" / "paper_case.json"


@pytest.fixture(scope="session")
def database_url() -> str:
    value = os.environ.get("DATABASE_URL")
    if not value:
        pytest.skip("DATABASE_URL is not set; PostgreSQL integration tests are skipped")
    return value


@pytest.fixture(scope="session", autouse=True)
def migrated_database(database_url: str) -> None:
    admin_url = os.environ.get("DATABASE_ADMIN_URL")
    if admin_url:
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", admin_url.replace("%", "%%"))
        command.upgrade(config, "head")


@pytest.fixture(scope="session")
def storage(database_url: str) -> PostgresStorage:
    engine = create_engine(database_url, pool_pre_ping=True)
    yield PostgresStorage(engine)
    engine.dispose()


def _bound_binding(storage: PostgresStorage, tenant: str):
    records = []
    for number in (1, 2):
        document_id = f"document-{uuid.uuid4()}"
        source = Document()
        source.add_paragraph(f"Гарантия не менее {number + 23} месяцев")
        output = BytesIO()
        source.save(output)
        content = output.getvalue()
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        extraction = extract_document(
            DocumentInput(
                document_id=document_id,
                filename=f"package-{number}.docx",
                declared_media_type=media_type,
                content=content,
            )
        )
        document = storage.store_document(
            tenant,
            "snapshot-author",
            f"package-{number}.docx",
            media_type,
            DocumentRole.TENDER_REQUIREMENTS,
            content,
            extraction,
            f"from-evidence-source-{number}",
            str(number) * 64,
            document_id=document_id,
        )
        draft = storage.store_completeness_review(
            tenant,
            "snapshot-author",
            document.document_id,
            f"from-evidence-snapshot-{number}",
            str(number + 2) * 64,
            review_id=f"review-{uuid.uuid4()}",
        )
        records.append(
            storage.decide_completeness_review(
                tenant,
                "single-reviewer",
                draft.snapshot.review_id,
                draft.snapshot.evidence_sha256,
                CompletenessStatus.PASS,
                "entire document",
                "reviewed in full",
                (),
                f"from-evidence-decision-{number}",
                str(number + 4) * 64,
            )
        )
    refs = tuple((record.snapshot.review_id, record.snapshot.evidence_sha256) for record in records)
    manifest_id = f"manifest-{uuid.uuid4()}"
    manifest = storage.store_document_set_evidence_manifest(
        tenant,
        "manifest-author",
        "exact declared package",
        refs,
        "from-evidence-manifest",
        "7" * 64,
        manifest_id=manifest_id,
    )
    evidence = storage.get_document_set_review_evidence(tenant, manifest_id)
    assert evidence is not None
    attestations = tuple(
        DocumentSetMemberAttestation(
            reference=ConstituentDecisionRef(
                member_ordinal=item.member.ordinal,
                review_id=item.member.completeness_review_id,
                review_evidence_sha256=item.member.completeness_review_evidence_sha256,
                decision_sha256=item.decision_sha256 or "",
            ),
            assessment=DocumentSetMemberAssessment.REVIEWED_IN_SCOPE,
            rationale="reviewed together in the declared package scope",
        )
        for item in evidence.constituents
    )
    decision = storage.store_document_set_review_decision(
        tenant,
        "package-reviewer",
        manifest_id,
        manifest.evidence_sha256,
        attestations,
        DocumentSetInventoryAssessment.CONFIRMED_FOR_DECLARED_SCOPE,
        "all declared package documents are present",
        DocumentSetCrossAssessment.CHECKED_NO_OPEN_ISSUES,
        "all exact constituent decisions were compared",
        (),
        CompletenessStatus.PASS,
        "complete for the exact declared scope",
        "from-evidence-terminal",
        "8" * 64,
    )
    binding = storage.store_case_document_evidence_binding(
        tenant,
        "case-operator",
        manifest.manifest_id,
        manifest.evidence_sha256,
        decision.decision_sha256,
        "from-evidence-binding",
        "9" * 64,
        binding_id=f"binding-{uuid.uuid4()}",
    )
    return binding


def _case_draft(tenant: str, case_id: str) -> ProcurementCase:
    payload = json.loads(PAPER_CASE.read_text(encoding="utf-8"))
    payload["case_id"] = case_id
    payload["version"] = 1
    payload["company_id"] = tenant
    payload["profile"]["company_id"] = tenant
    if payload.get("selected_quote") is not None:
        payload["selected_quote"]["company_id"] = tenant
    payload["assessment"] = None
    return ProcurementCase.model_validate(payload)


def _legal_check() -> GateCheck:
    return GateCheck(
        kind=GateKind.LEGAL,
        status=GateStatus.PASS,
        reason="manual legal review passed",
        evidence=(
            Provenance(
                document_id="legal-manual",
                locator="reviewer note 1",
                extractor=Extractor.MANUAL,
                confidence=1.0,
            ),
        ),
    )


def test_case_created_from_evidence_has_server_assessment(
    storage: PostgresStorage,
) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    binding = _bound_binding(storage, tenant)
    draft = _case_draft(tenant, f"case-{uuid.uuid4()}")
    created = storage.create_case_from_evidence(
        tenant,
        "case-operator",
        draft,
        binding.binding_id,
        binding.manifest_evidence_sha256,
        binding.decision_sha256,
        (_legal_check(),),
        "from-evidence-idempotency",
        "a" * 64,
    )
    assert created.assessment is not None
    assert created.assessment.reviewer_id == "case-operator"
    assert created.assessment.input_digest == case_input_digest(draft)
    kinds = [check.kind for check in created.assessment.checks]
    assert kinds == [GateKind.DOCUMENT, GateKind.LEGAL]
    document_check = created.assessment.checks[0]
    assert document_check.status is GateStatus.PASS
    assert binding.decision_sha256 in document_check.reason
    assert storage.get_case(tenant, created.case_id, created.version) == created
    replay = storage.create_case_from_evidence(
        tenant,
        "case-operator",
        draft,
        binding.binding_id,
        binding.manifest_evidence_sha256,
        binding.decision_sha256,
        (_legal_check(),),
        "from-evidence-idempotency",
        "a" * 64,
    )
    assert replay == created
    with pytest.raises(IdempotencyConflict):
        storage.create_case_from_evidence(
            tenant,
            "case-operator",
            draft,
            binding.binding_id,
            binding.manifest_evidence_sha256,
            binding.decision_sha256,
            (_legal_check(),),
            "from-evidence-idempotency",
            "b" * 64,
        )
    with storage.transaction(tenant) as connection:
        events = (
            connection.execute(
                select(audit_events.c.event_type, audit_events.c.object_id).where(
                    audit_events.c.event_type == "case.created_from_evidence"
                )
            )
            .mappings()
            .all()
        )
    assert (f"{created.case_id}:v{created.version}") in [event["object_id"] for event in events]


def test_case_from_evidence_rejects_bad_refs_and_caller_assessment(
    storage: PostgresStorage,
) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    other = f"tenant-{uuid.uuid4()}"
    binding = _bound_binding(storage, tenant)
    draft = _case_draft(tenant, f"case-{uuid.uuid4()}")
    with pytest.raises(CaseEvidenceNotFound, match="not found"):
        storage.create_case_from_evidence(
            tenant,
            "case-operator",
            draft,
            "no-such-binding",
            "0" * 64,
            "0" * 64,
            (),
            "from-evidence-missing",
            "c" * 64,
        )
    with pytest.raises(CaseEvidenceSourceMismatch, match="stale"):
        storage.create_case_from_evidence(
            tenant,
            "case-operator",
            draft,
            binding.binding_id,
            "0" * 64,
            binding.decision_sha256,
            (),
            "from-evidence-stale",
            "d" * 64,
        )
    with pytest.raises(CaseEvidenceNotFound, match="not found"):
        storage.create_case_from_evidence(
            other,
            "case-operator",
            _case_draft(other, f"case-{uuid.uuid4()}"),
            binding.binding_id,
            binding.manifest_evidence_sha256,
            binding.decision_sha256,
            (),
            "from-evidence-foreign",
            "e" * 64,
        )
    assessed = draft.model_copy(
        update={
            "assessment": {
                "reviewer_id": "case-operator",
                "assessed_at": "2026-09-18T12:00:00+00:00",
                "input_digest": "0" * 64,
                "checks": [],
            }
        }
    )
    with pytest.raises(ValueError, match="server-owned"):
        storage.create_case_from_evidence(
            tenant,
            "case-operator",
            assessed,
            binding.binding_id,
            binding.manifest_evidence_sha256,
            binding.decision_sha256,
            (),
            "from-evidence-assessed",
            "f" * 64,
        )
    document_check = GateCheck(
        kind=GateKind.DOCUMENT,
        status=GateStatus.PASS,
        reason="caller supplied",
        evidence=(
            Provenance(
                document_id="manual",
                locator="note",
                extractor=Extractor.MANUAL,
            ),
        ),
    )
    with pytest.raises(ValueError, match="DOCUMENT"):
        storage.create_case_from_evidence(
            tenant,
            "case-operator",
            draft,
            binding.binding_id,
            binding.manifest_evidence_sha256,
            binding.decision_sha256,
            (document_check,),
            "from-evidence-document",
            "1" * 64,
        )


def test_case_from_evidence_detects_version_collision(
    storage: PostgresStorage,
) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    binding = _bound_binding(storage, tenant)
    case_id = f"case-{uuid.uuid4()}"
    first = storage.create_case_from_evidence(
        tenant,
        "case-operator",
        _case_draft(tenant, case_id),
        binding.binding_id,
        binding.manifest_evidence_sha256,
        binding.decision_sha256,
        (),
        "from-evidence-first",
        "2" * 64,
    )
    assert first.version == 1
    with pytest.raises(CaseVersionConflict):
        storage.create_case_from_evidence(
            tenant,
            "case-operator",
            _case_draft(tenant, case_id),
            binding.binding_id,
            binding.manifest_evidence_sha256,
            binding.decision_sha256,
            (),
            "from-evidence-second",
            "3" * 64,
        )
    with storage.transaction(tenant) as connection, pytest.raises(DBAPIError):
        connection.execute(
            audit_events.delete().where(audit_events.c.event_type == "case.created_from_evidence")
        )
