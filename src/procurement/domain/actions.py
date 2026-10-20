"""Human-in-the-loop для любых исходящих и юридически значимых действий."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_PAYLOAD_DEPTH = 64


class ActionType(str, Enum):
    SEND_RFQ = "send_rfq"
    SUBMIT_APPLICATION = "submit_application"
    PLACE_BID = "place_bid"
    REQUEST_BANK_GUARANTEE = "request_bank_guarantee"
    ACCEPT_BANK_GUARANTEE = "accept_bank_guarantee"
    PUBLISH_PLATFORM_OFFER = "publish_platform_offer"
    ACCEPT_PLATFORM_ORDER = "accept_platform_order"
    SIGN_CUSTOMER_CONTRACT = "sign_customer_contract"
    SIGN_SUPPLIER_CONTRACT = "sign_supplier_contract"


def payload_digest(payload: dict[str, Any]) -> str:
    """Вернуть SHA-256 канонического JSON-объекта без неявных приведений типов.

    Допускаются только JSON-значения с рекурсивно строковыми ключами. Например,
    ``payload_digest({"price": "1270000.00"})``. Некорректный или циклический
    payload всегда отклоняется ``ValueError``.
    """
    _validate_payload(payload)
    try:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        encoded = canonical.encode("utf-8")
    except (OverflowError, RecursionError, TypeError, UnicodeError, ValueError) as error:
        raise ValueError("payload must be a valid JSON object") from error
    return hashlib.sha256(encoded).hexdigest()


def _validate_payload(payload: object) -> None:
    """Проверить JSON-дерево до сериализации, не допуская coercion ключей."""
    if type(payload) is not dict:
        raise ValueError("payload must be a JSON object")
    _validate_json_value(payload, depth=0, ancestors=set())


def _validate_json_value(value: object, *, depth: int, ancestors: set[int]) -> None:
    """Проверить ограниченное JSON-значение и обнаружить циклы контейнеров."""
    if depth > MAX_PAYLOAD_DEPTH:
        raise ValueError("payload exceeds maximum nesting depth")
    if type(value) is dict:
        identity = id(value)
        if identity in ancestors:
            raise ValueError("payload must not contain cycles")
        ancestors.add(identity)
        try:
            for key, nested_value in value.items():
                if type(key) is not str:
                    raise ValueError("payload object keys must be strings")
                _validate_json_value(nested_value, depth=depth + 1, ancestors=ancestors)
        finally:
            ancestors.remove(identity)
        return
    if type(value) is list:
        identity = id(value)
        if identity in ancestors:
            raise ValueError("payload must not contain cycles")
        ancestors.add(identity)
        try:
            for nested_value in value:
                _validate_json_value(nested_value, depth=depth + 1, ancestors=ancestors)
        finally:
            ancestors.remove(identity)
        return
    if type(value) is float and not math.isfinite(value):
        raise ValueError("payload must not contain non-finite floats")
    if type(value) not in (type(None), bool, int, float, str):
        raise ValueError("payload must contain only JSON values")


def _is_aware_datetime(value: datetime) -> bool:
    """Проверить timezone-aware datetime, включая tzinfo с offset=None."""
    try:
        return value.tzinfo is not None and value.utcoffset() is not None
    except Exception:
        return False


def _as_utc(value: datetime) -> datetime:
    """Normalize an already validated aware time before ordering it."""
    if not _is_aware_datetime(value):
        raise ValueError("datetime must contain a timezone")
    return value.astimezone(UTC)


class ActionRequest(BaseModel):
    """Подготовленное A1-действие; само по себе ничего наружу не отправляет."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action_id: str = Field(min_length=1)
    company_id: str = Field(min_length=1)
    tender_id: str = Field(min_length=1)
    action_type: ActionType
    payload: dict[str, Any]
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime

    @field_validator("payload", mode="before")
    @classmethod
    def _payload_is_json_object(cls, value: object) -> object:
        _validate_payload(value)
        return value

    @model_validator(mode="after")
    def _payload_and_time_are_valid(self) -> ActionRequest:
        if self.payload_sha256 != payload_digest(self.payload):
            raise ValueError("payload_sha256 не соответствует payload")
        if not _is_aware_datetime(self.created_at):
            raise ValueError("время создания действия должно содержать часовой пояс")
        return self

    @classmethod
    def prepare(
        cls,
        *,
        action_id: str,
        company_id: str,
        tender_id: str,
        action_type: ActionType,
        payload: dict[str, Any],
        created_at: datetime,
    ) -> ActionRequest:
        return cls(
            action_id=action_id,
            company_id=company_id,
            tender_id=tender_id,
            action_type=action_type,
            payload=payload,
            payload_sha256=payload_digest(payload),
            created_at=created_at,
        )


class Approval(BaseModel):
    """Одноразовое подтверждение конкретного действия и его точного содержимого."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: str = Field(min_length=1)
    tender_id: str = Field(min_length=1)
    action_type: ActionType
    action_id: str = Field(min_length=1)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_by: str = Field(min_length=1)
    approved_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def _window_is_valid(self) -> Approval:
        if not _is_aware_datetime(self.approved_at) or not _is_aware_datetime(self.expires_at):
            raise ValueError("окно подтверждения должно содержать часовой пояс")
        if _as_utc(self.expires_at) <= _as_utc(self.approved_at):
            raise ValueError("срок подтверждения должен заканчиваться после его выдачи")
        return self


def is_authorized(request: ActionRequest, approval: Approval, now: datetime) -> bool:
    """Проверить контекст, текущий payload и окно подтверждения.

    Проверка чистая: одноразовое использование, RBAC и price floor обязан
    обеспечить исполнитель в транзакции. True само по себе не отправляет действие.
    """
    if not _is_aware_datetime(now):
        raise ValueError("время подтверждения должно содержать часовой пояс")
    try:
        current_payload_sha256 = payload_digest(request.payload)
        request = ActionRequest.model_validate(request.model_dump(round_trip=True))
        approval = Approval.model_validate(approval.model_dump(round_trip=True))
        request_created_at = _as_utc(request.created_at)
        approved_at = _as_utc(approval.approved_at)
        expires_at = _as_utc(approval.expires_at)
        current_time = _as_utc(now)
        return (
            request.action_id == approval.action_id
            and request.company_id == approval.company_id
            and request.tender_id == approval.tender_id
            and request.action_type == approval.action_type
            and current_payload_sha256 == request.payload_sha256
            and request.payload_sha256 == approval.payload_sha256
            and request_created_at <= approved_at
            and approved_at <= current_time < expires_at
        )
    except Exception:
        return False


class AuditEvent(BaseModel):
    """Append-only факт: кто, что, когда и на каком основании сделал."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(min_length=1)
    company_id: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    action: str = Field(min_length=1)
    basis: tuple[str, ...] = Field(min_length=1)
    occurred_at: datetime
    object_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def _occurred_at_is_aware(self) -> AuditEvent:
        if not _is_aware_datetime(self.occurred_at):
            raise ValueError("время audit event должно содержать часовой пояс")
        return self
