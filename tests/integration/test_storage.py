"""PostgreSQL-only integration checks for persistence and tenant isolation."""

from __future__ import annotations

import hashlib
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError

from case_support import paper_case_at, reviewed
from procurement.access import AccessRole
from procurement.documents import (
    ApplicationAttachmentInput,
    ApplicationAttachmentReview,
    ApplicationDocumentRequirement,
    ApplicationInventoryAssessment,
    ApplicationPriceAssessment,
    ApplicationRequirementKind,
    ApplicationRequirementReview,
    DocumentRole,
    ExtractionResult,
    ExtractionStatus,
    ParticipationDecisionStatus,
)
from procurement.documents.application_submission import SubmissionApprovalStatus
from procurement.domain.cases import ProcurementCase, case_input_digest, evaluate_case
from procurement.domain.compliance import Verdict
from procurement.domain.sourcing import (
    LeadSourceKind,
    ServerShortlist,
    SourcingRunRecord,
    SourcingRunStatus,
    SourcingSourceSnapshot,
    SourcingSourceStatus,
)
from procurement.storage import (
    ApplicationReviewSourceMismatch,
    AuditEventRecord,
    CaseVersionConflict,
    IdempotencyConflict,
    ParticipationDecisionSourceMismatch,
    PostgresStorage,
)
from procurement.storage.models import (
    application_package_reviews,
    application_packages,
    application_submission_admissions,
    application_submission_approvals,
    application_submission_intents,
    audit_events,
    case_versions,
    participation_decisions,
    sourcing_run_sources,
    sourcing_runs,
)
from procurement.storage.repository import (
    ApplicationSubmissionConflict,
    ApplicationSubmissionSourceMismatch,
)

AT = datetime.now(UTC)


def _retarget_case(company_id: str, *, case_id: str | None = None) -> ProcurementCase:
    payload = paper_case_at(AT).model_dump(mode="python")
    payload["company_id"] = company_id
    payload["case_id"] = case_id or f"case-{uuid.uuid4()}"
    payload["profile"]["company_id"] = company_id
    if payload["selected_quote"] is not None:
        payload["selected_quote"]["company_id"] = company_id
    return ProcurementCase.model_validate(payload)


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


def test_case_roundtrip_is_scoped_and_preserves_economics(storage: PostgresStorage) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    other = f"tenant-{uuid.uuid4()}"
    case = _retarget_case(tenant)

    storage.save_case(tenant, case)
    restored = storage.get_case(tenant, case.case_id, case.version)

    assert restored == case
    assert restored is not None and restored.scenarios == case.scenarios
    assert storage.get_case(other, case.case_id, case.version) is None
    assert storage.list_case_versions(other, case.case_id) == []
    assert storage.list_cases(other).items == ()


def test_sourcing_snapshot_roundtrip_is_idempotent_and_tenant_scoped(
    storage: PostgresStorage,
) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    other = f"tenant-{uuid.uuid4()}"
    case = _retarget_case(tenant)
    storage.save_case(tenant, case)
    content = b"<html>immutable public catalog snapshot</html>"
    created_at = datetime.now(UTC)
    record = SourcingRunRecord(
        company_id=tenant,
        run_id=f"run-{uuid.uuid4()}",
        case_id=case.case_id,
        case_version=case.version,
        query="DL360 Gen12",
        source_name="ServerMall",
        source_url="https://servermall.ru/sets/servery-hp-proliant-gen12/",
        status=SourcingRunStatus.COMPLETED,
        source_sha256=hashlib.sha256(content).hexdigest(),
        source_byte_size=len(content),
        observed_at=created_at,
        shortlist=ServerShortlist(review_queue=(), rejected=()),
        technical_scope_reason="Проверенный набор требований ещё не привязан.",
        created_at=created_at,
    )

    stored = storage.store_sourcing_run(
        tenant,
        "operator",
        record,
        content,
        idempotency_key="source-once",
        request_sha256="7" * 64,
    )
    replay = storage.store_sourcing_run(
        tenant,
        "operator",
        record.model_copy(update={"run_id": "ignored-on-replay"}),
        content,
        idempotency_key="source-once",
        request_sha256="7" * 64,
    )

    assert stored == replay == record
    assert storage.get_latest_sourcing_run(tenant, case.case_id, case.version) == record
    assert storage.get_latest_sourcing_run(other, case.case_id, case.version) is None
    with storage.transaction(other) as connection:
        assert connection.execute(select(func.count()).select_from(sourcing_runs)).scalar_one() == 0


def test_multi_source_sourcing_artifacts_are_exact_and_tenant_scoped(
    storage: PostgresStorage,
) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    other = f"tenant-{uuid.uuid4()}"
    case = _retarget_case(tenant)
    storage.save_case(tenant, case)
    exact_source = b"<html>HPE ProLiant Compute DL360 Gen12 QuickSpecs</html>"
    manifest = b'{"schema_version":"sourcing-source-manifest-v1"}'
    observed_at = datetime.now(UTC)
    record = SourcingRunRecord(
        company_id=tenant,
        run_id=f"run-{uuid.uuid4()}",
        case_id=case.case_id,
        case_version=case.version,
        query="DL360 Gen12",
        source_name="Manufacturer and supplier catalogs",
        source_url="https://www.hpe.com/psnow/doc/a50006984enw",
        status=SourcingRunStatus.COMPLETED,
        source_sha256=hashlib.sha256(manifest).hexdigest(),
        source_byte_size=len(manifest),
        observed_at=observed_at,
        sources=(
            SourcingSourceSnapshot(
                ordinal=1,
                source_name="HPE official catalog",
                source_kind=LeadSourceKind.MANUFACTURER_CATALOG,
                source_url="https://www.hpe.com/psnow/doc/a50006984enw",
                media_type="text/html",
                status=SourcingSourceStatus.COMPLETED,
                source_sha256=hashlib.sha256(exact_source).hexdigest(),
                source_byte_size=len(exact_source),
                observed_at=observed_at,
            ),
            SourcingSourceSnapshot(
                ordinal=2,
                source_name="ServerMall",
                source_kind=LeadSourceKind.SUPPLIER_CATALOG,
                source_url="https://servermall.ru/sets/servery-hp-proliant-gen12/",
                media_type="text/html",
                status=SourcingSourceStatus.SOURCE_ERROR,
                observed_at=observed_at,
                error_code="SOURCE_UNAVAILABLE_OR_CHANGED",
            ),
        ),
        shortlist=ServerShortlist(review_queue=(), rejected=()),
        technical_scope_reason="Exact BOM remains unverified.",
        created_at=observed_at,
    )

    stored = storage.store_sourcing_run(
        tenant,
        "operator",
        record,
        manifest,
        source_contents=(exact_source, None),
        idempotency_key="multi-source-once",
        request_sha256="8" * 64,
    )

    assert stored == record
    with storage.transaction(tenant) as connection:
        rows = (
            connection.execute(
                select(sourcing_run_sources).order_by(sourcing_run_sources.c.ordinal)
            )
            .mappings()
            .all()
        )
        assert len(rows) == 2
        assert rows[0]["source_content"] == exact_source
        assert rows[1]["source_content"] is None
    with storage.transaction(other) as connection:
        assert (
            connection.execute(select(func.count()).select_from(sourcing_run_sources)).scalar_one()
            == 0
        )


def test_case_versions_are_immutable_and_exact_replay_is_idempotent(
    storage: PostgresStorage,
) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    case = _retarget_case(tenant)
    storage.save_case(tenant, case)
    assert storage.save_case(tenant, case) == case

    changed = case.model_copy(update={"nmck_ex_vat": case.nmck_ex_vat + 1})
    with pytest.raises(CaseVersionConflict):
        storage.save_case(tenant, changed)


def test_strict_create_replays_only_the_same_idempotency_request(
    storage: PostgresStorage,
) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    case = _retarget_case(tenant)
    digest = "1" * 64
    storage.save_case(
        tenant,
        case,
        idempotency_key="create-one",
        request_sha256=digest,
    )
    assert (
        storage.save_case(
            tenant,
            case,
            idempotency_key="create-one",
            request_sha256=digest,
        )
        == case
    )
    with pytest.raises(IdempotencyConflict):
        storage.save_case(
            tenant,
            case,
            idempotency_key="create-one",
            request_sha256="2" * 64,
        )
    with pytest.raises(CaseVersionConflict):
        storage.save_case(
            tenant,
            case,
            idempotency_key="create-two",
            request_sha256=digest,
        )


def test_same_idempotent_create_is_serialized_under_concurrency(storage: PostgresStorage) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    case = _retarget_case(tenant)

    def save() -> ProcurementCase:
        return storage.save_case(
            tenant,
            case,
            idempotency_key="concurrent-create",
            request_sha256="3" * 64,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: save(), range(2)))
    assert results == [case, case]


def test_latest_case_list_uses_cursor_and_never_crosses_tenant(storage: PostgresStorage) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    other = f"tenant-{uuid.uuid4()}"
    first = _retarget_case(tenant, case_id="a-case")
    second = _retarget_case(tenant, case_id="b-case")
    storage.save_case(tenant, first)
    storage.save_case(tenant, first.model_copy(update={"version": 2}))
    storage.save_case(tenant, second)
    storage.save_case(other, _retarget_case(other, case_id="secret-case"))

    page_one = storage.list_cases(tenant, limit=1)
    page_two = storage.list_cases(tenant, limit=1, cursor=page_one.next_cursor)

    assert [(item.case_id, item.version) for item in page_one.items] == [("a-case", 2)]
    assert [(item.case_id, item.version) for item in page_two.items] == [("b-case", 1)]
    assert page_two.next_cursor is None


def test_audit_is_tenant_scoped_and_append_only(storage: PostgresStorage) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    other = f"tenant-{uuid.uuid4()}"
    event = AuditEventRecord(
        event_id=f"event-{uuid.uuid4()}",
        company_id=tenant,
        actor_id="tester",
        event_type="case.saved",
        object_type="procurement_case",
        object_id="case-one",
        object_version=1,
        basis={"source": "integration-test"},
        occurred_at=datetime.now(UTC),
    )
    storage.append_audit(event)

    assert storage.list_audit_events(tenant) == [event]
    assert storage.list_audit_events(other) == []
    with storage.transaction(tenant) as connection, pytest.raises(DBAPIError):
        connection.execute(
            audit_events.update()
            .where(audit_events.c.event_id == event.event_id)
            .values(event_type="tampered")
        )


def test_direct_sql_rls_cannot_read_guessed_other_tenant_rows(storage: PostgresStorage) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    other = f"tenant-{uuid.uuid4()}"
    secret = _retarget_case(other)
    storage.save_case(other, secret)

    with storage.transaction(tenant) as connection:
        visible = connection.execute(select(func.count()).select_from(case_versions)).scalar_one()
        guessed = connection.execute(
            select(case_versions.c.payload).where(case_versions.c.case_id == secret.case_id)
        ).scalar_one_or_none()
    assert visible == 0
    assert guessed is None


def test_case_rows_cannot_be_updated_or_deleted(storage: PostgresStorage) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    case = _retarget_case(tenant)
    storage.save_case(tenant, case)

    with storage.transaction(tenant) as connection, pytest.raises(DBAPIError):
        connection.execute(
            case_versions.update()
            .where(case_versions.c.case_id == case.case_id)
            .values(input_sha256="0" * 64)
        )
    with storage.transaction(tenant) as connection, pytest.raises(DBAPIError):
        connection.execute(case_versions.delete().where(case_versions.c.case_id == case.case_id))


def test_evaluation_audit_and_receipt_are_atomic_and_replayable(
    storage: PostgresStorage,
) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    case = _retarget_case(tenant)
    storage.save_case(tenant, case)
    recommendation = evaluate_case(case, at=AT)
    digest = case_input_digest(case)

    first = storage.record_evaluation(
        tenant,
        "reviewer",
        case.case_id,
        case.version,
        AT,
        digest,
        "domain-s1-v1",
        recommendation,
        "evaluate-once",
        "4" * 64,
    )
    replay = storage.record_evaluation(
        tenant,
        "reviewer",
        case.case_id,
        case.version,
        AT,
        digest,
        "domain-s1-v1",
        recommendation,
        "evaluate-once",
        "4" * 64,
    )

    assert replay == first
    assert first.engine_version == "domain-s1-v1"
    events = storage.list_audit_events(
        tenant,
        object_type="procurement_case",
        object_id=case.case_id,
    )
    assert len(events) == 1
    assert events[0].event_id == first.evaluation_id
    assert events[0].occurred_at == first.created_at
    assert events[0].basis["engine_version"] == "domain-s1-v1"


def test_latest_evaluation_is_ordered_and_tenant_scoped(storage: PostgresStorage) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    other = f"tenant-{uuid.uuid4()}"
    case = _retarget_case(tenant)
    storage.save_case(tenant, case)
    digest = case_input_digest(case)

    assert storage.get_latest_evaluation(tenant, case.case_id, case.version) is None
    first = storage.record_evaluation(
        tenant,
        "reviewer",
        case.case_id,
        case.version,
        AT,
        digest,
        "engine-v1",
        evaluate_case(case, at=AT),
        "latest-first",
        "5" * 64,
    )
    second = storage.record_evaluation(
        tenant,
        "reviewer",
        case.case_id,
        case.version,
        AT,
        digest,
        "engine-v2",
        evaluate_case(case, at=AT),
        "latest-second",
        "6" * 64,
    )

    assert first.evaluation_id != second.evaluation_id
    assert storage.get_latest_evaluation(tenant, case.case_id, case.version) == second
    assert storage.get_latest_evaluation(other, case.case_id, case.version) is None


def test_participation_decision_is_exact_independent_atomic_and_tenant_scoped(
    storage: PostgresStorage,
) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    other = f"tenant-{uuid.uuid4()}"
    case = reviewed(_retarget_case(tenant))
    storage.save_case(tenant, case)
    evaluation = storage.record_evaluation(
        tenant,
        "operator-a",
        case.case_id,
        case.version,
        AT,
        case_input_digest(case),
        "domain-s1-v1",
        evaluate_case(case, at=AT),
        "participation-evaluation",
        "a" * 64,
    )
    pending = storage.get_participation_decision(tenant, evaluation.evaluation_id)
    assert pending is not None and pending.decision is None
    decision = storage.decide_participation(
        tenant,
        "approver-a",
        evaluation.evaluation_id,
        pending.evidence.evidence_sha256,
        ParticipationDecisionStatus.APPROVED,
        "Все основания проверены независимо",
        "participation-decision",
        "b" * 64,
    )
    replay = storage.decide_participation(
        tenant,
        "approver-a",
        evaluation.evaluation_id,
        pending.evidence.evidence_sha256,
        ParticipationDecisionStatus.APPROVED,
        "Все основания проверены независимо",
        "participation-decision",
        "b" * 64,
    )
    assert replay == decision
    assert decision.external_action_authorized is False
    assert decision.decided_by == "approver-a"
    assert storage.get_participation_decision(other, evaluation.evaluation_id) is None
    events = storage.list_audit_events(
        tenant, object_type="procurement_case", object_id=case.case_id
    )
    assert [event.event_type for event in events] == [
        "case.evaluated",
        "case.participation_decided",
    ]
    with storage.transaction(tenant) as connection, pytest.raises(DBAPIError):
        connection.execute(
            participation_decisions.update()
            .where(participation_decisions.c.evaluation_id == evaluation.evaluation_id)
            .values(status="REJECTED")
        )


def test_participation_decision_blocks_self_approval(storage: PostgresStorage) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    case = reviewed(_retarget_case(tenant))
    storage.save_case(tenant, case)
    evaluation = storage.record_evaluation(
        tenant,
        "operator-a",
        case.case_id,
        case.version,
        AT,
        case_input_digest(case),
        "domain-s1-v1",
        evaluate_case(case, at=AT),
        "self-evaluation",
        "c" * 64,
    )
    pending = storage.get_participation_decision(tenant, evaluation.evaluation_id)
    assert pending is not None
    with pytest.raises(ParticipationDecisionSourceMismatch):
        storage.decide_participation(
            tenant,
            "operator-a",
            evaluation.evaluation_id,
            pending.evidence.evidence_sha256,
            ParticipationDecisionStatus.APPROVED,
            "Попытка self approval",
            "self-decision",
            "d" * 64,
        )
    assert storage.get_participation_decision(tenant, evaluation.evaluation_id) == pending


def test_application_package_is_exact_pending_atomic_and_tenant_scoped(
    storage: PostgresStorage,
) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    other = f"tenant-{uuid.uuid4()}"
    case = reviewed(_retarget_case(tenant))
    storage.save_case(tenant, case)
    evaluation = storage.record_evaluation(
        tenant,
        "operator-a",
        case.case_id,
        case.version,
        AT,
        case_input_digest(case),
        "domain-s1-v1",
        evaluate_case(case, at=AT),
        "package-evaluation",
        "e" * 64,
    )
    pending = storage.get_participation_decision(tenant, evaluation.evaluation_id)
    assert pending is not None
    decision = storage.decide_participation(
        tenant,
        "approver-a",
        evaluation.evaluation_id,
        pending.evidence.evidence_sha256,
        ParticipationDecisionStatus.APPROVED,
        "Основания проверены для подготовки заявки",
        "package-participation",
        "f" * 64,
    )
    empty_extraction = ExtractionResult(
        status=ExtractionStatus.UNKNOWN,
        source_units_total=0,
        source_units_extracted=0,
        characters_extracted=0,
    )
    tender_document = storage.store_document(
        tenant,
        "operator-b",
        "tender-requirements.pdf",
        "application/pdf",
        DocumentRole.TENDER_REQUIREMENTS,
        b"%PDF-1.4 exact tender requirements",
        empty_extraction,
        "package-tender-document",
        "1" * 64,
        document_id=f"tender-document-{uuid.uuid4()}",
    )
    attachment_document = storage.store_document(
        tenant,
        "operator-b",
        "filled-application.pdf",
        "application/pdf",
        DocumentRole.APPLICATION_ATTACHMENT,
        b"%PDF-1.4 exact filled application",
        empty_extraction,
        "package-attachment-document",
        "2" * 64,
        document_id=f"application-document-{uuid.uuid4()}",
    )
    requirements = (
        ApplicationDocumentRequirement(
            ordinal=1,
            kind=ApplicationRequirementKind.FORM,
            title="Форма заявки",
            source_document_id=tender_document.document_id,
            source_document_sha256=tender_document.sha256,
            source_locator="Раздел 4, форма 1",
        ),
    )
    attachments = (
        ApplicationAttachmentInput(
            ordinal=1,
            requirement_ordinals=(1,),
            document_id=attachment_document.document_id,
            document_sha256=attachment_document.sha256,
            submission_filename="application.pdf",
        ),
    )
    stored = storage.store_application_package(
        tenant,
        "operator-b",
        package_id=f"package-{uuid.uuid4()}",
        participation_decision_id=decision.decision_id,
        participation_decision_sha256=decision.decision_sha256,
        proposed_price_ex_vat=Decimal("1300000.00"),
        requirements=requirements,
        attachments=attachments,
        idempotency_key="application-package",
        request_sha256="3" * 64,
    )
    replay = storage.store_application_package(
        tenant,
        "operator-b",
        package_id="ignored-on-replay",
        participation_decision_id=decision.decision_id,
        participation_decision_sha256=decision.decision_sha256,
        proposed_price_ex_vat=Decimal("1300000.00"),
        requirements=requirements,
        attachments=attachments,
        idempotency_key="application-package",
        request_sha256="3" * 64,
    )

    assert replay == stored
    assert stored.review_status == "PENDING_REVIEW"
    assert stored.coverage_status.value == "UNKNOWN"
    assert stored.external_action_authorized is False
    loaded = storage.get_application_package(tenant, decision.decision_id)
    assert loaded is not None and loaded.package == stored
    assert storage.get_application_package(other, decision.decision_id) is None
    events = storage.list_audit_events(
        tenant, object_type="application_package", object_id=stored.package_id
    )
    assert [event.event_type for event in events] == ["application.package_prepared"]
    assert events[0].basis["package_sha256"] == stored.package_sha256
    assert storage.get_application_review(other, stored.package_id) is None
    review_pending = storage.get_application_review(tenant, stored.package_id)
    assert review_pending is not None and review_pending.decision is None
    requirement_reviews = (
        ApplicationRequirementReview(
            requirement_ordinal=1,
            status=Verdict.UNKNOWN,
            reason="Содержимое файла требует ручной проверки",
            attachment_ordinals=(1,),
        ),
    )
    attachment_reviews = (
        ApplicationAttachmentReview(
            attachment_ordinal=1,
            status=Verdict.UNKNOWN,
            reason="Извлечение текста не подтвердило содержимое",
        ),
    )
    review_kwargs = dict(
        package_id=stored.package_id,
        package_sha256=stored.package_sha256,
        requirement_reviews=requirement_reviews,
        attachment_reviews=attachment_reviews,
        inventory_assessment=ApplicationInventoryAssessment.UNRESOLVED,
        inventory_source_document_ids=(tender_document.document_id,),
        inventory_reason="Полный перечень ещё не подтверждён",
        price_assessment=ApplicationPriceAssessment.CONFIRMED,
        price_reason="Цена и НДС сверены",
        reason="Нужна дополнительная ручная проверка",
    )
    with pytest.raises(ApplicationReviewSourceMismatch):
        storage.decide_application_review(
            tenant,
            "operator-b",
            **review_kwargs,
            idempotency_key="application-self-review",
            request_sha256="4" * 64,
        )
    reviewed_package = storage.decide_application_review(
        tenant,
        "reviewer-a",
        **review_kwargs,
        idempotency_key="application-review",
        request_sha256="5" * 64,
    )
    review_replay = storage.decide_application_review(
        tenant,
        "reviewer-a",
        **review_kwargs,
        idempotency_key="application-review",
        request_sha256="5" * 64,
    )
    assert reviewed_package == review_replay
    assert reviewed_package.status is Verdict.UNKNOWN
    assert reviewed_package.external_action_authorized is False
    stored_review = storage.get_application_review(tenant, stored.package_id)
    assert stored_review is not None and stored_review.decision == reviewed_package
    review_events = storage.list_audit_events(
        tenant, object_type="application_package", object_id=stored.package_id
    )
    assert [event.event_type for event in review_events] == [
        "application.package_prepared",
        "application.package_reviewed",
    ]
    with storage.transaction(tenant) as connection, pytest.raises(DBAPIError):
        connection.execute(
            application_package_reviews.update()
            .where(application_package_reviews.c.package_id == stored.package_id)
            .values(status="PASS")
        )
    with storage.transaction(tenant) as connection, pytest.raises(DBAPIError):
        connection.execute(
            application_packages.update()
            .where(application_packages.c.package_id == stored.package_id)
            .values(package_sha256="0" * 64)
        )


def test_application_submission_is_exact_atomic_and_tenant_scoped(
    storage: PostgresStorage,
) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    other = f"tenant-{uuid.uuid4()}"
    case = reviewed(_retarget_case(tenant))
    storage.save_case(tenant, case)
    evaluation = storage.record_evaluation(
        tenant,
        "operator-a",
        case.case_id,
        case.version,
        AT,
        case_input_digest(case),
        "domain-s1-v1",
        evaluate_case(case, at=AT),
        "submission-evaluation",
        "6" * 64,
    )
    pending = storage.get_participation_decision(tenant, evaluation.evaluation_id)
    assert pending is not None
    participation = storage.decide_participation(
        tenant,
        "approver-a",
        evaluation.evaluation_id,
        pending.evidence.evidence_sha256,
        ParticipationDecisionStatus.APPROVED,
        "Участие подтверждено",
        "submission-participation",
        "7" * 64,
    )
    extraction = ExtractionResult(
        status=ExtractionStatus.UNKNOWN,
        source_units_total=0,
        source_units_extracted=0,
        characters_extracted=0,
    )
    source = storage.store_document(
        tenant,
        "operator-b",
        "requirements.pdf",
        "application/pdf",
        DocumentRole.TENDER_REQUIREMENTS,
        b"%PDF-1.4 requirements",
        extraction,
        "submission-requirements",
        "8" * 64,
        document_id=f"submission-source-{uuid.uuid4()}",
    )
    attachment = storage.store_document(
        tenant,
        "operator-b",
        "form.pdf",
        "application/pdf",
        DocumentRole.APPLICATION_ATTACHMENT,
        b"%PDF-1.4 form",
        extraction,
        "submission-attachment",
        "9" * 64,
        document_id=f"submission-file-{uuid.uuid4()}",
    )
    package = storage.store_application_package(
        tenant,
        "operator-b",
        package_id=f"package-{uuid.uuid4()}",
        participation_decision_id=participation.decision_id,
        participation_decision_sha256=participation.decision_sha256,
        proposed_price_ex_vat=Decimal("1300000.00"),
        requirements=(
            ApplicationDocumentRequirement(
                ordinal=1,
                kind=ApplicationRequirementKind.FORM,
                title="Форма",
                source_document_id=source.document_id,
                source_document_sha256=source.sha256,
                source_locator="раздел 4",
            ),
        ),
        attachments=(
            ApplicationAttachmentInput(
                ordinal=1,
                requirement_ordinals=(1,),
                document_id=attachment.document_id,
                document_sha256=attachment.sha256,
                submission_filename="form.pdf",
            ),
        ),
        idempotency_key="submission-package",
        request_sha256="a" * 64,
    )
    review = storage.decide_application_review(
        tenant,
        "reviewer-a",
        package_id=package.package_id,
        package_sha256=package.package_sha256,
        requirement_reviews=(
            ApplicationRequirementReview(
                requirement_ordinal=1,
                status=Verdict.PASS,
                reason="Сверено",
                attachment_ordinals=(1,),
            ),
        ),
        attachment_reviews=(
            ApplicationAttachmentReview(
                attachment_ordinal=1,
                status=Verdict.PASS,
                reason="Файл сверён",
            ),
        ),
        inventory_assessment=ApplicationInventoryAssessment.CONFIRMED_COMPLETE,
        inventory_source_document_ids=(source.document_id,),
        inventory_reason="Документация проверена полностью",
        price_assessment=ApplicationPriceAssessment.CONFIRMED,
        price_reason="Цена сверена",
        reason="Комплект подтверждён",
        idempotency_key="submission-review",
        request_sha256="b" * 64,
    )
    assert review.status is Verdict.PASS
    assert storage.get_application_submission(other, package.package_id) is None
    intent_kwargs = dict(
        package_id=package.package_id,
        package_sha256=package.package_sha256,
        review_decision_sha256=review.decision_sha256,
        destination="https://zakupki.example/submit/123",
        idempotency_key="submission-intent",
        request_sha256="c" * 64,
    )
    intent = storage.prepare_application_submission(tenant, "operator-c", **intent_kwargs)
    assert storage.prepare_application_submission(tenant, "operator-c", **intent_kwargs) == intent
    assert intent.request.payload["attachments"][0]["document_sha256"] == attachment.sha256
    assert storage.get_application_submission(tenant, package.package_id).intent == intent  # type: ignore[union-attr]
    decision_kwargs = dict(
        action_id=intent.request.action_id,
        payload_sha256=intent.request.payload_sha256,
        status=SubmissionApprovalStatus.APPROVED,
        reason="Адрес, цена и файлы сверены",
        idempotency_key="submission-approval",
        request_sha256="d" * 64,
    )
    with pytest.raises(ApplicationSubmissionSourceMismatch):
        storage.decide_application_submission(
            tenant, "operator-c", **(decision_kwargs | {"idempotency_key": "self"})
        )
    with pytest.raises(ApplicationSubmissionSourceMismatch):
        storage.decide_application_submission(
            tenant,
            "approver-b",
            **(
                decision_kwargs
                | {
                    "idempotency_key": "wrong-sha",
                    "payload_sha256": "e" * 64,
                }
            ),
        )
    decision = storage.decide_application_submission(tenant, "approver-b", **decision_kwargs)
    assert (
        storage.decide_application_submission(tenant, "approver-b", **decision_kwargs) == decision
    )
    assert decision.approval is not None and not decision.external_action_performed
    loaded = storage.get_application_submission(tenant, package.package_id)
    assert loaded is not None and loaded.decision == decision
    events = storage.list_audit_events(
        tenant, object_type="application_submission", object_id=intent.request.action_id
    )
    assert [event.event_type for event in events] == [
        "application.submission_prepared",
        "application.submission_approval_decided",
    ]
    with storage.transaction(tenant) as connection, pytest.raises(DBAPIError):
        connection.execute(application_submission_intents.update().values(payload_sha256="0" * 64))
    with storage.transaction(tenant) as connection, pytest.raises(DBAPIError):
        connection.execute(application_submission_approvals.update().values(status="REJECTED"))
    assert storage.get_application_submission_execution(other, package.package_id) is None
    claim_kwargs = dict(
        package_id=package.package_id,
        action_id=intent.request.action_id,
        payload_sha256=intent.request.payload_sha256,
        approval_decision_sha256=decision.decision_sha256,
        idempotency_key="submission-claim",
        request_sha256="f" * 64,
    )
    with pytest.raises(ApplicationSubmissionSourceMismatch):
        storage.claim_application_submission(
            tenant, "approver-b", **(claim_kwargs | {"idempotency_key": "self-claim"})
        )
    with pytest.raises(ApplicationSubmissionSourceMismatch):
        storage.claim_application_submission(
            tenant,
            "executor-a",
            **(
                claim_kwargs
                | {
                    "idempotency_key": "wrong-approval",
                    "approval_decision_sha256": "0" * 64,
                }
            ),
        )
    admission = storage.claim_application_submission(tenant, "executor-a", **claim_kwargs)
    assert admission.status == "ADMITTED_NO_DISPATCH"
    assert admission.attachments[0].sha256 == attachment.sha256
    assert admission.attachments[0].byte_size == len(b"%PDF-1.4 form")
    assert admission.external_action_performed is False
    assert storage.claim_application_submission(tenant, "executor-a", **claim_kwargs) == admission
    with pytest.raises(ApplicationSubmissionConflict):
        storage.claim_application_submission(
            tenant, "executor-a", **(claim_kwargs | {"idempotency_key": "second-claim"})
        )
    execution = storage.get_application_submission_execution(tenant, package.package_id)
    assert execution is not None and execution.admission == admission
    claim_events = storage.list_audit_events(
        tenant, object_type="application_submission", object_id=intent.request.action_id
    )
    assert [event.event_type for event in claim_events][-1] == "application.submission_admitted"
    with storage.transaction(tenant) as connection, pytest.raises(DBAPIError):
        connection.execute(
            application_submission_admissions.update().values(admission_sha256="0" * 64)
        )


def test_runtime_connection_has_no_unscoped_api_key_read(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection, pytest.raises(DBAPIError):
            connection.execute(text("SELECT key_digest FROM api_keys"))
    finally:
        engine.dispose()


def test_authentication_resolves_tenant_without_caller_claim(
    storage: PostgresStorage,
    database_url: str,
) -> None:
    admin_url = os.environ.get("DATABASE_ADMIN_URL")
    if not admin_url:
        pytest.skip("DATABASE_ADMIN_URL is required to provision an authentication fixture")
    secret = f"secret-{uuid.uuid4()}"
    digest = hashlib.sha256(secret.encode()).hexdigest()
    tenant = f"tenant-{uuid.uuid4()}"
    key_id = f"key-{uuid.uuid4()}"
    admin_engine = create_engine(admin_url)
    try:
        with admin_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO api_keys "
                    "(key_id, company_id, key_digest, actor_id, enabled) "
                    "VALUES (:key_id, :company_id, :key_digest, 'api-user', true)"
                ),
                {"key_id": key_id, "company_id": tenant, "key_digest": digest},
            )
    finally:
        admin_engine.dispose()

    principal = storage.authenticate_api_key(secret)
    assert principal is not None
    assert principal.company_id == tenant
    assert principal.actor_id == "api-user"
    assert principal.access_role is AccessRole.OPERATOR
    assert storage.authenticate_api_key(f"wrong-{secret}") is None
