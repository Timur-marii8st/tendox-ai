"""Immutable human-review contract for imported AI requirement reports.

The report remains review-only evidence.  Importing or accepting candidates does
not create executable ``Requirement`` or ``LineItem`` domain objects and never
changes document completeness from ``UNKNOWN``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.documents.ai_requirements import (
    AiProcurementItemCandidate,
    AiRequirementAnalysisReport,
    AiRequirementAnalysisReportV2,
    AiRequirementCandidate,
    AiRequirementRunStatus,
    AiSourceBlock,
    validate_ai_requirement_report,
)
from procurement.documents.ai_transfer_requirement_result import (
    AiTransferRequirementBatchResult,
    AiTransferRequirementResult,
)
from procurement.documents.completeness_review import canonical_json_sha256
from procurement.documents.extraction import ExtractionResult, ExtractionStatus
from procurement.documents.facts import CompletenessStatus
from procurement.domain.provenance import Extractor

AiRequirementReport = Annotated[
    AiRequirementAnalysisReport | AiRequirementAnalysisReportV2,
    Field(discriminator="schema_version"),
]


class CandidateKind(StrEnum):
    """Review namespace for the two non-executable candidate families."""

    REQUIREMENT = "REQUIREMENT"
    PROCUREMENT_ITEM = "PROCUREMENT_ITEM"


class CandidateDisposition(StrEnum):
    """Independent human disposition without automatic domain promotion."""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"


class AiRequirementCandidateDecision(BaseModel):
    """One decision for one exact report candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_kind: CandidateKind
    candidate_id: str = Field(pattern=r"^(ai-req|ai-item)-[0-9a-f]{16}$")
    disposition: CandidateDisposition
    reason: str = Field(min_length=1, max_length=4_000)

    @field_validator("reason")
    @classmethod
    def _reason_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("candidate review reason must not be blank")
        return value.strip()

    @model_validator(mode="after")
    def _kind_matches_id_namespace(self) -> Self:
        prefix = "ai-req-" if self.candidate_kind is CandidateKind.REQUIREMENT else "ai-item-"
        if not self.candidate_id.startswith(prefix):
            raise ValueError("candidate kind does not match candidate ID namespace")
        return self


class AiRequirementRunSnapshot(BaseModel):
    """Exact imported report bound again to the persisted extraction source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["persisted-ai-requirement-run-v1"] = "persisted-ai-requirement-run-v1"
    origin: Literal["IMPORTED_REPORT"] = "IMPORTED_REPORT"
    company_id: str = Field(min_length=1, max_length=200)
    run_id: str = Field(min_length=1, max_length=200)
    source_document_id: str = Field(min_length=1, max_length=200)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extraction: ExtractionResult
    report: AiRequirementReport
    completeness_status: Literal[CompletenessStatus.UNKNOWN] = CompletenessStatus.UNKNOWN
    submitted_by: str = Field(min_length=1, max_length=200)
    submitted_at: datetime
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("submitted_at")
    @classmethod
    def _submitted_at_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("AI report submission time must include a timezone")
        return value

    @model_validator(mode="after")
    def _snapshot_is_exactly_bound(self) -> Self:
        _validate_report_source_binding(
            report=self.report,
            company_id=self.company_id,
            source_document_id=self.source_document_id,
            source_sha256=self.source_sha256,
            extraction=self.extraction,
        )
        expected = canonical_json_sha256(self.model_dump(mode="json", exclude={"evidence_sha256"}))
        if self.evidence_sha256 != expected:
            raise ValueError("persisted AI run evidence digest does not match")
        return self


class AiRequirementTransferRunSnapshot(BaseModel):
    """Server-managed raw-free transfer result bound to persisted source evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["persisted-ai-requirement-run-v2"] = "persisted-ai-requirement-run-v2"
    origin: Literal["SERVER_MANAGED_TRANSFER"] = "SERVER_MANAGED_TRANSFER"
    company_id: str = Field(min_length=1, max_length=200)
    run_id: str = Field(min_length=1, max_length=200)
    source_document_id: str = Field(min_length=1, max_length=200)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extraction: ExtractionResult
    result: AiTransferRequirementResult
    completeness_status: Literal[CompletenessStatus.UNKNOWN] = CompletenessStatus.UNKNOWN
    prepared_by: str = Field(min_length=1, max_length=200)
    materialized_by: str = Field(min_length=1, max_length=200)
    materialized_at: datetime
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("materialized_at")
    @classmethod
    def _materialized_at_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("AI transfer result materialization time must include timezone")
        return value

    @model_validator(mode="after")
    def _snapshot_is_exactly_bound(self) -> Self:
        _validate_transfer_result_source_binding(
            result=self.result,
            company_id=self.company_id,
            source_document_id=self.source_document_id,
            source_sha256=self.source_sha256,
            extraction=self.extraction,
        )
        if (
            self.prepared_by != self.result.prepared_by
            or self.materialized_by != self.result.materialized_by
            or self.materialized_at != self.result.materialized_at
        ):
            raise ValueError("persisted AI transfer run actor binding does not match")
        expected = canonical_json_sha256(self.model_dump(mode="json", exclude={"evidence_sha256"}))
        if self.evidence_sha256 != expected:
            raise ValueError("persisted AI transfer run evidence digest does not match")
        return self


class AiRequirementTransferBatchRunSnapshot(BaseModel):
    """Complete raw-free ordered transfer batch exposed for independent review."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["persisted-ai-requirement-run-v3"] = "persisted-ai-requirement-run-v3"
    origin: Literal["SERVER_MANAGED_TRANSFER_BATCH"] = "SERVER_MANAGED_TRANSFER_BATCH"
    company_id: str = Field(min_length=1, max_length=200)
    run_id: str = Field(min_length=1, max_length=200)
    source_document_id: str = Field(min_length=1, max_length=200)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extraction: ExtractionResult
    result: AiTransferRequirementBatchResult
    completeness_status: Literal[CompletenessStatus.UNKNOWN] = CompletenessStatus.UNKNOWN
    prepared_by: str = Field(min_length=1, max_length=200)
    aggregated_by: str = Field(min_length=1, max_length=200)
    aggregated_at: datetime
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("aggregated_at")
    @classmethod
    def _aggregated_at_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("AI transfer batch aggregation time must include timezone")
        return value

    @model_validator(mode="after")
    def _snapshot_is_exactly_bound(self) -> Self:
        _validate_transfer_result_source_binding(
            result=self.result,
            company_id=self.company_id,
            source_document_id=self.source_document_id,
            source_sha256=self.source_sha256,
            extraction=self.extraction,
        )
        if (
            self.prepared_by != self.result.prepared_by
            or self.aggregated_by != self.result.aggregated_by
            or self.aggregated_at != self.result.aggregated_at
        ):
            raise ValueError("persisted AI transfer batch actor binding does not match")
        expected = canonical_json_sha256(self.model_dump(mode="json", exclude={"evidence_sha256"}))
        if self.evidence_sha256 != expected:
            raise ValueError("persisted AI transfer batch evidence digest does not match")
        return self


AiRequirementRun = Annotated[
    AiRequirementRunSnapshot
    | AiRequirementTransferRunSnapshot
    | AiRequirementTransferBatchRunSnapshot,
    Field(discriminator="schema_version"),
]


class AiRequirementReviewDecision(BaseModel):
    """Terminal, exact-evidence decision over every report candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["persisted-ai-requirement-review-v1"] = (
        "persisted-ai-requirement-review-v1"
    )
    company_id: str = Field(min_length=1, max_length=200)
    run_id: str = Field(min_length=1, max_length=200)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_decisions: tuple[AiRequirementCandidateDecision, ...]
    reviewed_by: str = Field(min_length=1, max_length=200)
    reviewed_at: datetime
    completeness_status: Literal[CompletenessStatus.UNKNOWN] = CompletenessStatus.UNKNOWN

    @field_validator("reviewed_at")
    @classmethod
    def _reviewed_at_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("AI report review time must include a timezone")
        return value

    @model_validator(mode="after")
    def _candidate_decisions_are_unique(self) -> Self:
        keys = [
            (decision.candidate_kind, decision.candidate_id)
            for decision in self.candidate_decisions
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("each AI report candidate may be reviewed only once")
        return self


class AiRequirementReviewRecord(BaseModel):
    """Imported snapshot and its optional immutable terminal review."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot: AiRequirementRun
    decision: AiRequirementReviewDecision | None = None

    @model_validator(mode="after")
    def _decision_matches_snapshot(self) -> Self:
        if self.decision is None:
            return self
        decision = self.decision
        snapshot = self.snapshot
        if (
            decision.company_id != snapshot.company_id
            or decision.run_id != snapshot.run_id
            or decision.evidence_sha256 != snapshot.evidence_sha256
        ):
            raise ValueError("AI report decision does not match exact run evidence")
        if decision.reviewed_by == _snapshot_prepared_by(snapshot):
            raise ValueError("AI report submitter cannot review their own run")
        _validate_complete_candidate_decisions(
            _snapshot_candidate_source(snapshot), decision.candidate_decisions
        )
        return self


def build_ai_requirement_run_snapshot(
    *,
    company_id: str,
    run_id: str,
    source_document_id: str,
    source_sha256: str,
    extraction: ExtractionResult,
    report: Mapping[str, object] | AiRequirementAnalysisReport | AiRequirementAnalysisReportV2,
    submitted_by: str,
    submitted_at: datetime,
) -> AiRequirementRunSnapshot:
    """Validate an untrusted report and bind it to exact stored extraction evidence."""
    payload = report.model_dump(mode="json") if isinstance(report, BaseModel) else dict(report)
    checked_report = validate_ai_requirement_report(payload)
    fields = {
        "origin": "IMPORTED_REPORT",
        "company_id": company_id,
        "run_id": run_id,
        "source_document_id": source_document_id,
        "source_sha256": source_sha256,
        "extraction": extraction,
        "report": checked_report,
        "completeness_status": CompletenessStatus.UNKNOWN,
        "submitted_by": submitted_by,
        "submitted_at": submitted_at,
    }
    evidence_sha256 = canonical_json_sha256(
        {"schema_version": "persisted-ai-requirement-run-v1", **fields}
    )
    return AiRequirementRunSnapshot(**fields, evidence_sha256=evidence_sha256)


def build_ai_requirement_transfer_run_snapshot(
    *,
    run_id: str,
    extraction: ExtractionResult,
    result: AiTransferRequirementResult,
) -> AiRequirementTransferRunSnapshot:
    """Persist a validated server-managed result without provider response content."""
    checked_result = AiTransferRequirementResult.model_validate(
        result.model_dump(mode="python"), strict=True
    )
    fields = {
        "origin": "SERVER_MANAGED_TRANSFER",
        "company_id": checked_result.company_id,
        "run_id": run_id,
        "source_document_id": checked_result.source_document_id,
        "source_sha256": checked_result.source_sha256,
        "extraction": extraction,
        "result": checked_result,
        "completeness_status": CompletenessStatus.UNKNOWN,
        "prepared_by": checked_result.prepared_by,
        "materialized_by": checked_result.materialized_by,
        "materialized_at": checked_result.materialized_at,
    }
    evidence_sha256 = canonical_json_sha256(
        {"schema_version": "persisted-ai-requirement-run-v2", **fields}
    )
    return AiRequirementTransferRunSnapshot(**fields, evidence_sha256=evidence_sha256)


def build_ai_requirement_transfer_batch_run_snapshot(
    *,
    run_id: str,
    extraction: ExtractionResult,
    result: AiTransferRequirementBatchResult,
) -> AiRequirementTransferBatchRunSnapshot:
    """Bind one complete ordered batch to exact source extraction evidence."""
    checked_result = AiTransferRequirementBatchResult.model_validate(
        result.model_dump(mode="python"), strict=True
    )
    fields = {
        "origin": "SERVER_MANAGED_TRANSFER_BATCH",
        "company_id": checked_result.company_id,
        "run_id": run_id,
        "source_document_id": checked_result.source_document_id,
        "source_sha256": checked_result.source_sha256,
        "extraction": extraction,
        "result": checked_result,
        "completeness_status": CompletenessStatus.UNKNOWN,
        "prepared_by": checked_result.prepared_by,
        "aggregated_by": checked_result.aggregated_by,
        "aggregated_at": checked_result.aggregated_at,
    }
    evidence_sha256 = canonical_json_sha256(
        {"schema_version": "persisted-ai-requirement-run-v3", **fields}
    )
    return AiRequirementTransferBatchRunSnapshot(**fields, evidence_sha256=evidence_sha256)


def build_ai_requirement_review_decision(
    snapshot: (
        AiRequirementRunSnapshot
        | AiRequirementTransferRunSnapshot
        | AiRequirementTransferBatchRunSnapshot
    ),
    *,
    evidence_sha256: str,
    candidate_decisions: tuple[AiRequirementCandidateDecision, ...],
    reviewed_by: str,
    reviewed_at: datetime,
) -> AiRequirementReviewDecision:
    """Create a terminal independent review covering every candidate exactly once."""
    if evidence_sha256 != snapshot.evidence_sha256:
        raise ValueError("AI report review evidence digest is stale")
    if reviewed_by == _snapshot_prepared_by(snapshot):
        raise ValueError("AI report submitter cannot review their own run")
    _validate_complete_candidate_decisions(
        _snapshot_candidate_source(snapshot), candidate_decisions
    )
    decision = AiRequirementReviewDecision(
        company_id=snapshot.company_id,
        run_id=snapshot.run_id,
        evidence_sha256=evidence_sha256,
        candidate_decisions=candidate_decisions,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
    )
    AiRequirementReviewRecord(snapshot=snapshot, decision=decision)
    return decision


def _validate_report_source_binding(
    *,
    report: AiRequirementAnalysisReport | AiRequirementAnalysisReportV2,
    company_id: str,
    source_document_id: str,
    source_sha256: str,
    extraction: ExtractionResult,
) -> None:
    native_extractors = {
        Extractor.NATIVE_PDF,
        Extractor.NATIVE_DOCX,
        Extractor.NATIVE_XLSX,
    }
    if (
        extraction.status is not ExtractionStatus.PASS
        or extraction.reasons
        or not extraction.blocks
        or extraction.source_units_extracted != extraction.source_units_total
        or any(block.provenance.extractor not in native_extractors for block in extraction.blocks)
        or {block.provenance.document_id for block in extraction.blocks} != {source_document_id}
    ):
        raise ValueError("persisted AI run requires complete native source extraction")
    if (
        report.company_id != company_id
        or report.source_document_id != source_document_id
        or report.source_sha256 != source_sha256
    ):
        raise ValueError("AI report source identity does not match stored document")
    if report.extraction_sha256 != canonical_json_sha256(extraction):
        raise ValueError("AI report extraction digest does not match stored extraction")
    if report.blocks_total != len(extraction.blocks):
        raise ValueError("AI report block count does not match stored extraction")

    expected_blocks = {
        f"b{index:06d}": AiSourceBlock(
            block_id=f"b{index:06d}",
            text=block.text,
            provenance=block.provenance,
        )
        for index, block in enumerate(extraction.blocks, start=1)
    }
    expected_ids = set(expected_blocks)
    expected_chunk_ids = tuple(f"chunk-{index:04d}" for index in range(1, len(report.chunks) + 1))
    if tuple(chunk.chunk_id for chunk in report.chunks) != expected_chunk_ids:
        raise ValueError("AI report chunk IDs are not unique sequential run IDs")
    chunk_source_union: set[str] = set()
    for chunk in report.chunks:
        source_ids = set(chunk.source_block_ids)
        if not source_ids.issubset(expected_ids):
            raise ValueError("AI report chunk references an unknown source block")
        if not set(chunk.unresolved_block_ids).issubset(expected_ids):
            raise ValueError("AI report unresolved block is not in stored extraction")
        if chunk.response_content is not None:
            response_sha256 = hashlib.sha256(chunk.response_content.encode("utf-8")).hexdigest()
            if chunk.response_sha256 != response_sha256:
                raise ValueError("AI report response digest does not match content")
        if chunk.provider_model is not None and chunk.provider_model != report.model:
            raise ValueError("AI report provider model does not match run model")
        chunk_source_union.update(source_ids)
        _validate_requirement_evidence(chunk.candidates, expected_blocks)
        if hasattr(chunk, "item_candidates"):
            _validate_item_evidence(chunk.item_candidates, expected_blocks)
    if chunk_source_union != expected_ids:
        raise ValueError("AI report chunks do not cover every stored extraction block")
    _validate_requirement_evidence(report.candidates, expected_blocks)
    if isinstance(report, AiRequirementAnalysisReportV2):
        _validate_item_evidence(report.item_candidates, expected_blocks)


def _validate_requirement_evidence(
    candidates: tuple[AiRequirementCandidate, ...],
    expected_blocks: dict[str, AiSourceBlock],
) -> None:
    for candidate in candidates:
        for cited in candidate.evidence:
            expected = expected_blocks.get(cited.block_id)
            if expected is None or cited != expected:
                raise ValueError("AI requirement evidence differs from stored extraction")


def _validate_item_evidence(
    candidates: tuple[AiProcurementItemCandidate, ...],
    expected_blocks: dict[str, AiSourceBlock],
) -> None:
    for candidate in candidates:
        evidence_groups = [
            candidate.item_name.evidence,
            *(claim.evidence for claim in candidate.okpd2_codes),
            *(claim.evidence for claim in candidate.ktru_codes),
        ]
        if candidate.unit is not None:
            evidence_groups.append(candidate.unit.evidence)
        if candidate.quantity is not None:
            evidence_groups.append(candidate.quantity.evidence)
        for evidence in evidence_groups:
            for cited in evidence:
                expected = expected_blocks.get(cited.block_id)
                if expected is None or cited != expected:
                    raise ValueError("AI item field evidence differs from stored extraction")


def _validate_transfer_result_source_binding(
    *,
    result: AiTransferRequirementResult | AiTransferRequirementBatchResult,
    company_id: str,
    source_document_id: str,
    source_sha256: str,
    extraction: ExtractionResult,
) -> None:
    native_extractors = {
        Extractor.NATIVE_PDF,
        Extractor.NATIVE_DOCX,
        Extractor.NATIVE_XLSX,
    }
    if (
        extraction.status is not ExtractionStatus.PASS
        or extraction.reasons
        or not extraction.blocks
        or extraction.source_units_extracted != extraction.source_units_total
        or any(block.provenance.extractor not in native_extractors for block in extraction.blocks)
        or {block.provenance.document_id for block in extraction.blocks} != {source_document_id}
    ):
        raise ValueError("persisted AI run requires complete native source extraction")
    if (
        result.company_id != company_id
        or result.source_document_id != source_document_id
        or result.source_sha256 != source_sha256
        or result.extraction_sha256 != canonical_json_sha256(extraction)
    ):
        raise ValueError("AI transfer result source identity does not match stored document")
    expected_blocks = {
        f"b{index:06d}": AiSourceBlock(
            block_id=f"b{index:06d}",
            text=block.text,
            provenance=block.provenance,
        )
        for index, block in enumerate(extraction.blocks, start=1)
    }
    if result.source_block_ids != tuple(expected_blocks):
        raise ValueError("AI transfer result does not cover exact stored extraction")
    _validate_requirement_evidence(result.candidates, expected_blocks)
    _validate_item_evidence(result.item_candidates, expected_blocks)


def _snapshot_prepared_by(
    snapshot: (
        AiRequirementRunSnapshot
        | AiRequirementTransferRunSnapshot
        | AiRequirementTransferBatchRunSnapshot
    ),
) -> str:
    if isinstance(
        snapshot,
        (AiRequirementTransferRunSnapshot, AiRequirementTransferBatchRunSnapshot),
    ):
        return snapshot.prepared_by
    return snapshot.submitted_by


def _snapshot_candidate_source(
    snapshot: (
        AiRequirementRunSnapshot
        | AiRequirementTransferRunSnapshot
        | AiRequirementTransferBatchRunSnapshot
    ),
) -> (
    AiRequirementAnalysisReport
    | AiRequirementAnalysisReportV2
    | AiTransferRequirementResult
    | AiTransferRequirementBatchResult
):
    if isinstance(
        snapshot,
        (AiRequirementTransferRunSnapshot, AiRequirementTransferBatchRunSnapshot),
    ):
        return snapshot.result
    return snapshot.report


def _expected_candidate_keys(
    report: (
        AiRequirementAnalysisReport
        | AiRequirementAnalysisReportV2
        | AiTransferRequirementResult
        | AiTransferRequirementBatchResult
    ),
) -> set[tuple[CandidateKind, str]]:
    keys = {(CandidateKind.REQUIREMENT, candidate.candidate_id) for candidate in report.candidates}
    if isinstance(
        report,
        (
            AiRequirementAnalysisReportV2,
            AiTransferRequirementResult,
            AiTransferRequirementBatchResult,
        ),
    ):
        keys.update(
            (CandidateKind.PROCUREMENT_ITEM, candidate.candidate_id)
            for candidate in report.item_candidates
        )
    return keys


def _validate_complete_candidate_decisions(
    report: (
        AiRequirementAnalysisReport
        | AiRequirementAnalysisReportV2
        | AiTransferRequirementResult
        | AiTransferRequirementBatchResult
    ),
    decisions: tuple[AiRequirementCandidateDecision, ...],
) -> None:
    if report.execution_status is not AiRequirementRunStatus.COMPLETE:
        raise ValueError("only a COMPLETE AI report can receive a terminal review")
    keys = [(decision.candidate_kind, decision.candidate_id) for decision in decisions]
    if len(keys) != len(set(keys)):
        raise ValueError("each AI report candidate may be reviewed only once")
    if set(keys) != _expected_candidate_keys(report):
        raise ValueError("AI report review must cover every exact candidate once")
