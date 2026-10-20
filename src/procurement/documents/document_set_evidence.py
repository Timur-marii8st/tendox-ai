"""Immutable multi-document evidence manifest that deliberately remains UNKNOWN.

This domain boundary only records an ordered set of already validated native
completeness snapshots. It neither merges requirements nor creates a terminal
completeness decision; a separate multi-document review contract is required.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.documents.completeness_review import (
    CompletenessReviewSnapshot,
    canonical_json_sha256,
)
from procurement.documents.extraction import ExtractionStatus
from procurement.documents.facts import CompletenessStatus, DocumentRole
from procurement.domain.provenance import Extractor

DOCUMENT_SET_EVIDENCE_SCHEMA_VERSION: Literal["document-set-evidence-manifest-v1"] = (
    "document-set-evidence-manifest-v1"
)
MULTI_DOCUMENT_REVIEW_REQUIRED: Literal["MULTI_DOCUMENT_REVIEW_REQUIRED"] = (
    "MULTI_DOCUMENT_REVIEW_REQUIRED"
)


class DocumentSetEvidenceMember(BaseModel):
    """One source-bound projection of a completeness review snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    ordinal: int = Field(ge=1)
    source_document_id: str = Field(min_length=1, max_length=200)
    source_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    completeness_review_id: str = Field(min_length=1, max_length=200)
    completeness_review_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mapper_version: str = Field(min_length=1, max_length=200)
    mapper_min_confidence: float = Field(ge=0.0, le=1.0)


class DocumentSetEvidenceManifest(BaseModel):
    """Ordered evidence for later human multi-document review, never a verdict."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["document-set-evidence-manifest-v1"] = (
        DOCUMENT_SET_EVIDENCE_SCHEMA_VERSION
    )
    company_id: str = Field(min_length=1, max_length=200)
    manifest_id: str = Field(min_length=1, max_length=200)
    scope: str = Field(min_length=1, max_length=4_000)
    members: tuple[DocumentSetEvidenceMember, ...] = Field(min_length=2, max_length=10)
    completeness_status: Literal[CompletenessStatus.UNKNOWN] = CompletenessStatus.UNKNOWN
    reason: Literal["MULTI_DOCUMENT_REVIEW_REQUIRED"] = MULTI_DOCUMENT_REVIEW_REQUIRED
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_by: str = Field(min_length=1, max_length=200)
    created_at: datetime

    @field_validator("company_id", "manifest_id", "scope", "created_by")
    @classmethod
    def _nonblank_text_is_trimmed(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("document set evidence text must not be blank")
        return normalized

    @field_validator("created_at")
    @classmethod
    def _created_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("document set evidence time must include a timezone")
        return value

    @model_validator(mode="after")
    def _manifest_is_structurally_bound(self) -> Self:
        expected_ordinals = tuple(range(1, len(self.members) + 1))
        if tuple(member.ordinal for member in self.members) != expected_ordinals:
            raise ValueError("document set evidence member ordinals must be contiguous")
        source_ids = [member.source_document_id for member in self.members]
        review_ids = [member.completeness_review_id for member in self.members]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("document set evidence source document IDs must be unique")
        if len(set(review_ids)) != len(review_ids):
            raise ValueError("document set evidence review IDs must be unique")
        evidence = self.model_dump(mode="json", exclude={"evidence_sha256"})
        if canonical_json_sha256(evidence) != self.evidence_sha256:
            raise ValueError("document set evidence digest does not match manifest")
        return self


def project_document_set_evidence_member(
    snapshot: CompletenessReviewSnapshot,
    *,
    ordinal: int,
) -> DocumentSetEvidenceMember:
    """Derive one member only from an exact validated review snapshot."""
    validated = CompletenessReviewSnapshot.model_validate(snapshot.model_dump(mode="python"))
    return DocumentSetEvidenceMember(
        ordinal=ordinal,
        source_document_id=validated.source_document_id,
        source_document_sha256=validated.source_document_sha256,
        completeness_review_id=validated.review_id,
        completeness_review_evidence_sha256=validated.evidence_sha256,
        mapper_version=validated.mapper_version,
        mapper_min_confidence=validated.mapper_min_confidence,
    )


def build_document_set_evidence_manifest(
    snapshots: tuple[CompletenessReviewSnapshot, ...],
    *,
    company_id: str,
    manifest_id: str,
    scope: str,
    created_by: str,
    created_at: datetime,
) -> DocumentSetEvidenceManifest:
    """Project 2..10 server-derived snapshots without merging their facts.

    Caller order is evidence and is retained exactly. Every manifest remains
    ``UNKNOWN`` even if a source could later receive a terminal review decision.
    """
    if type(snapshots) is not tuple:
        raise TypeError("document set evidence snapshots must be an explicit tuple")
    if not 2 <= len(snapshots) <= 10:
        raise ValueError("document set evidence requires 2..10 snapshots")
    if not all(isinstance(snapshot, CompletenessReviewSnapshot) for snapshot in snapshots):
        raise TypeError("document set evidence snapshots must be completeness review snapshots")
    validated_snapshots = tuple(
        CompletenessReviewSnapshot.model_validate(snapshot.model_dump(mode="python"))
        for snapshot in snapshots
    )
    if any(
        snapshot.mapping.document_role is not DocumentRole.TENDER_REQUIREMENTS
        or snapshot.extraction.status is not ExtractionStatus.PASS
        or snapshot.extraction.reasons
        or snapshot.extraction.source_units_extracted != snapshot.extraction.source_units_total
        or any(
            block.provenance.extractor
            not in {Extractor.NATIVE_PDF, Extractor.NATIVE_DOCX, Extractor.NATIVE_XLSX}
            for block in snapshot.extraction.blocks
        )
        for snapshot in validated_snapshots
    ):
        raise ValueError("document set evidence requires complete native TENDER snapshots")
    normalized_company_id = company_id.strip()
    if not normalized_company_id:
        raise ValueError("company_id must not be blank")
    if any(snapshot.company_id != normalized_company_id for snapshot in validated_snapshots):
        raise ValueError("document set evidence snapshots must belong to one company")
    members = tuple(
        project_document_set_evidence_member(snapshot, ordinal=ordinal)
        for ordinal, snapshot in enumerate(validated_snapshots, start=1)
    )
    evidence = canonical_json_sha256(
        {
            "schema_version": DOCUMENT_SET_EVIDENCE_SCHEMA_VERSION,
            "company_id": normalized_company_id,
            "manifest_id": manifest_id,
            "scope": scope,
            "members": members,
            "completeness_status": CompletenessStatus.UNKNOWN,
            "reason": MULTI_DOCUMENT_REVIEW_REQUIRED,
            "created_by": created_by,
            "created_at": created_at,
        }
    )
    return DocumentSetEvidenceManifest(
        company_id=normalized_company_id,
        manifest_id=manifest_id,
        scope=scope,
        members=members,
        evidence_sha256=evidence,
        created_by=created_by,
        created_at=created_at,
    )
