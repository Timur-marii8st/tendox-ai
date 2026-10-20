"""Подтверждение человека связано с точным исходящим payload."""

from datetime import UTC, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel, ValidationError

from procurement.domain.actions import (
    ActionRequest,
    ActionType,
    Approval,
    AuditEvent,
    is_authorized,
    payload_digest,
)


class NoOffsetTimezone(tzinfo):
    """tzinfo присутствует, но не делает время timezone-aware."""

    def utcoffset(self, dt: datetime | None) -> None:
        return None


class InjectedPayloadModel(BaseModel):
    value: str


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


def test_models_forbid_extra_fields_and_are_frozen() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        ActionRequest(
            action_id="extra-request",
            company_id="tenant-1",
            tender_id="t-1",
            action_type=ActionType.SEND_RFQ,
            payload={"message": "test"},
            payload_sha256=payload_digest({"message": "test"}),
            created_at=now,
            unexpected="value",  # type: ignore[call-arg]
        )
    with pytest.raises(ValidationError):
        Approval(
            company_id="tenant-1",
            tender_id="t-1",
            action_type=ActionType.SEND_RFQ,
            action_id="extra-approval",
            payload_sha256=payload_digest({"message": "test"}),
            approved_by="owner-1",
            approved_at=now,
            expires_at=now + timedelta(minutes=1),
            unexpected="value",
        )
    with pytest.raises(ValidationError):
        AuditEvent(
            event_id="extra-audit",
            company_id="tenant-1",
            actor="owner-1",
            action="prepared",
            basis=("request-1",),
            occurred_at=now,
            object_id="request-1",
            unexpected="value",
        )

    request = ActionRequest.prepare(
        action_id="frozen-request",
        company_id="tenant-1",
        tender_id="t-1",
        action_type=ActionType.SEND_RFQ,
        payload={"message": "test"},
        created_at=now,
    )
    with pytest.raises(ValidationError):
        request.company_id = "tenant-2"


@pytest.mark.parametrize(
    "payload",
    [
        {"value": b"bytes"},
        {"value": datetime.now(UTC)},
        {"value": object()},
        {"value": ("tuple",)},
        {"nested": {1: "numeric-key"}},
        {"nested": {True: "boolean-key"}},
    ],
)
def test_payload_digest_rejects_non_json_values_and_non_string_keys(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        payload_digest(payload)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_payload_digest_rejects_non_finite_floats(value: float) -> None:
    with pytest.raises(ValueError):
        payload_digest({"value": value})


def test_payload_digest_rejects_root_non_object_and_python_key_collision() -> None:
    with pytest.raises(ValueError):
        payload_digest([])  # type: ignore[arg-type]

    boolean_integer_collision = {True: "boolean"}
    boolean_integer_collision[1] = "integer"
    assert len(boolean_integer_collision) == 1
    with pytest.raises(ValueError):
        payload_digest(boolean_integer_collision)  # type: ignore[arg-type]


def test_payload_digest_is_type_sensitive_and_deterministic_for_unicode() -> None:
    digests = {
        payload_digest({"value": True}),
        payload_digest({"value": 1}),
        payload_digest({"value": 1.0}),
    }
    assert len(digests) == 3
    assert payload_digest({"ключ": "ёж", "a": [1, "два"]}) == payload_digest(
        {"a": [1, "два"], "ключ": "ёж"}
    )


def test_payload_digest_rejects_cycles_and_excessive_depth() -> None:
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic
    with pytest.raises(ValueError):
        payload_digest(cyclic)

    deep: dict[str, object] = {}
    cursor = deep
    for _ in range(66):
        nested: dict[str, object] = {}
        cursor["nested"] = nested
        cursor = nested
    with pytest.raises(ValueError):
        payload_digest(deep)


def test_action_request_rejects_payload_before_pydantic_can_coerce_keys() -> None:
    with pytest.raises(ValidationError):
        ActionRequest(
            action_id="a-coercion",
            company_id="tenant-1",
            tender_id="t-1",
            action_type=ActionType.SEND_RFQ,
            payload={1: "not-a-string-key"},  # type: ignore[dict-item]
            payload_sha256="0" * 64,
            created_at=datetime.now(UTC),
        )


def test_naive_or_offsetless_times_are_rejected() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        ActionRequest.prepare(
            action_id="naive-request",
            company_id="tenant-1",
            tender_id="t-1",
            action_type=ActionType.SEND_RFQ,
            payload={"message": "test"},
            created_at=datetime.now(),
        )
    with pytest.raises(ValidationError):
        Approval(
            company_id="tenant-1",
            tender_id="t-1",
            action_type=ActionType.SEND_RFQ,
            action_id="offsetless-approval",
            payload_sha256=payload_digest({"message": "test"}),
            approved_by="owner-1",
            approved_at=now,
            expires_at=datetime(2026, 1, 1, tzinfo=NoOffsetTimezone()),
        )
    with pytest.raises(ValidationError):
        AuditEvent(
            event_id="naive-audit",
            company_id="tenant-1",
            actor="owner-1",
            action="prepared",
            basis=("request-1",),
            occurred_at=datetime.now(),
            object_id="request-1",
        )


def test_authorization_fails_closed_for_corrupted_payload_or_times() -> None:
    now = datetime.now(UTC)
    request = ActionRequest.prepare(
        action_id="a-corrupted",
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
        approved_by="owner-1",
        approved_at=now,
        expires_at=now + timedelta(minutes=1),
    )

    corrupted_payload = request.model_copy(update={"payload": {"when": datetime.now(UTC)}})
    assert not is_authorized(corrupted_payload, approval, now)
    injected_payload = request.model_copy(
        update={"payload": {"message": InjectedPayloadModel(value="test")}}
    )
    assert not is_authorized(injected_payload, approval, now)
    corrupted_time = approval.model_copy(update={"approved_at": datetime.now()})
    assert not is_authorized(request, corrupted_time, now)
    corrupted_actor = approval.model_copy(update={"approved_by": None})
    assert not is_authorized(request, corrupted_actor, now)
    with pytest.raises(ValueError):
        is_authorized(request, approval, datetime.now())


def test_authorization_compares_dst_fold_times_as_utc_instants() -> None:
    timezone = ZoneInfo("Europe/Berlin")
    request_created_at = datetime(2026, 10, 25, 2, 0, tzinfo=timezone, fold=0)
    approved_at = datetime(2026, 10, 25, 2, 15, tzinfo=timezone, fold=0)
    expires_at = datetime(2026, 10, 25, 2, 30, tzinfo=timezone, fold=0)
    after_expiry = datetime(2026, 10, 25, 2, 15, tzinfo=timezone, fold=1)
    request = ActionRequest.prepare(
        action_id="a-dst-fold",
        company_id="tenant-1",
        tender_id="t-1",
        action_type=ActionType.SEND_RFQ,
        payload={"message": "test"},
        created_at=request_created_at,
    )
    approval = Approval(
        company_id=request.company_id,
        tender_id=request.tender_id,
        action_type=request.action_type,
        action_id=request.action_id,
        payload_sha256=request.payload_sha256,
        approved_by="owner-1",
        approved_at=approved_at,
        expires_at=expires_at,
    )

    assert not is_authorized(request, approval, after_expiry)
