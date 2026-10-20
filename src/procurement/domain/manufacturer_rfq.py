"""Immutable no-dispatch RFQ draft for one independently verified manufacturer."""

from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal, InvalidOperation
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.domain.manufacturer_review import LegalIdentity


class ManufacturerRfqCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    command_id: str
    run_id: str
    record_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    proposal_id: str
    decision_id: str
    quantity: str = Field(min_length=1, max_length=100)
    unit_raw: str = Field(min_length=1, max_length=100)
    quantity_basis_raw: str = Field(min_length=1, max_length=500)
    requirements: tuple[str, ...] = Field(min_length=1, max_length=20)
    delivery_address_raw: str = Field(min_length=1, max_length=1000)
    desired_delivery_raw: str = Field(min_length=1, max_length=500)
    reply_due_at: AwareDatetime

    @field_validator("command_id", "run_id", "proposal_id", "decision_id")
    @classmethod
    def canonical_uuid(cls, value: str) -> str:
        if str(uuid.UUID(value)) != value:
            raise ValueError("MANUFACTURER_RFQ_UUID_INVALID")
        return value

    @field_validator(
        "quantity", "unit_raw", "quantity_basis_raw", "delivery_address_raw",
        "desired_delivery_raw",
    )
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("MANUFACTURER_RFQ_TEXT_BLANK")
        return value.strip()

    @field_validator("requirements")
    @classmethod
    def requirements_valid(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in value)
        if any(not item or len(item) > 500 for item in cleaned):
            raise ValueError("MANUFACTURER_RFQ_REQUIREMENT_INVALID")
        return cleaned

    @model_validator(mode="after")
    def time_and_quantity(self) -> Self:
        canonical_quantity(self.quantity)
        return self


class ManualProvenance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    document_id: str
    locator: str
    extractor: Literal["manual"] = "manual"
    actor_id: str
    recorded_at: AwareDatetime


class ManualTextFact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    value: str = Field(min_length=1, max_length=1000)
    provenance: ManualProvenance


class RfqRegistrySnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    record_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    registry_number: str
    product_name: str
    source_manufacturer_name: str
    record_url: str
    document_expires_on: str | None


class ManufacturerRfqDraft(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["manufacturer-rfq-draft-v1"] = "manufacturer-rfq-draft-v1"
    draft_id: str
    command_id: str
    status: Literal["DRAFT_NO_DISPATCH"] = "DRAFT_NO_DISPATCH"
    run_id: str
    proposal_id: str
    decision_id: str
    manufacturer_identity: LegalIdentity
    registry_snapshot: RfqRegistrySnapshot
    quantity_input: ManualTextFact
    quantity: str
    unit: ManualTextFact
    quantity_basis: ManualTextFact
    requirements: tuple[ManualTextFact, ...] = Field(min_length=1, max_length=20)
    delivery_address: ManualTextFact
    desired_delivery: ManualTextFact
    reply_due_at: AwareDatetime
    reply_due_provenance: ManualProvenance
    source_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dossier_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manual_inputs_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    text: str
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_by: str
    created_at: AwareDatetime
    draft_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    contact: Literal["UNKNOWN"] = "UNKNOWN"
    website: Literal["UNKNOWN"] = "UNKNOWN"
    price: Literal["UNKNOWN"] = "UNKNOWN"
    quote: Literal["UNKNOWN"] = "UNKNOWN"
    technical: Literal["UNKNOWN"] = "UNKNOWN"
    participation: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def exact_hashes(self) -> Self:
        for identity in (
            self.draft_id, self.command_id, self.run_id, self.proposal_id, self.decision_id
        ):
            if str(uuid.UUID(identity)) != identity:
                raise ValueError("MANUFACTURER_RFQ_UUID_INVALID")
        if hashlib.sha256(self.text.encode()).hexdigest() != self.text_sha256:
            raise ValueError("MANUFACTURER_RFQ_TEXT_SHA_CONFLICT")
        if canonical_quantity(self.quantity_input.value) != self.quantity:
            raise ValueError("MANUFACTURER_RFQ_QUANTITY_CONFLICT")
        if (
            len(self.quantity_input.value) > 100
            or len(self.unit.value) > 100
            or len(self.quantity_basis.value) > 500
            or len(self.delivery_address.value) > 1000
            or len(self.desired_delivery.value) > 500
            or any(len(requirement.value) > 500 for requirement in self.requirements)
        ):
            raise ValueError("MANUFACTURER_RFQ_MANUAL_FIELD_BOUNDS")
        if (
            canonical_sha256(self.model_dump(mode="json", exclude={"draft_sha256"}))
            != self.draft_sha256
        ):
            raise ValueError("MANUFACTURER_RFQ_DRAFT_SHA_CONFLICT")
        return self


def canonical_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def canonical_sha256(payload: object) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def canonical_quantity(value: str) -> str:
    quantity = safe_quantity(value)
    rendered = format(quantity, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    if len(rendered) > 100:
        raise ValueError("MANUFACTURER_RFQ_QUANTITY_INVALID")
    return rendered


def safe_quantity(value: str) -> Decimal:
    try:
        quantity = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("MANUFACTURER_RFQ_QUANTITY_INVALID") from error
    digits = len(quantity.as_tuple().digits)
    exponent = quantity.as_tuple().exponent
    if (
        not quantity.is_finite()
        or quantity <= 0
        or not isinstance(exponent, int)
        or digits > 100
        or exponent < -100
        or exponent > 100
    ):
        raise ValueError("MANUFACTURER_RFQ_QUANTITY_INVALID")
    return quantity


def render_rfq_text(
    identity: LegalIdentity,
    snapshot: RfqRegistrySnapshot,
    command: ManufacturerRfqCommand,
) -> str:
    requirements = "\n".join(
        f"{index}. {value}" for index, value in enumerate(command.requirements, start=1)
    )
    return (
        "Черновик запроса коммерческого предложения\n\n"
        f"Юридическое лицо: {identity.legal_name} "
        f"({identity.country_code}, {identity.identifier_scheme}: {identity.registration_id})\n"
        f"Товар из реестра: {snapshot.product_name}\n"
        f"Реестровая запись: {snapshot.registry_number}; {snapshot.record_url}\n"
        f"Количество: {canonical_quantity(command.quantity)} {command.unit_raw}\n"
        f"Основание количества: {command.quantity_basis_raw}\n\n"
        "Требования, введённые оператором (не являются полностью проверенным ТЗ):\n"
        f"{requirements}\n\n"
        f"Адрес поставки: {command.delivery_address_raw}\n"
        f"Желаемый срок поставки: {command.desired_delivery_raw}\n"
        f"Просим ответить до: {command.reply_due_at.isoformat()}\n\n"
        "Просим указать цену за единицу, НДС, MOQ и шаг партии, наличие или срок "
        "производства, упаковку, условия оплаты и доставки, гарантию и полный срок "
        "действия коммерческого предложения.\n\n"
        "Статус: DRAFT_NO_DISPATCH. Получатель и отправка не определены."
    )
