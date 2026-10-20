from datetime import timedelta

import pytest

from case_support import AT
from procurement.documents.application_review import ApplicationReviewRecord
from procurement.documents.application_submission import (
    ApplicationSubmissionRecord,
    SubmissionApprovalStatus,
    build_submission_approval,
    build_submission_intent,
    submission_approval_is_current,
)
from procurement.domain.actions import is_authorized
from test_application_review import _decide, _record


def _reviewed() -> ApplicationReviewRecord:
    package = _record()
    return ApplicationReviewRecord(evidence=package, decision=_decide(package))


def test_exact_submission_approval_is_independent_and_short_lived() -> None:
    reviewed = _reviewed()
    intent = build_submission_intent(
        reviewed,
        action_id="submission-1",
        destination="https://zakupki.example/submit/123",
        prepared_by="operator-c",
        prepared_at=AT + timedelta(minutes=4),
    )
    assert intent.request.payload["price_ex_vat"] == str(
        reviewed.evidence.package.proposed_price_ex_vat  # type: ignore[union-attr]
    )
    assert intent.request.payload["attachments"][0]["document_sha256"] == "b" * 64
    pending = ApplicationSubmissionRecord(evidence=reviewed, intent=intent)
    decided_at = AT + timedelta(minutes=5)
    decision = build_submission_approval(
        pending,
        status=SubmissionApprovalStatus.APPROVED,
        reason="Цена, файлы и адрес сверены",
        decided_by="approver-b",
        decided_at=decided_at,
    )
    record = ApplicationSubmissionRecord(evidence=reviewed, intent=intent, decision=decision)
    assert decision.approval is not None
    assert decision.approval.expires_at <= decided_at + timedelta(minutes=15)
    assert submission_approval_is_current(record, decided_at)
    assert not submission_approval_is_current(record, decision.approval.expires_at)
    assert not is_authorized(
        intent.request.model_copy(
            update={"payload": intent.request.payload | {"price_ex_vat": "1"}}
        ),
        decision.approval,
        decided_at,
    )
    tampered_request = intent.request.model_copy(
        update={"payload": intent.request.payload | {"destination": "https://other.example/submit"}}
    )
    tampered_record = record.model_copy(
        update={"intent": intent.model_copy(update={"request": tampered_request})}
    )
    assert not submission_approval_is_current(tampered_record, decided_at)
    assert not decision.external_action_performed


def test_submission_rejects_unreviewed_self_approval_and_bad_destination() -> None:
    package = _record()
    with pytest.raises(ValueError, match="PASS package review"):
        build_submission_intent(
            ApplicationReviewRecord(evidence=package),
            action_id="submission-1",
            destination="https://zakupki.example/submit",
            prepared_by="operator-c",
            prepared_at=AT + timedelta(minutes=4),
        )
    reviewed = ApplicationReviewRecord(evidence=package, decision=_decide(package))
    with pytest.raises(ValueError, match="HTTPS"):
        build_submission_intent(
            reviewed,
            action_id="submission-1",
            destination="http://zakupki.example/submit",
            prepared_by="operator-c",
            prepared_at=AT + timedelta(minutes=4),
        )
    intent = build_submission_intent(
        reviewed,
        action_id="submission-1",
        destination="https://zakupki.example/submit",
        prepared_by="operator-c",
        prepared_at=AT + timedelta(minutes=4),
    )
    record = ApplicationSubmissionRecord(evidence=reviewed, intent=intent)
    for actor in ("operator-c", "operator-b", "reviewer-a"):
        with pytest.raises(ValueError, match="independent"):
            build_submission_approval(
                record,
                status=SubmissionApprovalStatus.APPROVED,
                reason="ok",
                decided_by=actor,
                decided_at=AT + timedelta(minutes=5),
            )
    rejected = build_submission_approval(
        record,
        status=SubmissionApprovalStatus.REJECTED,
        reason="Адрес не подтверждён",
        decided_by="approver-b",
        decided_at=AT + timedelta(minutes=5),
    )
    assert rejected.approval is None
    assert not submission_approval_is_current(
        ApplicationSubmissionRecord(evidence=reviewed, intent=intent, decision=rejected),
        AT + timedelta(minutes=5),
    )
