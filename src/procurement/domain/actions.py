"""Human-in-the-loop для любых исходящих и юридически значимых действий."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    """SHA-256 канонического JSON: одобрение относится к точному payload."""
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class ActionRequest(BaseModel):
    """Подготовленное A1-действие; само по себе ничего наружу не отправляет."""

    model_config = ConfigDict(frozen=True)

    action_id: str = Field(min_length=1)
    company_id: str = Field(min_length=1)
    tender_id: str = Field(min_length=1)
    action_type: ActionType
    payload: dict[str, Any]
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime

    @model_validator(mode="after")
    def _payload_and_time_are_valid(self) -> ActionRequest:
        if self.payload_sha256 != payload_digest(self.payload):
            raise ValueError("payload_sha256 не соответствует payload")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
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

    model_config = ConfigDict(frozen=True)

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
        if (
            self.approved_at.tzinfo is None
            or self.approved_at.utcoffset() is None
            or self.expires_at.tzinfo is None
            or self.expires_at.utcoffset() is None
        ):
            raise ValueError("окно подтверждения должно содержать часовой пояс")
        if self.expires_at <= self.approved_at:
            raise ValueError("срок подтверждения должен заканчиваться после его выдачи")
        return self


def is_authorized(request: ActionRequest, approval: Approval, now: datetime) -> bool:
    """Проверить контекст, текущий payload и окно подтверждения.

    Проверка чистая: одноразовое использование, RBAC и price floor обязан
    обеспечить исполнитель в транзакции. True само по себе не отправляет действие.
    """
    if (
        now.tzinfo is None
        or approval.approved_at.tzinfo is None
        or approval.expires_at.tzinfo is None
    ):
        raise ValueError("время подтверждения должно содержать часовой пояс")
    return (
        request.action_id == approval.action_id
        and request.company_id == approval.company_id
        and request.tender_id == approval.tender_id
        and request.action_type == approval.action_type
        and payload_digest(request.payload) == request.payload_sha256
        and request.payload_sha256 == approval.payload_sha256
        and request.created_at <= approval.approved_at
        and approval.approved_at <= now < approval.expires_at
    )


class AuditEvent(BaseModel):
    """Append-only факт: кто, что, когда и на каком основании сделал."""

    model_config = ConfigDict(frozen=True)

    event_id: str = Field(min_length=1)
    company_id: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    action: str = Field(min_length=1)
    basis: tuple[str, ...] = Field(min_length=1)
    occurred_at: datetime
    object_id: str = Field(min_length=1)
