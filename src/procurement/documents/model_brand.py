"""Доказательный tenant-scoped справочник точных связей model→brand."""

from __future__ import annotations

import json
import unicodedata
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_MODEL_BRAND_CATALOG_BYTES = 2 * 1024 * 1024


class ModelBrandResolutionReason(StrEnum):
    RESOLVED = "RESOLVED"
    NOT_FOUND = "NOT_FOUND"
    TENANT_MISMATCH = "TENANT_MISMATCH"
    NO_ACTIVE_EVIDENCE = "NO_ACTIVE_EVIDENCE"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"


class ModelBrandReviewStatus(StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ModelBrandSourceEvidence(BaseModel):
    """Официальный источник одной точной связи модели и бренда."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_kind: Literal["OFFICIAL_MANUFACTURER"] = "OFFICIAL_MANUFACTURER"
    source_artifact_id: str | None = Field(default=None, min_length=1, max_length=200)
    source_title: str = Field(min_length=1, max_length=500)
    source_url: AnyHttpUrl
    source_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: str = Field(min_length=1, max_length=1_000)
    retrieved_at: datetime

    @field_validator("source_url")
    @classmethod
    def _source_is_https(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.scheme != "https":
            raise ValueError("model-brand evidence source must use HTTPS")
        return value

    @model_validator(mode="after")
    def _evidence_is_explicit(self) -> Self:
        if (
            (self.source_artifact_id is not None and not self.source_artifact_id.strip())
            or not self.source_title.strip()
            or not self.locator.strip()
        ):
            raise ValueError("model-brand evidence text must not be blank")
        if self.retrieved_at.utcoffset() is None:
            raise ValueError("model-brand evidence retrieval time must include a timezone")
        return self


class ModelBrandCatalogEntry(BaseModel):
    """Одна effective-dated связь без неявных алиасов и fuzzy matching."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entry_id: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=256)
    brand: str = Field(min_length=1, max_length=200)
    valid_from: datetime
    valid_to: datetime | None = None
    evidence: ModelBrandSourceEvidence

    @model_validator(mode="after")
    def _entry_is_explicit(self) -> Self:
        if not self.entry_id.strip() or not self.model.strip() or not self.brand.strip():
            raise ValueError("model-brand entry values must not be blank")
        if self.valid_from.utcoffset() is None:
            raise ValueError("model-brand valid_from must include a timezone")
        if self.valid_to is not None:
            if self.valid_to.utcoffset() is None:
                raise ValueError("model-brand valid_to must include a timezone")
            if self.valid_to <= self.valid_from:
                raise ValueError("model-brand valid_to must be after valid_from")
        return self

    def is_active_at(self, at: datetime) -> bool:
        """Проверить полуоткрытый effective interval ``[valid_from, valid_to)``."""
        if at.utcoffset() is None:
            raise ValueError("model-brand resolution time must include a timezone")
        return self.valid_from <= at and (self.valid_to is None or at < self.valid_to)


class ModelBrandCatalog(BaseModel):
    """Неизменяемый tenant-scoped снимок доказательного справочника."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["model-brand-catalog-v1"] = "model-brand-catalog-v1"
    catalog_id: str = Field(min_length=1, max_length=200)
    company_id: str = Field(min_length=1, max_length=200)
    created_at: datetime
    approved_by: str = Field(min_length=1, max_length=200)
    approval_reference: str = Field(min_length=1, max_length=500)
    entries: tuple[ModelBrandCatalogEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _catalog_is_explicit(self) -> Self:
        if (
            not self.catalog_id.strip()
            or not self.company_id.strip()
            or not self.approved_by.strip()
            or not self.approval_reference.strip()
        ):
            raise ValueError("model-brand catalog identity must not be blank")
        if self.created_at.utcoffset() is None:
            raise ValueError("model-brand catalog creation time must include a timezone")
        entry_ids = [entry.entry_id for entry in self.entries]
        if len(set(entry_ids)) != len(entry_ids):
            raise ValueError("model-brand catalog entry IDs must be unique")
        if any(entry.evidence.retrieved_at > self.created_at for entry in self.entries):
            raise ValueError("model-brand evidence cannot be retrieved in the future")
        return self


class ModelBrandReviewProposal(BaseModel):
    """Immutable tenant-scoped catalog draft awaiting an independent decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["model-brand-review-proposal-v1"] = (
        "model-brand-review-proposal-v1"
    )
    proposal_id: str = Field(min_length=1, max_length=200)
    company_id: str = Field(min_length=1, max_length=200)
    submitted_by: str = Field(min_length=1, max_length=200)
    submitted_at: datetime
    catalog_id: str = Field(min_length=1, max_length=200)
    approval_reference: str = Field(min_length=1, max_length=500)
    entries: tuple[ModelBrandCatalogEntry, ...] = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def _proposal_is_explicit(self) -> Self:
        if any(
            not value.strip()
            for value in (
                self.proposal_id,
                self.company_id,
                self.submitted_by,
                self.catalog_id,
                self.approval_reference,
            )
        ):
            raise ValueError("model-brand review proposal fields must not be blank")
        if self.submitted_at.utcoffset() is None:
            raise ValueError("proposal submission time must include a timezone")
        if any(entry.evidence.source_artifact_id is None for entry in self.entries):
            raise ValueError("persisted proposal evidence requires source_artifact_id")
        if any(entry.evidence.retrieved_at > self.submitted_at for entry in self.entries):
            raise ValueError("proposal evidence cannot be retrieved in the future")
        return self


class ModelBrandResolution(BaseModel):
    """Результат exact lookup; UNKNOWN никогда не содержит выбранный бренд."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: str
    model: str
    status: Literal["PASS", "UNKNOWN"]
    reason: ModelBrandResolutionReason
    brand: str | None = None
    entries: tuple[ModelBrandCatalogEntry, ...] = ()

    @model_validator(mode="after")
    def _resolution_is_honest(self) -> Self:
        if self.status == "PASS":
            if self.reason is not ModelBrandResolutionReason.RESOLVED:
                raise ValueError("resolved model-brand result requires RESOLVED reason")
            if self.brand is None or not self.brand.strip() or not self.entries:
                raise ValueError("resolved model-brand result requires brand and evidence")
        elif self.brand is not None:
            raise ValueError("UNKNOWN model-brand result cannot select a brand")
        return self


def load_model_brand_catalog(path: Path) -> ModelBrandCatalog:
    """Загрузить bounded strict JSON без повторяющихся ключей и NaN/Infinity."""
    if path.stat().st_size > MAX_MODEL_BRAND_CATALOG_BYTES:
        raise ValueError("model-brand catalog is too large")
    raw = path.read_bytes()
    if len(raw) > MAX_MODEL_BRAND_CATALOG_BYTES:
        raise ValueError("model-brand catalog is too large")
    payload = json.loads(
        raw.decode("utf-8-sig"),
        parse_constant=_reject_constant,
        object_pairs_hook=_unique_object,
    )
    return ModelBrandCatalog.model_validate(payload)


def resolve_model_brand(
    catalog: ModelBrandCatalog,
    *,
    company_id: str,
    model: str,
    at: datetime,
) -> ModelBrandResolution:
    """Разрешить только точную модель по активному непротиворечивому evidence."""
    if not company_id.strip() or not model.strip():
        raise ValueError("model-brand lookup values must not be blank")
    if at.utcoffset() is None:
        raise ValueError("model-brand resolution time must include a timezone")
    if catalog.company_id != company_id:
        return ModelBrandResolution(
            company_id=company_id,
            model=model,
            status="UNKNOWN",
            reason=ModelBrandResolutionReason.TENANT_MISMATCH,
        )
    matching = tuple(
        entry for entry in catalog.entries if normalize_model(entry.model) == normalize_model(model)
    )
    if not matching:
        return ModelBrandResolution(
            company_id=company_id,
            model=model,
            status="UNKNOWN",
            reason=ModelBrandResolutionReason.NOT_FOUND,
        )
    active = tuple(entry for entry in matching if entry.is_active_at(at))
    if not active:
        return ModelBrandResolution(
            company_id=company_id,
            model=model,
            status="UNKNOWN",
            reason=ModelBrandResolutionReason.NO_ACTIVE_EVIDENCE,
            entries=matching,
        )
    brands = {_normalize_text(entry.brand) for entry in active}
    if len(brands) != 1:
        return ModelBrandResolution(
            company_id=company_id,
            model=model,
            status="UNKNOWN",
            reason=ModelBrandResolutionReason.CONFLICTING_EVIDENCE,
            entries=active,
        )
    return ModelBrandResolution(
        company_id=company_id,
        model=model,
        status="PASS",
        reason=ModelBrandResolutionReason.RESOLVED,
        brand=active[0].brand,
        entries=active,
    )


def normalize_model(value: str) -> str:
    """Нормализовать регистр/Unicode/пробелы, сохранив значимую пунктуацию модели."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON contains a duplicate key")
        result[key] = value
    return result
