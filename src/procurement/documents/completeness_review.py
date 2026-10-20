"""Immutable, evidence-bound review of document requirement completeness."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import to_jsonable_python

from procurement.documents.extraction import ExtractionResult, ExtractionStatus
from procurement.documents.facts import (
    DEFAULT_FACT_MIN_CONFIDENCE,
    CompletenessAssessment,
    CompletenessStatus,
    DocumentRole,
    FactMappingResult,
    UnmappedBlockReview,
    UnmappedDisposition,
    map_blocks_to_requirements,
)
from procurement.domain.provenance import Extractor

COMPLETENESS_MAPPER_VERSION = "document-facts-v1"


class CompletenessReviewSourceInvalid(ValueError):
    """The persisted source cannot safely support a completeness review."""


class CompletenessBlockDecision(BaseModel):
    """Reviewer disposition of one stable index in ``mapping.unmapped``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    unmapped_index: int = Field(ge=0)
    disposition: UnmappedDisposition
    rationale: str = Field(min_length=1, max_length=2_000)

    @field_validator("rationale")
    @classmethod
    def _rationale_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("block decision rationale must not be blank")
        return value.strip()


class CompletenessReviewSnapshot(BaseModel):
    """Server-derived snapshot of immutable bytes, extraction, and mapping."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["document-completeness-review-v1"] = "document-completeness-review-v1"
    company_id: str = Field(min_length=1, max_length=200)
    review_id: str = Field(min_length=1, max_length=200)
    source_document_id: str = Field(min_length=1, max_length=200)
    source_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extraction: ExtractionResult
    mapping: FactMappingResult
    mapper_version: str = Field(min_length=1, max_length=200)
    mapper_min_confidence: float = Field(ge=0.0, le=1.0)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_by: str = Field(min_length=1, max_length=200)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _created_at_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("completeness review time must include a timezone")
        return value

    @model_validator(mode="after")
    def _snapshot_is_bound(self) -> Self:
        if self.mapping.document_role is not DocumentRole.TENDER_REQUIREMENTS:
            raise ValueError("completeness review requires a TENDER_REQUIREMENTS document")
        if self.mapping.completeness.status is not CompletenessStatus.UNKNOWN:
            raise ValueError("new completeness review mapping must remain UNKNOWN")
        source_ids = {block.provenance.document_id for block in self.extraction.blocks}
        if source_ids != {self.source_document_id}:
            raise ValueError("extraction provenance does not match the source document")
        if self.mapping.blocks_total != len(self.extraction.blocks):
            raise ValueError("mapping does not cover the snapshotted extraction")
        if completeness_evidence_sha256(self) != self.evidence_sha256:
            raise ValueError("completeness review evidence digest does not match snapshot")
        return self


class CompletenessReviewDecision(BaseModel):
    """One immutable reviewer decision reconstructed from the snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["document-completeness-decision-v1"] = (
        "document-completeness-decision-v1"
    )
    company_id: str = Field(min_length=1, max_length=200)
    review_id: str = Field(min_length=1, max_length=200)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: CompletenessStatus
    scope: str = Field(min_length=1, max_length=4_000)
    reason: str = Field(min_length=1, max_length=4_000)
    block_decisions: tuple[CompletenessBlockDecision, ...] = ()
    reviewed_mapping: FactMappingResult
    decided_by: str = Field(min_length=1, max_length=200)
    decided_at: datetime
    review_reference: str = Field(min_length=1, max_length=500)

    @field_validator("scope", "reason")
    @classmethod
    def _text_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("review scope and reason must not be blank")
        return value.strip()

    @field_validator("decided_at")
    @classmethod
    def _decided_at_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("decision time must include a timezone")
        return value

    @model_validator(mode="after")
    def _decision_is_consistent(self) -> Self:
        if self.reviewed_mapping.completeness.status is not self.status:
            raise ValueError("decision status does not match reviewed mapping")
        indexes = [item.unmapped_index for item in self.block_decisions]
        if len(indexes) != len(set(indexes)):
            raise ValueError("unmapped indexes must not repeat")
        if any(index >= len(self.reviewed_mapping.unmapped) for index in indexes):
            raise ValueError("unmapped index is outside the reviewed mapping")
        return self


class CompletenessReviewRecord(BaseModel):
    """Tenant-visible immutable review snapshot and optional terminal decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot: CompletenessReviewSnapshot
    decision: CompletenessReviewDecision | None = None

    @model_validator(mode="after")
    def _decision_is_bound_to_snapshot(self) -> Self:
        if self.decision is None:
            return self
        if (
            self.decision.company_id != self.snapshot.company_id
            or self.decision.review_id != self.snapshot.review_id
            or self.decision.evidence_sha256 != self.snapshot.evidence_sha256
        ):
            raise ValueError("completeness decision identity does not match snapshot")
        base_mapping = self.decision.reviewed_mapping.model_copy(
            update={"completeness": CompletenessAssessment()}
        )
        if base_mapping != self.snapshot.mapping:
            raise ValueError("completeness decision mapping does not match snapshot")
        return self


def canonical_json_sha256(payload: object) -> str:
    """Hash canonical UTF-8 JSON (sorted keys, no insignificant whitespace)."""
    normalized = to_jsonable_python(payload)
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def completeness_evidence_sha256(snapshot: CompletenessReviewSnapshot) -> str:
    """Bind every evidence field except the digest itself."""
    return canonical_json_sha256(snapshot.model_dump(mode="json", exclude={"evidence_sha256"}))


def build_completeness_review_snapshot(
    *,
    company_id: str,
    review_id: str,
    source_document_id: str,
    source_document_sha256: str,
    document_role: DocumentRole,
    extraction: ExtractionResult,
    created_by: str,
    created_at: datetime,
    mapper_version: str = COMPLETENESS_MAPPER_VERSION,
    mapper_min_confidence: float = DEFAULT_FACT_MIN_CONFIDENCE,
) -> CompletenessReviewSnapshot:
    """Build the only accepted snapshot: complete native extraction mapped by server code."""
    if document_role is not DocumentRole.TENDER_REQUIREMENTS:
        raise CompletenessReviewSourceInvalid("document role is not TENDER_REQUIREMENTS")
    if (
        extraction.status is not ExtractionStatus.PASS
        or extraction.reasons
        or extraction.source_units_extracted != extraction.source_units_total
        or not extraction.blocks
        or any(
            block.provenance.extractor
            not in {Extractor.NATIVE_PDF, Extractor.NATIVE_DOCX, Extractor.NATIVE_XLSX}
            for block in extraction.blocks
        )
    ):
        raise CompletenessReviewSourceInvalid("document extraction is not complete native text")
    if {block.provenance.document_id for block in extraction.blocks} != {source_document_id}:
        raise CompletenessReviewSourceInvalid("extraction provenance does not match source")
    mapping = map_blocks_to_requirements(
        extraction.blocks,
        document_role=document_role,
        min_confidence=mapper_min_confidence,
    )
    fields = dict(
        company_id=company_id,
        review_id=review_id,
        source_document_id=source_document_id,
        source_document_sha256=source_document_sha256,
        extraction=extraction,
        mapping=mapping,
        mapper_version=mapper_version,
        mapper_min_confidence=mapper_min_confidence,
        created_by=created_by,
        created_at=created_at,
    )
    digest = canonical_json_sha256({"schema_version": "document-completeness-review-v1", **fields})
    return CompletenessReviewSnapshot(**fields, evidence_sha256=digest)


def build_completeness_review_decision(
    snapshot: CompletenessReviewSnapshot,
    *,
    status: CompletenessStatus,
    scope: str,
    reason: str,
    block_decisions: tuple[CompletenessBlockDecision, ...],
    decided_by: str,
    decided_at: datetime,
    review_reference: str,
) -> CompletenessReviewDecision:
    """Reconstruct reviewed blocks server-side and validate ``FactMappingResult``."""
    indexes = [item.unmapped_index for item in block_decisions]
    if len(indexes) != len(set(indexes)):
        raise ValueError("unmapped indexes must not repeat")
    if any(index >= len(snapshot.mapping.unmapped) for index in indexes):
        raise ValueError("unmapped index is outside the snapshot")
    reviews = tuple(
        UnmappedBlockReview(
            block=snapshot.mapping.unmapped[item.unmapped_index],
            disposition=item.disposition,
            rationale=item.rationale,
        )
        for item in block_decisions
    )
    if status is CompletenessStatus.UNKNOWN:
        reviewed_mapping = snapshot.mapping
    else:
        assessment = CompletenessAssessment(
            status=status,
            scope=scope.strip(),
            source_document_ids=(snapshot.source_document_id,),
            reviewer_id=decided_by,
            reviewed_at=decided_at,
            review_reference=review_reference,
            unmapped_reviews=reviews,
        )
        reviewed_mapping = FactMappingResult.model_validate(
            snapshot.mapping.model_dump(mode="python") | {"completeness": assessment}
        )
    return CompletenessReviewDecision(
        company_id=snapshot.company_id,
        review_id=snapshot.review_id,
        evidence_sha256=snapshot.evidence_sha256,
        status=status,
        scope=scope,
        reason=reason,
        block_decisions=block_decisions,
        reviewed_mapping=reviewed_mapping,
        decided_by=decided_by,
        decided_at=decided_at,
        review_reference=review_reference,
    )
