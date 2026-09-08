"""Подтверждение человека связано с точным исходящим payload."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from procurement.domain.actions import ActionRequest, ActionType, Approval, is_authorized


def test_modified_payload_is_not_authorized() -> None:
    now = datetime.now(UTC)
    request = ActionRequest.prepare(
        action_id="a-1",
        company_id="tenant-1",
        tender_id="t-1",
        action_type=ActionType.SUBMIT_APPLICATION,
        payload={"price": "1270000.00"},
        created_at=now,
    )
    approval = Approval(
        company_id=request.company_id,
        tender_id=request.tender_id,
        action_type=request.action_type,
        action_id="a-1",
        payload_sha256=request.payload_sha256,
        approved_by="owner-1",
        approved_at=now,
        expires_at=now + timedelta(minutes=10),
    )
    changed = ActionRequest.prepare(
        action_id="a-1",
        company_id="tenant-1",
        tender_id="t-1",
        action_type=ActionType.SUBMIT_APPLICATION,
        payload={"price": "1260000.00"},
        created_at=now,
    )
    assert is_authorized(request, approval, now + timedelta(minutes=1)) is True
    assert is_authorized(changed, approval, now + timedelta(minutes=1)) is False


def test_expired_approval_is_not_authorized() -> None:
    now = datetime.now(UTC)
    request = ActionRequest.prepare(
        action_id="a-2",
        company_id="tenant-1",
        tender_id="t-2",
        action_type=ActionType.REQUEST_BANK_GUARANTEE,
        payload={"amount": "100000.00"},
        created_at=now,
    )
    approval = Approval(
        company_id=request.company_id,
        tender_id=request.tender_id,
        action_type=request.action_type,
        action_id=request.action_id,
        payload_sha256=request.payload_sha256,
        approved_by="owner-1",
        approved_at=now,
        expires_at=now + timedelta(minutes=1),
    )
    assert is_authorized(request, approval, now + timedelta(minutes=2)) is False


@pytest.mark.parametrize(
    "change",
    [
        {"company_id": "tenant-2"},
        {"tender_id": "another-tender"},
        {"action_type": ActionType.SIGN_SUPPLIER_CONTRACT},
    ],
)
def test_approval_cannot_cross_context(change: dict[str, str]) -> None:
    now = datetime.now(UTC)
    request = ActionRequest.prepare(
        action_id="same-id",
        company_id="tenant-1",
        tender_id="t-1",
        action_type=ActionType.SEND_RFQ,
        payload={"message": "test"},
        created_at=now,
    )
    approval = Approval(
        company_id=request.company_id,
        tender_id=request.tender_id,
        action_type=request.action_type,
        action_id=request.action_id,
        payload_sha256=request.payload_sha256,
        approved_by="owner",
        approved_at=now,
        expires_at=now + timedelta(minutes=1),
    )
    assert not is_authorized(request.model_copy(update=change), approval, now)


def test_in_place_payload_mutation_revokes_approval() -> None:
    now = datetime.now(UTC)
    request = ActionRequest.prepare(
        action_id="a",
        company_id="c",
        tender_id="t",
        action_type=ActionType.SEND_RFQ,
        payload={"attachment": {"sha256": "original"}},
        created_at=now,
    )
    approval = Approval(
        company_id="c",
        tender_id="t",
        action_type=request.action_type,
        action_id="a",
        payload_sha256=request.payload_sha256,
        approved_by="owner",
        approved_at=now,
        expires_at=now + timedelta(minutes=1),
    )
    request.payload["attachment"]["sha256"] = "changed"
    assert not is_authorized(request, approval, now)


def test_forged_payload_digest_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ActionRequest(
            action_id="a-3",
            company_id="tenant-1",
            tender_id="t-3",
            action_type=ActionType.PLACE_BID,
            payload={"price": "100.00"},
            payload_sha256="0" * 64,
            created_at=datetime.now(UTC),
        )
