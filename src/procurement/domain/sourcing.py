"""Предварительный shortlist серверных карточек, не решение о допуске.

Карточка/цена поставщика не доказывает состав поставляемой сборки. Здесь
отсекаются только подтверждённые обязательные FAIL; остальное ждёт review.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.domain.compliance import Verdict
from procurement.domain.economics import _finite_decimal
from procurement.domain.requirements import Requirement
from procurement.domain.server_bom import BomAssessment, ServerBom, assess_server_bom


class LeadStatus(str, Enum):
    REJECTED = "REJECTED"
    NEEDS_TECHNICAL_REVIEW = "NEEDS_TECHNICAL_REVIEW"


class LeadSourceKind(str, Enum):
    MANUFACTURER_CATALOG = "MANUFACTURER_CATALOG"
    SUPPLIER_CATALOG = "SUPPLIER_CATALOG"


class SourcingRunStatus(str, Enum):
    COMPLETED = "COMPLETED"
    SOURCE_ERROR = "SOURCE_ERROR"


class SourcingSourceStatus(str, Enum):
    COMPLETED = "COMPLETED"
    SOURCE_ERROR = "SOURCE_ERROR"


class SourcingSourceSnapshot(BaseModel):
    """Metadata for one exact source artifact within a sourcing run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ordinal: int = Field(ge=1, le=10)
    source_name: str = Field(min_length=1, max_length=200)
    source_kind: LeadSourceKind
    source_url: str = Field(pattern=r"^https://[^\s]+$")
    media_type: str = Field(pattern=r"^(text/html|application/pdf)$")
    status: SourcingSourceStatus
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_byte_size: int | None = Field(default=None, gt=0, le=20 * 1024 * 1024)
    observed_at: datetime
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{1,63}$")

    @model_validator(mode="after")
    def _consistent_source(self) -> SourcingSourceSnapshot:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("source observed_at must be timezone-aware")
        if self.status is SourcingSourceStatus.COMPLETED:
            if (
                self.source_sha256 is None
                or self.source_byte_size is None
                or self.error_code is not None
            ):
                raise ValueError("completed source requires digest and size without error")
        elif (
            self.source_sha256 is not None
            or self.source_byte_size is not None
            or self.error_code is None
        ):
            raise ValueError("source error cannot claim an exact snapshot")
        return self


class ServerLead(BaseModel):
    """Наблюдение публичной карточки; не КП и не подтверждение наличия."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lead_id: str = Field(min_length=1)
    supplier: str = Field(min_length=1)
    manufacturer: str | None = Field(default=None, min_length=1, max_length=200)
    source_kind: LeadSourceKind = LeadSourceKind.SUPPLIER_CATALOG
    product_name: str = Field(min_length=1)
    source_url: str = Field(pattern=r"^https://[^\s]+$")
    product_url: str | None = Field(default=None, pattern=r"^https://[^\s]+$")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_at: datetime
    price_rub: Decimal | None = Field(default=None, gt=0)
    price_includes_vat: bool | None = None
    bom: ServerBom | None = None

    @field_validator("price_rub", mode="before")
    @classmethod
    def _exact_price(cls, value: object) -> Decimal | None:
        return None if value is None else _finite_decimal(value)  # type: ignore[arg-type]

    @model_validator(mode="after")
    def _valid_observation(self) -> ServerLead:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("время наблюдения должно содержать часовой пояс")
        if self.price_rub is None and self.price_includes_vat is not None:
            raise ValueError("НДС нельзя заявить без цены")
        if self.source_kind is LeadSourceKind.MANUFACTURER_CATALOG:
            if self.manufacturer is None:
                raise ValueError("официальная карточка требует manufacturer")
            if self.price_rub is not None or self.bom is not None:
                raise ValueError("страница семейства производителя не является ценой или exact BOM")
        return self


class ShortlistEntry(BaseModel):
    """Техническая очередь: статус PASS намеренно отсутствует."""

    model_config = ConfigDict(frozen=True)

    lead: ServerLead
    status: LeadStatus
    assessment: BomAssessment | None
    open_properties: tuple[str, ...]


class ServerShortlist(BaseModel):
    model_config = ConfigDict(frozen=True)

    review_queue: tuple[ShortlistEntry, ...]
    rejected: tuple[ShortlistEntry, ...]


class SourcingRunRecord(BaseModel):
    """Immutable result of one case-bound, read-only catalog observation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    case_version: int = Field(ge=1)
    query: str = Field(min_length=1, max_length=80)
    source_name: str = Field(min_length=1)
    source_url: str = Field(pattern=r"^https://[^\s]+$")
    status: SourcingRunStatus
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_byte_size: int | None = Field(default=None, gt=0)
    observed_at: datetime
    sources: tuple[SourcingSourceSnapshot, ...] = Field(default=(), max_length=10)
    shortlist: ServerShortlist
    requirement_set_binding_id: str | None = Field(default=None, min_length=1, max_length=200)
    requirement_set_id: str | None = Field(default=None, min_length=1, max_length=200)
    requirement_set_proposal_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    requirement_set_decision_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    requirement_set_binding_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    technical_scope_status: Verdict = Verdict.UNKNOWN
    technical_scope_reason: str = Field(min_length=1)
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    created_at: datetime

    @field_validator("query")
    @classmethod
    def _bounded_query(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not 1 <= len(normalized.split()) <= 5:
            raise ValueError("поисковая строка должна содержать 1–5 слов")
        return normalized

    @model_validator(mode="after")
    def _consistent_result(self) -> SourcingRunRecord:
        for value, field in ((self.observed_at, "observed_at"), (self.created_at, "created_at")):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field} должен содержать часовой пояс")
        if self.technical_scope_status is not Verdict.UNKNOWN:
            raise ValueError("поиск карточек не подтверждает техническое соответствие")
        requirement_set_refs = (
            self.requirement_set_id,
            self.requirement_set_proposal_sha256,
            self.requirement_set_decision_sha256,
            self.requirement_set_binding_sha256,
        )
        if any(value is None for value in requirement_set_refs) != all(
            value is None for value in requirement_set_refs
        ):
            raise ValueError("ссылка на reviewed requirement set должна быть полной")
        if (
            self.requirement_set_binding_id is not None
            and self.requirement_set_binding_sha256 is None
        ):
            raise ValueError("binding ID требует exact binding digest")
        if self.sources:
            if tuple(item.ordinal for item in self.sources) != tuple(
                range(1, len(self.sources) + 1)
            ):
                raise ValueError("source ordinals must be contiguous and ordered")
            successful = tuple(
                item for item in self.sources if item.status is SourcingSourceStatus.COMPLETED
            )
            if (self.status is SourcingRunStatus.COMPLETED) != bool(successful):
                raise ValueError("run status must reflect whether any source completed")
            source_digests = {
                item.source_sha256 for item in successful if item.source_sha256 is not None
            }
            if any(
                entry.lead.source_sha256 not in source_digests
                for entry in (*self.shortlist.review_queue, *self.shortlist.rejected)
            ):
                raise ValueError("every lead must reference a completed source snapshot")
        if self.status is SourcingRunStatus.COMPLETED:
            if (
                self.source_sha256 is None
                or self.source_byte_size is None
                or self.error_code is not None
            ):
                raise ValueError("успешный поиск требует exact snapshot без ошибки источника")
        elif (
            self.source_sha256 is not None
            or self.source_byte_size is not None
            or self.error_code is None
            or self.shortlist.review_queue
            or self.shortlist.rejected
        ):
            raise ValueError(
                "ошибка источника не может содержать неподтверждённый snapshot или карточки"
            )
        return self


def shortlist_server_leads(
    leads: tuple[ServerLead, ...], requirements: tuple[Requirement, ...]
) -> ServerShortlist:
    """Убрать лишь доказанный hard FAIL, не повышая UNKNOWN до PASS.

    Цена сохранена как неподтверждённое наблюдение, но не влияет на порядок:
    сначала нужна техническая проверка, полное ТЗ и действительное КП.
    """
    ids = [lead.lead_id for lead in leads]
    if len(ids) != len(set(ids)):
        raise ValueError("lead_id должен быть уникальным в shortlist")
    queue: list[ShortlistEntry] = []
    rejected: list[ShortlistEntry] = []
    for lead in leads:
        assessment = assess_server_bom(lead.bom, requirements) if lead.bom else None
        failed = assessment is not None and assessment.verdict is Verdict.FAIL
        if assessment is None:
            open_properties = tuple(dict.fromkeys(req.property for req in requirements))
        else:
            open_properties = tuple(
                dict.fromkeys(
                    (
                        *(
                            check.requirement.property
                            for check in assessment.checks
                            if check.verdict is Verdict.UNKNOWN
                        ),
                        *assessment.missing_gate_properties,
                        *(req.property for req in assessment.out_of_scope_requirements),
                    )
                )
            )
        entry = ShortlistEntry(
            lead=lead,
            status=(LeadStatus.REJECTED if failed else LeadStatus.NEEDS_TECHNICAL_REVIEW),
            assessment=assessment,
            open_properties=open_properties,
        )
        (rejected if failed else queue).append(entry)
    return ServerShortlist(review_queue=tuple(queue), rejected=tuple(rejected))
