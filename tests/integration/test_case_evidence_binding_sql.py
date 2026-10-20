"""PostgreSQL invariants for persisted case-document-evidence bindings."""

from __future__ import annotations

import os
import uuid
from io import BytesIO

import pytest
from alembic import command
from alembic.config import Config
from docx import Document
from sqlalchemy import create_engine, delete, func, select, update
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
from procurement.storage import (
    CaseEvidenceNotFound,
    CaseEvidenceSourceMismatch,
    IdempotencyConflict,
    PostgresStorage,
)
from procurement.storage.models import (
    audit_events,
    case_document_evidence_bindings,
)


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


def _decided_manifest(storage: PostgresStorage, tenant: str):
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
            f"binding-source-{number}",
            str(number) * 64,
            document_id=document_id,
        )
        draft = storage.store_completeness_review(
            tenant,
            "snapshot-author",
            document.document_id,
            f"binding-snapshot-{number}",
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
                f"binding-decision-{number}",
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
        "binding-manifest",
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
        "binding-terminal",
        "8" * 64,
    )
    return manifest, decision


def test_case_evidence_binding_is_exact_atomic_and_tenant_scoped(
    storage: PostgresStorage,
) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    other = f"tenant-{uuid.uuid4()}"
    manifest, decision = _decided_manifest(storage, tenant)
    binding = storage.store_case_document_evidence_binding(
        tenant,
        "case-operator",
        manifest.manifest_id,
        manifest.evidence_sha256,
        decision.decision_sha256,
        "binding-idempotency",
        "9" * 64,
        binding_id=f"binding-{uuid.uuid4()}",
    )
    assert binding.company_id == tenant
    assert binding.manifest_id == manifest.manifest_id
    assert binding.manifest_evidence_sha256 == manifest.evidence_sha256
    assert binding.decision_sha256 == decision.decision_sha256
    assert binding.status is CompletenessStatus.PASS
    assert binding.bound_by == "case-operator"
    assert len(binding.binding_sha256) == 64
    replay = storage.store_case_document_evidence_binding(
        tenant,
        "case-operator",
        manifest.manifest_id,
        manifest.evidence_sha256,
        decision.decision_sha256,
        "binding-idempotency",
        "9" * 64,
        binding_id=f"binding-{uuid.uuid4()}",
    )
    assert replay == binding
    assert storage.get_case_document_evidence_binding(tenant, binding.binding_id) == binding
    assert storage.get_case_document_evidence_binding(other, binding.binding_id) is None
    assert storage.get_case_document_evidence_binding(tenant, "no-such-binding") is None
    with pytest.raises(IdempotencyConflict):
        storage.store_case_document_evidence_binding(
            tenant,
            "case-operator",
            manifest.manifest_id,
            manifest.evidence_sha256,
            decision.decision_sha256,
            "binding-idempotency",
            "a" * 64,
            binding_id=f"binding-{uuid.uuid4()}",
        )
    with storage.transaction(other) as connection:
        assert (
            connection.execute(select(func.count()).select_from(case_document_evidence_bindings)).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                select(func.count()).select_from(audit_events).where(
                    audit_events.c.event_type == "case.evidence_binding_created"
                )
            ).scalar_one()
            == 0
        )
    with storage.transaction(tenant) as connection, pytest.raises(DBAPIError):
        connection.execute(
            update(case_document_evidence_bindings)
            .where(case_document_evidence_bindings.c.binding_id == binding.binding_id)
            .values(status="FAIL")
        )
    with storage.transaction(tenant) as connection, pytest.raises(DBAPIError):
        connection.execute(
            delete(case_document_evidence_bindings).where(
                case_document_evidence_bindings.c.binding_id == binding.binding_id
            )
        )


def test_case_evidence_binding_rejects_stale_and_missing(
    storage: PostgresStorage,
) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    manifest, decision = _decided_manifest(storage, tenant)
    with pytest.raises(CaseEvidenceNotFound, match="not found"):
        storage.store_case_document_evidence_binding(
            tenant,
            "case-operator",
            "no-such-manifest",
            "0" * 64,
            decision.decision_sha256,
            "binding-missing",
            "b" * 64,
        )
    with pytest.raises(CaseEvidenceSourceMismatch, match="stale"):
        storage.store_case_document_evidence_binding(
            tenant,
            "case-operator",
            manifest.manifest_id,
            "0" * 64,
            decision.decision_sha256,
            "binding-stale-manifest",
            "c" * 64,
        )
    with pytest.raises(CaseEvidenceSourceMismatch, match="stale"):
        storage.store_case_document_evidence_binding(
            tenant,
            "case-operator",
            manifest.manifest_id,
            manifest.evidence_sha256,
            "1" * 64,
            "binding-stale-decision",
            "d" * 64,
        )


def test_case_evidence_binding_forged_row_is_rejected(
    storage: PostgresStorage,
) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    manifest, decision = _decided_manifest(storage, tenant)
    binding = storage.store_case_document_evidence_binding(
        tenant,
        "case-operator",
        manifest.manifest_id,
        manifest.evidence_sha256,
        decision.decision_sha256,
        "binding-forged",
        "e" * 64,
    )
    with storage.transaction(tenant) as connection:
        row = (
            connection.execute(
                select(case_document_evidence_bindings).where(
                    case_document_evidence_bindings.c.binding_id == binding.binding_id
                )
            )
            .mappings()
            .one()
        )
        forged = dict(row)
        forged["binding_id"] = f"forged-{uuid.uuid4()}"
        forged["status"] = "FAIL"
        with pytest.raises(DBAPIError):
            connection.execute(case_document_evidence_bindings.insert().values(**forged))
