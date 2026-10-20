from datetime import timedelta

import pytest

from case_support import AT
from procurement.documents.application_review import ApplicationReviewRecord
from procurement.documents.application_submission import (
    ApplicationSubmissionRecord,
    SubmissionApprovalStatus,
    build_submission_approval,
    build_submission_intent,
)
from procurement.documents.application_submission_execution import (
    ApplicationSubmissionExecutionRecord,
    build_submission_admission,
)
from test_application_review import _decide
from test_application_review_api import Service

BYTES = b"exact application bytes"


def _approved() -> ApplicationSubmissionRecord:
    source = Service().evidence
    reviewed = ApplicationReviewRecord(evidence=source, decision=_decide(source))
    intent = build_submission_intent(
        reviewed,
        action_id="action-1",
        destination="https://zakupki.example/submit",
        prepared_by="operator-c",
        prepared_at=AT + timedelta(minutes=4),
    )
    pending = ApplicationSubmissionRecord(evidence=reviewed, intent=intent)
    decision = build_submission_approval(
        pending,
        status=SubmissionApprovalStatus.APPROVED,
        reason="Адрес и файлы сверены",
        decided_by="approver-b",
        decided_at=AT + timedelta(minutes=5),
    )
    return ApplicationSubmissionRecord(evidence=reviewed, intent=intent, decision=decision)


def test_admission_binds_approved_command_and_original_bytes_without_dispatch() -> None:
    approved = _approved()
    admitted_at = AT + timedelta(minutes=6)
    admission = build_submission_admission(
        approved,
        attachment_bytes={"application-document": BYTES},
        admission_id="admission-1",
        admitted_by="executor-a",
        admitted_at=admitted_at,
    )
    record = ApplicationSubmissionExecutionRecord(submission=approved, admission=admission)
    assert record.admission is not None
    assert record.admission.attachments[0].byte_size == len(BYTES)
    assert record.admission.payload_sha256 == approved.intent.request.payload_sha256  # type: ignore[union-attr]
    assert record.admission.status == "ADMITTED_NO_DISPATCH"
    assert record.admission.external_action_performed is False


def test_admission_rejects_changed_missing_extra_bytes_and_expired_approval() -> None:
    approved = _approved()
    base = dict(
        admission_id="admission-1",
        admitted_by="executor-a",
        admitted_at=AT + timedelta(minutes=6),
    )
    for payload in (
        {"application-document": b"changed"},
        {},
        {"application-document": BYTES, "unexpected": b"x"},
    ):
        with pytest.raises(ValueError):
            build_submission_admission(approved, attachment_bytes=payload, **base)
    with pytest.raises(ValueError, match="independent"):
        build_submission_admission(
            approved,
            attachment_bytes={"application-document": BYTES},
            **(base | {"admitted_by": "approver-b"}),
        )
    assert approved.decision is not None and approved.decision.approval is not None
    with pytest.raises(ValueError, match="expired"):
        build_submission_admission(
            approved,
            attachment_bytes={"application-document": BYTES},
            **(base | {"admitted_at": approved.decision.approval.expires_at}),
        )
