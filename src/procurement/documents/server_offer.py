"""Immutable operator proposal for one exact server BOM and supplier quote.

The proposal binds source evidence; it is deliberately pending independent
technical review and can never claim product compliance by itself.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.documents.completeness_review import canonical_json_sha256
from procurement.domain.compliance import Verdict
from procurement.domain.economics import _finite_decimal
from procurement.domain.provenance import Extractor, Provenance


class ServerOfferPartKind(StrEnum):
    CHASSIS = "CHASSIS"
    CPU = "CPU"
    MEMORY = "MEMORY"
    STORAGE = "STORAGE"
    RAID_CONTROLLER = "RAID_CONTROLLER"
    NETWORK = "NETWORK"
    PSU = "PSU"
    COOLING = "COOLING"
    RAILS = "RAILS"
    CABLE = "CABLE"
    LICENSE = "LICENSE"
    SERVICE = "SERVICE"
    OTHER = "OTHER"


class ServerOfferBomLineInput(BaseModel):
    """Operator transcription of one explicitly located quote/BOM line."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ordinal: int = Field(ge=1, le=500)
    kind: ServerOfferPartKind
    manufacturer: str | None = Field(default=None, min_length=1, max_length=200)
    sku: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=2_000)
    quantity: Decimal = Field(gt=0)
    unit: str = Field(min_length=1, max_length=50)
    unit_price_ex_vat: Decimal | None = Field(default=None, gt=0)
    line_total_ex_vat: Decimal | None = Field(default=None, gt=0)
    source_locator: str = Field(min_length=1, max_length=1_000)

    @field_validator("quantity", "unit_price_ex_vat", "line_total_ex_vat", mode="before")
    @classmethod
    def _exact_decimal(cls, value: object) -> Decimal | None:
        return None if value is None else _finite_decimal(value)  # type: ignore[arg-type]

    @field_validator("manufacturer", "sku", "description", "unit", "source_locator")
    @classmethod
    def _trim_text(cls, value: str | None) -> str | None:
        return None if value is None else value.strip()

    @model_validator(mode="after")
    def _price_shape(self) -> Self:
        if self.unit_price_ex_vat is not None and self.line_total_ex_vat is None:
            raise ValueError("unit price requires an explicit line total")
        if (
            self.unit_price_ex_vat is not None
            and self.line_total_ex_vat != self.unit_price_ex_vat * self.quantity
        ):
            raise ValueError("line total must equal unit price multiplied by quantity")
        return self


class ServerOfferCommercialTermsInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    quote_number: str = Field(min_length=1, max_length=300)
    supplier_id: str = Field(min_length=1, max_length=300)
    supplier_name: str = Field(min_length=1, max_length=500)
    amount_ex_vat: Decimal = Field(gt=0)
    nds_rate: Decimal | None = Field(default=None, ge=0, le=1)
    currency: Literal["RUB"] = "RUB"
    issued_at: datetime
    valid_until: datetime
    covers_full_scope: bool | None
    availability_terms: str | None = Field(default=None, min_length=1, max_length=2_000)
    delivery_terms: str | None = Field(default=None, min_length=1, max_length=2_000)
    payment_terms: str | None = Field(default=None, min_length=1, max_length=2_000)
    source_locator: str = Field(min_length=1, max_length=1_000)

    @field_validator("amount_ex_vat", "nds_rate", mode="before")
    @classmethod
    def _exact_money(cls, value: object) -> Decimal | None:
        return None if value is None else _finite_decimal(value)  # type: ignore[arg-type]

    @field_validator(
        "quote_number",
        "supplier_id",
        "supplier_name",
        "availability_terms",
        "delivery_terms",
        "payment_terms",
        "source_locator",
    )
    @classmethod
    def _trim_text(cls, value: str | None) -> str | None:
        return None if value is None else value.strip()

    @model_validator(mode="after")
    def _validity_window(self) -> Self:
        for moment in (self.issued_at, self.valid_until):
            if moment.tzinfo is None or moment.utcoffset() is None:
                raise ValueError("quote dates must include timezone")
        if self.valid_until <= self.issued_at:
            raise ValueError("quote valid_until must be after issued_at")
        return self


class ServerOfferBomLine(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ordinal: int = Field(ge=1, le=500)
    kind: ServerOfferPartKind
    manufacturer: str | None = Field(default=None, min_length=1, max_length=200)
    sku: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=2_000)
    quantity: Decimal = Field(gt=0)
    unit: str = Field(min_length=1, max_length=50)
    unit_price_ex_vat: Decimal | None = Field(default=None, gt=0)
    line_total_ex_vat: Decimal | None = Field(default=None, gt=0)
    provenance: Provenance

    @field_validator("quantity", "unit_price_ex_vat", "line_total_ex_vat", mode="before")
    @classmethod
    def _exact_decimal(cls, value: object) -> Decimal | None:
        return None if value is None else _finite_decimal(value)  # type: ignore[arg-type]

    @model_validator(mode="after")
    def _price_shape(self) -> Self:
        if self.unit_price_ex_vat is not None and self.line_total_ex_vat is None:
            raise ValueError("unit price requires an explicit line total")
        if (
            self.unit_price_ex_vat is not None
            and self.line_total_ex_vat != self.unit_price_ex_vat * self.quantity
        ):
            raise ValueError("line total must equal unit price multiplied by quantity")
        return self


class ServerOfferCommercialTerms(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    quote_number: str = Field(min_length=1, max_length=300)
    supplier_id: str = Field(min_length=1, max_length=300)
    supplier_name: str = Field(min_length=1, max_length=500)
    amount_ex_vat: Decimal = Field(gt=0)
    nds_rate: Decimal | None = Field(default=None, ge=0, le=1)
    currency: Literal["RUB"] = "RUB"
    issued_at: datetime
    valid_until: datetime
    covers_full_scope: bool | None
    availability_terms: str | None = Field(default=None, min_length=1, max_length=2_000)
    delivery_terms: str | None = Field(default=None, min_length=1, max_length=2_000)
    payment_terms: str | None = Field(default=None, min_length=1, max_length=2_000)
    provenance: Provenance

    @field_validator("amount_ex_vat", "nds_rate", mode="before")
    @classmethod
    def _exact_money(cls, value: object) -> Decimal | None:
        return None if value is None else _finite_decimal(value)  # type: ignore[arg-type]

    @model_validator(mode="after")
    def _validity_window(self) -> Self:
        for moment in (self.issued_at, self.valid_until):
            if moment.tzinfo is None or moment.utcoffset() is None:
                raise ValueError("quote dates must include timezone")
        if self.valid_until <= self.issued_at:
            raise ValueError("quote valid_until must be after issued_at")
        return self

    @property
    def is_complete(self) -> bool:
        return (
            self.nds_rate is not None
            and self.covers_full_scope is True
            and self.availability_terms is not None
            and self.delivery_terms is not None
            and self.payment_terms is not None
        )


class ServerOfferProposal(BaseModel):
    """Exact evidence binding that still requires independent technical review."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["server-offer-proposal-v1"] = "server-offer-proposal-v1"
    company_id: str = Field(min_length=1, max_length=200)
    offer_id: str = Field(min_length=1, max_length=200)
    case_id: str = Field(min_length=1, max_length=200)
    case_version: int = Field(ge=1)
    requirement_set_binding_id: str = Field(min_length=1, max_length=200)
    requirement_set_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sourcing_run_id: str = Field(min_length=1, max_length=200)
    lead_id: str = Field(min_length=1, max_length=500)
    lead_product_name: str = Field(min_length=1, max_length=2_000)
    lead_product_url: str = Field(pattern=r"^https://[^\s]+$")
    lead_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_document_id: str = Field(min_length=1, max_length=200)
    source_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bom_lines: tuple[ServerOfferBomLine, ...] = Field(min_length=1, max_length=500)
    commercial_terms: ServerOfferCommercialTerms
    technical_status: Literal[Verdict.UNKNOWN] = Verdict.UNKNOWN
    review_status: Literal["PENDING_REVIEW"] = "PENDING_REVIEW"
    prepared_by: str = Field(min_length=1, max_length=200)
    prepared_at: datetime
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("prepared_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("proposal time must include timezone")
        return value

    @model_validator(mode="after")
    def _exact_shape(self) -> Self:
        if tuple(line.ordinal for line in self.bom_lines) != tuple(
            range(1, len(self.bom_lines) + 1)
        ):
            raise ValueError("BOM line ordinals must be contiguous and ordered")
        evidence = (
            self.commercial_terms.provenance,
            *(line.provenance for line in self.bom_lines),
        )
        if any(item.document_id != self.source_document_id for item in evidence):
            raise ValueError("every BOM and quote fact must reference the exact source document")
        priced = tuple(line.line_total_ex_vat for line in self.bom_lines)
        if all(value is not None for value in priced) and sum(
            (value for value in priced if value is not None), Decimal(0)
        ) != self.commercial_terms.amount_ex_vat:
            raise ValueError("sum of all priced BOM lines must equal quote amount")
        payload = self.model_dump(mode="json", exclude={"proposal_sha256"})
        if canonical_json_sha256(payload) != self.proposal_sha256:
            raise ValueError("server-offer proposal digest does not match payload")
        return self


def build_server_offer_proposal(
    *,
    company_id: str,
    offer_id: str,
    case_id: str,
    case_version: int,
    requirement_set_binding_id: str,
    requirement_set_binding_sha256: str,
    sourcing_run_id: str,
    lead_id: str,
    lead_product_name: str,
    lead_product_url: str,
    lead_source_sha256: str,
    source_document_id: str,
    source_document_sha256: str,
    bom_lines: tuple[ServerOfferBomLineInput, ...],
    commercial_terms: ServerOfferCommercialTermsInput,
    prepared_by: str,
    prepared_at: datetime,
) -> ServerOfferProposal:
    """Bind operator-entered facts to server-owned case, binding and lead identity."""
    lines = tuple(
        ServerOfferBomLine(
            **line.model_dump(mode="python", exclude={"source_locator"}),
            provenance=Provenance(
                document_id=source_document_id,
                locator=line.source_locator,
                extractor=Extractor.MANUAL,
                confidence=1.0,
            ),
        )
        for line in bom_lines
    )
    terms = ServerOfferCommercialTerms(
        **commercial_terms.model_dump(mode="python", exclude={"source_locator"}),
        provenance=Provenance(
            document_id=source_document_id,
            locator=commercial_terms.source_locator,
            extractor=Extractor.MANUAL,
            confidence=1.0,
        ),
    )
    draft = ServerOfferProposal.model_construct(
        schema_version="server-offer-proposal-v1",
        company_id=company_id,
        offer_id=offer_id,
        case_id=case_id,
        case_version=case_version,
        requirement_set_binding_id=requirement_set_binding_id,
        requirement_set_binding_sha256=requirement_set_binding_sha256,
        sourcing_run_id=sourcing_run_id,
        lead_id=lead_id,
        lead_product_name=lead_product_name,
        lead_product_url=lead_product_url,
        lead_source_sha256=lead_source_sha256,
        source_document_id=source_document_id,
        source_document_sha256=source_document_sha256,
        bom_lines=lines,
        commercial_terms=terms,
        technical_status=Verdict.UNKNOWN,
        review_status="PENDING_REVIEW",
        prepared_by=prepared_by,
        prepared_at=prepared_at,
        proposal_sha256="0" * 64,
    )
    digest = canonical_json_sha256(draft.model_dump(mode="json", exclude={"proposal_sha256"}))
    return ServerOfferProposal.model_validate(
        draft.model_dump(mode="python") | {"proposal_sha256": digest}
    )
