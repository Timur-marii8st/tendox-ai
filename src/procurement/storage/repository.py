"""Tenant-scoped synchronous repositories backed only by PostgreSQL."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import (
    Engine,
    Text,
    and_,
    cast,
    create_engine,
    delete,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import Connection, RowMapping

from procurement.access import AccessRole
from procurement.documents import (
    ZIP_MEDIA_TYPES,
    AiRequirementAnalysisReport,
    AiRequirementAnalysisReportV2,
    AiRequirementCandidateDecision,
    AiRequirementReviewDecision,
    AiRequirementReviewRecord,
    AiRequirementRunSnapshot,
    ApplicationAttachment,
    ApplicationAttachmentInput,
    ApplicationAttachmentReview,
    ApplicationDocumentRequirement,
    ApplicationInventoryAssessment,
    ApplicationPackage,
    ApplicationPackageEvidence,
    ApplicationPackageRecord,
    ApplicationPriceAssessment,
    ApplicationRequirementReview,
    ApplicationReviewDecision,
    ApplicationReviewRecord,
    CaseDocumentEvidenceBinding,
    CaseHardGateDecisionInput,
    CaseRequirementSetBinding,
    CompletenessBlockDecision,
    CompletenessReviewDecision,
    CompletenessReviewRecord,
    CompletenessReviewSnapshot,
    CompletenessReviewSourceInvalid,
    CompletenessStatus,
    DocumentBundleResult,
    DocumentRole,
    DocumentSearchEntry,
    DocumentSetCrossAssessment,
    DocumentSetFinding,
    DocumentSetFindingOrigin,
    DocumentSetInventoryAssessment,
    DocumentSetMemberAttestation,
    DocumentSetReviewDecision,
    DocumentSetReviewEvidence,
    ExtractionReason,
    ExtractionResult,
    ExtractionStatus,
    ModelBrandCatalog,
    ModelBrandCatalogEntry,
    ModelBrandReviewProposal,
    ModelBrandReviewStatus,
    OcrDerivative,
    ParticipationDecision,
    ParticipationDecisionRecord,
    ParticipationDecisionStatus,
    RequirementSetCoverageAssessment,
    RequirementSetNormalizationAssessment,
    ReviewedRequirementEntry,
    ReviewedRequirementSetDecision,
    ReviewedRequirementSetProposal,
    ReviewedRequirementSetRecord,
    ServerOfferBomLineInput,
    ServerOfferBomScopeAssessment,
    ServerOfferCommercialAssessment,
    ServerOfferCommercialTermsInput,
    ServerOfferEconomicsEvidence,
    ServerOfferEconomicsPackage,
    ServerOfferEconomicsRecord,
    ServerOfferProposal,
    ServerOfferRequirementDecision,
    ServerOfferReviewDecision,
    ServerOfferReviewEvidence,
    ServerOfferReviewRecord,
    ServerOfferScenarioInput,
    build_ai_requirement_review_decision,
    build_ai_requirement_run_snapshot,
    build_application_package,
    build_application_review_decision,
    build_case_document_evidence_binding,
    build_case_requirement_set_binding,
    build_completeness_review_decision,
    build_completeness_review_snapshot,
    build_document_search_entry,
    build_document_set_review_decision,
    build_document_set_review_evidence,
    build_participation_decision,
    build_participation_evaluation_evidence,
    build_reviewed_requirement_set_decision,
    build_reviewed_requirement_set_proposal,
    build_server_offer_economics_package,
    build_server_offer_proposal,
    build_server_offer_review_decision,
    bundle_member_source_id,
    canonical_json_sha256,
    document_gate_check_from_binding,
    docx_media_source_id,
    extract_docx_media,
    materialize_case_from_server_offer_economics,
    materialize_case_hard_gate_assessment,
)
from procurement.documents.ai_requirement_review import (
    AiRequirementTransferBatchRunSnapshot,
    AiRequirementTransferRunSnapshot,
    build_ai_requirement_transfer_batch_run_snapshot,
    build_ai_requirement_transfer_run_snapshot,
)
from procurement.documents.ai_requirements import (
    AiRequirementError,
    prepare_ai_requirements_transfer,
)
from procurement.documents.ai_transfer import (
    PersistedAiTransferApproval,
    PersistedAiTransferRequest,
    build_persisted_ai_transfer_approval,
    build_persisted_ai_transfer_request,
)
from procurement.documents.ai_transfer_execution import (
    AiTransferDispatchClaim,
    AiTransferDispatchReceipt,
    AiTransferExecutionAdmission,
    build_ai_transfer_dispatch_claim,
    build_ai_transfer_dispatch_receipt,
    build_ai_transfer_execution_admission,
)
from procurement.documents.ai_transfer_raw import (
    AiTransferRawBinding,
    AiTransferRawDeletionReceipt,
    AiTransferRawEnvelope,
    AiTransferRawError,
    AiTransferRawErrorCode,
    AiTransferRawMetadata,
    TenantKekProvider,
    build_ai_transfer_raw_deletion_receipt,
    decrypt_ai_transfer_raw_response,
    encrypt_ai_transfer_raw_response,
)
from procurement.documents.ai_transfer_requirement_result import (
    AI_TRANSFER_REQUIREMENT_PARSER_VERSION,
    AiTransferRequirementBatchResult,
    AiTransferRequirementChunkRejection,
    AiTransferRequirementMaterialization,
    AiTransferRequirementResult,
    AiTransferRequirementResultError,
    AiTransferRequirementResultErrorCode,
    build_ai_transfer_requirement_batch_result,
    build_ai_transfer_requirement_chunk_rejection,
    build_ai_transfer_requirement_materialization,
    build_ai_transfer_requirement_result,
)
from procurement.documents.ai_transfer_transport import (
    AiTransferTransportAttempt,
    ExactAiTransferHttpRequest,
)
from procurement.documents.ai_transfer_worker import AiTransferPreparedDispatch
from procurement.documents.application_submission import (
    ApplicationSubmissionApproval,
    ApplicationSubmissionIntent,
    ApplicationSubmissionRecord,
    SubmissionApprovalStatus,
    build_submission_approval,
    build_submission_intent,
)
from procurement.documents.application_submission_execution import (
    ApplicationSubmissionAdmission,
    ApplicationSubmissionExecutionRecord,
    build_submission_admission,
)
from procurement.documents.document_set_evidence import (
    DocumentSetEvidenceManifest,
    DocumentSetEvidenceMember,
    build_document_set_evidence_manifest,
    project_document_set_evidence_member,
)
from procurement.documents.docx_media import DocxMediaRejected
from procurement.documents.extraction import DocumentInput
from procurement.domain.cases import (
    CaseAssessment,
    GateCheck,
    GateKind,
    ProcurementCase,
    case_input_digest,
    evaluate_case,
)
from procurement.domain.compliance import Verdict
from procurement.domain.decisions import Recommendation
from procurement.domain.sourcing import (
    SourcingRunRecord,
    SourcingRunStatus,
    SourcingSourceStatus,
)
from procurement.storage.models import (
    MAX_DOCUMENT_BYTES,
    MAX_SOURCING_SNAPSHOT_BYTES,
    MAX_SOURCING_SOURCE_BYTES,
    ai_transfer_approvals,
    ai_transfer_chunks,
    ai_transfer_dispatch_claims,
    ai_transfer_dispatch_receipts,
    ai_transfer_execution_admissions,
    ai_transfer_raw_response_blobs,
    ai_transfer_raw_response_deletion_receipts,
    ai_transfer_raw_responses,
    ai_transfer_requests,
    ai_transfer_requirement_batch_results,
    ai_transfer_requirement_chunk_rejections,
    ai_transfer_requirement_chunk_results,
    ai_transfer_requirement_materializations,
    api_keys,
    application_package_reviews,
    application_packages,
    application_submission_admissions,
    application_submission_approvals,
    application_submission_intents,
    audit_events,
    case_document_evidence_bindings,
    case_requirement_set_bindings,
    case_versions,
    document_ai_requirement_review_decisions,
    document_ai_requirement_runs,
    document_bundle_member_ocr_derivatives,
    document_bundles,
    document_completeness_review_decisions,
    document_completeness_reviews,
    document_docx_media_ocr_derivatives,
    document_ocr_derivatives,
    document_search_indexes,
    document_set_completeness_decisions,
    document_set_completeness_member_attestations,
    document_set_evidence_manifests,
    document_set_evidence_members,
    documents,
    evaluations,
    model_brand_catalogs,
    model_brand_review_decisions,
    model_brand_review_proposals,
    model_brand_source_artifacts,
    participation_decisions,
    reviewed_requirement_set_decisions,
    reviewed_requirement_set_proposals,
    server_offer_economics_packages,
    server_offer_proposals,
    server_offer_review_decisions,
    sourcing_run_sources,
    sourcing_runs,
    write_receipts,
)

MAX_DOCUMENT_SET_EVIDENCE_BYTES = 20 * 1024 * 1024
MAX_DOCUMENT_SET_REVIEW_EVIDENCE_BYTES = 40 * 1024 * 1024
MAX_AI_TRANSFER_EVIDENCE_BYTES = 40 * 1024 * 1024


class StorageError(RuntimeError):
    """Base error exposed by the storage boundary."""


class AiTransferConflict(StorageError):
    """Exact request, actor-bound replay, or terminal approval conflicts."""


class AiTransferNotFound(StorageError):
    """Tenant-visible transfer or source document is absent."""


class AiTransferSourceMismatch(StorageError):
    """Stored source/request/approval evidence cannot be verified."""


class CaseVersionConflict(StorageError):
    """The immutable identity already exists with a different payload."""


class CaseHardGateAssessmentConflict(StorageError):
    """The next assessed case version or idempotent request conflicts."""


class CaseHardGateAssessmentNotFound(StorageError):
    """The source case, its S89 lineage, or referenced evidence is absent."""


class CaseHardGateAssessmentSourceMismatch(StorageError):
    """The source case lineage or exact evidence digest cannot be verified."""


class DocumentConflict(StorageError):
    """The tenant already has an immutable document with this identity."""


class DocumentSearchIndexConflict(StorageError):
    """The tenant already has this immutable document-search identity."""


class ModelBrandCatalogConflict(StorageError):
    """The tenant already has this immutable reviewed catalog identity."""


class ModelBrandSourceArtifactConflict(StorageError):
    """The tenant already has this immutable official-source artifact identity."""


class ModelBrandSourceEvidenceMismatch(StorageError):
    """Catalog evidence is not backed by the exact tenant-visible artifact bytes."""


class ModelBrandReviewConflict(StorageError):
    """A review proposal or terminal decision already exists."""


class ModelBrandReviewNotFound(StorageError):
    """The tenant-visible review proposal does not exist."""


class CompletenessReviewConflict(StorageError):
    """The immutable snapshot or its single terminal decision conflicts."""


class CompletenessReviewNotFound(StorageError):
    """The tenant-visible source or completeness review does not exist."""


class CompletenessReviewSourceMismatch(StorageError):
    """Persisted bytes/extraction cannot safely support the review."""


class DocumentSetEvidenceConflict(StorageError):
    """The immutable selected document-set identity or request conflicts."""


class DocumentSetEvidenceNotFound(StorageError):
    """A tenant-visible manifest or selected completeness review is absent."""


class DocumentSetEvidenceSourceMismatch(StorageError):
    """Selected review/source evidence changed or does not match its digest."""


class DocumentSetReviewConflict(StorageError):
    """The terminal document-set decision or idempotent request conflicts."""


class DocumentSetReviewNotFound(StorageError):
    """The exact manifest or one of its constituent decisions is absent."""


class DocumentSetReviewSourceMismatch(StorageError):
    """Stored document-set review evidence is stale, invalid, or inconsistent."""


class CaseEvidenceConflict(StorageError):
    """The immutable case evidence binding identity or request conflicts."""


class CaseEvidenceNotFound(StorageError):
    """The tenant-visible manifest, decision, or binding is absent."""


class CaseEvidenceSourceMismatch(StorageError):
    """Selected manifest/decision evidence is stale, invalid, or inconsistent."""


class RequirementSetConflict(StorageError):
    """The immutable proposal, decision, binding, or request conflicts."""


class RequirementSetNotFound(StorageError):
    """A tenant-visible source, requirement set, decision, case, or binding is absent."""


class RequirementSetSourceMismatch(StorageError):
    """Stored requirement-set evidence cannot be reconstructed exactly."""


class ServerOfferConflict(StorageError):
    """The immutable server-offer proposal or idempotent request conflicts."""


class ServerOfferNotFound(StorageError):
    """A selected binding, sourcing lead, quote document, or offer is absent."""


class ServerOfferSourceMismatch(StorageError):
    """Selected server-offer evidence is stale, invalid, or cross-bound."""


class ServerOfferReviewConflict(StorageError):
    """The immutable review decision or idempotent request conflicts."""


class ServerOfferReviewNotFound(StorageError):
    """The offer or its exact reviewed requirement evidence is absent."""


class ServerOfferReviewSourceMismatch(StorageError):
    """Stored offer-review evidence is invalid, stale, or cross-bound."""


class ServerOfferEconomicsConflict(StorageError):
    """An economics package or idempotent request conflicts."""


class ServerOfferEconomicsNotFound(StorageError):
    """The exact case or reviewed offer needed for economics is absent."""


class ServerOfferEconomicsSourceMismatch(StorageError):
    """Stored case, offer review, or economics package cannot be verified."""


class ParticipationDecisionConflict(StorageError):
    """The exact evaluation already has a terminal decision or replay conflicts."""


class ParticipationDecisionNotFound(StorageError):
    """The tenant-visible evaluation does not exist."""


class ParticipationDecisionSourceMismatch(StorageError):
    """Evaluation evidence, actor separation, or current recommendation is invalid."""


class ApplicationPackageConflict(StorageError):
    """The approved decision already has a package or idempotency replay conflicts."""


class ApplicationPackageNotFound(StorageError):
    """The tenant-visible approved participation decision is absent."""


class ApplicationPackageSourceMismatch(StorageError):
    """Decision, case, price, requirement, or attachment evidence is invalid."""


class ApplicationReviewConflict(StorageError):
    """The exact package already has a terminal review or replay conflicts."""


class ApplicationReviewNotFound(StorageError):
    """The tenant-visible application package does not exist."""


class ApplicationReviewSourceMismatch(StorageError):
    """Review input or persisted package evidence is invalid."""


class ApplicationSubmissionConflict(StorageError):
    """The package already has an intent/decision or replay conflicts."""


class ApplicationSubmissionNotFound(StorageError):
    """The tenant-visible reviewed package or intent does not exist."""


class ApplicationSubmissionSourceMismatch(StorageError):
    """Exact submission evidence or proposed approval is invalid."""


class AiRequirementReviewConflict(StorageError):
    """The immutable imported run or its single terminal decision conflicts."""


class AiRequirementRunNotFound(StorageError):
    """The tenant-visible source document or imported run does not exist."""


class AiRequirementRunSourceMismatch(StorageError):
    """Stored document evidence does not match the imported AI run."""


class DocumentBundleConflict(StorageError):
    """The tenant already has an immutable document bundle with this identity."""


class BundleMemberOcrConflict(StorageError):
    """The tenant already has this immutable bundle-member OCR identity."""


class DocxMediaOcrConflict(StorageError):
    """The tenant already has this immutable DOCX-media OCR identity."""


class OcrDerivativeConflict(StorageError):
    """The tenant already has an immutable OCR derivative with this identity."""


class AuditEventConflict(StorageError):
    """The tenant already has an audit event with this identity."""


class ApiKeyConflict(StorageError):
    """An API key identity or digest is already registered."""


class IdempotencyConflict(StorageError):
    """An idempotency key was reused for a different request payload."""


class AuditEventRecord(BaseModel):
    """Complete persisted audit fact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(min_length=1)
    company_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    object_type: str | None = Field(default=None, min_length=1)
    object_id: str | None = Field(default=None, min_length=1)
    object_version: int | None = Field(default=None, ge=1)
    basis: dict[str, Any]
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def _occurred_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value


class ApiKeyRecord(BaseModel):
    """Stored API-key metadata; plaintext key material is never persisted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key_id: str = Field(min_length=1)
    company_id: str = Field(min_length=1)
    key_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    actor_id: str = Field(min_length=1)
    access_role: AccessRole = AccessRole.OPERATOR
    enabled: bool = True
    created_at: datetime | None = None

    @field_validator("created_at")
    @classmethod
    def _created_at_is_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("created_at must include a timezone")
        return value


class Principal(BaseModel):
    """Identity returned by database-backed bearer authentication."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    key_id: str = Field(min_length=1)
    access_role: AccessRole


class WriteReceiptRecord(BaseModel):
    """Immutable response associated with an exact idempotent request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response: dict[str, Any]
    created_at: datetime | None = None


class EvaluationRecord(BaseModel):
    """Immutable result of evaluating one exact case version at one instant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: str = Field(min_length=1)
    evaluation_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    case_version: int = Field(ge=1)
    effective_at: datetime
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    engine_version: str = Field(min_length=1)
    recommendation: Recommendation
    created_at: datetime | None = None

    @field_validator("effective_at", "created_at")
    @classmethod
    def _times_are_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("evaluation times must include a timezone")
        return value


class DocumentRecord(BaseModel):
    """Complete immutable source document and its typed extraction envelope."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    original_filename: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    document_role: DocumentRole
    byte_size: int = Field(ge=1, le=MAX_DOCUMENT_BYTES)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: bytes
    extraction: ExtractionResult
    created_at: datetime

    @field_validator("company_id", "document_id", "original_filename", "media_type")
    @classmethod
    def _text_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("document text fields must not be blank")
        return value

    @field_validator("created_at")
    @classmethod
    def _created_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value

    @field_validator("content")
    @classmethod
    def _content_is_not_empty(cls, value: bytes) -> bytes:
        if not value:
            raise ValueError("document content must not be empty")
        if len(value) > MAX_DOCUMENT_BYTES:
            raise ValueError(f"document content exceeds {MAX_DOCUMENT_BYTES} bytes")
        return value

    @model_validator(mode="after")
    def _content_matches_metadata(self) -> Self:
        if len(self.content) != self.byte_size:
            raise ValueError("byte_size does not match document content")
        if hashlib.sha256(self.content).hexdigest() != self.sha256:
            raise ValueError("sha256 does not match document content")
        return self


class DocumentSearchIndexRecord(BaseModel):
    """Immutable search material bound to one exact stored document."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: str = Field(min_length=1)
    search_index_id: str = Field(min_length=1)
    source_document_id: str = Field(min_length=1)
    source_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    entry: DocumentSearchEntry
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _created_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value

    @model_validator(mode="after")
    def _entry_matches_record(self) -> Self:
        if (
            self.entry.company_id != self.company_id
            or self.entry.document_id != self.source_document_id
            or self.entry.source_sha256 != self.source_document_sha256
        ):
            raise ValueError("search entry does not match persisted identity")
        return self


class ModelBrandCatalogRecord(BaseModel):
    """One immutable reviewed tenant-scoped model-brand catalog snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: str = Field(min_length=1)
    catalog_id: str = Field(min_length=1)
    catalog: ModelBrandCatalog
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _created_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value

    @model_validator(mode="after")
    def _catalog_matches_record(self) -> Self:
        if self.catalog.company_id != self.company_id or self.catalog.catalog_id != self.catalog_id:
            raise ValueError("model-brand catalog does not match persisted identity")
        return self


class ModelBrandSourceArtifactRecord(BaseModel):
    """Immutable official PDF bytes used by reviewed model-brand evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1, max_length=200)
    source_title: str = Field(min_length=1, max_length=500)
    source_url: str = Field(min_length=1, max_length=2_048)
    original_filename: str = Field(min_length=1, max_length=255)
    media_type: str
    byte_size: int = Field(ge=1, le=MAX_DOCUMENT_BYTES)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: bytes
    retrieved_at: datetime
    created_at: datetime

    @field_validator(
        "company_id",
        "artifact_id",
        "source_title",
        "source_url",
        "original_filename",
    )
    @classmethod
    def _text_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model-brand source artifact fields must not be blank")
        return value

    @field_validator("retrieved_at", "created_at")
    @classmethod
    def _times_are_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("model-brand source artifact times must include a timezone")
        return value

    @model_validator(mode="after")
    def _bytes_match_metadata(self) -> Self:
        if self.media_type != "application/pdf":
            raise ValueError("model-brand source artifact must be a PDF")
        if not self.original_filename.casefold().endswith(".pdf"):
            raise ValueError("model-brand source artifact filename must end with .pdf")
        if not self.source_url.casefold().startswith("https://"):
            raise ValueError("model-brand source artifact URL must use HTTPS")
        if not self.content.startswith(b"%PDF-"):
            raise ValueError("model-brand source artifact has an invalid PDF signature")
        if len(self.content) != self.byte_size:
            raise ValueError("model-brand source artifact byte_size does not match content")
        if hashlib.sha256(self.content).hexdigest() != self.sha256:
            raise ValueError("model-brand source artifact SHA-256 does not match content")
        if self.retrieved_at > self.created_at:
            raise ValueError("model-brand source artifact retrieval cannot be in the future")
        return self


class ModelBrandReviewDecisionRecord(BaseModel):
    """One terminal append-only decision for a model-brand proposal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    status: ModelBrandReviewStatus
    decided_by: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=2_000)
    catalog_id: str | None = None
    created_at: datetime

    @model_validator(mode="after")
    def _decision_is_terminal_and_consistent(self) -> Self:
        if self.status is ModelBrandReviewStatus.DRAFT:
            raise ValueError("review decision cannot be DRAFT")
        if (self.status is ModelBrandReviewStatus.APPROVED) != (self.catalog_id is not None):
            raise ValueError("only an approved decision must reference a catalog")
        if self.created_at.utcoffset() is None:
            raise ValueError("review decision time must include a timezone")
        return self


class ModelBrandReviewRecord(BaseModel):
    """Proposal with its derived current state and optional terminal decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal: ModelBrandReviewProposal
    status: ModelBrandReviewStatus
    decision: ModelBrandReviewDecisionRecord | None = None

    @model_validator(mode="after")
    def _state_matches_decision(self) -> Self:
        if self.decision is None and self.status is not ModelBrandReviewStatus.DRAFT:
            raise ValueError("proposal without decision must remain DRAFT")
        if self.decision is not None and self.decision.status is not self.status:
            raise ValueError("review status does not match decision")
        return self


class DocumentBundleRecord(BaseModel):
    """Complete immutable ZIP source and its typed member snapshots."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: str = Field(min_length=1)
    bundle_id: str = Field(min_length=1)
    original_filename: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    document_role: DocumentRole
    byte_size: int = Field(ge=1, le=MAX_DOCUMENT_BYTES)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: bytes
    result: DocumentBundleResult
    created_at: datetime

    @field_validator("company_id", "bundle_id", "original_filename", "media_type")
    @classmethod
    def _text_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("document bundle text fields must not be blank")
        return value

    @field_validator("created_at")
    @classmethod
    def _created_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value

    @field_validator("content")
    @classmethod
    def _content_is_not_empty(cls, value: bytes) -> bytes:
        if not value:
            raise ValueError("document bundle content must not be empty")
        if len(value) > MAX_DOCUMENT_BYTES:
            raise ValueError(f"document bundle content exceeds {MAX_DOCUMENT_BYTES} bytes")
        return value

    @model_validator(mode="after")
    def _content_matches_metadata(self) -> Self:
        if not self.original_filename.casefold().endswith(".zip"):
            raise ValueError("document bundle filename must end with .zip")
        if self.media_type.casefold() not in ZIP_MEDIA_TYPES:
            raise ValueError("document bundle media type must be ZIP")
        if len(self.content) != self.byte_size:
            raise ValueError("byte_size does not match document bundle content")
        if hashlib.sha256(self.content).hexdigest() != self.sha256:
            raise ValueError("sha256 does not match document bundle content")
        if self.result.source_document_id != self.bundle_id:
            raise ValueError("bundle result source id does not match bundle_id")
        if self.result.source_sha256 != self.sha256:
            raise ValueError("bundle result SHA-256 does not match source content")
        return self


class OcrDerivativeRecord(BaseModel):
    """Immutable OCR derivative of one exact source document version."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: str = Field(min_length=1)
    ocr_id: str = Field(min_length=1)
    source_document_id: str = Field(min_length=1)
    engine: str = Field(min_length=1)
    threshold: float = Field(ge=0.0, le=1.0, multiple_of=0.01)
    status: str = Field(min_length=1)
    result: dict[str, Any]
    mean_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    created_at: datetime

    @field_validator("company_id", "ocr_id", "source_document_id", "engine")
    @classmethod
    def _text_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("ocr text fields must not be blank")
        return value

    @field_validator("created_at")
    @classmethod
    def _created_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value

    @field_validator("status")
    @classmethod
    def _status_is_allowed(cls, value: str) -> str:
        if value not in ("PASS", "FAIL", "UNKNOWN"):
            raise ValueError("ocr status must be PASS, FAIL, or UNKNOWN")
        return value


class BundleMemberOcrRecord(BaseModel):
    """Immutable OCR derivative tied to one exact member of one exact ZIP."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: str = Field(min_length=1)
    ocr_id: str = Field(min_length=1)
    source_bundle_id: str = Field(min_length=1)
    member_index: int = Field(ge=0)
    archive_path: str = Field(min_length=1, max_length=512)
    source_member_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    engine: str = Field(min_length=1)
    threshold: float = Field(ge=0.0, le=1.0, multiple_of=0.01)
    status: str = Field(min_length=1)
    result: OcrDerivative
    mean_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _created_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value

    @model_validator(mode="after")
    def _result_matches_member(self) -> Self:
        if self.result.source_document_id != bundle_member_source_id(
            self.source_bundle_id,
            self.member_index,
        ):
            raise ValueError("OCR result source id does not match bundle member")
        if self.result.source_sha256 != self.source_member_sha256:
            raise ValueError("OCR result SHA-256 does not match bundle member")
        if self.result.engine != self.engine:
            raise ValueError("OCR result engine does not match record")
        if self.result.threshold != self.threshold:
            raise ValueError("OCR result threshold does not match record")
        if self.result.status.value != self.status:
            raise ValueError("OCR result status does not match record")
        if self.mean_confidence is not None and self.result.mean_confidence != self.mean_confidence:
            raise ValueError("OCR result mean confidence does not match record")
        return self


class DocxMediaOcrRecord(BaseModel):
    """Immutable OCR derivative tied to one linked image of one exact DOCX."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: str = Field(min_length=1)
    ocr_id: str = Field(min_length=1)
    source_document_id: str = Field(min_length=1)
    media_index: int = Field(ge=0)
    archive_path: str = Field(min_length=1, max_length=512)
    source_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_media_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str = Field(pattern=r"^image/(jpeg|png)$")
    engine: str = Field(min_length=1)
    threshold: float = Field(ge=0.0, le=1.0, multiple_of=0.01)
    status: str = Field(min_length=1)
    result: OcrDerivative
    mean_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _created_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value

    @model_validator(mode="after")
    def _result_matches_media(self) -> Self:
        if self.status not in ("PASS", "FAIL", "UNKNOWN"):
            raise ValueError("OCR status must be PASS, FAIL, or UNKNOWN")
        if self.result.source_document_id != docx_media_source_id(
            self.source_document_id,
            self.media_index,
        ):
            raise ValueError("OCR result source id does not match DOCX media")
        if self.result.source_sha256 != self.source_media_sha256:
            raise ValueError("OCR result SHA-256 does not match DOCX media")
        if self.result.engine != self.engine or self.result.threshold != self.threshold:
            raise ValueError("OCR result engine or threshold does not match record")
        if self.result.status.value != self.status:
            raise ValueError("OCR result status does not match record")
        if self.mean_confidence is not None and self.result.mean_confidence != self.mean_confidence:
            raise ValueError("OCR result mean confidence does not match record")
        return self


class CasePage(BaseModel):
    """One cursor-addressed page containing the latest visible case versions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[ProcurementCase, ...]
    next_cursor: str | None = None


def _encode_cursor(case_id: str) -> str:
    encoded = base64.urlsafe_b64encode(
        json.dumps({"after_case_id": case_id}, separators=(",", ":")).encode()
    )
    return encoded.decode().rstrip("=")


def _decode_cursor(cursor: str) -> str:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        case_id = payload["after_case_id"]
    except (KeyError, UnicodeDecodeError, ValueError, TypeError) as error:
        raise ValueError("invalid case-list cursor") from error
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("invalid case-list cursor")
    return case_id


def api_key_digest(secret: str) -> str:
    """Return the lowercase SHA-256 digest used for API-key lookup."""
    if not secret:
        raise ValueError("API key must not be empty")
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _require_tenant(company_id: str) -> str:
    if not company_id:
        raise ValueError("company_id must not be empty")
    return company_id


def _require_sha256(value: str, *, field: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


class PostgresStorage:
    """One explicit tenant context and transaction per repository operation."""

    def __init__(
        self,
        engine: Engine,
        *,
        raw_key_provider: TenantKekProvider | None = None,
    ) -> None:
        if engine.dialect.name != "postgresql":
            raise ValueError("PostgresStorage requires a PostgreSQL engine")
        self._engine = engine
        self._raw_key_provider = raw_key_provider

    @classmethod
    def from_url(
        cls,
        database_url: str,
        *,
        raw_key_provider: TenantKekProvider | None = None,
        **engine_options: Any,
    ) -> PostgresStorage:
        """Build storage from a SQLAlchemy PostgreSQL URL."""
        return cls(
            create_engine(database_url, **engine_options),
            raw_key_provider=raw_key_provider,
        )

    @contextmanager
    def transaction(
        self, company_id: str, *, consistent_read: bool = False
    ) -> Iterator[Connection]:
        """Open a transaction and bind PostgreSQL RLS to one tenant."""
        tenant = _require_tenant(company_id)
        engine = (
            self._engine.execution_options(
                isolation_level="REPEATABLE READ", postgresql_readonly=True
            )
            if consistent_read
            else self._engine
        )
        with engine.begin() as connection:
            connection.execute(
                text("SELECT set_config('app.company_id', :company_id, true)"),
                {"company_id": tenant},
            )
            yield connection

    @staticmethod
    def _verify_model_brand_source_evidence(
        connection: Connection,
        tenant: str,
        entries: tuple[ModelBrandCatalogEntry, ...],
    ) -> None:
        if any(entry.evidence.source_artifact_id is None for entry in entries):
            raise ModelBrandSourceEvidenceMismatch(
                "persisted model-brand evidence requires a source artifact"
            )
        artifact_ids = {
            entry.evidence.source_artifact_id
            for entry in entries
            if entry.evidence.source_artifact_id is not None
        }
        artifact_rows = connection.execute(
            select(model_brand_source_artifacts).where(
                and_(
                    model_brand_source_artifacts.c.company_id == tenant,
                    model_brand_source_artifacts.c.artifact_id.in_(artifact_ids),
                )
            )
        ).mappings()
        artifacts = {
            row["artifact_id"]: ModelBrandSourceArtifactRecord.model_validate(dict(row))
            for row in artifact_rows
        }
        for entry in entries:
            evidence = entry.evidence
            artifact = artifacts.get(evidence.source_artifact_id)
            if (
                artifact is None
                or artifact.source_title != evidence.source_title
                or artifact.source_url != str(evidence.source_url)
                or artifact.sha256 != evidence.source_document_sha256
                or artifact.retrieved_at != evidence.retrieved_at
                or hashlib.sha256(artifact.content).hexdigest() != artifact.sha256
            ):
                raise ModelBrandSourceEvidenceMismatch(
                    "model-brand evidence does not match exact source artifact"
                )

    @staticmethod
    def _insert_case(
        connection: Connection,
        tenant: str,
        checked: ProcurementCase,
        *,
        allow_exact_replay: bool,
    ) -> None:
        payload = checked.model_dump(mode="json")
        statement = (
            postgresql_insert(case_versions)
            .values(
                company_id=tenant,
                case_id=checked.case_id,
                version=checked.version,
                payload=payload,
                input_sha256=case_input_digest(checked),
            )
            .on_conflict_do_nothing(
                index_elements=[
                    case_versions.c.company_id,
                    case_versions.c.case_id,
                    case_versions.c.version,
                ]
            )
            .returning(case_versions.c.payload)
        )
        inserted = connection.execute(statement).scalar_one_or_none()
        if inserted is None:
            stored = connection.execute(
                select(case_versions.c.payload).where(
                    and_(
                        case_versions.c.company_id == tenant,
                        case_versions.c.case_id == checked.case_id,
                        case_versions.c.version == checked.version,
                    )
                )
            ).scalar_one_or_none()
            if stored != payload or not allow_exact_replay:
                raise CaseVersionConflict(
                    f"case {checked.case_id!r} version {checked.version} already exists"
                )

    @staticmethod
    def _lock_idempotency(
        connection: Connection,
        tenant: str,
        operation: str,
        idempotency_key: str,
    ) -> None:
        if not idempotency_key:
            raise ValueError("idempotency_key must not be empty")
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": (f"{len(tenant)}:{tenant}{len(operation)}:{operation}{idempotency_key}")},
        )

    @staticmethod
    def _existing_receipt(
        connection: Connection,
        tenant: str,
        operation: str,
        idempotency_key: str,
        request_sha256: str,
    ) -> dict[str, Any] | None:
        row = (
            connection.execute(
                select(write_receipts.c.request_sha256, write_receipts.c.response).where(
                    and_(
                        write_receipts.c.company_id == tenant,
                        write_receipts.c.operation == operation,
                        write_receipts.c.idempotency_key == idempotency_key,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        if row["request_sha256"] != request_sha256:
            raise IdempotencyConflict(
                f"idempotency key {idempotency_key!r} was already used for another request"
            )
        return dict(row["response"])

    @staticmethod
    def _insert_receipt(
        connection: Connection,
        *,
        tenant: str,
        operation: str,
        idempotency_key: str,
        request_sha256: str,
        response: dict[str, Any],
    ) -> None:
        connection.execute(
            insert(write_receipts).values(
                company_id=tenant,
                operation=operation,
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
                response=response,
            )
        )

    def save_case(
        self,
        company_id: str,
        case: ProcurementCase,
        *,
        idempotency_key: str | None = None,
        request_sha256: str | None = None,
    ) -> ProcurementCase:
        """Insert an immutable version, with exact replay treated as idempotent."""
        tenant = _require_tenant(company_id)
        checked = ProcurementCase.model_validate(case.model_dump(mode="python"))
        if checked.company_id != tenant:
            raise ValueError("case company_id does not match repository tenant")
        if (idempotency_key is None) != (request_sha256 is None):
            raise ValueError("idempotency_key and request_sha256 must be supplied together")
        if request_sha256 is not None:
            _require_sha256(request_sha256, field="request_sha256")
        with self.transaction(tenant) as connection:
            if idempotency_key is not None and request_sha256 is not None:
                self._lock_idempotency(connection, tenant, "save_case", idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, "save_case", idempotency_key, request_sha256
                )
                if replay is not None:
                    identity = (replay.get("case_id"), replay.get("version"))
                    if identity != (checked.case_id, checked.version):
                        raise StorageError("stored save_case receipt has an invalid response")
                    return checked
            self._insert_case(
                connection,
                tenant,
                checked,
                allow_exact_replay=idempotency_key is None,
            )
            if idempotency_key is not None and request_sha256 is not None:
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation="save_case",
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"case_id": checked.case_id, "version": checked.version},
                )
        return checked

    def store_document(
        self,
        company_id: str,
        actor_id: str,
        original_filename: str,
        media_type: str,
        document_role: DocumentRole,
        content: bytes,
        extraction: ExtractionResult | dict[str, Any],
        idempotency_key: str,
        request_sha256: str,
        *,
        document_id: str | None = None,
    ) -> DocumentRecord:
        """Atomically store source bytes, extraction, audit fact, and replay receipt."""
        tenant = _require_tenant(company_id)
        if not actor_id.strip():
            raise ValueError("actor_id must not be empty")
        if not original_filename.strip():
            raise ValueError("original_filename must not be empty")
        if not media_type.strip():
            raise ValueError("media_type must not be empty")
        if not isinstance(document_role, DocumentRole):
            raise TypeError("document_role must be DocumentRole")
        raw_content = bytes(content)
        if not raw_content:
            raise ValueError("document content must not be empty")
        if len(raw_content) > MAX_DOCUMENT_BYTES:
            raise ValueError(f"document content exceeds {MAX_DOCUMENT_BYTES} bytes")
        _require_sha256(request_sha256, field="request_sha256")
        try:
            checked_extraction = ExtractionResult.model_validate(extraction)
            normalized_extraction = checked_extraction.model_dump(mode="json")
        except (TypeError, ValueError) as error:
            raise ValueError("extraction must match the typed extraction schema") from error

        chosen_id = document_id or str(uuid.uuid4())
        if not chosen_id.strip():
            raise ValueError("document_id must not be empty")
        content_sha256 = hashlib.sha256(raw_content).hexdigest()
        created_at = datetime.now(UTC)
        candidate = DocumentRecord(
            company_id=tenant,
            document_id=chosen_id,
            original_filename=original_filename,
            media_type=media_type,
            document_role=document_role,
            byte_size=len(raw_content),
            sha256=content_sha256,
            content=raw_content,
            extraction=checked_extraction,
            created_at=created_at,
        )
        extraction_sha256 = hashlib.sha256(
            json.dumps(
                normalized_extraction,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

        try:
            with self.transaction(tenant) as connection:
                self._lock_idempotency(
                    connection,
                    tenant,
                    "store_document",
                    idempotency_key,
                )
                replay = self._existing_receipt(
                    connection,
                    tenant,
                    "store_document",
                    idempotency_key,
                    request_sha256,
                )
                if replay is not None:
                    replay_id = replay.get("document_id")
                    row = (
                        connection.execute(
                            select(documents).where(
                                and_(
                                    documents.c.company_id == tenant,
                                    documents.c.document_id == replay_id,
                                )
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if row is None:
                        raise StorageError("stored document receipt points to a missing record")
                    return DocumentRecord.model_validate(dict(row))

                row = (
                    connection.execute(
                        insert(documents)
                        .values(
                            **(
                                candidate.model_dump(mode="python", exclude={"extraction"})
                                | {"extraction": normalized_extraction}
                            )
                        )
                        .returning(documents)
                    )
                    .mappings()
                    .one()
                )
                event = AuditEventRecord(
                    event_id=str(uuid.uuid4()),
                    company_id=tenant,
                    actor_id=actor_id,
                    event_type="document.stored",
                    object_type="source_document",
                    object_id=chosen_id,
                    basis={
                        "original_filename": original_filename,
                        "media_type": media_type,
                        "document_role": document_role.value,
                        "byte_size": len(raw_content),
                        "sha256": content_sha256,
                        "extraction_sha256": extraction_sha256,
                    },
                    occurred_at=created_at,
                )
                connection.execute(insert(audit_events).values(**event.model_dump(mode="python")))
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation="store_document",
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"document_id": chosen_id},
                )
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise DocumentConflict(
                    f"document {chosen_id!r} already exists for tenant"
                ) from error
            raise
        return DocumentRecord.model_validate(dict(row))

    def get_document(self, company_id: str, document_id: str) -> DocumentRecord | None:
        """Load one visible immutable document, including its original bytes."""
        tenant = _require_tenant(company_id)
        if not document_id:
            raise ValueError("document_id must not be empty")
        with self.transaction(tenant) as connection:
            row = (
                connection.execute(
                    select(documents).where(
                        and_(
                            documents.c.company_id == tenant,
                            documents.c.document_id == document_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else DocumentRecord.model_validate(dict(row))

    @staticmethod
    def _load_completeness_review_snapshot(
        connection: Connection,
        tenant: str,
        review_id: str,
    ) -> CompletenessReviewSnapshot:
        row = (
            connection.execute(
                select(document_completeness_reviews).where(
                    and_(
                        document_completeness_reviews.c.company_id == tenant,
                        document_completeness_reviews.c.review_id == review_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise CompletenessReviewNotFound("completeness review was not found")
        try:
            snapshot = CompletenessReviewSnapshot.model_validate_json(
                json.dumps(row["snapshot"], ensure_ascii=False)
            )
        except (TypeError, ValueError) as error:
            raise CompletenessReviewSourceMismatch(
                "stored completeness review snapshot is invalid"
            ) from error
        if (
            row["company_id"] != tenant
            or row["review_id"] != snapshot.review_id
            or row["source_document_id"] != snapshot.source_document_id
            or row["source_document_sha256"] != snapshot.source_document_sha256
            or row["evidence_sha256"] != snapshot.evidence_sha256
        ):
            raise CompletenessReviewSourceMismatch(
                "stored completeness review columns do not match snapshot"
            )
        return snapshot

    @staticmethod
    def _load_completeness_review(
        connection: Connection,
        tenant: str,
        review_id: str,
    ) -> CompletenessReviewRecord:
        row = (
            connection.execute(
                select(
                    document_completeness_reviews.c.snapshot,
                    document_completeness_review_decisions.c.decision,
                )
                .select_from(
                    document_completeness_reviews.outerjoin(
                        document_completeness_review_decisions,
                        and_(
                            document_completeness_review_decisions.c.company_id
                            == document_completeness_reviews.c.company_id,
                            document_completeness_review_decisions.c.review_id
                            == document_completeness_reviews.c.review_id,
                        ),
                    )
                )
                .where(
                    and_(
                        document_completeness_reviews.c.company_id == tenant,
                        document_completeness_reviews.c.review_id == review_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise CompletenessReviewNotFound("completeness review was not found")
        return CompletenessReviewRecord(
            # Pydantic's JSON validation mode restores Decimal values in the
            # RequirementValue union from their lossless JSON strings. Python
            # dict validation would prefer the exact ``str`` union branch and
            # then reject numeric operators after a PostgreSQL JSONB roundtrip.
            snapshot=CompletenessReviewSnapshot.model_validate_json(
                json.dumps(row["snapshot"], ensure_ascii=False)
            ),
            decision=(
                None
                if row["decision"] is None
                else CompletenessReviewDecision.model_validate_json(
                    json.dumps(row["decision"], ensure_ascii=False)
                )
            ),
        )

    @staticmethod
    def _verify_completeness_source_bytes(
        connection: Connection,
        tenant: str,
        snapshot: CompletenessReviewSnapshot,
    ) -> None:
        source_row = (
            connection.execute(
                select(documents).where(
                    and_(
                        documents.c.company_id == tenant,
                        documents.c.document_id == snapshot.source_document_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if source_row is None:
            raise CompletenessReviewSourceMismatch("review source is unavailable")
        source = DocumentRecord.model_validate(dict(source_row))
        if (
            source.sha256 != snapshot.source_document_sha256
            or hashlib.sha256(source.content).hexdigest() != snapshot.source_document_sha256
            or len(source.content) != source.byte_size
            or source.document_role is not snapshot.mapping.document_role
            or source.extraction != snapshot.extraction
        ):
            raise CompletenessReviewSourceMismatch("review source evidence changed")

    def store_completeness_review(
        self,
        company_id: str,
        actor_id: str,
        source_document_id: str,
        idempotency_key: str,
        request_sha256: str,
        *,
        review_id: str | None = None,
    ) -> CompletenessReviewRecord:
        """Derive and persist a review snapshot from exact stored bytes/extraction."""
        tenant = _require_tenant(company_id)
        _require_sha256(request_sha256, field="request_sha256")
        if not actor_id.strip() or not source_document_id.strip():
            raise ValueError("actor_id and source_document_id must not be blank")
        chosen_id = review_id or str(uuid.uuid4())
        now = datetime.now(UTC)
        try:
            with self.transaction(tenant) as connection:
                operation = "store_document_completeness_review"
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, operation, idempotency_key, request_sha256
                )
                if replay is not None:
                    original = self._load_completeness_review(
                        connection, tenant, str(replay["review_id"])
                    )
                    # Creation originally returned a DRAFT. A later decision
                    # must not change the body of an exact replay of that
                    # earlier idempotent operation.
                    return CompletenessReviewRecord(snapshot=original.snapshot)
                source_row = (
                    connection.execute(
                        select(documents).where(
                            and_(
                                documents.c.company_id == tenant,
                                documents.c.document_id == source_document_id,
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if source_row is None:
                    raise CompletenessReviewNotFound("source document was not found")
                source = DocumentRecord.model_validate(dict(source_row))
                if (
                    hashlib.sha256(source.content).hexdigest() != source.sha256
                    or len(source.content) != source.byte_size
                ):
                    raise CompletenessReviewSourceMismatch("stored document bytes are invalid")
                try:
                    snapshot = build_completeness_review_snapshot(
                        company_id=tenant,
                        review_id=chosen_id,
                        source_document_id=source.document_id,
                        source_document_sha256=source.sha256,
                        document_role=source.document_role,
                        extraction=source.extraction,
                        created_by=actor_id,
                        created_at=now,
                    )
                except CompletenessReviewSourceInvalid as error:
                    raise CompletenessReviewSourceMismatch from error
                connection.execute(
                    insert(document_completeness_reviews).values(
                        company_id=tenant,
                        review_id=chosen_id,
                        source_document_id=source.document_id,
                        source_document_sha256=source.sha256,
                        evidence_sha256=snapshot.evidence_sha256,
                        snapshot=snapshot.model_dump(mode="json"),
                        created_at=now,
                    )
                )
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=actor_id,
                            event_type="document.completeness_review_created",
                            object_type="document_completeness_review",
                            object_id=chosen_id,
                            basis={
                                "source_document_id": source.document_id,
                                "source_document_sha256": source.sha256,
                                "evidence_sha256": snapshot.evidence_sha256,
                            },
                            occurred_at=now,
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"review_id": chosen_id},
                )
                return CompletenessReviewRecord(snapshot=snapshot)
        except (CompletenessReviewNotFound, CompletenessReviewSourceMismatch):
            raise
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise CompletenessReviewConflict("completeness review conflicts") from error
            raise

    @staticmethod
    def _ai_transfer_source(
        connection: Connection, tenant: str, document_id: str
    ) -> DocumentRecord:
        condition = and_(documents.c.company_id == tenant, documents.c.document_id == document_id)
        size = connection.execute(
            select(func.octet_length(cast(documents.c.extraction, Text))).where(condition)
        ).scalar_one_or_none()
        if size is None:
            raise AiTransferNotFound("AI transfer source was not found")
        if size > MAX_AI_TRANSFER_EVIDENCE_BYTES:
            raise AiTransferSourceMismatch("AI transfer source exceeds evidence limit")
        row = connection.execute(select(documents).where(condition)).mappings().one()
        try:
            source = DocumentRecord.model_validate(dict(row))
            if (
                source.company_id != tenant
                or source.document_id != document_id
                or source.document_role is not DocumentRole.TENDER_REQUIREMENTS
                or hashlib.sha256(source.content).hexdigest() != source.sha256
                or len(source.content) != source.byte_size
            ):
                raise ValueError("AI transfer source identity differs")
            return source
        except (TypeError, ValueError) as error:
            raise AiTransferSourceMismatch("AI transfer source is invalid") from error

    @staticmethod
    def _load_ai_transfer(
        connection: Connection, tenant: str, transfer_id: str
    ) -> tuple[PersistedAiTransferRequest, PersistedAiTransferApproval | None]:
        condition = and_(
            ai_transfer_requests.c.company_id == tenant,
            ai_transfer_requests.c.transfer_id == transfer_id,
        )
        size = connection.execute(
            select(func.octet_length(cast(ai_transfer_requests.c.request, Text))).where(condition)
        ).scalar_one_or_none()
        if size is None:
            raise AiTransferNotFound("AI transfer request was not found")
        if size > MAX_AI_TRANSFER_EVIDENCE_BYTES:
            raise AiTransferSourceMismatch("AI transfer request exceeds evidence limit")
        chunk_condition = and_(
            ai_transfer_chunks.c.company_id == tenant,
            ai_transfer_chunks.c.transfer_id == transfer_id,
        )
        chunk_size = connection.execute(
            select(
                func.sum(
                    func.octet_length(cast(ai_transfer_chunks.c.chunk, Text))
                    + func.octet_length(ai_transfer_chunks.c.request_body_json)
                )
            ).where(chunk_condition)
        ).scalar_one()
        if chunk_size is None or chunk_size > 2 * MAX_AI_TRANSFER_EVIDENCE_BYTES:
            raise AiTransferSourceMismatch("AI transfer chunks exceed evidence limit")
        row = connection.execute(select(ai_transfer_requests).where(condition)).mappings().one()
        try:
            request = PersistedAiTransferRequest.model_validate_json(json.dumps(row["request"]))
            if (
                request.company_id != tenant
                or request.transfer_id != transfer_id
                or request.source_document_id != row["source_document_id"]
                or request.source_sha256 != row["source_sha256"]
                or request.payload_sha256 != row["payload_sha256"]
                or request.prepared_by != row["prepared_by"]
                or request.prepared_at != row["created_at"]
                or len(request.chunks) != row["chunk_count"]
            ):
                raise ValueError("AI transfer row identity differs")
            chunks = (
                connection.execute(
                    select(ai_transfer_chunks)
                    .where(chunk_condition)
                    .order_by(ai_transfer_chunks.c.ordinal)
                )
                .mappings()
                .all()
            )
            if len(chunks) != len(request.chunks):
                raise ValueError("AI transfer chunk count differs")
            for ordinal, (stored, chunk) in enumerate(zip(chunks, request.chunks, strict=True), 1):
                if (
                    stored["ordinal"] != ordinal
                    or stored["chunk_id"] != chunk.chunk_id
                    or stored["payload_sha256"] != request.payload_sha256
                    or stored["request_body_json"] != chunk.request_body_json
                    or stored["request_sha256"] != chunk.request_sha256
                    or stored["chunk"] != chunk.model_dump(mode="json")
                ):
                    raise ValueError("AI transfer chunk projection differs")
            source = PostgresStorage._ai_transfer_source(
                connection, tenant, request.source_document_id
            )
            rebuilt = build_persisted_ai_transfer_request(
                prepare_ai_requirements_transfer(
                    source.extraction,
                    company_id=tenant,
                    source_document_id=source.document_id,
                    source_sha256=source.sha256,
                    model=request.model_profile.model,
                    max_chunk_characters=request.max_chunk_characters,
                ),
                transfer_id=transfer_id,
                prepared_by=request.prepared_by,
                prepared_at=request.prepared_at,
            )
            if rebuilt != request:
                raise ValueError("AI transfer request differs from persisted source")
            approval_condition = and_(
                ai_transfer_approvals.c.company_id == tenant,
                ai_transfer_approvals.c.transfer_id == transfer_id,
            )
            approval_size = connection.execute(
                select(func.octet_length(cast(ai_transfer_approvals.c.approval, Text))).where(
                    approval_condition
                )
            ).scalar_one_or_none()
            if approval_size is not None and approval_size > 16 * 1024:
                raise ValueError("AI transfer approval exceeds evidence limit")
            approval_row = (
                connection.execute(select(ai_transfer_approvals).where(approval_condition))
                .mappings()
                .one_or_none()
            )
            approval = None
            if approval_row is not None:
                approval = PersistedAiTransferApproval.model_validate_json(
                    json.dumps(approval_row["approval"])
                )
                expected = build_persisted_ai_transfer_approval(
                    request, approved_by=approval.approved_by, approved_at=approval.approved_at
                )
                if (
                    approval != expected
                    or approval.request_payload_sha256 != approval_row["request_payload_sha256"]
                    or approval.approved_by != approval_row["approved_by"]
                    or approval.approved_at != approval_row["approved_at"]
                    or approval.expires_at != approval_row["expires_at"]
                ):
                    raise ValueError("AI transfer approval projection differs")
            return request, approval
        except (TypeError, ValueError, AiRequirementError, AiTransferNotFound) as error:
            raise AiTransferSourceMismatch("AI transfer evidence is invalid") from error

    @staticmethod
    def _ai_transfer_audit(
        connection: Connection,
        request: PersistedAiTransferRequest,
        actor_id: str,
        event_type: str,
        occurred_at: datetime,
    ) -> None:
        connection.execute(
            insert(audit_events).values(
                **AuditEventRecord(
                    event_id=str(uuid.uuid4()),
                    company_id=request.company_id,
                    actor_id=actor_id,
                    event_type=event_type,
                    object_type="ai_transfer_request",
                    object_id=request.transfer_id,
                    basis={
                        "request_payload_sha256": request.payload_sha256,
                        "source_document_id": request.source_document_id,
                        "source_sha256": request.source_sha256,
                    },
                    occurred_at=occurred_at,
                ).model_dump(mode="python")
            )
        )

    @staticmethod
    def _load_ai_transfer_execution(
        connection: Connection,
        tenant: str,
        execution_id: str,
    ) -> tuple[
        AiTransferExecutionAdmission,
        AiTransferDispatchClaim | None,
        AiTransferDispatchReceipt | None,
    ]:
        condition = and_(
            ai_transfer_execution_admissions.c.company_id == tenant,
            ai_transfer_execution_admissions.c.execution_id == execution_id,
        )
        size = connection.execute(
            select(
                func.octet_length(cast(ai_transfer_execution_admissions.c.admission, Text))
            ).where(condition)
        ).scalar_one_or_none()
        if size is None:
            raise AiTransferNotFound("AI transfer execution was not found")
        if size > 16 * 1024:
            raise AiTransferSourceMismatch("AI transfer execution exceeds evidence limit")
        row = (
            connection.execute(select(ai_transfer_execution_admissions).where(condition))
            .mappings()
            .one()
        )
        try:
            request, approval = PostgresStorage._load_ai_transfer(
                connection, tenant, str(row["transfer_id"])
            )
            if approval is None:
                raise ValueError("AI transfer execution approval is absent")
            admission = AiTransferExecutionAdmission.model_validate_json(
                json.dumps(row["admission"])
            )
            rebuilt = build_ai_transfer_execution_admission(
                request,
                approval,
                company_id=tenant,
                transfer_id=request.transfer_id,
                execution_id=str(row["execution_id"]),
                admitted_by=str(row["admitted_by"]),
                # The event digest binds the exact JSON timestamp spelling. A
                # timestamptz column can return the same instant in another
                # session timezone, so rebuild from the persisted event and
                # compare the SQL projection separately below.
                admitted_at=admission.admitted_at,
                existing_admission=None,
            )
            if (
                admission != rebuilt
                or admission.company_id != tenant
                or admission.execution_id != row["execution_id"]
                or admission.transfer_id != row["transfer_id"]
                or admission.request_payload_sha256 != row["request_payload_sha256"]
                or admission.approved_by != row["approved_by"]
                or admission.approved_at != row["approved_at"]
                or admission.approval_expires_at != row["approval_expires_at"]
                or admission.chunk_count != row["chunk_count"]
                or admission.payload_sha256 != row["payload_sha256"]
                or admission.admitted_by != row["admitted_by"]
                or admission.admitted_at != row["admitted_at"]
            ):
                raise ValueError("AI transfer execution projection differs")
            claims, receipts = PostgresStorage._load_ai_transfer_dispatch_history(
                connection,
                tenant,
                execution_id,
                request=request,
                approval=approval,
                admission=admission,
            )
            return (
                admission,
                claims[-1] if claims else None,
                receipts[-1] if claims and len(receipts) == len(claims) else None,
            )
        except (TypeError, ValueError, AiTransferNotFound) as error:
            raise AiTransferSourceMismatch("AI transfer execution evidence is invalid") from error

    @staticmethod
    def _load_ai_transfer_dispatch_history(
        connection: Connection,
        tenant: str,
        execution_id: str,
        *,
        request: PersistedAiTransferRequest,
        approval: PersistedAiTransferApproval,
        admission: AiTransferExecutionAdmission,
    ) -> tuple[tuple[AiTransferDispatchClaim, ...], tuple[AiTransferDispatchReceipt, ...]]:
        claim_rows = (
            connection.execute(
                select(ai_transfer_dispatch_claims)
                .where(
                    and_(
                        ai_transfer_dispatch_claims.c.company_id == tenant,
                        ai_transfer_dispatch_claims.c.execution_id == execution_id,
                    )
                )
                .order_by(ai_transfer_dispatch_claims.c.ordinal)
            )
            .mappings()
            .all()
        )
        receipt_rows = (
            connection.execute(
                select(ai_transfer_dispatch_receipts)
                .where(
                    and_(
                        ai_transfer_dispatch_receipts.c.company_id == tenant,
                        ai_transfer_dispatch_receipts.c.execution_id == execution_id,
                    )
                )
                .order_by(ai_transfer_dispatch_receipts.c.ordinal)
            )
            .mappings()
            .all()
        )
        receipt_rows_by_ordinal = {int(row["ordinal"]): row for row in receipt_rows}
        if len(receipt_rows_by_ordinal) != len(receipt_rows):
            raise ValueError("AI transfer dispatch receipt ordinals are not unique")
        claims: list[AiTransferDispatchClaim] = []
        receipts: list[AiTransferDispatchReceipt] = []
        for claim_row in claim_rows:
            if len(json.dumps(claim_row["claim"]).encode("utf-8")) > 16 * 1024:
                raise ValueError("AI transfer dispatch claim exceeds evidence limit")
            claim = AiTransferDispatchClaim.model_validate_json(json.dumps(claim_row["claim"]))
            rebuilt_claim = build_ai_transfer_dispatch_claim(
                request,
                approval,
                admission,
                claim_id=str(claim_row["claim_id"]),
                claimed_by=str(claim_row["claimed_by"]),
                claimed_at=claim.claimed_at,
                existing_claims=tuple(claims),
                existing_receipts=tuple(receipts),
            )
            if claim != rebuilt_claim or any(
                (
                    claim.company_id != tenant,
                    claim.execution_id != execution_id,
                    claim.claim_id != claim_row["claim_id"],
                    claim.transfer_id != claim_row["transfer_id"],
                    claim.request_payload_sha256 != claim_row["request_payload_sha256"],
                    claim.admission_payload_sha256 != claim_row["admission_payload_sha256"],
                    claim.ordinal != claim_row["ordinal"],
                    claim.chunk_id != claim_row["chunk_id"],
                    claim.request_sha256 != claim_row["request_sha256"],
                    claim.attempt != claim_row["attempt"],
                    claim.claim_status != claim_row["claim_status"],
                    claim.delivery_state != claim_row["delivery_state"],
                    claim.claimed_by != claim_row["claimed_by"],
                    claim.claimed_at != claim_row["claimed_at"],
                    claim.payload_sha256 != claim_row["payload_sha256"],
                )
            ):
                raise ValueError("AI transfer dispatch claim projection differs")
            claims.append(claim)
            receipt_row = receipt_rows_by_ordinal.get(claim.ordinal)
            if receipt_row is None:
                if claim.ordinal != len(claim_rows):
                    raise ValueError("non-terminal AI transfer claim is not last")
                continue
            if len(json.dumps(receipt_row["receipt"]).encode("utf-8")) > 16 * 1024:
                raise ValueError("AI transfer dispatch receipt exceeds evidence limit")
            receipt = AiTransferDispatchReceipt.model_validate_json(
                json.dumps(receipt_row["receipt"])
            )
            rebuilt_receipt = build_ai_transfer_dispatch_receipt(
                claim,
                receipt_id=str(receipt_row["receipt_id"]),
                outcome=receipt_row["outcome"],
                reason=receipt_row["reason"],
                attempted=receipt_row["attempted"],
                request_sha256=str(receipt_row["request_sha256"]),
                http_status=receipt_row["http_status"],
                capture_complete=receipt_row["capture_complete"],
                captured_byte_count=receipt_row["captured_byte_count"],
                response_body_sha256=receipt_row["response_body_sha256"],
                provider_response_id=receipt_row["provider_response_id"],
                provider_model=receipt_row["provider_model"],
                assistant_content_sha256=receipt_row["assistant_content_sha256"],
                assistant_content_byte_count=receipt_row["assistant_content_byte_count"],
                # Rebuild the content-addressed event from its exact JSON timestamp
                # representation. PostgreSQL may return the same timestamptz instant
                # in the session timezone, which is semantically equal but hashes to
                # a different ISO-8601 string.
                started_at=receipt.started_at,
                finished_at=receipt.finished_at,
                recorded_by=str(receipt_row["recorded_by"]),
                recorded_at=receipt.recorded_at,
            )
            receipt_projection = {
                "company_id": tenant,
                "transfer_id": receipt_row["transfer_id"],
                "execution_id": execution_id,
                "ordinal": receipt_row["ordinal"],
                "claim_id": receipt_row["claim_id"],
                "chunk_id": receipt_row["chunk_id"],
                "claim_payload_sha256": receipt_row["claim_payload_sha256"],
                "receipt_id": receipt_row["receipt_id"],
                "outcome": receipt_row["outcome"],
                "reason": receipt_row["reason"],
                "attempted": receipt_row["attempted"],
                "request_sha256": receipt_row["request_sha256"],
                "http_status": receipt_row["http_status"],
                "capture_complete": receipt_row["capture_complete"],
                "captured_byte_count": receipt_row["captured_byte_count"],
                "response_body_sha256": receipt_row["response_body_sha256"],
                "provider_response_id": receipt_row["provider_response_id"],
                "provider_model": receipt_row["provider_model"],
                "assistant_content_sha256": receipt_row["assistant_content_sha256"],
                "assistant_content_byte_count": receipt_row["assistant_content_byte_count"],
                "validator_version": receipt_row["validator_version"],
                "started_at": receipt_row["started_at"],
                "finished_at": receipt_row["finished_at"],
                "status": receipt_row["status"],
                "recorded_by": receipt_row["recorded_by"],
                "recorded_at": receipt_row["recorded_at"],
                "payload_sha256": receipt_row["payload_sha256"],
            }
            persisted_differences = tuple(
                field
                for field, expected in receipt_projection.items()
                if getattr(receipt, field) != expected
            )
            rebuilt_differences = tuple(
                field
                for field in type(receipt).model_fields
                if getattr(receipt, field) != getattr(rebuilt_receipt, field)
            )
            if persisted_differences or rebuilt_differences:
                raise ValueError(
                    "AI transfer dispatch receipt projection differs: "
                    f"persisted={persisted_differences}, rebuilt={rebuilt_differences}"
                )
            receipts.append(receipt)
        if set(receipt_rows_by_ordinal) - {claim.ordinal for claim in claims}:
            raise ValueError("AI transfer dispatch receipt lacks its claim")
        return tuple(claims), tuple(receipts)

    @staticmethod
    def _load_ai_transfer_raw_envelope(
        connection: Connection,
        tenant: str,
        raw_response_id: str,
    ) -> tuple[AiTransferRawMetadata, AiTransferRawEnvelope]:
        condition = and_(
            ai_transfer_raw_responses.c.company_id == tenant,
            ai_transfer_raw_responses.c.raw_response_id == raw_response_id,
        )
        statement = select(ai_transfer_raw_responses).where(condition)
        metadata_row = connection.execute(statement).mappings().one_or_none()
        if metadata_row is None:
            raise AiTransferNotFound("AI transfer raw response was not found")
        deletion_exists = connection.execute(
            select(ai_transfer_raw_response_deletion_receipts.c.raw_response_id).where(
                and_(
                    ai_transfer_raw_response_deletion_receipts.c.company_id == tenant,
                    ai_transfer_raw_response_deletion_receipts.c.raw_response_id == raw_response_id,
                )
            )
        ).scalar_one_or_none()
        blob_row = (
            connection.execute(
                select(ai_transfer_raw_response_blobs).where(
                    and_(
                        ai_transfer_raw_response_blobs.c.company_id == tenant,
                        ai_transfer_raw_response_blobs.c.raw_response_id == raw_response_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if deletion_exists is not None or blob_row is None:
            raise AiTransferNotFound("AI transfer raw response is no longer available")
        try:
            metadata = PostgresStorage._validated_ai_transfer_raw_metadata(metadata_row)
            envelope = AiTransferRawEnvelope(
                metadata=metadata,
                raw_response_id=str(blob_row["raw_response_id"]),
                algorithm=blob_row["algorithm"],
                key_id=str(blob_row["key_id"]),
                body_nonce=bytes(blob_row["body_nonce"]),
                ciphertext=bytes(blob_row["ciphertext"]),
                wrapping_nonce=bytes(blob_row["wrapping_nonce"]),
                wrapped_dek=bytes(blob_row["wrapped_dek"]),
                wrap_aad_sha256=str(blob_row["wrap_aad_sha256"]),
                envelope_sha256=str(blob_row["envelope_sha256"]),
            )
            blob_projection = {
                "receipt_id": metadata.receipt_id,
                "response_body_sha256": metadata.response_body_sha256,
                "response_byte_count": metadata.response_byte_count,
                "received_at": metadata.received_at,
                "expires_at": metadata.expires_at,
                "metadata_schema_version": metadata.schema_version,
                "schema_version": envelope.schema_version,
                "algorithm": metadata.algorithm,
                "key_id": metadata.key_id,
                "body_aad_sha256": metadata.body_aad_sha256,
                "metadata_sha256": metadata.metadata_sha256,
                "wrap_aad_sha256": envelope.wrap_aad_sha256,
                "envelope_sha256": envelope.envelope_sha256,
            }
            if any(blob_row[key] != value for key, value in blob_projection.items()):
                raise ValueError("raw response envelope projection differs")
            if (
                metadata_row["wrap_aad_sha256"] != envelope.wrap_aad_sha256
                or metadata_row["envelope_sha256"] != envelope.envelope_sha256
                or metadata_row["capture_complete"] is not True
            ):
                raise ValueError("raw response storage binding differs")
            return metadata, envelope
        except (TypeError, ValueError) as error:
            raise AiTransferSourceMismatch("encrypted AI transfer evidence is invalid") from error

    @staticmethod
    def _validated_ai_transfer_raw_metadata(
        metadata_row: RowMapping,
    ) -> AiTransferRawMetadata:
        try:
            metadata = AiTransferRawMetadata.model_validate_json(
                json.dumps(metadata_row["metadata"])
            )
            projection = {
                "company_id": metadata.company_id,
                "raw_response_id": metadata.raw_response_id,
                "transfer_id": metadata.transfer_id,
                "execution_id": metadata.execution_id,
                "ordinal": metadata.ordinal,
                "claim_id": metadata.claim_id,
                "chunk_id": metadata.chunk_id,
                "claim_payload_sha256": metadata.claim_payload_sha256,
                "receipt_id": metadata.receipt_id,
                "receipt_payload_sha256": metadata.receipt_payload_sha256,
                "request_sha256": metadata.request_sha256,
                "response_body_sha256": metadata.response_body_sha256,
                "response_byte_count": metadata.response_byte_count,
                "received_at": metadata.received_at,
                "expires_at": metadata.expires_at,
                "schema_version": metadata.schema_version,
                "algorithm": metadata.algorithm,
                "key_id": metadata.key_id,
                "body_aad_sha256": metadata.body_aad_sha256,
                "metadata_sha256": metadata.metadata_sha256,
            }
            if any(metadata_row[key] != value for key, value in projection.items()):
                raise ValueError("raw response metadata projection differs")
            if metadata_row["capture_complete"] is not True:
                raise ValueError("raw response metadata storage binding differs")
            return metadata
        except (KeyError, TypeError, ValueError) as error:
            raise AiTransferSourceMismatch("encrypted AI transfer metadata is invalid") from error

    @staticmethod
    def _ai_transfer_execution_audit(
        connection: Connection,
        *,
        company_id: str,
        actor_id: str,
        event_type: str,
        execution_id: str,
        transfer_id: str,
        request_payload_sha256: str,
        occurred_at: datetime,
        claim_id: str | None = None,
        receipt_id: str | None = None,
        receipt_payload_sha256: str | None = None,
        dispatch_outcome: str | None = None,
    ) -> None:
        basis: dict[str, Any] = {
            "transfer_id": transfer_id,
            "request_payload_sha256": request_payload_sha256,
        }
        if claim_id is not None:
            basis["claim_id"] = claim_id
        if receipt_id is not None:
            basis["receipt_id"] = receipt_id
        if receipt_payload_sha256 is not None:
            basis["receipt_payload_sha256"] = receipt_payload_sha256
        if dispatch_outcome is not None:
            basis["dispatch_outcome"] = dispatch_outcome
        connection.execute(
            insert(audit_events).values(
                **AuditEventRecord(
                    event_id=str(uuid.uuid4()),
                    company_id=company_id,
                    actor_id=actor_id,
                    event_type=event_type,
                    object_type="ai_transfer_execution",
                    object_id=execution_id,
                    basis=basis,
                    occurred_at=occurred_at,
                ).model_dump(mode="python")
            )
        )

    @staticmethod
    def _insert_ai_transfer_dispatch_receipt(
        connection: Connection,
        receipt: AiTransferDispatchReceipt,
    ) -> None:
        connection.execute(
            insert(ai_transfer_dispatch_receipts).values(
                company_id=receipt.company_id,
                transfer_id=receipt.transfer_id,
                execution_id=receipt.execution_id,
                ordinal=receipt.ordinal,
                claim_id=receipt.claim_id,
                chunk_id=receipt.chunk_id,
                claim_payload_sha256=receipt.claim_payload_sha256,
                receipt_id=receipt.receipt_id,
                outcome=receipt.outcome,
                reason=receipt.reason,
                attempted=receipt.attempted,
                request_sha256=receipt.request_sha256,
                http_status=receipt.http_status,
                capture_complete=receipt.capture_complete,
                captured_byte_count=receipt.captured_byte_count,
                response_body_sha256=receipt.response_body_sha256,
                provider_response_id=receipt.provider_response_id,
                provider_model=receipt.provider_model,
                assistant_content_sha256=receipt.assistant_content_sha256,
                assistant_content_byte_count=receipt.assistant_content_byte_count,
                validator_version=receipt.validator_version,
                started_at=receipt.started_at,
                finished_at=receipt.finished_at,
                status=receipt.status,
                receipt=receipt.model_dump(mode="json"),
                recorded_by=receipt.recorded_by,
                recorded_at=receipt.recorded_at,
                payload_sha256=receipt.payload_sha256,
            )
        )

    def store_ai_transfer_request(
        self,
        company_id: str,
        actor_id: str,
        source_document_id: str,
        model: str,
        idempotency_key: str,
        request_sha256: str,
    ) -> PersistedAiTransferRequest:
        """Prepare exact persisted source bytes for human approval; never send them."""
        tenant = _require_tenant(company_id)
        _require_sha256(request_sha256, field="request_sha256")
        if not actor_id.strip() or actor_id != actor_id.strip():
            raise AiTransferSourceMismatch("AI transfer actor is invalid")
        try:
            with self.transaction(tenant) as connection:
                operation = "store_ai_transfer_request"
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, operation, idempotency_key, request_sha256
                )
                if replay is not None:
                    existing, _ = self._load_ai_transfer(
                        connection, tenant, str(replay["transfer_id"])
                    )
                    if (
                        existing.prepared_by != actor_id
                        or existing.source_document_id != source_document_id
                        or existing.model_profile.model != model
                    ):
                        raise AiTransferConflict("AI transfer replay differs")
                    return existing
                source = self._ai_transfer_source(connection, tenant, source_document_id)
                try:
                    request = build_persisted_ai_transfer_request(
                        prepare_ai_requirements_transfer(
                            source.extraction,
                            company_id=tenant,
                            source_document_id=source_document_id,
                            source_sha256=source.sha256,
                            model=model,
                        ),
                        transfer_id=str(uuid.uuid4()),
                        prepared_by=actor_id,
                        prepared_at=datetime.now(UTC),
                    )
                except (ValueError, AiRequirementError) as error:
                    raise AiTransferSourceMismatch("AI transfer source is not eligible") from error
                if len(request.model_dump_json().encode("utf-8")) > MAX_AI_TRANSFER_EVIDENCE_BYTES:
                    raise AiTransferSourceMismatch("AI transfer request exceeds evidence limit")
                connection.execute(
                    insert(ai_transfer_requests).values(
                        company_id=tenant,
                        transfer_id=request.transfer_id,
                        source_document_id=source_document_id,
                        source_sha256=source.sha256,
                        payload_sha256=request.payload_sha256,
                        chunk_count=len(request.chunks),
                        request=request.model_dump(mode="json"),
                        prepared_by=actor_id,
                        created_at=request.prepared_at,
                    )
                )
                connection.execute(
                    insert(ai_transfer_chunks),
                    [
                        {
                            "company_id": tenant,
                            "transfer_id": request.transfer_id,
                            "payload_sha256": request.payload_sha256,
                            "ordinal": ordinal,
                            "chunk_id": chunk.chunk_id,
                            "request_body_json": chunk.request_body_json,
                            "request_sha256": chunk.request_sha256,
                            "chunk": chunk.model_dump(mode="json"),
                        }
                        for ordinal, chunk in enumerate(request.chunks, 1)
                    ],
                )
                self._ai_transfer_audit(
                    connection,
                    request,
                    actor_id,
                    "document.ai_transfer_prepared",
                    request.prepared_at,
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"transfer_id": request.transfer_id},
                )
                return request
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise AiTransferConflict("AI transfer request conflicts") from error
            raise

    def get_ai_transfer_request(
        self, company_id: str, transfer_id: str
    ) -> tuple[PersistedAiTransferRequest, PersistedAiTransferApproval | None] | None:
        """Read one exact transfer after revalidating source and immutable projections."""
        tenant = _require_tenant(company_id)
        with self.transaction(tenant) as connection:
            try:
                return self._load_ai_transfer(connection, tenant, transfer_id)
            except AiTransferNotFound:
                return None

    def approve_ai_transfer_request(
        self,
        company_id: str,
        actor_id: str,
        transfer_id: str,
        request_payload_sha256: str,
        idempotency_key: str,
        request_sha256: str,
    ) -> PersistedAiTransferApproval:
        """Append one independent exact-digest approval and its receipt atomically."""
        tenant = _require_tenant(company_id)
        _require_sha256(request_sha256, field="request_sha256")
        try:
            with self.transaction(tenant) as connection:
                operation = "approve_ai_transfer_request"
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, operation, idempotency_key, request_sha256
                )
                request, approval = self._load_ai_transfer(connection, tenant, transfer_id)
                if request.payload_sha256 != request_payload_sha256:
                    raise AiTransferConflict("AI transfer approval digest is stale")
                if replay is not None:
                    if (
                        str(replay["transfer_id"]) != transfer_id
                        or approval is None
                        or approval.approved_by != actor_id
                    ):
                        raise AiTransferConflict("AI transfer approval replay differs")
                    return approval
                if approval is not None or actor_id.strip() == request.prepared_by:
                    raise AiTransferConflict("AI transfer approval must be independent and unique")
                try:
                    approval = build_persisted_ai_transfer_approval(
                        request, approved_by=actor_id, approved_at=datetime.now(UTC)
                    )
                except ValueError as error:
                    raise AiTransferConflict("AI transfer approval is invalid") from error
                connection.execute(
                    insert(ai_transfer_approvals).values(
                        company_id=tenant,
                        transfer_id=transfer_id,
                        request_payload_sha256=request_payload_sha256,
                        approval=approval.model_dump(mode="json"),
                        approved_by=approval.approved_by,
                        approved_at=approval.approved_at,
                        expires_at=approval.expires_at,
                    )
                )
                self._ai_transfer_audit(
                    connection,
                    request,
                    approval.approved_by,
                    "document.ai_transfer_approved",
                    approval.approved_at,
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"transfer_id": transfer_id},
                )
                return approval
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise AiTransferConflict("AI transfer approval conflicts") from error
            raise

    def admit_ai_transfer_execution(
        self,
        company_id: str,
        actor_id: str,
        transfer_id: str,
        request_payload_sha256: str,
        idempotency_key: str,
        request_sha256: str,
    ) -> AiTransferExecutionAdmission:
        """Atomically consume one current approval without dispatching any bytes."""
        tenant = _require_tenant(company_id)
        _require_sha256(request_sha256, field="request_sha256")
        if not actor_id.strip() or actor_id != actor_id.strip():
            raise AiTransferSourceMismatch("AI transfer execution actor is invalid")
        try:
            with self.transaction(tenant) as connection:
                operation = "admit_ai_transfer_execution"
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                    {"lock_key": f"ai-transfer-execution:{tenant}:{transfer_id}"},
                )
                request, approval = self._load_ai_transfer(connection, tenant, transfer_id)
                if approval is None:
                    raise AiTransferConflict("AI transfer execution approval is absent")
                if request.payload_sha256 != request_payload_sha256:
                    raise AiTransferConflict("AI transfer execution digest is stale")
                replay = self._existing_receipt(
                    connection, tenant, operation, idempotency_key, request_sha256
                )
                if replay is not None:
                    admission, _, _ = self._load_ai_transfer_execution(
                        connection, tenant, str(replay["execution_id"])
                    )
                    if (
                        admission.transfer_id != transfer_id
                        or admission.admitted_by != actor_id
                        or admission.request_payload_sha256 != request_payload_sha256
                    ):
                        raise AiTransferConflict("AI transfer execution replay differs")
                    return admission
                if actor_id != request.prepared_by:
                    raise AiTransferConflict("only the transfer preparer may admit execution")
                existing_execution = connection.execute(
                    select(ai_transfer_execution_admissions.c.execution_id).where(
                        ai_transfer_execution_admissions.c.company_id == tenant,
                        ai_transfer_execution_admissions.c.transfer_id == transfer_id,
                    )
                ).scalar_one_or_none()
                if existing_execution is not None:
                    raise AiTransferConflict("AI transfer approval was already consumed")
                admitted_at = connection.execute(select(func.clock_timestamp())).scalar_one()
                try:
                    admission = build_ai_transfer_execution_admission(
                        request,
                        approval,
                        company_id=tenant,
                        transfer_id=transfer_id,
                        execution_id=str(uuid.uuid4()),
                        admitted_by=actor_id,
                        admitted_at=admitted_at,
                        existing_admission=None,
                    )
                except ValueError as error:
                    raise AiTransferConflict(
                        "AI transfer execution admission is invalid"
                    ) from error
                connection.execute(
                    insert(ai_transfer_execution_admissions).values(
                        company_id=tenant,
                        execution_id=admission.execution_id,
                        transfer_id=transfer_id,
                        request_payload_sha256=request_payload_sha256,
                        approved_by=admission.approved_by,
                        approved_at=admission.approved_at,
                        approval_expires_at=admission.approval_expires_at,
                        chunk_count=admission.chunk_count,
                        payload_sha256=admission.payload_sha256,
                        admission=admission.model_dump(mode="json"),
                        admitted_by=actor_id,
                        admitted_at=admission.admitted_at,
                    )
                )
                self._ai_transfer_execution_audit(
                    connection,
                    company_id=tenant,
                    actor_id=actor_id,
                    event_type="document.ai_transfer_execution_admitted",
                    execution_id=admission.execution_id,
                    transfer_id=transfer_id,
                    request_payload_sha256=request_payload_sha256,
                    occurred_at=admission.admitted_at,
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"execution_id": admission.execution_id},
                )
                return admission
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) in {"23505", "23514"}:
                raise AiTransferConflict("AI transfer execution admission conflicts") from error
            raise

    def get_ai_transfer_execution(
        self,
        company_id: str,
        execution_id: str,
    ) -> (
        tuple[
            AiTransferExecutionAdmission,
            AiTransferDispatchClaim | None,
            AiTransferDispatchReceipt | None,
        ]
        | None
    ):
        """Read an execution, its optional permanent claim, and safe receipt."""
        tenant = _require_tenant(company_id)
        with self.transaction(tenant) as connection:
            try:
                return self._load_ai_transfer_execution(connection, tenant, execution_id)
            except AiTransferNotFound:
                return None

    def get_ai_transfer_raw_metadata_for_execution(
        self,
        company_id: str,
        execution_id: str,
    ) -> AiTransferRawMetadata | None:
        """Return safe retained-capture metadata without decrypting response bytes.

        Metadata remains discoverable after the 720-hour ciphertext purge so an
        auditor can still account for the terminal receipt and deletion record.
        """
        tenant = _require_tenant(company_id)
        with self.transaction(tenant) as connection:
            row = (
                connection.execute(
                    select(ai_transfer_raw_responses)
                    .where(
                        and_(
                            ai_transfer_raw_responses.c.company_id == tenant,
                            ai_transfer_raw_responses.c.execution_id == execution_id,
                        )
                    )
                    .order_by(ai_transfer_raw_responses.c.ordinal.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            return self._validated_ai_transfer_raw_metadata(row)

    def claim_first_ai_transfer_dispatch(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
    ) -> AiTransferDispatchClaim:
        """Create the sole first-chunk claim; an existing claim never grants dispatch again."""
        tenant = _require_tenant(company_id)
        if not worker_id.strip() or worker_id != worker_id.strip():
            raise AiTransferSourceMismatch("AI transfer dispatch actor is invalid")
        try:
            with self.transaction(tenant) as connection:
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                    {"lock_key": f"ai-transfer-claim:{tenant}:{execution_id}"},
                )
                admission, existing_claim, existing_receipt = self._load_ai_transfer_execution(
                    connection, tenant, execution_id
                )
                if existing_claim is not None or existing_receipt is not None:
                    raise AiTransferConflict("AI transfer dispatch was already claimed")
                request, approval = self._load_ai_transfer(
                    connection, tenant, admission.transfer_id
                )
                if approval is None:
                    raise AiTransferConflict("AI transfer dispatch approval is absent")
                claimed_at = connection.execute(select(func.clock_timestamp())).scalar_one()
                try:
                    claim = build_ai_transfer_dispatch_claim(
                        request,
                        approval,
                        admission,
                        claim_id=str(uuid.uuid4()),
                        claimed_by=worker_id,
                        claimed_at=claimed_at,
                        existing_claims=(),
                        existing_receipts=(),
                    )
                except ValueError as error:
                    raise AiTransferConflict("AI transfer dispatch claim is invalid") from error
                connection.execute(
                    insert(ai_transfer_dispatch_claims).values(
                        company_id=tenant,
                        claim_id=claim.claim_id,
                        execution_id=execution_id,
                        transfer_id=claim.transfer_id,
                        request_payload_sha256=claim.request_payload_sha256,
                        admission_payload_sha256=claim.admission_payload_sha256,
                        ordinal=claim.ordinal,
                        chunk_id=claim.chunk_id,
                        request_sha256=claim.request_sha256,
                        claim=claim.model_dump(mode="json"),
                        attempt=claim.attempt,
                        claim_status=claim.claim_status,
                        delivery_state=claim.delivery_state,
                        claimed_by=claim.claimed_by,
                        claimed_at=claim.claimed_at,
                        payload_sha256=claim.payload_sha256,
                    )
                )
                self._ai_transfer_execution_audit(
                    connection,
                    company_id=tenant,
                    actor_id=worker_id,
                    event_type="document.ai_transfer_dispatch_claimed",
                    execution_id=execution_id,
                    transfer_id=claim.transfer_id,
                    request_payload_sha256=claim.request_payload_sha256,
                    occurred_at=claim.claimed_at,
                    claim_id=claim.claim_id,
                )
                return claim
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) in {"23505", "23514"}:
                raise AiTransferConflict("AI transfer dispatch claim conflicts") from error
            raise

    def claim_next_ai_transfer_dispatch(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
    ) -> AiTransferDispatchClaim:
        """Permanently claim exactly the next chunk after committed successful history.

        This boundary performs no network operation and intentionally has no API
        or live-worker route in S51.
        """
        tenant = _require_tenant(company_id)
        if not worker_id.strip() or worker_id != worker_id.strip():
            raise AiTransferSourceMismatch("AI transfer dispatch actor is invalid")
        try:
            with self.transaction(tenant) as connection:
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                    {"lock_key": f"ai-transfer-claim:{tenant}:{execution_id}"},
                )
                admission, latest_claim, latest_receipt = self._load_ai_transfer_execution(
                    connection, tenant, execution_id
                )
                if latest_claim is None:
                    raise AiTransferConflict("AI transfer first dispatch claim is absent")
                if latest_receipt is None:
                    raise AiTransferConflict("AI transfer prior dispatch is not terminal")
                request, approval = self._load_ai_transfer(
                    connection, tenant, admission.transfer_id
                )
                if approval is None:
                    raise AiTransferConflict("AI transfer dispatch approval is absent")
                claims, receipts = self._load_ai_transfer_dispatch_history(
                    connection,
                    tenant,
                    execution_id,
                    request=request,
                    approval=approval,
                    admission=admission,
                )
                claimed_at = connection.execute(select(func.clock_timestamp())).scalar_one()
                try:
                    claim = build_ai_transfer_dispatch_claim(
                        request,
                        approval,
                        admission,
                        claim_id=str(uuid.uuid4()),
                        claimed_by=worker_id,
                        claimed_at=claimed_at,
                        existing_claims=claims,
                        existing_receipts=receipts,
                    )
                except ValueError as error:
                    raise AiTransferConflict(
                        "AI transfer next dispatch claim is invalid"
                    ) from error
                connection.execute(
                    insert(ai_transfer_dispatch_claims).values(
                        company_id=tenant,
                        claim_id=claim.claim_id,
                        execution_id=execution_id,
                        transfer_id=claim.transfer_id,
                        request_payload_sha256=claim.request_payload_sha256,
                        admission_payload_sha256=claim.admission_payload_sha256,
                        ordinal=claim.ordinal,
                        chunk_id=claim.chunk_id,
                        request_sha256=claim.request_sha256,
                        claim=claim.model_dump(mode="json"),
                        attempt=claim.attempt,
                        claim_status=claim.claim_status,
                        delivery_state=claim.delivery_state,
                        claimed_by=claim.claimed_by,
                        claimed_at=claim.claimed_at,
                        payload_sha256=claim.payload_sha256,
                    )
                )
                self._ai_transfer_execution_audit(
                    connection,
                    company_id=tenant,
                    actor_id=worker_id,
                    event_type="document.ai_transfer_dispatch_claimed",
                    execution_id=execution_id,
                    transfer_id=claim.transfer_id,
                    request_payload_sha256=claim.request_payload_sha256,
                    occurred_at=claim.claimed_at,
                    claim_id=claim.claim_id,
                )
                return claim
        except (AiTransferConflict, AiTransferSourceMismatch):
            raise
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) in {
                "23503",
                "23505",
                "23514",
            }:
                raise AiTransferConflict("AI transfer next dispatch claim conflicts") from error
            raise

    def record_ai_transfer_dispatch_receipt(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
        attempt: AiTransferTransportAttempt,
    ) -> AiTransferDispatchReceipt:
        """Atomically append safe terminal metadata for the sole claimed attempt.

        This internal persistence boundary never accepts or stores response bytes,
        assistant content, authorization headers, or provider error text.
        """
        tenant = _require_tenant(company_id)
        if not worker_id.strip() or worker_id != worker_id.strip():
            raise AiTransferSourceMismatch("AI transfer dispatch actor is invalid")
        checked_attempt = AiTransferTransportAttempt.model_validate(
            attempt.model_dump(mode="python"), strict=True
        )
        if checked_attempt.capture_complete:
            raise AiTransferConflict(
                "complete dispatch capture requires atomic encrypted retention"
            )
        try:
            with self.transaction(tenant) as connection:
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                    {"lock_key": f"ai-transfer-receipt:{tenant}:{execution_id}"},
                )
                admission, claim, existing_receipt = self._load_ai_transfer_execution(
                    connection, tenant, execution_id
                )
                if claim is None:
                    raise AiTransferConflict("AI transfer dispatch has not been claimed")
                if existing_receipt is not None:
                    raise AiTransferConflict("AI transfer dispatch receipt already exists")
                if claim.claimed_by != worker_id:
                    raise AiTransferConflict(
                        "only the claiming worker may record dispatch evidence"
                    )
                if checked_attempt.request_sha256 != claim.request_sha256:
                    raise AiTransferConflict("AI transfer dispatch request digest differs")
                recorded_at = connection.execute(select(func.clock_timestamp())).scalar_one()
                try:
                    receipt = build_ai_transfer_dispatch_receipt(
                        claim,
                        receipt_id=str(uuid.uuid4()),
                        outcome=checked_attempt.outcome.value,
                        reason=checked_attempt.reason.value,
                        attempted=checked_attempt.attempted,
                        request_sha256=checked_attempt.request_sha256,
                        http_status=checked_attempt.http_status,
                        capture_complete=checked_attempt.capture_complete,
                        captured_byte_count=checked_attempt.captured_byte_count,
                        response_body_sha256=checked_attempt.response_body_sha256,
                        provider_response_id=checked_attempt.provider_response_id,
                        provider_model=checked_attempt.provider_model,
                        assistant_content_sha256=checked_attempt.assistant_content_sha256,
                        assistant_content_byte_count=(checked_attempt.assistant_content_byte_count),
                        started_at=checked_attempt.started_at,
                        finished_at=checked_attempt.finished_at,
                        recorded_by=worker_id,
                        recorded_at=recorded_at,
                    )
                except (TypeError, ValueError) as error:
                    raise AiTransferConflict("AI transfer dispatch receipt is invalid") from error
                self._insert_ai_transfer_dispatch_receipt(connection, receipt)
                self._ai_transfer_execution_audit(
                    connection,
                    company_id=tenant,
                    actor_id=worker_id,
                    event_type="document.ai_transfer_dispatch_receipted",
                    execution_id=execution_id,
                    transfer_id=admission.transfer_id,
                    request_payload_sha256=admission.request_payload_sha256,
                    occurred_at=receipt.recorded_at,
                    claim_id=claim.claim_id,
                    receipt_id=receipt.receipt_id,
                    receipt_payload_sha256=receipt.payload_sha256,
                    dispatch_outcome=receipt.outcome,
                )
                return receipt
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) in {
                "23503",
                "23505",
                "23514",
            }:
                raise AiTransferConflict("AI transfer dispatch receipt conflicts") from error
            raise

    @staticmethod
    def _append_ai_transfer_pre_dispatch_expiry(
        connection: Connection,
        *,
        admission: AiTransferExecutionAdmission,
        claim: AiTransferDispatchClaim,
        recorded_at: datetime,
    ) -> AiTransferDispatchReceipt:
        try:
            receipt = build_ai_transfer_dispatch_receipt(
                claim,
                receipt_id=str(uuid.uuid4()),
                outcome="FAILED",
                reason="APPROVAL_EXPIRED_BEFORE_DISPATCH",
                attempted=False,
                request_sha256=claim.request_sha256,
                http_status=None,
                capture_complete=False,
                captured_byte_count=0,
                response_body_sha256=None,
                provider_response_id=None,
                provider_model=None,
                assistant_content_sha256=None,
                assistant_content_byte_count=None,
                started_at=None,
                finished_at=None,
                recorded_by=claim.claimed_by,
                recorded_at=recorded_at,
            )
        except (TypeError, ValueError) as error:
            raise AiTransferConflict(
                "AI transfer pre-dispatch expiry receipt is invalid"
            ) from error
        PostgresStorage._insert_ai_transfer_dispatch_receipt(connection, receipt)
        PostgresStorage._ai_transfer_execution_audit(
            connection,
            company_id=claim.company_id,
            actor_id=claim.claimed_by,
            event_type="document.ai_transfer_dispatch_expired",
            execution_id=claim.execution_id,
            transfer_id=admission.transfer_id,
            request_payload_sha256=admission.request_payload_sha256,
            occurred_at=receipt.recorded_at,
            claim_id=claim.claim_id,
            receipt_id=receipt.receipt_id,
            receipt_payload_sha256=receipt.payload_sha256,
            dispatch_outcome=receipt.outcome,
        )
        return receipt

    def prepare_claimed_ai_transfer_dispatch(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
        claim: AiTransferDispatchClaim,
    ) -> AiTransferPreparedDispatch | AiTransferDispatchReceipt:
        """Revalidate a fresh claim and return its exact first request or expiry receipt."""
        tenant = _require_tenant(company_id)
        if not worker_id.strip() or worker_id != worker_id.strip():
            raise AiTransferSourceMismatch("AI transfer dispatch actor is invalid")
        if self._raw_key_provider is None:
            raise AiTransferSourceMismatch("raw response encryption key is unavailable")
        checked_claim = AiTransferDispatchClaim.model_validate(
            claim.model_dump(mode="python"), strict=True
        )
        try:
            with self.transaction(tenant) as connection:
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                    {"lock_key": f"ai-transfer-receipt:{tenant}:{execution_id}"},
                )
                admission, stored_claim, existing_receipt = self._load_ai_transfer_execution(
                    connection, tenant, execution_id
                )
                if stored_claim is None or stored_claim != checked_claim:
                    raise AiTransferConflict("AI transfer dispatch claim differs")
                if existing_receipt is not None:
                    raise AiTransferConflict("AI transfer dispatch receipt already exists")
                if (
                    checked_claim.company_id != tenant
                    or checked_claim.execution_id != execution_id
                    or checked_claim.claimed_by != worker_id
                ):
                    raise AiTransferConflict("AI transfer dispatch claim context differs")
                request, approval = self._load_ai_transfer(
                    connection, tenant, admission.transfer_id
                )
                if approval is None:
                    raise AiTransferConflict("AI transfer dispatch approval is absent")
                checked_at = connection.execute(select(func.clock_timestamp())).scalar_one()
                if checked_at >= approval.expires_at:
                    return self._append_ai_transfer_pre_dispatch_expiry(
                        connection,
                        admission=admission,
                        claim=checked_claim,
                        recorded_at=checked_at,
                    )
                chunk = request.chunks[checked_claim.ordinal - 1]
                exact_request = ExactAiTransferHttpRequest(
                    transport=request.transport,
                    model_profile=request.model_profile,
                    source_block_ids=chunk.source_block_ids,
                    request_body_utf8=chunk.request_body_json,
                    request_sha256=chunk.request_sha256,
                    response_capture_max_bytes=request.response_capture_max_bytes,
                )
                return AiTransferPreparedDispatch(
                    claim=checked_claim,
                    request=exact_request,
                    chunk_count=admission.chunk_count,
                    approval_expires_at=approval.expires_at,
                    checked_at=checked_at,
                )
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) in {
                "23503",
                "23505",
                "23514",
            }:
                raise AiTransferConflict("AI transfer dispatch preparation conflicts") from error
            raise

    def record_ai_transfer_pre_dispatch_expiry(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
        claim: AiTransferDispatchClaim,
        *,
        observed_at: datetime,
    ) -> AiTransferDispatchReceipt:
        """Fail closed when approval expires after DB preparation but before send."""
        tenant = _require_tenant(company_id)
        if not worker_id.strip() or worker_id != worker_id.strip():
            raise AiTransferSourceMismatch("AI transfer dispatch actor is invalid")
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise AiTransferSourceMismatch("AI transfer expiry observation is invalid")
        checked_claim = AiTransferDispatchClaim.model_validate(
            claim.model_dump(mode="python"), strict=True
        )
        try:
            with self.transaction(tenant) as connection:
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                    {"lock_key": f"ai-transfer-receipt:{tenant}:{execution_id}"},
                )
                admission, stored_claim, existing_receipt = self._load_ai_transfer_execution(
                    connection, tenant, execution_id
                )
                if stored_claim is None or stored_claim != checked_claim:
                    raise AiTransferConflict("AI transfer dispatch claim differs")
                if existing_receipt is not None:
                    raise AiTransferConflict("AI transfer dispatch receipt already exists")
                if (
                    checked_claim.company_id != tenant
                    or checked_claim.execution_id != execution_id
                    or checked_claim.claimed_by != worker_id
                ):
                    raise AiTransferConflict("AI transfer dispatch claim context differs")
                _, approval = self._load_ai_transfer(connection, tenant, admission.transfer_id)
                if approval is None:
                    raise AiTransferConflict("AI transfer dispatch approval is absent")
                recorded_at = connection.execute(select(func.clock_timestamp())).scalar_one()
                if (
                    observed_at.astimezone(UTC) < approval.expires_at.astimezone(UTC)
                    or recorded_at < approval.expires_at
                ):
                    raise AiTransferConflict("AI transfer approval has not expired")
                return self._append_ai_transfer_pre_dispatch_expiry(
                    connection,
                    admission=admission,
                    claim=checked_claim,
                    recorded_at=recorded_at,
                )
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) in {
                "23503",
                "23505",
                "23514",
            }:
                raise AiTransferConflict("AI transfer expiry receipt conflicts") from error
            raise

    def persist_captured_ai_transfer_result(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
        attempt: AiTransferTransportAttempt,
        raw_response_body: bytes,
    ) -> tuple[AiTransferDispatchReceipt, AiTransferRawMetadata]:
        """Atomically persist a complete receipt and encrypted bounded raw response."""
        tenant = _require_tenant(company_id)
        if not worker_id.strip() or worker_id != worker_id.strip():
            raise AiTransferSourceMismatch("AI transfer dispatch actor is invalid")
        provider = self._raw_key_provider
        if provider is None:
            raise AiTransferSourceMismatch("raw response encryption key is unavailable")
        checked_attempt = AiTransferTransportAttempt.model_validate(
            attempt.model_dump(mode="python"), strict=True
        )
        if not checked_attempt.capture_complete or checked_attempt.response_body_sha256 is None:
            raise AiTransferConflict("only a complete response capture can be retained")
        try:
            with self.transaction(tenant) as connection:
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                    {"lock_key": f"ai-transfer-receipt:{tenant}:{execution_id}"},
                )
                admission, claim, existing_receipt = self._load_ai_transfer_execution(
                    connection, tenant, execution_id
                )
                if claim is None:
                    raise AiTransferConflict("AI transfer dispatch has not been claimed")
                if existing_receipt is not None:
                    raise AiTransferConflict("AI transfer dispatch receipt already exists")
                if claim.claimed_by != worker_id:
                    raise AiTransferConflict(
                        "only the claiming worker may record dispatch evidence"
                    )
                if checked_attempt.request_sha256 != claim.request_sha256:
                    raise AiTransferConflict("AI transfer dispatch request digest differs")
                recorded_at = connection.execute(select(func.clock_timestamp())).scalar_one()
                try:
                    receipt = build_ai_transfer_dispatch_receipt(
                        claim,
                        receipt_id=str(uuid.uuid4()),
                        outcome=checked_attempt.outcome.value,
                        reason=checked_attempt.reason.value,
                        attempted=checked_attempt.attempted,
                        request_sha256=checked_attempt.request_sha256,
                        http_status=checked_attempt.http_status,
                        capture_complete=True,
                        captured_byte_count=checked_attempt.captured_byte_count,
                        response_body_sha256=checked_attempt.response_body_sha256,
                        provider_response_id=checked_attempt.provider_response_id,
                        provider_model=checked_attempt.provider_model,
                        assistant_content_sha256=checked_attempt.assistant_content_sha256,
                        assistant_content_byte_count=(checked_attempt.assistant_content_byte_count),
                        started_at=checked_attempt.started_at,
                        finished_at=checked_attempt.finished_at,
                        recorded_by=worker_id,
                        recorded_at=recorded_at,
                    )
                    envelope = encrypt_ai_transfer_raw_response(
                        binding=AiTransferRawBinding(
                            company_id=tenant,
                            raw_response_id=str(uuid.uuid4()),
                            transfer_id=claim.transfer_id,
                            execution_id=execution_id,
                            ordinal=claim.ordinal,
                            claim_id=claim.claim_id,
                            chunk_id=claim.chunk_id,
                            claim_payload_sha256=claim.payload_sha256,
                            receipt_id=receipt.receipt_id,
                            receipt_payload_sha256=receipt.payload_sha256,
                            request_sha256=claim.request_sha256,
                            response_body_sha256=checked_attempt.response_body_sha256,
                            response_byte_count=checked_attempt.captured_byte_count,
                            received_at=checked_attempt.finished_at,
                        ),
                        raw_response_body=raw_response_body,
                        key_provider=provider,
                    )
                except (AiTransferRawError, TypeError, ValueError) as error:
                    raise AiTransferConflict("complete AI transfer evidence is invalid") from error
                metadata = envelope.metadata
                self._insert_ai_transfer_dispatch_receipt(connection, receipt)
                connection.execute(
                    insert(ai_transfer_raw_responses).values(
                        company_id=metadata.company_id,
                        raw_response_id=metadata.raw_response_id,
                        transfer_id=metadata.transfer_id,
                        execution_id=metadata.execution_id,
                        ordinal=metadata.ordinal,
                        claim_id=metadata.claim_id,
                        chunk_id=metadata.chunk_id,
                        claim_payload_sha256=metadata.claim_payload_sha256,
                        receipt_id=metadata.receipt_id,
                        receipt_payload_sha256=metadata.receipt_payload_sha256,
                        request_sha256=metadata.request_sha256,
                        capture_complete=True,
                        response_body_sha256=metadata.response_body_sha256,
                        response_byte_count=metadata.response_byte_count,
                        received_at=metadata.received_at,
                        expires_at=metadata.expires_at,
                        schema_version=metadata.schema_version,
                        algorithm=metadata.algorithm,
                        key_id=metadata.key_id,
                        body_aad_sha256=metadata.body_aad_sha256,
                        metadata_sha256=metadata.metadata_sha256,
                        wrap_aad_sha256=envelope.wrap_aad_sha256,
                        envelope_sha256=envelope.envelope_sha256,
                        metadata=metadata.model_dump(mode="json"),
                    )
                )
                connection.execute(
                    insert(ai_transfer_raw_response_blobs).values(
                        company_id=tenant,
                        raw_response_id=metadata.raw_response_id,
                        receipt_id=metadata.receipt_id,
                        response_body_sha256=metadata.response_body_sha256,
                        response_byte_count=metadata.response_byte_count,
                        received_at=metadata.received_at,
                        expires_at=metadata.expires_at,
                        metadata_schema_version=metadata.schema_version,
                        schema_version=envelope.schema_version,
                        algorithm=metadata.algorithm,
                        key_id=metadata.key_id,
                        body_aad_sha256=metadata.body_aad_sha256,
                        metadata_sha256=metadata.metadata_sha256,
                        wrap_aad_sha256=envelope.wrap_aad_sha256,
                        envelope_sha256=envelope.envelope_sha256,
                        body_nonce=envelope.body_nonce,
                        ciphertext=envelope.ciphertext,
                        wrapping_nonce=envelope.wrapping_nonce,
                        wrapped_dek=envelope.wrapped_dek,
                    )
                )
                self._ai_transfer_execution_audit(
                    connection,
                    company_id=tenant,
                    actor_id=worker_id,
                    event_type="document.ai_transfer_dispatch_receipted",
                    execution_id=execution_id,
                    transfer_id=admission.transfer_id,
                    request_payload_sha256=admission.request_payload_sha256,
                    occurred_at=receipt.recorded_at,
                    claim_id=claim.claim_id,
                    receipt_id=receipt.receipt_id,
                    receipt_payload_sha256=receipt.payload_sha256,
                    dispatch_outcome=receipt.outcome,
                )
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=worker_id,
                            event_type="document.ai_transfer_raw_response_encrypted",
                            object_type="ai_transfer_raw_response",
                            object_id=metadata.raw_response_id,
                            basis={
                                "execution_id": execution_id,
                                "receipt_id": receipt.receipt_id,
                                "metadata_sha256": metadata.metadata_sha256,
                                "envelope_sha256": envelope.envelope_sha256,
                                "expires_at": metadata.expires_at.isoformat(),
                            },
                            occurred_at=receipt.recorded_at,
                        ).model_dump(mode="python")
                    )
                )
                return receipt, metadata
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) in {
                "23503",
                "23505",
                "23514",
            }:
                raise AiTransferConflict("encrypted AI transfer evidence conflicts") from error
            raise

    def read_ai_transfer_raw_response(
        self,
        company_id: str,
        actor_id: str,
        access_role: AccessRole,
        raw_response_id: str,
    ) -> tuple[bytes, AiTransferRawMetadata]:
        """Decrypt one unexpired raw response for an authorized review actor."""
        tenant = _require_tenant(company_id)
        if not actor_id.strip() or actor_id != actor_id.strip():
            raise AiTransferSourceMismatch("AI transfer raw response actor is invalid")
        try:
            role = AccessRole(access_role)
        except ValueError as error:
            raise AiTransferSourceMismatch("AI transfer raw response role is invalid") from error
        if role not in {AccessRole.AI_REQUIREMENTS_REVIEWER, AccessRole.AUDITOR}:
            raise AiTransferSourceMismatch("AI transfer raw response access is forbidden")
        provider = self._raw_key_provider
        if provider is None:
            raise AiTransferSourceMismatch("raw response encryption key is unavailable")
        with self.transaction(tenant) as connection:
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                {"lock_key": f"ai-transfer-raw:{tenant}:{raw_response_id}"},
            )
            metadata, envelope = self._load_ai_transfer_raw_envelope(
                connection,
                tenant,
                raw_response_id,
            )
            now = connection.execute(select(func.clock_timestamp())).scalar_one()
            if now >= metadata.expires_at:
                raise AiTransferNotFound("AI transfer raw response retention expired")
            try:
                plaintext = decrypt_ai_transfer_raw_response(
                    envelope=envelope,
                    expected_metadata=metadata,
                    key_provider=provider,
                    at=now,
                )
            except AiTransferRawError as error:
                if error.code is AiTransferRawErrorCode.EXPIRED:
                    raise AiTransferNotFound(
                        "AI transfer raw response retention expired"
                    ) from error
                raise AiTransferSourceMismatch(
                    "encrypted AI transfer evidence is invalid"
                ) from error
            checked_at = connection.execute(select(func.clock_timestamp())).scalar_one()
            if checked_at >= metadata.expires_at:
                raise AiTransferNotFound("AI transfer raw response retention expired")
            connection.execute(
                insert(audit_events).values(
                    **AuditEventRecord(
                        event_id=str(uuid.uuid4()),
                        company_id=tenant,
                        actor_id=actor_id,
                        event_type="document.ai_transfer_raw_response_accessed",
                        object_type="ai_transfer_raw_response",
                        object_id=raw_response_id,
                        basis={
                            "receipt_id": metadata.receipt_id,
                            "metadata_sha256": metadata.metadata_sha256,
                            "response_body_sha256": metadata.response_body_sha256,
                        },
                        occurred_at=checked_at,
                    ).model_dump(mode="python")
                )
            )
            return plaintext, metadata

    def purge_expired_ai_transfer_raw_responses(
        self,
        company_id: str,
        actor_id: str,
        *,
        limit: int = 100,
    ) -> tuple[AiTransferRawDeletionReceipt, ...]:
        """Delete expired ciphertext/DEKs and retain immutable deletion evidence."""
        tenant = _require_tenant(company_id)
        if not actor_id.strip() or actor_id != actor_id.strip():
            raise AiTransferSourceMismatch("AI transfer retention actor is invalid")
        if limit < 1 or limit > 500:
            raise ValueError("AI transfer retention purge limit must be between 1 and 500")
        try:
            with self.transaction(tenant) as connection:
                selection_cutoff = connection.execute(select(func.clock_timestamp())).scalar_one()
                rows = (
                    connection.execute(
                        select(ai_transfer_raw_responses)
                        .join(
                            ai_transfer_raw_response_blobs,
                            and_(
                                ai_transfer_raw_response_blobs.c.company_id
                                == ai_transfer_raw_responses.c.company_id,
                                ai_transfer_raw_response_blobs.c.raw_response_id
                                == ai_transfer_raw_responses.c.raw_response_id,
                            ),
                        )
                        .outerjoin(
                            ai_transfer_raw_response_deletion_receipts,
                            and_(
                                ai_transfer_raw_response_deletion_receipts.c.company_id
                                == ai_transfer_raw_responses.c.company_id,
                                ai_transfer_raw_response_deletion_receipts.c.raw_response_id
                                == ai_transfer_raw_responses.c.raw_response_id,
                            ),
                        )
                        .where(
                            ai_transfer_raw_responses.c.company_id == tenant,
                            ai_transfer_raw_responses.c.expires_at <= selection_cutoff,
                            ai_transfer_raw_response_deletion_receipts.c.raw_response_id.is_(None),
                        )
                        .order_by(
                            ai_transfer_raw_responses.c.expires_at,
                            ai_transfer_raw_responses.c.raw_response_id,
                        )
                        .limit(limit)
                    )
                    .mappings()
                    .all()
                )
                receipts: list[AiTransferRawDeletionReceipt] = []
                for row in rows:
                    raw_response_id = str(row["raw_response_id"])
                    connection.execute(
                        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                        {"lock_key": f"ai-transfer-raw:{tenant}:{raw_response_id}"},
                    )
                    deletion_exists = connection.execute(
                        select(ai_transfer_raw_response_deletion_receipts.c.raw_response_id).where(
                            and_(
                                ai_transfer_raw_response_deletion_receipts.c.company_id == tenant,
                                ai_transfer_raw_response_deletion_receipts.c.raw_response_id
                                == raw_response_id,
                            )
                        )
                    ).scalar_one_or_none()
                    blob_row = (
                        connection.execute(
                            select(ai_transfer_raw_response_blobs).where(
                                and_(
                                    ai_transfer_raw_response_blobs.c.company_id == tenant,
                                    ai_transfer_raw_response_blobs.c.raw_response_id
                                    == raw_response_id,
                                )
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if deletion_exists is not None or blob_row is None:
                        continue
                    deleted_at = connection.execute(select(func.clock_timestamp())).scalar_one()
                    try:
                        metadata = AiTransferRawMetadata.model_validate_json(
                            json.dumps(row["metadata"])
                        )
                        if deleted_at < metadata.expires_at:
                            continue
                        deletion_receipt = build_ai_transfer_raw_deletion_receipt(
                            metadata,
                            wrap_aad_sha256=str(blob_row["wrap_aad_sha256"]),
                            envelope_sha256=str(row["envelope_sha256"]),
                            deletion_receipt_id=str(uuid.uuid4()),
                            deleted_by=actor_id,
                            deleted_at=deleted_at,
                        )
                    except (AiTransferRawError, TypeError, ValueError) as error:
                        raise AiTransferSourceMismatch(
                            "AI transfer retention evidence is invalid"
                        ) from error
                    connection.execute(
                        insert(ai_transfer_raw_response_deletion_receipts).values(
                            company_id=tenant,
                            raw_response_id=deletion_receipt.raw_response_id,
                            deletion_receipt_id=deletion_receipt.deletion_receipt_id,
                            receipt_id=deletion_receipt.receipt_id,
                            response_body_sha256=deletion_receipt.response_body_sha256,
                            response_byte_count=deletion_receipt.response_byte_count,
                            received_at=deletion_receipt.received_at,
                            expires_at=deletion_receipt.expires_at,
                            metadata_schema_version=(deletion_receipt.metadata_schema_version),
                            algorithm=deletion_receipt.algorithm,
                            key_id=deletion_receipt.key_id,
                            body_aad_sha256=deletion_receipt.body_aad_sha256,
                            metadata_sha256=deletion_receipt.metadata_sha256,
                            wrap_aad_sha256=deletion_receipt.wrap_aad_sha256,
                            envelope_sha256=deletion_receipt.envelope_sha256,
                            reason=deletion_receipt.reason,
                            deleted_by=deletion_receipt.deleted_by,
                            deleted_at=deletion_receipt.deleted_at,
                            payload_sha256=deletion_receipt.payload_sha256,
                            deletion_receipt=deletion_receipt.model_dump(mode="json"),
                        )
                    )
                    deleted = connection.execute(
                        delete(ai_transfer_raw_response_blobs).where(
                            and_(
                                ai_transfer_raw_response_blobs.c.company_id == tenant,
                                ai_transfer_raw_response_blobs.c.raw_response_id
                                == deletion_receipt.raw_response_id,
                            )
                        )
                    ).rowcount
                    if deleted != 1:
                        raise AiTransferConflict(
                            "AI transfer raw response purge lost its exact blob"
                        )
                    connection.execute(
                        insert(audit_events).values(
                            **AuditEventRecord(
                                event_id=str(uuid.uuid4()),
                                company_id=tenant,
                                actor_id=actor_id,
                                event_type="document.ai_transfer_raw_response_deleted",
                                object_type="ai_transfer_raw_response",
                                object_id=deletion_receipt.raw_response_id,
                                basis={
                                    "deletion_receipt_id": (deletion_receipt.deletion_receipt_id),
                                    "metadata_sha256": deletion_receipt.metadata_sha256,
                                    "envelope_sha256": deletion_receipt.envelope_sha256,
                                },
                                occurred_at=deleted_at,
                            ).model_dump(mode="python")
                        )
                    )
                    receipts.append(deletion_receipt)
                return tuple(receipts)
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) in {
                "23503",
                "23505",
                "23514",
            }:
                raise AiTransferConflict("AI transfer raw response purge conflicts") from error
            raise

    def get_completeness_review(
        self,
        company_id: str,
        review_id: str,
    ) -> CompletenessReviewRecord | None:
        tenant = _require_tenant(company_id)
        with self.transaction(tenant) as connection:
            try:
                return self._load_completeness_review(connection, tenant, review_id)
            except CompletenessReviewNotFound:
                return None

    def list_completeness_reviews(
        self,
        company_id: str,
        *,
        limit: int = 100,
    ) -> tuple[CompletenessReviewRecord, ...]:
        tenant = _require_tenant(company_id)
        if limit < 1 or limit > 200:
            raise ValueError("completeness review limit must be between 1 and 200")
        with self.transaction(tenant) as connection:
            review_ids = connection.execute(
                select(document_completeness_reviews.c.review_id)
                .where(document_completeness_reviews.c.company_id == tenant)
                .order_by(
                    document_completeness_reviews.c.created_at.desc(),
                    document_completeness_reviews.c.review_id.desc(),
                )
                .limit(limit)
            ).scalars()
            return tuple(
                self._load_completeness_review(connection, tenant, review_id)
                for review_id in review_ids
            )

    @staticmethod
    def _load_document_set_evidence_manifest(
        connection: Connection,
        tenant: str,
        manifest_id: str,
    ) -> DocumentSetEvidenceManifest:
        manifest_row = (
            connection.execute(
                select(document_set_evidence_manifests).where(
                    and_(
                        document_set_evidence_manifests.c.company_id == tenant,
                        document_set_evidence_manifests.c.manifest_id == manifest_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if manifest_row is None:
            raise DocumentSetEvidenceNotFound("document set evidence manifest was not found")
        try:
            manifest = DocumentSetEvidenceManifest.model_validate_json(
                json.dumps(manifest_row["manifest"], ensure_ascii=False)
            )
            member_rows = tuple(
                connection.execute(
                    select(document_set_evidence_members)
                    .where(
                        and_(
                            document_set_evidence_members.c.company_id == tenant,
                            document_set_evidence_members.c.manifest_id == manifest_id,
                        )
                    )
                    .order_by(document_set_evidence_members.c.ordinal)
                ).mappings()
            )
            members = tuple(
                DocumentSetEvidenceMember.model_validate_json(
                    json.dumps(row["member"], ensure_ascii=False)
                )
                for row in member_rows
            )
        except (TypeError, ValueError) as error:
            raise DocumentSetEvidenceSourceMismatch(
                "stored document set evidence is invalid"
            ) from error
        if (
            manifest.company_id != tenant
            or manifest.manifest_id != manifest_id
            or manifest.members != members
            or len(member_rows) != int(manifest_row["member_count"])
        ):
            raise DocumentSetEvidenceSourceMismatch(
                "stored document set evidence rows do not match manifest"
            )
        for row, member in zip(member_rows, members, strict=True):
            if (
                row["company_id"] != tenant
                or row["manifest_id"] != manifest_id
                or row["ordinal"] != member.ordinal
                or row["source_document_id"] != member.source_document_id
                or row["source_document_sha256"] != member.source_document_sha256
                or row["completeness_review_id"] != member.completeness_review_id
                or row["completeness_review_evidence_sha256"]
                != member.completeness_review_evidence_sha256
                or row["mapper_version"] != member.mapper_version
                or float(row["mapper_min_confidence"]) != member.mapper_min_confidence
            ):
                raise DocumentSetEvidenceSourceMismatch(
                    "stored document set member columns do not match payload"
                )
            try:
                snapshot = PostgresStorage._load_completeness_review_snapshot(
                    connection,
                    tenant,
                    member.completeness_review_id,
                )
                expected_member = project_document_set_evidence_member(
                    snapshot,
                    ordinal=member.ordinal,
                )
            except (
                CompletenessReviewNotFound,
                CompletenessReviewSourceMismatch,
                TypeError,
                ValueError,
            ) as error:
                raise DocumentSetEvidenceSourceMismatch(
                    "stored document set member review binding is invalid"
                ) from error
            if member != expected_member:
                raise DocumentSetEvidenceSourceMismatch(
                    "stored document set member does not match its exact review"
                )
        return manifest

    def store_document_set_evidence_manifest(
        self,
        company_id: str,
        actor_id: str,
        scope: str,
        review_refs: tuple[tuple[str, str], ...],
        idempotency_key: str,
        request_sha256: str,
        *,
        manifest_id: str | None = None,
    ) -> DocumentSetEvidenceManifest:
        """Atomically persist an explicit ordered set of exact native review snapshots."""
        tenant = _require_tenant(company_id)
        _require_sha256(request_sha256, field="request_sha256")
        if not actor_id.strip() or not scope.strip():
            raise ValueError("actor_id and scope must not be blank")
        if not 2 <= len(review_refs) <= 10:
            raise ValueError("document set evidence requires 2..10 review refs")
        review_ids = [review_id for review_id, _ in review_refs]
        if len(set(review_ids)) != len(review_ids):
            raise ValueError("document set evidence review refs must be unique")
        for review_id, evidence_sha256 in review_refs:
            if not review_id.strip():
                raise ValueError("completeness review ID must not be blank")
            _require_sha256(evidence_sha256, field="completeness_review_evidence_sha256")
        chosen_id = manifest_id or str(uuid.uuid4())
        now = datetime.now(UTC)
        try:
            with self.transaction(tenant) as connection:
                operation = "store_document_set_evidence_manifest"
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, operation, idempotency_key, request_sha256
                )
                if replay is not None:
                    return self._load_document_set_evidence_manifest(
                        connection,
                        tenant,
                        str(replay["manifest_id"]),
                    )
                preflight_rows = tuple(
                    connection.execute(
                        select(
                            document_completeness_reviews.c.review_id,
                            document_completeness_reviews.c.evidence_sha256,
                            func.octet_length(
                                cast(document_completeness_reviews.c.snapshot, Text)
                            ).label("snapshot_bytes"),
                        ).where(
                            and_(
                                document_completeness_reviews.c.company_id == tenant,
                                document_completeness_reviews.c.review_id.in_(review_ids),
                            )
                        )
                    ).mappings()
                )
                if len(preflight_rows) != len(review_refs):
                    raise DocumentSetEvidenceNotFound("selected completeness review was not found")
                preflight = {str(row["review_id"]): row for row in preflight_rows}
                if any(
                    str(preflight[review_id]["evidence_sha256"]) != evidence_sha256
                    for review_id, evidence_sha256 in review_refs
                ):
                    raise DocumentSetEvidenceSourceMismatch(
                        "selected completeness review evidence is stale"
                    )
                if sum(int(row["snapshot_bytes"]) for row in preflight_rows) > (
                    MAX_DOCUMENT_SET_EVIDENCE_BYTES
                ):
                    raise DocumentSetEvidenceSourceMismatch(
                        "selected completeness review evidence exceeds aggregate budget"
                    )
                snapshots: list[CompletenessReviewSnapshot] = []
                for review_id, expected_evidence_sha256 in review_refs:
                    try:
                        snapshot = self._load_completeness_review_snapshot(
                            connection,
                            tenant,
                            review_id,
                        )
                    except CompletenessReviewNotFound as error:
                        raise DocumentSetEvidenceNotFound(
                            "selected completeness review was not found"
                        ) from error
                    if snapshot.evidence_sha256 != expected_evidence_sha256:
                        raise DocumentSetEvidenceSourceMismatch(
                            "selected completeness review evidence is stale"
                        )
                    try:
                        self._verify_completeness_source_bytes(connection, tenant, snapshot)
                    except CompletenessReviewSourceMismatch as error:
                        raise DocumentSetEvidenceSourceMismatch(
                            "selected completeness review source evidence changed"
                        ) from error
                    snapshots.append(snapshot)
                try:
                    manifest = build_document_set_evidence_manifest(
                        tuple(snapshots),
                        company_id=tenant,
                        manifest_id=chosen_id,
                        scope=scope,
                        created_by=actor_id,
                        created_at=now,
                    )
                except ValueError as error:
                    raise DocumentSetEvidenceSourceMismatch(
                        "selected reviews cannot form a document set"
                    ) from error
                connection.execute(
                    insert(document_set_evidence_manifests).values(
                        company_id=tenant,
                        manifest_id=chosen_id,
                        scope=manifest.scope,
                        member_count=len(manifest.members),
                        completeness_status=manifest.completeness_status.value,
                        reason=manifest.reason,
                        evidence_sha256=manifest.evidence_sha256,
                        manifest=manifest.model_dump(mode="json"),
                        created_by=actor_id,
                        created_at=now,
                    )
                )
                connection.execute(
                    insert(document_set_evidence_members),
                    [
                        {
                            "company_id": tenant,
                            "manifest_id": chosen_id,
                            "ordinal": member.ordinal,
                            "source_document_id": member.source_document_id,
                            "source_document_sha256": member.source_document_sha256,
                            "completeness_review_id": member.completeness_review_id,
                            "completeness_review_evidence_sha256": (
                                member.completeness_review_evidence_sha256
                            ),
                            "mapper_version": member.mapper_version,
                            "mapper_min_confidence": member.mapper_min_confidence,
                            "member": member.model_dump(mode="json"),
                        }
                        for member in manifest.members
                    ],
                )
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=actor_id,
                            event_type="document_set.evidence_manifest_created",
                            object_type="document_set_evidence_manifest",
                            object_id=chosen_id,
                            basis={
                                "evidence_sha256": manifest.evidence_sha256,
                                "member_count": len(manifest.members),
                                "review_refs": [
                                    {
                                        "review_id": review_id,
                                        "evidence_sha256": evidence_sha256,
                                    }
                                    for review_id, evidence_sha256 in review_refs
                                ],
                            },
                            occurred_at=now,
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"manifest_id": chosen_id},
                )
                return manifest
        except (
            DocumentSetEvidenceNotFound,
            DocumentSetEvidenceSourceMismatch,
        ):
            raise
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise DocumentSetEvidenceConflict(
                    "document set evidence manifest conflicts"
                ) from error
            raise

    def get_document_set_evidence_manifest(
        self,
        company_id: str,
        manifest_id: str,
    ) -> DocumentSetEvidenceManifest | None:
        tenant = _require_tenant(company_id)
        with self.transaction(tenant) as connection:
            try:
                return self._load_document_set_evidence_manifest(
                    connection,
                    tenant,
                    manifest_id,
                )
            except DocumentSetEvidenceNotFound:
                return None

    @staticmethod
    def _load_document_set_review_evidence(
        connection: Connection,
        tenant: str,
        manifest_id: str,
    ) -> DocumentSetReviewEvidence:
        manifest_count = connection.execute(
            select(document_set_evidence_manifests.c.member_count).where(
                and_(
                    document_set_evidence_manifests.c.company_id == tenant,
                    document_set_evidence_manifests.c.manifest_id == manifest_id,
                )
            )
        ).scalar_one_or_none()
        if manifest_count is None:
            raise DocumentSetReviewNotFound("document set evidence manifest was not found")
        preflight_rows = tuple(
            connection.execute(
                select(
                    document_set_evidence_members.c.ordinal,
                    document_set_evidence_members.c.completeness_review_id,
                    document_set_evidence_members.c.completeness_review_evidence_sha256.label(
                        "member_evidence_sha256"
                    ),
                    document_completeness_reviews.c.evidence_sha256.label("review_evidence_sha256"),
                    func.octet_length(cast(document_completeness_reviews.c.snapshot, Text)).label(
                        "snapshot_bytes"
                    ),
                    document_completeness_review_decisions.c.review_id.label("decision_review_id"),
                    func.coalesce(
                        func.octet_length(
                            cast(document_completeness_review_decisions.c.decision, Text)
                        ),
                        0,
                    ).label("decision_bytes"),
                )
                .select_from(
                    document_set_evidence_members.join(
                        document_completeness_reviews,
                        and_(
                            document_completeness_reviews.c.company_id
                            == document_set_evidence_members.c.company_id,
                            document_completeness_reviews.c.review_id
                            == document_set_evidence_members.c.completeness_review_id,
                        ),
                    ).outerjoin(
                        document_completeness_review_decisions,
                        and_(
                            document_completeness_review_decisions.c.company_id
                            == document_completeness_reviews.c.company_id,
                            document_completeness_review_decisions.c.review_id
                            == document_completeness_reviews.c.review_id,
                        ),
                    )
                )
                .where(
                    and_(
                        document_set_evidence_members.c.company_id == tenant,
                        document_set_evidence_members.c.manifest_id == manifest_id,
                    )
                )
                .order_by(document_set_evidence_members.c.ordinal)
            ).mappings()
        )
        if len(preflight_rows) != int(manifest_count) or tuple(
            int(row["ordinal"]) for row in preflight_rows
        ) != tuple(range(1, int(manifest_count) + 1)):
            raise DocumentSetReviewSourceMismatch("document set evidence members are incomplete")
        if any(
            row["member_evidence_sha256"] != row["review_evidence_sha256"] for row in preflight_rows
        ):
            raise DocumentSetReviewSourceMismatch("constituent completeness evidence is stale")
        if any(row["decision_review_id"] is None for row in preflight_rows):
            raise DocumentSetReviewNotFound(
                "every document set member needs a terminal completeness decision"
            )
        if (
            sum(int(row["snapshot_bytes"]) + int(row["decision_bytes"]) for row in preflight_rows)
            > MAX_DOCUMENT_SET_REVIEW_EVIDENCE_BYTES
        ):
            raise DocumentSetReviewSourceMismatch(
                "document set review evidence exceeds aggregate budget"
            )

        try:
            manifest = PostgresStorage._load_document_set_evidence_manifest(
                connection,
                tenant,
                manifest_id,
            )
        except DocumentSetEvidenceNotFound as error:
            raise DocumentSetReviewNotFound(
                "document set evidence manifest was not found"
            ) from error
        except DocumentSetEvidenceSourceMismatch as error:
            raise DocumentSetReviewSourceMismatch(
                "document set evidence manifest is invalid"
            ) from error

        records: list[CompletenessReviewRecord] = []
        for member in manifest.members:
            try:
                record = PostgresStorage._load_completeness_review(
                    connection,
                    tenant,
                    member.completeness_review_id,
                )
                PostgresStorage._verify_completeness_source_bytes(
                    connection,
                    tenant,
                    record.snapshot,
                )
            except CompletenessReviewNotFound as error:
                raise DocumentSetReviewNotFound(
                    "constituent completeness review was not found"
                ) from error
            except (CompletenessReviewSourceMismatch, TypeError, ValueError) as error:
                raise DocumentSetReviewSourceMismatch(
                    "constituent completeness evidence is invalid"
                ) from error
            records.append(record)
        try:
            return build_document_set_review_evidence(manifest, tuple(records))
        except (TypeError, ValueError) as error:
            raise DocumentSetReviewSourceMismatch(
                "document set review evidence cannot be reconstructed"
            ) from error

    def get_document_set_review_evidence(
        self,
        company_id: str,
        manifest_id: str,
    ) -> DocumentSetReviewEvidence | None:
        tenant = _require_tenant(company_id)
        with self.transaction(tenant) as connection:
            try:
                return self._load_document_set_review_evidence(
                    connection,
                    tenant,
                    manifest_id,
                )
            except DocumentSetReviewNotFound:
                return None

    @staticmethod
    def _load_document_set_review_decision(
        connection: Connection,
        tenant: str,
        manifest_id: str,
    ) -> DocumentSetReviewDecision:
        row = (
            connection.execute(
                select(document_set_completeness_decisions).where(
                    and_(
                        document_set_completeness_decisions.c.company_id == tenant,
                        document_set_completeness_decisions.c.manifest_id == manifest_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise DocumentSetReviewNotFound("document set completeness decision was not found")
        try:
            decision = DocumentSetReviewDecision.model_validate_json(
                json.dumps(row["decision"], ensure_ascii=False)
            )
            attestation_rows = tuple(
                connection.execute(
                    select(document_set_completeness_member_attestations)
                    .where(
                        and_(
                            document_set_completeness_member_attestations.c.company_id == tenant,
                            document_set_completeness_member_attestations.c.manifest_id
                            == manifest_id,
                        )
                    )
                    .order_by(document_set_completeness_member_attestations.c.ordinal)
                ).mappings()
            )
            attestations = tuple(
                DocumentSetMemberAttestation.model_validate_json(
                    json.dumps(item["attestation"], ensure_ascii=False)
                )
                for item in attestation_rows
            )
        except (TypeError, ValueError) as error:
            raise DocumentSetReviewSourceMismatch(
                "stored document set decision is invalid"
            ) from error
        if (
            row["company_id"] != tenant
            or row["manifest_id"] != manifest_id
            or row["manifest_evidence_sha256"] != decision.manifest_evidence_sha256
            or row["status"] != decision.status.value
            or row["decision_sha256"] != decision.decision_sha256
            or row["decided_by"] != decision.decided_by
            or row["created_at"] != decision.decided_at
            or attestations != decision.members
        ):
            raise DocumentSetReviewSourceMismatch(
                "stored document set decision columns do not match payload"
            )
        for item, attestation in zip(attestation_rows, attestations, strict=True):
            reference = attestation.reference
            if (
                item["company_id"] != tenant
                or item["manifest_id"] != manifest_id
                or item["ordinal"] != reference.member_ordinal
                or item["review_id"] != reference.review_id
                or item["review_evidence_sha256"] != reference.review_evidence_sha256
                or item["decision_sha256"] != reference.decision_sha256
                or item["assessment"] != attestation.assessment.value
            ):
                raise DocumentSetReviewSourceMismatch(
                    "stored document set attestation columns do not match payload"
                )

        evidence = PostgresStorage._load_document_set_review_evidence(
            connection,
            tenant,
            manifest_id,
        )
        reviewer_findings = tuple(
            item for item in decision.findings if item.origin is DocumentSetFindingOrigin.REVIEWER
        )
        try:
            rebuilt = build_document_set_review_decision(
                evidence,
                attestations=attestations,
                inventory_assessment=decision.inventory_assessment,
                inventory_rationale=decision.inventory_rationale,
                cross_document_assessment=decision.cross_document_assessment,
                cross_document_rationale=decision.cross_document_rationale,
                reviewer_findings=reviewer_findings,
                status=decision.status,
                reason=decision.reason,
                decided_by=decision.decided_by,
                decided_at=decision.decided_at,
            )
        except (TypeError, ValueError) as error:
            raise DocumentSetReviewSourceMismatch(
                "stored document set decision cannot be reconstructed"
            ) from error
        if rebuilt != decision:
            raise DocumentSetReviewSourceMismatch(
                "stored document set decision does not match current exact evidence"
            )
        return decision

    def store_document_set_review_decision(
        self,
        company_id: str,
        reviewer_id: str,
        manifest_id: str,
        manifest_evidence_sha256: str,
        attestations: tuple[DocumentSetMemberAttestation, ...],
        inventory_assessment: DocumentSetInventoryAssessment,
        inventory_rationale: str,
        cross_document_assessment: DocumentSetCrossAssessment,
        cross_document_rationale: str,
        reviewer_findings: tuple[DocumentSetFinding, ...],
        status: CompletenessStatus,
        reason: str,
        idempotency_key: str,
        request_sha256: str,
    ) -> DocumentSetReviewDecision:
        """Atomically persist the only terminal decision for an exact document set."""
        tenant = _require_tenant(company_id)
        _require_sha256(manifest_evidence_sha256, field="manifest_evidence_sha256")
        _require_sha256(request_sha256, field="request_sha256")
        if not reviewer_id.strip() or not manifest_id.strip():
            raise ValueError("reviewer_id and manifest_id must not be blank")
        now = datetime.now(UTC)
        try:
            with self.transaction(tenant) as connection:
                operation = "store_document_set_review_decision"
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection,
                    tenant,
                    operation,
                    idempotency_key,
                    request_sha256,
                )
                if replay is not None:
                    return self._load_document_set_review_decision(
                        connection,
                        tenant,
                        str(replay["manifest_id"]),
                    )
                evidence = self._load_document_set_review_evidence(
                    connection,
                    tenant,
                    manifest_id,
                )
                if evidence.manifest.evidence_sha256 != manifest_evidence_sha256:
                    raise DocumentSetReviewConflict("document set manifest evidence is stale")
                existing = connection.execute(
                    select(document_set_completeness_decisions.c.manifest_id).where(
                        and_(
                            document_set_completeness_decisions.c.company_id == tenant,
                            document_set_completeness_decisions.c.manifest_id == manifest_id,
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    raise DocumentSetReviewConflict("document set already has a terminal decision")
                decision = build_document_set_review_decision(
                    evidence,
                    attestations=attestations,
                    inventory_assessment=inventory_assessment,
                    inventory_rationale=inventory_rationale,
                    cross_document_assessment=cross_document_assessment,
                    cross_document_rationale=cross_document_rationale,
                    reviewer_findings=reviewer_findings,
                    status=status,
                    reason=reason,
                    decided_by=reviewer_id,
                    decided_at=now,
                )
                connection.execute(
                    insert(document_set_completeness_decisions).values(
                        company_id=tenant,
                        manifest_id=manifest_id,
                        manifest_evidence_sha256=decision.manifest_evidence_sha256,
                        status=decision.status.value,
                        decision_sha256=decision.decision_sha256,
                        decision=decision.model_dump(mode="json"),
                        decided_by=reviewer_id,
                        created_at=now,
                    )
                )
                connection.execute(
                    insert(document_set_completeness_member_attestations),
                    [
                        {
                            "company_id": tenant,
                            "manifest_id": manifest_id,
                            "ordinal": item.reference.member_ordinal,
                            "review_id": item.reference.review_id,
                            "review_evidence_sha256": (item.reference.review_evidence_sha256),
                            "decision_sha256": item.reference.decision_sha256,
                            "assessment": item.assessment.value,
                            "attestation": item.model_dump(mode="json"),
                        }
                        for item in decision.members
                    ],
                )
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=reviewer_id,
                            event_type="document_set.completeness_decided",
                            object_type="document_set_completeness_decision",
                            object_id=manifest_id,
                            basis={
                                "manifest_evidence_sha256": (decision.manifest_evidence_sha256),
                                "decision_sha256": decision.decision_sha256,
                                "status": decision.status.value,
                                "constituent_decisions": [
                                    item.reference.model_dump(mode="json")
                                    for item in decision.members
                                ],
                            },
                            occurred_at=now,
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"manifest_id": manifest_id},
                )
                return decision
        except (
            DocumentSetReviewConflict,
            DocumentSetReviewNotFound,
            DocumentSetReviewSourceMismatch,
        ):
            raise
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise DocumentSetReviewConflict(
                    "document set completeness decision conflicts"
                ) from error
            raise

    def get_document_set_review_decision(
        self,
        company_id: str,
        manifest_id: str,
    ) -> DocumentSetReviewDecision | None:
        tenant = _require_tenant(company_id)
        with self.transaction(tenant) as connection:
            try:
                return self._load_document_set_review_decision(
                    connection,
                    tenant,
                    manifest_id,
                )
            except DocumentSetReviewNotFound:
                return None

    def store_case_document_evidence_binding(
        self,
        company_id: str,
        actor_id: str,
        manifest_id: str,
        manifest_evidence_sha256: str,
        decision_sha256: str,
        idempotency_key: str,
        request_sha256: str,
        *,
        binding_id: str | None = None,
    ) -> CaseDocumentEvidenceBinding:
        """Atomically bind one exact terminal document-set decision to a case draft."""
        tenant = _require_tenant(company_id)
        _require_sha256(manifest_evidence_sha256, field="manifest_evidence_sha256")
        _require_sha256(decision_sha256, field="decision_sha256")
        _require_sha256(request_sha256, field="request_sha256")
        if not actor_id.strip() or not manifest_id.strip():
            raise ValueError("actor_id and manifest_id must not be blank")
        chosen_id = binding_id or str(uuid.uuid4())
        now = datetime.now(UTC)
        try:
            with self.transaction(tenant) as connection:
                operation = "store_case_document_evidence_binding"
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, operation, idempotency_key, request_sha256
                )
                if replay is not None:
                    return self._load_case_document_evidence_binding(
                        connection,
                        tenant,
                        str(replay["binding_id"]),
                    )
                try:
                    evidence = self._load_document_set_review_evidence(
                        connection,
                        tenant,
                        manifest_id,
                    )
                except DocumentSetReviewNotFound as error:
                    raise CaseEvidenceNotFound("selected document set was not found") from error
                except DocumentSetReviewSourceMismatch as error:
                    raise CaseEvidenceSourceMismatch(
                        "stored document set evidence is invalid"
                    ) from error
                if evidence.manifest.evidence_sha256 != manifest_evidence_sha256:
                    raise CaseEvidenceSourceMismatch("selected manifest evidence is stale")
                try:
                    decision = self._load_document_set_review_decision(
                        connection,
                        tenant,
                        manifest_id,
                    )
                except DocumentSetReviewNotFound as error:
                    raise CaseEvidenceNotFound(
                        "terminal document set decision was not found"
                    ) from error
                except DocumentSetReviewSourceMismatch as error:
                    raise CaseEvidenceSourceMismatch(
                        "stored document set decision is invalid"
                    ) from error
                if decision.decision_sha256 != decision_sha256:
                    raise CaseEvidenceSourceMismatch("selected terminal decision is stale")
                try:
                    binding = build_case_document_evidence_binding(
                        evidence,
                        decision,
                        company_id=tenant,
                        binding_id=chosen_id,
                        bound_by=actor_id,
                        bound_at=now,
                    )
                except ValueError as error:
                    raise CaseEvidenceSourceMismatch(
                        "exact document set evidence cannot be bound"
                    ) from error
                connection.execute(
                    insert(case_document_evidence_bindings).values(
                        company_id=tenant,
                        binding_id=chosen_id,
                        manifest_id=manifest_id,
                        manifest_evidence_sha256=binding.manifest_evidence_sha256,
                        decision_sha256=binding.decision_sha256,
                        status=binding.status.value,
                        binding_sha256=binding.binding_sha256,
                        binding=binding.model_dump(mode="json"),
                        bound_by=actor_id,
                        bound_at=now,
                        created_at=now,
                    )
                )
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=actor_id,
                            event_type="case.evidence_binding_created",
                            object_type="case_document_evidence_binding",
                            object_id=chosen_id,
                            basis={
                                "manifest_id": manifest_id,
                                "manifest_evidence_sha256": (binding.manifest_evidence_sha256),
                                "decision_sha256": binding.decision_sha256,
                                "status": binding.status.value,
                                "binding_sha256": binding.binding_sha256,
                            },
                            occurred_at=now,
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"binding_id": chosen_id},
                )
                return binding
        except (
            CaseEvidenceConflict,
            CaseEvidenceNotFound,
            CaseEvidenceSourceMismatch,
        ):
            raise
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise CaseEvidenceConflict("case document evidence binding conflicts") from error
            raise

    def get_case_document_evidence_binding(
        self,
        company_id: str,
        binding_id: str,
    ) -> CaseDocumentEvidenceBinding | None:
        tenant = _require_tenant(company_id)
        with self.transaction(tenant) as connection:
            try:
                return self._load_case_document_evidence_binding(
                    connection,
                    tenant,
                    binding_id,
                )
            except CaseEvidenceNotFound:
                return None

    def _load_case_document_evidence_binding(
        self,
        connection: Connection,
        tenant: str,
        binding_id: str,
    ) -> CaseDocumentEvidenceBinding:
        row = (
            connection.execute(
                select(case_document_evidence_bindings).where(
                    and_(
                        case_document_evidence_bindings.c.company_id == tenant,
                        case_document_evidence_bindings.c.binding_id == binding_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise CaseEvidenceNotFound("case document evidence binding was not found")
        try:
            binding = CaseDocumentEvidenceBinding.model_validate_json(
                json.dumps(row["binding"], ensure_ascii=False)
            )
        except (TypeError, ValueError) as error:
            raise CaseEvidenceSourceMismatch("stored case evidence binding is invalid") from error
        if (
            row["company_id"] != tenant
            or row["binding_id"] != binding_id
            or row["manifest_id"] != binding.manifest_id
            or row["manifest_evidence_sha256"] != binding.manifest_evidence_sha256
            or row["decision_sha256"] != binding.decision_sha256
            or row["status"] != binding.status.value
            or row["binding_sha256"] != binding.binding_sha256
            or row["bound_by"] != binding.bound_by
            or row["bound_at"] != binding.bound_at
            or row["created_at"] != binding.bound_at
        ):
            raise CaseEvidenceSourceMismatch(
                "stored case evidence binding columns do not match payload"
            )
        try:
            evidence = self._load_document_set_review_evidence(
                connection,
                tenant,
                binding.manifest_id,
            )
            decision = self._load_document_set_review_decision(
                connection,
                tenant,
                binding.manifest_id,
            )
            rebuilt = build_case_document_evidence_binding(
                evidence,
                decision,
                company_id=tenant,
                binding_id=binding.binding_id,
                bound_by=binding.bound_by,
                bound_at=binding.bound_at,
            )
        except (DocumentSetReviewNotFound, DocumentSetReviewSourceMismatch) as error:
            raise CaseEvidenceSourceMismatch(
                "case evidence binding source evidence is no longer exact"
            ) from error
        except (TypeError, ValueError) as error:
            raise CaseEvidenceSourceMismatch(
                "stored case evidence binding cannot be reconstructed"
            ) from error
        if rebuilt != binding:
            raise CaseEvidenceSourceMismatch(
                "stored case evidence binding does not match current exact evidence"
            )
        return binding

    def decide_completeness_review(
        self,
        company_id: str,
        reviewer_id: str,
        review_id: str,
        evidence_sha256: str,
        status: CompletenessStatus,
        scope: str,
        reason: str,
        block_decisions: tuple[CompletenessBlockDecision, ...],
        idempotency_key: str,
        request_sha256: str,
    ) -> CompletenessReviewRecord:
        """Validate and atomically persist the only decision for a review snapshot."""
        tenant = _require_tenant(company_id)
        _require_sha256(request_sha256, field="request_sha256")
        _require_sha256(evidence_sha256, field="evidence_sha256")
        now = datetime.now(UTC)
        try:
            with self.transaction(tenant) as connection:
                operation = "decide_document_completeness_review"
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, operation, idempotency_key, request_sha256
                )
                if replay is not None:
                    replayed = self._load_completeness_review(connection, tenant, review_id)
                    self._verify_completeness_source_bytes(connection, tenant, replayed.snapshot)
                    return replayed
                current = self._load_completeness_review(connection, tenant, review_id)
                if current.decision is not None:
                    raise CompletenessReviewConflict("completeness review already has a decision")
                snapshot = current.snapshot
                if snapshot.created_by == reviewer_id:
                    raise CompletenessReviewConflict("reviewer cannot decide their own snapshot")
                if snapshot.evidence_sha256 != evidence_sha256:
                    raise CompletenessReviewConflict("completeness review evidence is stale")
                self._verify_completeness_source_bytes(connection, tenant, snapshot)
                try:
                    decision = build_completeness_review_decision(
                        snapshot,
                        status=status,
                        scope=scope,
                        reason=reason,
                        block_decisions=block_decisions,
                        decided_by=reviewer_id,
                        decided_at=now,
                        review_reference=f"document-completeness-review:{review_id}",
                    )
                except ValueError as error:
                    raise CompletenessReviewSourceMismatch(
                        "invalid completeness decision"
                    ) from error
                connection.execute(
                    insert(document_completeness_review_decisions).values(
                        company_id=tenant,
                        review_id=review_id,
                        evidence_sha256=evidence_sha256,
                        status=status.value,
                        decision=decision.model_dump(mode="json"),
                        decided_by=reviewer_id,
                        created_at=now,
                    )
                )
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=reviewer_id,
                            event_type="document.completeness_review_decided",
                            object_type="document_completeness_review",
                            object_id=review_id,
                            basis={
                                "status": status.value,
                                "evidence_sha256": evidence_sha256,
                                "scope": scope.strip(),
                                "reason": reason.strip(),
                                "decision_sha256": canonical_json_sha256(decision),
                            },
                            occurred_at=now,
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"review_id": review_id, "status": status.value},
                )
                return CompletenessReviewRecord(snapshot=snapshot, decision=decision)
        except (
            CompletenessReviewConflict,
            CompletenessReviewNotFound,
            CompletenessReviewSourceMismatch,
        ):
            raise
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise CompletenessReviewConflict("completeness decision conflicts") from error
            raise

    def materialize_ai_transfer_requirement_batch(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
    ) -> tuple[
        tuple[AiTransferRequirementResult, ...],
        AiRequirementReviewRecord | None,
        AiTransferRequirementChunkRejection | None,
    ]:
        """Persist available ordered chunk results and publish only a complete batch."""
        tenant = _require_tenant(company_id)
        if not worker_id.strip() or worker_id != worker_id.strip():
            raise AiTransferSourceMismatch("AI transfer batch materialization actor is invalid")
        provider = self._raw_key_provider
        if provider is None:
            raise AiTransferSourceMismatch("raw response encryption key is unavailable")
        try:
            with self.transaction(tenant) as connection:
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                    {"lock_key": f"ai-transfer-batch-materialization:{tenant}:{execution_id}"},
                )
                admission, _, _ = self._load_ai_transfer_execution(connection, tenant, execution_id)
                if admission.chunk_count <= 1:
                    raise AiTransferConflict(
                        "AI transfer batch materialization requires multiple chunks"
                    )
                request, approval = self._load_ai_transfer(
                    connection, tenant, admission.transfer_id
                )
                if approval is None:
                    raise AiTransferSourceMismatch(
                        "AI transfer batch materialization approval evidence is absent"
                    )
                claims, receipts = self._load_ai_transfer_dispatch_history(
                    connection,
                    tenant,
                    execution_id,
                    request=request,
                    approval=approval,
                    admission=admission,
                )
                if any(
                    receipt.outcome != "SUCCESS"
                    or receipt.reason != "VALIDATED_RESPONSE"
                    or not receipt.capture_complete
                    for receipt in receipts
                ):
                    raise AiTransferConflict(
                        "AI transfer batch contains a non-successful terminal chunk"
                    )
                source = self._ai_transfer_source(connection, tenant, request.source_document_id)
                existing_rows = (
                    connection.execute(
                        select(ai_transfer_requirement_chunk_results)
                        .where(
                            and_(
                                ai_transfer_requirement_chunk_results.c.company_id == tenant,
                                ai_transfer_requirement_chunk_results.c.execution_id
                                == execution_id,
                                ai_transfer_requirement_chunk_results.c.parser_version
                                == AI_TRANSFER_REQUIREMENT_PARSER_VERSION,
                            )
                        )
                        .order_by(ai_transfer_requirement_chunk_results.c.ordinal)
                    )
                    .mappings()
                    .all()
                )
                results_by_ordinal: dict[int, AiTransferRequirementResult] = {}
                for row in existing_rows:
                    result = AiTransferRequirementResult.model_validate_json(
                        json.dumps(row["result"], ensure_ascii=False)
                    )
                    projection = {
                        "company_id": result.company_id,
                        "execution_id": result.execution_id,
                        "ordinal": result.ordinal,
                        "parser_version": AI_TRANSFER_REQUIREMENT_PARSER_VERSION,
                        "transfer_id": result.transfer_id,
                        "result_id": result.result_id,
                        "request_payload_sha256": result.request_payload_sha256,
                        "claim_id": result.claim_id,
                        "claim_payload_sha256": result.claim_payload_sha256,
                        "receipt_id": result.receipt_id,
                        "receipt_payload_sha256": result.receipt_payload_sha256,
                        "raw_response_id": result.raw_response_id,
                        "raw_metadata_sha256": result.raw_metadata_sha256,
                        "result_payload_sha256": result.payload_sha256,
                        "materialized_by": result.materialized_by,
                        "materialized_at": result.materialized_at,
                        "created_at": result.materialized_at,
                    }
                    if any(row[key] != value for key, value in projection.items()):
                        raise AiTransferSourceMismatch(
                            "AI transfer chunk result projection differs"
                        )
                    results_by_ordinal[result.ordinal] = result

                rejection_row = (
                    connection.execute(
                        select(ai_transfer_requirement_chunk_rejections).where(
                            and_(
                                ai_transfer_requirement_chunk_rejections.c.company_id == tenant,
                                ai_transfer_requirement_chunk_rejections.c.execution_id
                                == execution_id,
                                ai_transfer_requirement_chunk_rejections.c.parser_version
                                == AI_TRANSFER_REQUIREMENT_PARSER_VERSION,
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if rejection_row is not None:
                    rejection = AiTransferRequirementChunkRejection.model_validate_json(
                        json.dumps(rejection_row["rejection"], ensure_ascii=False)
                    )
                    projection = {
                        "company_id": rejection.company_id,
                        "execution_id": rejection.execution_id,
                        "ordinal": rejection.ordinal,
                        "parser_version": rejection.parser_version,
                        "transfer_id": rejection.transfer_id,
                        "rejection_id": rejection.rejection_id,
                        "request_payload_sha256": rejection.request_payload_sha256,
                        "claim_id": rejection.claim_id,
                        "claim_payload_sha256": rejection.claim_payload_sha256,
                        "receipt_id": rejection.receipt_id,
                        "receipt_payload_sha256": rejection.receipt_payload_sha256,
                        "raw_response_id": rejection.raw_response_id,
                        "raw_metadata_sha256": rejection.raw_metadata_sha256,
                        "reason": rejection.reason,
                        "rejected_by": rejection.rejected_by,
                        "rejected_at": rejection.rejected_at,
                        "payload_sha256": rejection.payload_sha256,
                        "created_at": rejection.rejected_at,
                    }
                    if any(rejection_row[key] != value for key, value in projection.items()):
                        raise AiTransferSourceMismatch(
                            "AI transfer chunk rejection projection differs"
                        )
                    ordered_existing = tuple(
                        results_by_ordinal[ordinal] for ordinal in sorted(results_by_ordinal)
                    )
                    return ordered_existing, None, rejection

                for claim, receipt in zip(claims, receipts, strict=False):
                    existing_result = results_by_ordinal.get(claim.ordinal)
                    if existing_result is not None:
                        if (
                            existing_result.claim_id != claim.claim_id
                            or existing_result.receipt_id != receipt.receipt_id
                        ):
                            raise AiTransferSourceMismatch(
                                "AI transfer chunk result durable binding differs"
                            )
                        continue
                    raw_row = (
                        connection.execute(
                            select(ai_transfer_raw_responses).where(
                                and_(
                                    ai_transfer_raw_responses.c.company_id == tenant,
                                    ai_transfer_raw_responses.c.execution_id == execution_id,
                                    ai_transfer_raw_responses.c.ordinal == claim.ordinal,
                                )
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if raw_row is None:
                        raise AiTransferConflict(
                            "AI transfer chunk result requires retained raw capture"
                        )
                    raw_metadata = self._validated_ai_transfer_raw_metadata(raw_row)
                    checked_metadata, envelope = self._load_ai_transfer_raw_envelope(
                        connection, tenant, raw_metadata.raw_response_id
                    )
                    materialized_at = connection.execute(
                        select(func.clock_timestamp())
                    ).scalar_one()
                    if materialized_at >= checked_metadata.expires_at:
                        raise AiTransferConflict("AI transfer raw response retention expired")
                    try:
                        raw_response = decrypt_ai_transfer_raw_response(
                            envelope=envelope,
                            expected_metadata=checked_metadata,
                            key_provider=provider,
                            at=materialized_at,
                        )
                        result = build_ai_transfer_requirement_result(
                            request,
                            claim,
                            receipt,
                            checked_metadata,
                            raw_response,
                            source.extraction,
                            result_id=str(uuid.uuid4()),
                            prepared_by=request.prepared_by,
                            materialized_by=worker_id,
                            materialized_at=materialized_at,
                        )
                    except AiTransferRawError as error:
                        raise AiTransferSourceMismatch(
                            "AI transfer chunk semantic evidence is invalid"
                        ) from error
                    except AiTransferRequirementResultError as error:
                        if (
                            error.code
                            is not AiTransferRequirementResultErrorCode.INVALID_WIRE_RESPONSE
                        ):
                            raise AiTransferSourceMismatch(
                                "AI transfer chunk semantic evidence is invalid"
                            ) from error
                        rejected_at = connection.execute(
                            select(func.clock_timestamp())
                        ).scalar_one()
                        if rejected_at >= checked_metadata.expires_at:
                            raise AiTransferConflict(
                                "AI transfer raw response retention expired"
                            ) from None
                        rejection = build_ai_transfer_requirement_chunk_rejection(
                            request,
                            claim,
                            receipt,
                            checked_metadata,
                            rejection_id=str(uuid.uuid4()),
                            rejected_by=worker_id,
                            rejected_at=rejected_at,
                        )
                        connection.execute(
                            insert(ai_transfer_requirement_chunk_rejections).values(
                                company_id=tenant,
                                execution_id=execution_id,
                                ordinal=rejection.ordinal,
                                parser_version=rejection.parser_version,
                                transfer_id=rejection.transfer_id,
                                rejection_id=rejection.rejection_id,
                                request_payload_sha256=rejection.request_payload_sha256,
                                claim_id=rejection.claim_id,
                                claim_payload_sha256=rejection.claim_payload_sha256,
                                receipt_id=rejection.receipt_id,
                                receipt_payload_sha256=rejection.receipt_payload_sha256,
                                raw_response_id=rejection.raw_response_id,
                                raw_metadata_sha256=rejection.raw_metadata_sha256,
                                reason=rejection.reason,
                                rejection=rejection.model_dump(mode="json"),
                                rejected_by=rejection.rejected_by,
                                rejected_at=rejection.rejected_at,
                                payload_sha256=rejection.payload_sha256,
                                created_at=rejection.rejected_at,
                            )
                        )
                        connection.execute(
                            insert(audit_events).values(
                                **AuditEventRecord(
                                    event_id=str(uuid.uuid4()),
                                    company_id=tenant,
                                    actor_id=worker_id,
                                    event_type=("document.ai_transfer_chunk_requirement_rejected"),
                                    object_type="ai_transfer_requirement_chunk_rejection",
                                    object_id=rejection.rejection_id,
                                    basis={
                                        "execution_id": execution_id,
                                        "ordinal": rejection.ordinal,
                                        "claim_id": rejection.claim_id,
                                        "receipt_id": rejection.receipt_id,
                                        "raw_response_id": rejection.raw_response_id,
                                        "reason": rejection.reason,
                                        "payload_sha256": rejection.payload_sha256,
                                    },
                                    occurred_at=rejection.rejected_at,
                                ).model_dump(mode="python")
                            )
                        )
                        ordered_existing = tuple(
                            results_by_ordinal[ordinal] for ordinal in sorted(results_by_ordinal)
                        )
                        return ordered_existing, None, rejection
                    connection.execute(
                        insert(ai_transfer_requirement_chunk_results).values(
                            company_id=tenant,
                            execution_id=execution_id,
                            ordinal=result.ordinal,
                            parser_version=AI_TRANSFER_REQUIREMENT_PARSER_VERSION,
                            transfer_id=result.transfer_id,
                            result_id=result.result_id,
                            request_payload_sha256=result.request_payload_sha256,
                            claim_id=result.claim_id,
                            claim_payload_sha256=result.claim_payload_sha256,
                            receipt_id=result.receipt_id,
                            receipt_payload_sha256=result.receipt_payload_sha256,
                            raw_response_id=result.raw_response_id,
                            raw_metadata_sha256=result.raw_metadata_sha256,
                            result_payload_sha256=result.payload_sha256,
                            result=result.model_dump(mode="json"),
                            materialized_by=result.materialized_by,
                            materialized_at=result.materialized_at,
                            created_at=result.materialized_at,
                        )
                    )
                    results_by_ordinal[result.ordinal] = result
                    connection.execute(
                        insert(audit_events).values(
                            **AuditEventRecord(
                                event_id=str(uuid.uuid4()),
                                company_id=tenant,
                                actor_id=worker_id,
                                event_type="document.ai_transfer_chunk_result_materialized",
                                object_type="ai_transfer_requirement_chunk_result",
                                object_id=result.result_id,
                                basis={
                                    "execution_id": execution_id,
                                    "ordinal": result.ordinal,
                                    "claim_id": result.claim_id,
                                    "receipt_id": result.receipt_id,
                                    "raw_response_id": result.raw_response_id,
                                    "payload_sha256": result.payload_sha256,
                                },
                                occurred_at=result.materialized_at,
                            ).model_dump(mode="python")
                        )
                    )

                ordered_results = tuple(
                    results_by_ordinal[ordinal] for ordinal in sorted(results_by_ordinal)
                )
                if len(ordered_results) != admission.chunk_count:
                    return ordered_results, None, None
                existing_batch = (
                    connection.execute(
                        select(ai_transfer_requirement_batch_results).where(
                            and_(
                                ai_transfer_requirement_batch_results.c.company_id == tenant,
                                ai_transfer_requirement_batch_results.c.execution_id
                                == execution_id,
                                ai_transfer_requirement_batch_results.c.parser_version
                                == AI_TRANSFER_REQUIREMENT_PARSER_VERSION,
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing_batch is not None:
                    batch = AiTransferRequirementBatchResult.model_validate_json(
                        json.dumps(existing_batch["result"], ensure_ascii=False)
                    )
                    record = self._load_ai_requirement_run(
                        connection, tenant, str(existing_batch["run_id"])
                    )
                    if (
                        batch.chunk_results != ordered_results
                        or batch.payload_sha256 != existing_batch["batch_payload_sha256"]
                        or record.snapshot.evidence_sha256 != existing_batch["run_evidence_sha256"]
                    ):
                        raise AiTransferSourceMismatch(
                            "AI transfer batch result projection differs"
                        )
                    return ordered_results, record, None

                aggregated_at = connection.execute(select(func.clock_timestamp())).scalar_one()
                batch = build_ai_transfer_requirement_batch_result(
                    request,
                    ordered_results,
                    batch_result_id=str(uuid.uuid4()),
                    aggregated_by=worker_id,
                    aggregated_at=aggregated_at,
                )
                run_id = str(uuid.uuid4())
                snapshot = build_ai_requirement_transfer_batch_run_snapshot(
                    run_id=run_id,
                    extraction=source.extraction,
                    result=batch,
                )
                connection.execute(
                    insert(document_ai_requirement_runs).values(
                        company_id=tenant,
                        run_id=run_id,
                        source_document_id=source.document_id,
                        source_sha256=source.sha256,
                        evidence_sha256=snapshot.evidence_sha256,
                        snapshot=snapshot.model_dump(mode="json"),
                        created_at=aggregated_at,
                    )
                )
                connection.execute(
                    insert(ai_transfer_requirement_batch_results).values(
                        company_id=tenant,
                        execution_id=execution_id,
                        parser_version=AI_TRANSFER_REQUIREMENT_PARSER_VERSION,
                        transfer_id=batch.transfer_id,
                        batch_result_id=batch.batch_result_id,
                        request_payload_sha256=batch.request_payload_sha256,
                        batch_payload_sha256=batch.payload_sha256,
                        run_id=run_id,
                        run_evidence_sha256=snapshot.evidence_sha256,
                        result=batch.model_dump(mode="json"),
                        aggregated_by=batch.aggregated_by,
                        aggregated_at=batch.aggregated_at,
                        created_at=batch.aggregated_at,
                    )
                )
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=worker_id,
                            event_type="document.ai_transfer_batch_result_materialized",
                            object_type="ai_transfer_requirement_batch_result",
                            object_id=batch.batch_result_id,
                            basis={
                                "execution_id": execution_id,
                                "chunk_count": len(batch.chunk_results),
                                "run_id": run_id,
                                "run_evidence_sha256": snapshot.evidence_sha256,
                                "payload_sha256": batch.payload_sha256,
                            },
                            occurred_at=batch.aggregated_at,
                        ).model_dump(mode="python")
                    )
                )
                return ordered_results, AiRequirementReviewRecord(snapshot=snapshot), None
        except (AiTransferConflict, AiTransferNotFound, AiTransferSourceMismatch):
            raise
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) in {
                "23503",
                "23505",
                "23514",
            }:
                raise AiTransferConflict("AI transfer batch materialization conflicts") from error
            raise

    def materialize_ai_transfer_requirement_run(
        self,
        company_id: str,
        worker_id: str,
        execution_id: str,
    ) -> tuple[
        AiTransferRequirementMaterialization,
        AiRequirementReviewRecord | None,
    ]:
        """Idempotently materialize one captured single-chunk response for review.

        This transaction performs no network operation.  Durable transport/raw
        evidence already exists and is never rolled back by semantic rejection.
        """
        tenant = _require_tenant(company_id)
        if not worker_id.strip() or worker_id != worker_id.strip():
            raise AiTransferSourceMismatch("AI transfer materialization actor is invalid")
        provider = self._raw_key_provider
        if provider is None:
            raise AiTransferSourceMismatch("raw response encryption key is unavailable")
        try:
            with self.transaction(tenant) as connection:
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                    {"lock_key": f"ai-transfer-materialization:{tenant}:{execution_id}"},
                )
                existing = self._load_ai_transfer_requirement_materialization(
                    connection, tenant, execution_id
                )
                if existing is not None:
                    return existing

                admission, claim, receipt = self._load_ai_transfer_execution(
                    connection, tenant, execution_id
                )
                if claim is None or receipt is None:
                    raise AiTransferConflict(
                        "AI transfer materialization requires terminal dispatch evidence"
                    )
                request, approval = self._load_ai_transfer(
                    connection, tenant, admission.transfer_id
                )
                if approval is None:
                    raise AiTransferSourceMismatch(
                        "AI transfer materialization approval evidence is absent"
                    )
                raw_row = (
                    connection.execute(
                        select(ai_transfer_raw_responses).where(
                            and_(
                                ai_transfer_raw_responses.c.company_id == tenant,
                                ai_transfer_raw_responses.c.execution_id == execution_id,
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if raw_row is None:
                    raise AiTransferConflict(
                        "AI transfer materialization requires a complete retained capture"
                    )
                raw_metadata = self._validated_ai_transfer_raw_metadata(raw_row)
                materialized_at = connection.execute(select(func.clock_timestamp())).scalar_one()

                if len(request.chunks) != 1:
                    rejected = build_ai_transfer_requirement_materialization(
                        request,
                        claim,
                        receipt,
                        raw_metadata,
                        materialization_id=str(uuid.uuid4()),
                        status="REJECTED",
                        reason="UNSUPPORTED_MULTI_CHUNK",
                        result=None,
                        run_id=None,
                        run_evidence_sha256=None,
                        materialized_by=worker_id,
                        materialized_at=materialized_at,
                    )
                    self._insert_ai_transfer_requirement_materialization(connection, rejected)
                    self._audit_ai_transfer_requirement_materialization(connection, rejected)
                    return rejected, None

                connection.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                    {"lock_key": (f"ai-transfer-raw:{tenant}:{raw_metadata.raw_response_id}")},
                )
                checked_metadata, envelope = self._load_ai_transfer_raw_envelope(
                    connection, tenant, raw_metadata.raw_response_id
                )
                now = connection.execute(select(func.clock_timestamp())).scalar_one()
                if now >= checked_metadata.expires_at:
                    raise AiTransferConflict("AI transfer raw response retention expired")
                try:
                    raw_response = decrypt_ai_transfer_raw_response(
                        envelope=envelope,
                        expected_metadata=checked_metadata,
                        key_provider=provider,
                        at=now,
                    )
                except AiTransferRawError as error:
                    raise AiTransferSourceMismatch(
                        "encrypted AI transfer evidence is invalid"
                    ) from error
                materialized_at = connection.execute(select(func.clock_timestamp())).scalar_one()
                if materialized_at >= checked_metadata.expires_at:
                    raise AiTransferConflict("AI transfer raw response retention expired")

                source_row = (
                    connection.execute(
                        select(documents).where(
                            and_(
                                documents.c.company_id == tenant,
                                documents.c.document_id == request.source_document_id,
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if source_row is None:
                    raise AiTransferSourceMismatch(
                        "AI transfer materialization source is unavailable"
                    )
                source = DocumentRecord.model_validate(dict(source_row))
                if (
                    source.document_role is not DocumentRole.TENDER_REQUIREMENTS
                    or source.sha256 != request.source_sha256
                    or hashlib.sha256(source.content).hexdigest() != source.sha256
                    or len(source.content) != source.byte_size
                ):
                    raise AiTransferSourceMismatch(
                        "AI transfer materialization source evidence changed"
                    )
                try:
                    result = build_ai_transfer_requirement_result(
                        request,
                        claim,
                        receipt,
                        checked_metadata,
                        raw_response,
                        source.extraction,
                        result_id=str(uuid.uuid4()),
                        prepared_by=request.prepared_by,
                        materialized_by=worker_id,
                        materialized_at=materialized_at,
                    )
                except AiTransferRequirementResultError as error:
                    if error.code is not AiTransferRequirementResultErrorCode.INVALID_WIRE_RESPONSE:
                        raise AiTransferSourceMismatch(
                            "AI transfer materialization evidence is invalid"
                        ) from error
                    retention_checked_at = connection.execute(
                        select(func.clock_timestamp())
                    ).scalar_one()
                    if retention_checked_at >= checked_metadata.expires_at:
                        raise AiTransferConflict(
                            "AI transfer raw response retention expired"
                        ) from None
                    rejected = build_ai_transfer_requirement_materialization(
                        request,
                        claim,
                        receipt,
                        checked_metadata,
                        materialization_id=str(uuid.uuid4()),
                        status="REJECTED",
                        reason="INVALID_CANDIDATE_EVIDENCE",
                        result=None,
                        run_id=None,
                        run_evidence_sha256=None,
                        materialized_by=worker_id,
                        materialized_at=materialized_at,
                    )
                    self._insert_ai_transfer_requirement_materialization(connection, rejected)
                    self._audit_ai_transfer_requirement_materialization(connection, rejected)
                    return rejected, None

                retention_checked_at = connection.execute(
                    select(func.clock_timestamp())
                ).scalar_one()
                if retention_checked_at >= checked_metadata.expires_at:
                    raise AiTransferConflict("AI transfer raw response retention expired")
                run_id = str(uuid.uuid4())
                snapshot = build_ai_requirement_transfer_run_snapshot(
                    run_id=run_id,
                    extraction=source.extraction,
                    result=result,
                )
                materialization = build_ai_transfer_requirement_materialization(
                    request,
                    claim,
                    receipt,
                    checked_metadata,
                    materialization_id=str(uuid.uuid4()),
                    status="MATERIALIZED",
                    reason="MATERIALIZED",
                    result=result,
                    run_id=run_id,
                    run_evidence_sha256=snapshot.evidence_sha256,
                    materialized_by=worker_id,
                    materialized_at=materialized_at,
                )
                connection.execute(
                    insert(document_ai_requirement_runs).values(
                        company_id=tenant,
                        run_id=run_id,
                        source_document_id=source.document_id,
                        source_sha256=source.sha256,
                        evidence_sha256=snapshot.evidence_sha256,
                        snapshot=snapshot.model_dump(mode="json"),
                        created_at=materialized_at,
                    )
                )
                self._insert_ai_transfer_requirement_materialization(connection, materialization)
                self._audit_ai_transfer_requirement_materialization(connection, materialization)
                return materialization, AiRequirementReviewRecord(snapshot=snapshot)
        except (AiTransferConflict, AiTransferSourceMismatch):
            raise
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) in {
                "23503",
                "23505",
                "23514",
            }:
                raise AiTransferConflict(
                    "AI transfer requirement materialization conflicts"
                ) from error
            raise

    @staticmethod
    def _audit_ai_transfer_requirement_materialization(
        connection: Connection,
        receipt: AiTransferRequirementMaterialization,
    ) -> None:
        connection.execute(
            insert(audit_events).values(
                **AuditEventRecord(
                    event_id=str(uuid.uuid4()),
                    company_id=receipt.company_id,
                    actor_id=receipt.materialized_by,
                    event_type="document.ai_transfer_requirement_materialization_recorded",
                    object_type="ai_transfer_requirement_materialization",
                    object_id=receipt.materialization_id,
                    basis={
                        "execution_id": receipt.execution_id,
                        "receipt_id": receipt.receipt_id,
                        "raw_response_id": receipt.raw_response_id,
                        "parser_version": receipt.parser_version,
                        "status": receipt.status,
                        "reason": receipt.reason,
                        "run_id": receipt.run_id,
                        "run_evidence_sha256": receipt.run_evidence_sha256,
                        "payload_sha256": receipt.payload_sha256,
                    },
                    occurred_at=receipt.materialized_at,
                ).model_dump(mode="python")
            )
        )

    @staticmethod
    def _insert_ai_transfer_requirement_materialization(
        connection: Connection,
        receipt: AiTransferRequirementMaterialization,
    ) -> None:
        connection.execute(
            insert(ai_transfer_requirement_materializations).values(
                company_id=receipt.company_id,
                materialization_id=receipt.materialization_id,
                transfer_id=receipt.transfer_id,
                execution_id=receipt.execution_id,
                ordinal=receipt.ordinal,
                claim_id=receipt.claim_id,
                receipt_id=receipt.receipt_id,
                raw_response_id=receipt.raw_response_id,
                request_payload_sha256=receipt.request_payload_sha256,
                claim_payload_sha256=receipt.claim_payload_sha256,
                receipt_payload_sha256=receipt.receipt_payload_sha256,
                raw_metadata_sha256=receipt.raw_metadata_sha256,
                parser_version=receipt.parser_version,
                status=receipt.status,
                reason=receipt.reason,
                result_id=receipt.result_id,
                result_payload_sha256=receipt.result_payload_sha256,
                run_id=receipt.run_id,
                run_evidence_sha256=receipt.run_evidence_sha256,
                materialization=receipt.model_dump(mode="json"),
                materialized_by=receipt.materialized_by,
                materialized_at=receipt.materialized_at,
                payload_sha256=receipt.payload_sha256,
                created_at=receipt.materialized_at,
            )
        )

    @staticmethod
    def _load_ai_transfer_requirement_materialization(
        connection: Connection,
        tenant: str,
        execution_id: str,
    ) -> (
        tuple[
            AiTransferRequirementMaterialization,
            AiRequirementReviewRecord | None,
        ]
        | None
    ):
        row = (
            connection.execute(
                select(ai_transfer_requirement_materializations).where(
                    and_(
                        ai_transfer_requirement_materializations.c.company_id == tenant,
                        ai_transfer_requirement_materializations.c.execution_id == execution_id,
                        ai_transfer_requirement_materializations.c.parser_version
                        == AI_TRANSFER_REQUIREMENT_PARSER_VERSION,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        try:
            receipt = AiTransferRequirementMaterialization.model_validate_json(
                json.dumps(row["materialization"], ensure_ascii=False)
            )
            projection = {
                "company_id": receipt.company_id,
                "materialization_id": receipt.materialization_id,
                "transfer_id": receipt.transfer_id,
                "execution_id": receipt.execution_id,
                "ordinal": receipt.ordinal,
                "claim_id": receipt.claim_id,
                "receipt_id": receipt.receipt_id,
                "raw_response_id": receipt.raw_response_id,
                "request_payload_sha256": receipt.request_payload_sha256,
                "claim_payload_sha256": receipt.claim_payload_sha256,
                "receipt_payload_sha256": receipt.receipt_payload_sha256,
                "raw_metadata_sha256": receipt.raw_metadata_sha256,
                "parser_version": receipt.parser_version,
                "status": receipt.status,
                "reason": receipt.reason,
                "result_id": receipt.result_id,
                "result_payload_sha256": receipt.result_payload_sha256,
                "run_id": receipt.run_id,
                "run_evidence_sha256": receipt.run_evidence_sha256,
                "materialized_by": receipt.materialized_by,
                "materialized_at": receipt.materialized_at,
                "payload_sha256": receipt.payload_sha256,
                "created_at": receipt.materialized_at,
            }
            if any(row[key] != value for key, value in projection.items()):
                raise ValueError("AI transfer materialization projection differs")
            if receipt.status == "REJECTED":
                return receipt, None
            if receipt.run_id is None:
                raise ValueError("materialized AI transfer run ID is absent")
            record = PostgresStorage._load_ai_requirement_run(connection, tenant, receipt.run_id)
            snapshot = record.snapshot
            if not isinstance(snapshot, AiRequirementTransferRunSnapshot) or (
                snapshot.result.result_id != receipt.result_id
                or snapshot.result.payload_sha256 != receipt.result_payload_sha256
                or snapshot.evidence_sha256 != receipt.run_evidence_sha256
                or snapshot.result.execution_id != receipt.execution_id
                or snapshot.result.raw_response_id != receipt.raw_response_id
            ):
                raise ValueError("materialized AI transfer run differs from its receipt")
            return receipt, record
        except (KeyError, TypeError, ValueError) as error:
            raise AiTransferSourceMismatch(
                "AI transfer materialization evidence is invalid"
            ) from error

    @staticmethod
    def _load_ai_requirement_run(
        connection: Connection,
        tenant: str,
        run_id: str,
    ) -> AiRequirementReviewRecord:
        row = (
            connection.execute(
                select(
                    document_ai_requirement_runs.c.snapshot,
                    document_ai_requirement_review_decisions.c.decision,
                    ai_transfer_requirement_materializations.c.materialization,
                    ai_transfer_requirement_batch_results.c.result.label("batch_result"),
                )
                .select_from(
                    document_ai_requirement_runs.outerjoin(
                        document_ai_requirement_review_decisions,
                        and_(
                            document_ai_requirement_review_decisions.c.company_id
                            == document_ai_requirement_runs.c.company_id,
                            document_ai_requirement_review_decisions.c.run_id
                            == document_ai_requirement_runs.c.run_id,
                        ),
                    )
                    .outerjoin(
                        ai_transfer_requirement_materializations,
                        and_(
                            ai_transfer_requirement_materializations.c.company_id
                            == document_ai_requirement_runs.c.company_id,
                            ai_transfer_requirement_materializations.c.run_id
                            == document_ai_requirement_runs.c.run_id,
                            ai_transfer_requirement_materializations.c.status == "MATERIALIZED",
                        ),
                    )
                    .outerjoin(
                        ai_transfer_requirement_batch_results,
                        and_(
                            ai_transfer_requirement_batch_results.c.company_id
                            == document_ai_requirement_runs.c.company_id,
                            ai_transfer_requirement_batch_results.c.run_id
                            == document_ai_requirement_runs.c.run_id,
                        ),
                    )
                )
                .where(
                    and_(
                        document_ai_requirement_runs.c.company_id == tenant,
                        document_ai_requirement_runs.c.run_id == run_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise AiRequirementRunNotFound("AI requirement run was not found")
        snapshot_json = json.dumps(row["snapshot"], ensure_ascii=False)
        schema_version = row["snapshot"].get("schema_version")
        if schema_version == "persisted-ai-requirement-run-v1":
            snapshot: (
                AiRequirementRunSnapshot
                | AiRequirementTransferRunSnapshot
                | AiRequirementTransferBatchRunSnapshot
            ) = AiRequirementRunSnapshot.model_validate_json(snapshot_json)
        elif schema_version == "persisted-ai-requirement-run-v2":
            snapshot = AiRequirementTransferRunSnapshot.model_validate_json(snapshot_json)
            if row["materialization"] is None:
                raise AiRequirementRunSourceMismatch(
                    "server-managed AI requirement run lacks materialization evidence"
                )
            materialization = AiTransferRequirementMaterialization.model_validate_json(
                json.dumps(row["materialization"], ensure_ascii=False)
            )
            result = snapshot.result
            if (
                materialization.status != "MATERIALIZED"
                or materialization.reason != "MATERIALIZED"
                or materialization.company_id != snapshot.company_id
                or materialization.run_id != snapshot.run_id
                or materialization.run_evidence_sha256 != snapshot.evidence_sha256
                or materialization.result_id != result.result_id
                or materialization.result_payload_sha256 != result.payload_sha256
                or materialization.transfer_id != result.transfer_id
                or materialization.execution_id != result.execution_id
                or materialization.ordinal != result.ordinal
                or materialization.claim_id != result.claim_id
                or materialization.receipt_id != result.receipt_id
                or materialization.raw_response_id != result.raw_response_id
                or materialization.request_payload_sha256 != result.request_payload_sha256
                or materialization.claim_payload_sha256 != result.claim_payload_sha256
                or materialization.receipt_payload_sha256 != result.receipt_payload_sha256
                or materialization.raw_metadata_sha256 != result.raw_metadata_sha256
                or materialization.materialized_by != result.materialized_by
                or materialization.materialized_at != result.materialized_at
            ):
                raise AiRequirementRunSourceMismatch(
                    "server-managed AI requirement materialization differs"
                )
        elif schema_version == "persisted-ai-requirement-run-v3":
            snapshot = AiRequirementTransferBatchRunSnapshot.model_validate_json(snapshot_json)
            if row["batch_result"] is None:
                raise AiRequirementRunSourceMismatch(
                    "server-managed AI transfer batch lacks persisted result"
                )
            batch = AiTransferRequirementBatchResult.model_validate_json(
                json.dumps(row["batch_result"], ensure_ascii=False)
            )
            if batch != snapshot.result:
                raise AiRequirementRunSourceMismatch("server-managed AI transfer batch differs")
        else:
            raise AiRequirementRunSourceMismatch("AI requirement run schema version is invalid")
        decision = (
            None
            if row["decision"] is None
            else AiRequirementReviewDecision.model_validate_json(
                json.dumps(row["decision"], ensure_ascii=False)
            )
        )
        return AiRequirementReviewRecord(snapshot=snapshot, decision=decision)

    @staticmethod
    def _verify_ai_requirement_source(
        connection: Connection,
        tenant: str,
        snapshot: (
            AiRequirementRunSnapshot
            | AiRequirementTransferRunSnapshot
            | AiRequirementTransferBatchRunSnapshot
        ),
    ) -> None:
        source_row = (
            connection.execute(
                select(documents).where(
                    and_(
                        documents.c.company_id == tenant,
                        documents.c.document_id == snapshot.source_document_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if source_row is None:
            raise AiRequirementRunSourceMismatch("AI run source is unavailable")
        source = DocumentRecord.model_validate(dict(source_row))
        if (
            source.document_role is not DocumentRole.TENDER_REQUIREMENTS
            or source.sha256 != snapshot.source_sha256
            or hashlib.sha256(source.content).hexdigest() != snapshot.source_sha256
            or len(source.content) != source.byte_size
            or source.extraction != snapshot.extraction
        ):
            raise AiRequirementRunSourceMismatch("AI run source evidence changed")

    def store_ai_requirement_run(
        self,
        company_id: str,
        actor_id: str,
        source_document_id: str,
        report: Mapping[str, object] | AiRequirementAnalysisReport | AiRequirementAnalysisReportV2,
        idempotency_key: str,
        request_sha256: str,
        *,
        run_id: str | None = None,
    ) -> AiRequirementReviewRecord:
        """Persist an imported report bound only to the exact stored extraction."""
        tenant = _require_tenant(company_id)
        _require_sha256(request_sha256, field="request_sha256")
        if not actor_id.strip() or not source_document_id.strip():
            raise ValueError("actor_id and source_document_id must not be blank")
        chosen_id = run_id or str(uuid.uuid4())
        if not chosen_id.strip():
            raise ValueError("run_id must not be blank")
        now = datetime.now(UTC)
        try:
            with self.transaction(tenant) as connection:
                operation = "store_document_ai_requirement_run"
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, operation, idempotency_key, request_sha256
                )
                if replay is not None:
                    original = self._load_ai_requirement_run(
                        connection, tenant, str(replay["run_id"])
                    )
                    if (
                        not isinstance(original.snapshot, AiRequirementRunSnapshot)
                        or original.snapshot.submitted_by != actor_id
                    ):
                        raise AiRequirementReviewConflict("AI run replay actor differs")
                    self._verify_ai_requirement_source(connection, tenant, original.snapshot)
                    return AiRequirementReviewRecord(snapshot=original.snapshot)
                source_row = (
                    connection.execute(
                        select(documents).where(
                            and_(
                                documents.c.company_id == tenant,
                                documents.c.document_id == source_document_id,
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if source_row is None:
                    raise AiRequirementRunNotFound("source document was not found")
                source = DocumentRecord.model_validate(dict(source_row))
                if (
                    source.document_role is not DocumentRole.TENDER_REQUIREMENTS
                    or hashlib.sha256(source.content).hexdigest() != source.sha256
                    or len(source.content) != source.byte_size
                ):
                    raise AiRequirementRunSourceMismatch("stored source is not eligible")
                try:
                    snapshot = build_ai_requirement_run_snapshot(
                        company_id=tenant,
                        run_id=chosen_id,
                        source_document_id=source.document_id,
                        source_sha256=source.sha256,
                        extraction=source.extraction,
                        report=report,
                        submitted_by=actor_id,
                        submitted_at=now,
                    )
                except ValueError as error:
                    raise AiRequirementRunSourceMismatch(
                        "imported AI report does not match stored source"
                    ) from error
                connection.execute(
                    insert(document_ai_requirement_runs).values(
                        company_id=tenant,
                        run_id=chosen_id,
                        source_document_id=source.document_id,
                        source_sha256=source.sha256,
                        evidence_sha256=snapshot.evidence_sha256,
                        snapshot=snapshot.model_dump(mode="json"),
                        created_at=now,
                    )
                )
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=actor_id,
                            event_type="document.ai_requirement_run_imported",
                            object_type="document_ai_requirement_run",
                            object_id=chosen_id,
                            basis={
                                "source_document_id": source.document_id,
                                "source_sha256": source.sha256,
                                "evidence_sha256": snapshot.evidence_sha256,
                                "report_schema_version": snapshot.report.schema_version,
                                "execution_status": snapshot.report.execution_status.value,
                            },
                            occurred_at=now,
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"run_id": chosen_id},
                )
                return AiRequirementReviewRecord(snapshot=snapshot)
        except (
            AiRequirementReviewConflict,
            AiRequirementRunNotFound,
            AiRequirementRunSourceMismatch,
        ):
            raise
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise AiRequirementReviewConflict("AI requirement run conflicts") from error
            raise

    def get_ai_requirement_run(
        self,
        company_id: str,
        run_id: str,
    ) -> AiRequirementReviewRecord | None:
        tenant = _require_tenant(company_id)
        with self.transaction(tenant) as connection:
            try:
                return self._load_ai_requirement_run(connection, tenant, run_id)
            except AiRequirementRunNotFound:
                return None

    def list_ai_requirement_runs(
        self,
        company_id: str,
        *,
        limit: int = 100,
    ) -> tuple[AiRequirementReviewRecord, ...]:
        tenant = _require_tenant(company_id)
        if limit < 1 or limit > 200:
            raise ValueError("AI requirement run limit must be between 1 and 200")
        with self.transaction(tenant) as connection:
            run_ids = connection.execute(
                select(document_ai_requirement_runs.c.run_id)
                .where(document_ai_requirement_runs.c.company_id == tenant)
                .order_by(
                    document_ai_requirement_runs.c.created_at.desc(),
                    document_ai_requirement_runs.c.run_id.desc(),
                )
                .limit(limit)
            ).scalars()
            return tuple(
                self._load_ai_requirement_run(connection, tenant, run_id) for run_id in run_ids
            )

    def decide_ai_requirement_review(
        self,
        company_id: str,
        reviewer_id: str,
        run_id: str,
        evidence_sha256: str,
        candidate_decisions: tuple[AiRequirementCandidateDecision, ...],
        idempotency_key: str,
        request_sha256: str,
    ) -> AiRequirementReviewRecord:
        """Atomically persist the only independent terminal review decision."""
        tenant = _require_tenant(company_id)
        _require_sha256(evidence_sha256, field="evidence_sha256")
        _require_sha256(request_sha256, field="request_sha256")
        if not reviewer_id.strip():
            raise ValueError("reviewer_id must not be blank")
        now = datetime.now(UTC)
        try:
            with self.transaction(tenant) as connection:
                operation = "decide_document_ai_requirement_review"
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, operation, idempotency_key, request_sha256
                )
                if replay is not None:
                    receipt_run_id = replay.get("run_id")
                    if not isinstance(receipt_run_id, str) or receipt_run_id != run_id:
                        raise AiRequirementReviewConflict(
                            "AI review replay run differs from receipt"
                        )
                    replayed = self._load_ai_requirement_run(connection, tenant, receipt_run_id)
                    if replayed.decision is None or replayed.decision.reviewed_by != reviewer_id:
                        raise AiRequirementReviewConflict("AI review replay actor differs")
                    self._verify_ai_requirement_source(connection, tenant, replayed.snapshot)
                    return replayed
                current = self._load_ai_requirement_run(connection, tenant, run_id)
                if current.decision is not None:
                    raise AiRequirementReviewConflict("AI requirement run already has a decision")
                snapshot = current.snapshot
                prepared_by = (
                    snapshot.submitted_by
                    if isinstance(snapshot, AiRequirementRunSnapshot)
                    else snapshot.prepared_by
                )
                if prepared_by == reviewer_id:
                    raise AiRequirementReviewConflict("reviewer cannot decide their own AI run")
                if snapshot.evidence_sha256 != evidence_sha256:
                    raise AiRequirementReviewConflict("AI requirement run evidence is stale")
                self._verify_ai_requirement_source(connection, tenant, snapshot)
                try:
                    decision = build_ai_requirement_review_decision(
                        snapshot,
                        evidence_sha256=evidence_sha256,
                        candidate_decisions=candidate_decisions,
                        reviewed_by=reviewer_id,
                        reviewed_at=now,
                    )
                except ValueError as error:
                    raise AiRequirementReviewConflict("invalid AI requirement review") from error
                connection.execute(
                    insert(document_ai_requirement_review_decisions).values(
                        company_id=tenant,
                        run_id=run_id,
                        evidence_sha256=evidence_sha256,
                        decision=decision.model_dump(mode="json"),
                        reviewed_by=reviewer_id,
                        created_at=now,
                    )
                )
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=reviewer_id,
                            event_type="document.ai_requirement_review_decided",
                            object_type="document_ai_requirement_run",
                            object_id=run_id,
                            basis={
                                "evidence_sha256": evidence_sha256,
                                "candidate_decisions_total": len(candidate_decisions),
                                "decision_sha256": canonical_json_sha256(decision),
                            },
                            occurred_at=now,
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"run_id": run_id},
                )
                return AiRequirementReviewRecord(snapshot=snapshot, decision=decision)
        except (
            AiRequirementReviewConflict,
            AiRequirementRunNotFound,
            AiRequirementRunSourceMismatch,
        ):
            raise
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise AiRequirementReviewConflict("AI requirement decision conflicts") from error
            raise

    def store_document_search_index(
        self,
        company_id: str,
        actor_id: str,
        source_document_id: str,
        entry: DocumentSearchEntry | dict[str, Any],
        idempotency_key: str,
        request_sha256: str,
        *,
        search_index_id: str | None = None,
    ) -> DocumentSearchIndexRecord:
        """Persist verified search material, audit fact, and receipt atomically."""
        tenant = _require_tenant(company_id)
        if not actor_id.strip():
            raise ValueError("actor_id must not be empty")
        if not source_document_id.strip():
            raise ValueError("source_document_id must not be empty")
        _require_sha256(request_sha256, field="request_sha256")
        try:
            checked_entry = DocumentSearchEntry.model_validate(entry)
        except (TypeError, ValueError) as error:
            raise ValueError("entry must match the typed document search schema") from error
        if checked_entry.company_id != tenant or checked_entry.document_id != source_document_id:
            raise ValueError("search entry tenant/document identity does not match request")

        chosen_id = search_index_id or str(uuid.uuid4())
        if not chosen_id.strip():
            raise ValueError("search_index_id must not be empty")
        normalized_entry = checked_entry.model_dump(mode="json")
        entry_sha256 = hashlib.sha256(
            json.dumps(
                normalized_entry,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        created_at = datetime.now(UTC)

        try:
            with self.transaction(tenant) as connection:
                operation = "store_document_search_index"
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection,
                    tenant,
                    operation,
                    idempotency_key,
                    request_sha256,
                )
                if replay is not None:
                    replay_id = replay.get("search_index_id")
                    row = (
                        connection.execute(
                            select(document_search_indexes).where(
                                and_(
                                    document_search_indexes.c.company_id == tenant,
                                    document_search_indexes.c.search_index_id == replay_id,
                                )
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if row is None:
                        raise StorageError(
                            "stored document search receipt points to a missing record"
                        )
                    return DocumentSearchIndexRecord.model_validate(dict(row))

                source_row = (
                    connection.execute(
                        select(documents).where(
                            and_(
                                documents.c.company_id == tenant,
                                documents.c.document_id == source_document_id,
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if source_row is None:
                    raise StorageError("source document is not visible to tenant")
                source = DocumentRecord.model_validate(dict(source_row))
                rebuilt = build_document_search_entry(
                    DocumentInput(
                        document_id=source.document_id,
                        filename=source.original_filename,
                        declared_media_type=source.media_type,
                        content=source.content,
                    ),
                    source.extraction,
                    company_id=tenant,
                    title=checked_entry.title,
                    vision_manifest=checked_entry.vision_manifest,
                )
                if rebuilt != checked_entry:
                    raise ValueError("search entry does not match immutable source document")

                row = (
                    connection.execute(
                        insert(document_search_indexes)
                        .values(
                            company_id=tenant,
                            search_index_id=chosen_id,
                            source_document_id=source_document_id,
                            source_document_sha256=source.sha256,
                            entry=normalized_entry,
                            created_at=created_at,
                        )
                        .returning(document_search_indexes)
                    )
                    .mappings()
                    .one()
                )
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=actor_id,
                            event_type="document.search_index_stored",
                            object_type="document_search_index",
                            object_id=chosen_id,
                            basis={
                                "source_document_id": source_document_id,
                                "source_document_sha256": source.sha256,
                                "entry_sha256": entry_sha256,
                                "extraction_status": checked_entry.extraction_status.value,
                                "vision_tags_total": (
                                    len(checked_entry.vision_manifest.tags)
                                    if checked_entry.vision_manifest is not None
                                    else 0
                                ),
                            },
                            occurred_at=created_at,
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"search_index_id": chosen_id},
                )
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise DocumentSearchIndexConflict(
                    f"document search index {chosen_id!r} already exists for tenant"
                ) from error
            raise
        return DocumentSearchIndexRecord.model_validate(dict(row))

    def list_latest_document_search_indexes(
        self,
        company_id: str,
        *,
        limit: int = 200,
    ) -> tuple[DocumentSearchIndexRecord, ...]:
        """List only the newest immutable search version for each visible document."""
        tenant = _require_tenant(company_id)
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        ranked = (
            select(
                *document_search_indexes.c,
                func.row_number()
                .over(
                    partition_by=(
                        document_search_indexes.c.company_id,
                        document_search_indexes.c.source_document_id,
                    ),
                    order_by=(
                        document_search_indexes.c.created_at.desc(),
                        document_search_indexes.c.search_index_id.desc(),
                    ),
                )
                .label("row_number"),
            )
            .where(document_search_indexes.c.company_id == tenant)
            .subquery()
        )
        statement = (
            select(*(ranked.c[column.name] for column in document_search_indexes.c))
            .where(ranked.c.row_number == 1)
            .order_by(ranked.c.created_at.desc(), ranked.c.search_index_id.desc())
            .limit(limit)
        )
        with self.transaction(tenant) as connection:
            rows = connection.execute(statement).mappings().all()
        return tuple(DocumentSearchIndexRecord.model_validate(dict(row)) for row in rows)

    def store_model_brand_catalog(
        self,
        company_id: str,
        actor_id: str,
        catalog: ModelBrandCatalog | dict[str, Any],
        idempotency_key: str,
        request_sha256: str,
    ) -> ModelBrandCatalogRecord:
        """Persist one reviewed catalog, audit event, and receipt atomically."""
        tenant = _require_tenant(company_id)
        if not actor_id.strip():
            raise ValueError("actor_id must not be empty")
        _require_sha256(request_sha256, field="request_sha256")
        try:
            checked = ModelBrandCatalog.model_validate(catalog)
        except (TypeError, ValueError) as error:
            raise ValueError("catalog must match the typed model-brand schema") from error
        if checked.company_id != tenant or checked.approved_by != actor_id:
            raise ValueError("catalog tenant/reviewer identity does not match request")
        normalized = checked.model_dump(mode="json")
        catalog_sha256 = hashlib.sha256(
            json.dumps(
                normalized,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        created_at = checked.created_at
        try:
            with self.transaction(tenant) as connection:
                operation = "store_model_brand_catalog"
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection,
                    tenant,
                    operation,
                    idempotency_key,
                    request_sha256,
                )
                if replay is not None:
                    replay_id = replay.get("catalog_id")
                    row = (
                        connection.execute(
                            select(model_brand_catalogs).where(
                                and_(
                                    model_brand_catalogs.c.company_id == tenant,
                                    model_brand_catalogs.c.catalog_id == replay_id,
                                )
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if row is None:
                        raise StorageError("stored model-brand receipt points to a missing record")
                    return ModelBrandCatalogRecord.model_validate(dict(row))

                self._verify_model_brand_source_evidence(connection, tenant, checked.entries)

                row = (
                    connection.execute(
                        insert(model_brand_catalogs)
                        .values(
                            company_id=tenant,
                            catalog_id=checked.catalog_id,
                            catalog=normalized,
                            created_at=created_at,
                        )
                        .returning(model_brand_catalogs)
                    )
                    .mappings()
                    .one()
                )
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=actor_id,
                            event_type="model_brand.catalog_stored",
                            object_type="model_brand_catalog",
                            object_id=checked.catalog_id,
                            basis={
                                "catalog_sha256": catalog_sha256,
                                "entries_total": len(checked.entries),
                                "approval_reference": checked.approval_reference,
                            },
                            occurred_at=created_at,
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"catalog_id": checked.catalog_id},
                )
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise ModelBrandCatalogConflict(
                    f"model-brand catalog {checked.catalog_id!r} already exists for tenant"
                ) from error
            raise
        return ModelBrandCatalogRecord.model_validate(dict(row))

    def store_model_brand_source_artifact(
        self,
        company_id: str,
        actor_id: str,
        artifact_id: str,
        source_title: str,
        source_url: str,
        original_filename: str,
        content: bytes,
        retrieved_at: datetime,
        idempotency_key: str,
        request_sha256: str,
    ) -> ModelBrandSourceArtifactRecord:
        """Atomically persist exact official PDF bytes, audit event, and receipt."""
        tenant = _require_tenant(company_id)
        if not actor_id.strip():
            raise ValueError("actor_id must not be empty")
        _require_sha256(request_sha256, field="request_sha256")
        raw_content = bytes(content)
        created_at = datetime.now(UTC)
        candidate = ModelBrandSourceArtifactRecord(
            company_id=tenant,
            artifact_id=artifact_id,
            source_title=source_title,
            source_url=source_url,
            original_filename=original_filename,
            media_type="application/pdf",
            byte_size=len(raw_content),
            sha256=hashlib.sha256(raw_content).hexdigest(),
            content=raw_content,
            retrieved_at=retrieved_at,
            created_at=created_at,
        )
        try:
            with self.transaction(tenant) as connection:
                operation = "store_model_brand_source_artifact"
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection,
                    tenant,
                    operation,
                    idempotency_key,
                    request_sha256,
                )
                if replay is not None:
                    replay_id = replay.get("artifact_id")
                    replay_row = (
                        connection.execute(
                            select(model_brand_source_artifacts).where(
                                and_(
                                    model_brand_source_artifacts.c.company_id == tenant,
                                    model_brand_source_artifacts.c.artifact_id == replay_id,
                                )
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if replay_row is None:
                        raise StorageError("source-artifact receipt points to a missing record")
                    return ModelBrandSourceArtifactRecord.model_validate(dict(replay_row))

                row = (
                    connection.execute(
                        insert(model_brand_source_artifacts)
                        .values(**candidate.model_dump(mode="python"))
                        .returning(model_brand_source_artifacts)
                    )
                    .mappings()
                    .one()
                )
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=actor_id,
                            event_type="model_brand.source_artifact_stored",
                            object_type="model_brand_source_artifact",
                            object_id=artifact_id,
                            basis={
                                "sha256": candidate.sha256,
                                "byte_size": candidate.byte_size,
                                "source_url": candidate.source_url,
                            },
                            occurred_at=created_at,
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"artifact_id": artifact_id},
                )
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise ModelBrandSourceArtifactConflict(
                    f"model-brand source artifact {artifact_id!r} already exists for tenant"
                ) from error
            raise
        return ModelBrandSourceArtifactRecord.model_validate(dict(row))

    def get_model_brand_source_artifact(
        self,
        company_id: str,
        artifact_id: str,
    ) -> ModelBrandSourceArtifactRecord | None:
        """Return one tenant-visible source artifact including bytes for internal checks."""
        tenant = _require_tenant(company_id)
        statement = select(model_brand_source_artifacts).where(
            and_(
                model_brand_source_artifacts.c.company_id == tenant,
                model_brand_source_artifacts.c.artifact_id == artifact_id,
            )
        )
        with self.transaction(tenant) as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return None if row is None else ModelBrandSourceArtifactRecord.model_validate(dict(row))

    def store_model_brand_review_proposal(
        self,
        company_id: str,
        actor_id: str,
        proposal: ModelBrandReviewProposal | dict[str, Any],
        idempotency_key: str,
        request_sha256: str,
    ) -> ModelBrandReviewRecord:
        """Persist an immutable draft after verifying every exact source artifact."""
        tenant = _require_tenant(company_id)
        _require_sha256(request_sha256, field="request_sha256")
        checked = ModelBrandReviewProposal.model_validate(proposal)
        if checked.company_id != tenant or checked.submitted_by != actor_id:
            raise ValueError("proposal tenant/submitter identity does not match request")
        try:
            with self.transaction(tenant) as connection:
                operation = "store_model_brand_review_proposal"
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, operation, idempotency_key, request_sha256
                )
                if replay is not None:
                    replay_id = replay.get("proposal_id")
                    return self._load_model_brand_review(connection, tenant, str(replay_id))
                self._verify_model_brand_source_evidence(connection, tenant, checked.entries)
                connection.execute(
                    insert(model_brand_review_proposals).values(
                        company_id=tenant,
                        proposal_id=checked.proposal_id,
                        catalog_id=checked.catalog_id,
                        proposal=checked.model_dump(mode="json"),
                        created_at=checked.submitted_at,
                    )
                )
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=actor_id,
                            event_type="model_brand.review_submitted",
                            object_type="model_brand_review",
                            object_id=checked.proposal_id,
                            basis={
                                "catalog_id": checked.catalog_id,
                                "entries_total": len(checked.entries),
                            },
                            occurred_at=checked.submitted_at,
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"proposal_id": checked.proposal_id},
                )
                return ModelBrandReviewRecord(
                    proposal=checked,
                    status=ModelBrandReviewStatus.DRAFT,
                )
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise ModelBrandReviewConflict(
                    f"model-brand review proposal {checked.proposal_id!r} already exists"
                ) from error
            raise

    @staticmethod
    def _load_model_brand_review(
        connection: Connection,
        tenant: str,
        proposal_id: str,
    ) -> ModelBrandReviewRecord:
        row = (
            connection.execute(
                select(
                    model_brand_review_proposals.c.proposal,
                    model_brand_review_decisions.c.status,
                    model_brand_review_decisions.c.decided_by,
                    model_brand_review_decisions.c.reason,
                    model_brand_review_decisions.c.catalog_id,
                    model_brand_review_decisions.c.created_at.label("decision_created_at"),
                )
                .select_from(
                    model_brand_review_proposals.outerjoin(
                        model_brand_review_decisions,
                        and_(
                            model_brand_review_decisions.c.company_id
                            == model_brand_review_proposals.c.company_id,
                            model_brand_review_decisions.c.proposal_id
                            == model_brand_review_proposals.c.proposal_id,
                        ),
                    )
                )
                .where(
                    and_(
                        model_brand_review_proposals.c.company_id == tenant,
                        model_brand_review_proposals.c.proposal_id == proposal_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ModelBrandReviewNotFound("model-brand review proposal was not found")
        proposal = ModelBrandReviewProposal.model_validate(row["proposal"])
        if row["status"] is None:
            return ModelBrandReviewRecord(proposal=proposal, status=ModelBrandReviewStatus.DRAFT)
        decision = ModelBrandReviewDecisionRecord(
            company_id=tenant,
            proposal_id=proposal_id,
            status=row["status"],
            decided_by=row["decided_by"],
            reason=row["reason"],
            catalog_id=row["catalog_id"],
            created_at=row["decision_created_at"],
        )
        return ModelBrandReviewRecord(
            proposal=proposal,
            status=decision.status,
            decision=decision,
        )

    def list_model_brand_reviews(
        self,
        company_id: str,
        *,
        limit: int = 100,
    ) -> tuple[ModelBrandReviewRecord, ...]:
        """List newest tenant-visible proposals with their derived terminal state."""
        tenant = _require_tenant(company_id)
        if limit < 1 or limit > 200:
            raise ValueError("model-brand review limit must be between 1 and 200")
        with self.transaction(tenant) as connection:
            proposal_ids = (
                connection.execute(
                    select(model_brand_review_proposals.c.proposal_id)
                    .where(model_brand_review_proposals.c.company_id == tenant)
                    .order_by(
                        model_brand_review_proposals.c.created_at.desc(),
                        model_brand_review_proposals.c.proposal_id.desc(),
                    )
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return tuple(
                self._load_model_brand_review(connection, tenant, proposal_id)
                for proposal_id in proposal_ids
            )

    def decide_model_brand_review(
        self,
        company_id: str,
        reviewer_id: str,
        proposal_id: str,
        decision: ModelBrandReviewStatus,
        reason: str,
        idempotency_key: str,
        request_sha256: str,
    ) -> ModelBrandReviewRecord:
        """Atomically publish an approved catalog or record a terminal rejection."""
        tenant = _require_tenant(company_id)
        _require_sha256(request_sha256, field="request_sha256")
        if decision is ModelBrandReviewStatus.DRAFT:
            raise ValueError("review decision must be APPROVED or REJECTED")
        if not reason.strip():
            raise ValueError("review reason must not be blank")
        now = datetime.now(UTC)
        try:
            with self.transaction(tenant) as connection:
                operation = "decide_model_brand_review"
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, operation, idempotency_key, request_sha256
                )
                if replay is not None:
                    return self._load_model_brand_review(connection, tenant, proposal_id)
                current = self._load_model_brand_review(connection, tenant, proposal_id)
                if current.status is not ModelBrandReviewStatus.DRAFT:
                    raise ModelBrandReviewConflict("model-brand review already has a decision")
                if current.proposal.submitted_by == reviewer_id:
                    raise ModelBrandReviewConflict("reviewer cannot decide their own proposal")

                catalog_id: str | None = None
                if decision is ModelBrandReviewStatus.APPROVED:
                    proposal = current.proposal
                    self._verify_model_brand_source_evidence(connection, tenant, proposal.entries)
                    catalog = ModelBrandCatalog(
                        catalog_id=proposal.catalog_id,
                        company_id=tenant,
                        created_at=now,
                        approved_by=reviewer_id,
                        approval_reference=proposal.approval_reference,
                        entries=proposal.entries,
                    )
                    connection.execute(
                        insert(model_brand_catalogs).values(
                            company_id=tenant,
                            catalog_id=catalog.catalog_id,
                            catalog=catalog.model_dump(mode="json"),
                            created_at=now,
                        )
                    )
                    catalog_id = catalog.catalog_id
                    connection.execute(
                        insert(audit_events).values(
                            **AuditEventRecord(
                                event_id=str(uuid.uuid4()),
                                company_id=tenant,
                                actor_id=reviewer_id,
                                event_type="model_brand.catalog_stored",
                                object_type="model_brand_catalog",
                                object_id=catalog_id,
                                basis={"review_proposal_id": proposal_id},
                                occurred_at=now,
                            ).model_dump(mode="python")
                        )
                    )

                decision_record = ModelBrandReviewDecisionRecord(
                    company_id=tenant,
                    proposal_id=proposal_id,
                    status=decision,
                    decided_by=reviewer_id,
                    reason=reason.strip(),
                    catalog_id=catalog_id,
                    created_at=now,
                )
                connection.execute(
                    insert(model_brand_review_decisions).values(
                        **decision_record.model_dump(mode="python")
                    )
                )
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=reviewer_id,
                            event_type=f"model_brand.review_{decision.value.casefold()}",
                            object_type="model_brand_review",
                            object_id=proposal_id,
                            basis={"catalog_id": catalog_id, "reason": reason.strip()},
                            occurred_at=now,
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"proposal_id": proposal_id, "status": decision.value},
                )
                return ModelBrandReviewRecord(
                    proposal=current.proposal,
                    status=decision,
                    decision=decision_record,
                )
        except (ModelBrandReviewConflict, ModelBrandReviewNotFound):
            raise
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise ModelBrandReviewConflict("model-brand review decision conflicts") from error
            raise

    def get_latest_model_brand_catalog(
        self,
        company_id: str,
        *,
        at: datetime,
    ) -> ModelBrandCatalogRecord | None:
        """Return the newest tenant-visible catalog created no later than ``at``."""
        tenant = _require_tenant(company_id)
        if at.utcoffset() is None:
            raise ValueError("model-brand lookup time must include a timezone")
        statement = (
            select(model_brand_catalogs)
            .where(
                and_(
                    model_brand_catalogs.c.company_id == tenant,
                    model_brand_catalogs.c.created_at <= at,
                )
            )
            .order_by(
                model_brand_catalogs.c.created_at.desc(),
                model_brand_catalogs.c.catalog_id.desc(),
            )
            .limit(1)
        )
        with self.transaction(tenant) as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return None if row is None else ModelBrandCatalogRecord.model_validate(dict(row))

    def store_document_bundle(
        self,
        company_id: str,
        actor_id: str,
        original_filename: str,
        media_type: str,
        document_role: DocumentRole,
        content: bytes,
        result: DocumentBundleResult | dict[str, Any],
        idempotency_key: str,
        request_sha256: str,
        *,
        bundle_id: str | None = None,
    ) -> DocumentBundleRecord:
        """Atomically store one ZIP, member snapshots, audit fact, and replay receipt."""
        tenant = _require_tenant(company_id)
        if not actor_id.strip():
            raise ValueError("actor_id must not be empty")
        if not original_filename.strip():
            raise ValueError("original_filename must not be empty")
        normalized_media_type = media_type.strip().casefold()
        if normalized_media_type not in ZIP_MEDIA_TYPES:
            raise ValueError("media_type must be ZIP")
        if not isinstance(document_role, DocumentRole):
            raise TypeError("document_role must be DocumentRole")
        raw_content = bytes(content)
        if not raw_content:
            raise ValueError("document bundle content must not be empty")
        if len(raw_content) > MAX_DOCUMENT_BYTES:
            raise ValueError(f"document bundle content exceeds {MAX_DOCUMENT_BYTES} bytes")
        _require_sha256(request_sha256, field="request_sha256")
        try:
            checked_result = DocumentBundleResult.model_validate(result)
            normalized_result = checked_result.model_dump(mode="json")
        except (TypeError, ValueError) as error:
            raise ValueError("result must match the typed document bundle schema") from error

        chosen_id = bundle_id or str(uuid.uuid4())
        if not chosen_id.strip():
            raise ValueError("bundle_id must not be empty")
        content_sha256 = hashlib.sha256(raw_content).hexdigest()
        created_at = datetime.now(UTC)
        candidate = DocumentBundleRecord(
            company_id=tenant,
            bundle_id=chosen_id,
            original_filename=original_filename,
            media_type=normalized_media_type,
            document_role=document_role,
            byte_size=len(raw_content),
            sha256=content_sha256,
            content=raw_content,
            result=checked_result,
            created_at=created_at,
        )
        result_sha256 = hashlib.sha256(
            json.dumps(
                normalized_result,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

        try:
            with self.transaction(tenant) as connection:
                self._lock_idempotency(
                    connection,
                    tenant,
                    "store_document_bundle",
                    idempotency_key,
                )
                replay = self._existing_receipt(
                    connection,
                    tenant,
                    "store_document_bundle",
                    idempotency_key,
                    request_sha256,
                )
                if replay is not None:
                    replay_id = replay.get("bundle_id")
                    row = (
                        connection.execute(
                            select(document_bundles).where(
                                and_(
                                    document_bundles.c.company_id == tenant,
                                    document_bundles.c.bundle_id == replay_id,
                                )
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if row is None:
                        raise StorageError(
                            "stored document bundle receipt points to a missing record"
                        )
                    return DocumentBundleRecord.model_validate(dict(row))

                row = (
                    connection.execute(
                        insert(document_bundles)
                        .values(
                            **(
                                candidate.model_dump(mode="python", exclude={"result"})
                                | {"result": normalized_result}
                            )
                        )
                        .returning(document_bundles)
                    )
                    .mappings()
                    .one()
                )
                event = AuditEventRecord(
                    event_id=str(uuid.uuid4()),
                    company_id=tenant,
                    actor_id=actor_id,
                    event_type="document_bundle.stored",
                    object_type="document_bundle",
                    object_id=chosen_id,
                    basis={
                        "original_filename": original_filename,
                        "media_type": normalized_media_type,
                        "document_role": document_role.value,
                        "byte_size": len(raw_content),
                        "sha256": content_sha256,
                        "result_sha256": result_sha256,
                        "status": checked_result.status.value,
                        "members_total": checked_result.members_total,
                        "supported_members": checked_result.supported_members,
                        "unsupported_members": checked_result.unsupported_members,
                    },
                    occurred_at=created_at,
                )
                connection.execute(insert(audit_events).values(**event.model_dump(mode="python")))
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation="store_document_bundle",
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"bundle_id": chosen_id},
                )
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise DocumentBundleConflict(
                    f"document bundle {chosen_id!r} already exists for tenant"
                ) from error
            raise
        return DocumentBundleRecord.model_validate(dict(row))

    def get_document_bundle(
        self,
        company_id: str,
        bundle_id: str,
    ) -> DocumentBundleRecord | None:
        """Load one visible immutable ZIP and its member snapshots."""
        tenant = _require_tenant(company_id)
        if not bundle_id:
            raise ValueError("bundle_id must not be empty")
        with self.transaction(tenant) as connection:
            row = (
                connection.execute(
                    select(document_bundles).where(
                        and_(
                            document_bundles.c.company_id == tenant,
                            document_bundles.c.bundle_id == bundle_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else DocumentBundleRecord.model_validate(dict(row))

    @staticmethod
    def _ocr_record(row: Any) -> OcrDerivativeRecord:
        payload = dict(row)
        threshold = payload.get("threshold")
        if threshold is not None:
            payload["threshold"] = float(threshold)
        confidence = payload.get("mean_confidence")
        if confidence is not None:
            payload["mean_confidence"] = float(confidence)
        return OcrDerivativeRecord.model_validate(payload)

    def store_ocr_derivative(
        self,
        company_id: str,
        actor_id: str,
        source_document_id: str,
        *,
        engine: str,
        threshold: float,
        status: str,
        result: dict[str, Any],
        mean_confidence: float | None,
        idempotency_key: str,
        request_sha256: str,
        ocr_id: str | None = None,
    ) -> OcrDerivativeRecord:
        """Atomically store one immutable OCR derivative, audit fact, and receipt."""
        from procurement.documents.ocr import OcrDerivative

        tenant = _require_tenant(company_id)
        if not actor_id.strip():
            raise ValueError("actor_id must not be empty")
        if not source_document_id.strip():
            raise ValueError("source_document_id must not be empty")
        if not engine.strip():
            raise ValueError("engine must not be empty")
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be within [0, 1]")
        if threshold != round(threshold, 2):
            raise ValueError("persisted threshold must have at most two decimal places")
        if status not in ("PASS", "FAIL", "UNKNOWN"):
            raise ValueError("ocr status must be PASS, FAIL, or UNKNOWN")
        if not isinstance(result, dict):
            raise ValueError("ocr result must be a JSON object")
        if mean_confidence is not None and not 0.0 <= mean_confidence <= 1.0:
            raise ValueError("mean_confidence must be within [0, 1]")
        _require_sha256(request_sha256, field="request_sha256")
        try:
            checked_result = OcrDerivative.model_validate(result)
            normalized_result = checked_result.model_dump(mode="json")
        except (TypeError, ValueError) as error:
            raise ValueError("ocr result must match the typed OCR derivative schema") from error
        if checked_result.status.value != status:
            raise ValueError("ocr status does not match the typed OCR derivative")
        chosen_id = ocr_id or str(uuid.uuid4())
        if not chosen_id.strip():
            raise ValueError("ocr_id must not be empty")
        created_at = datetime.now(UTC)
        result_sha256 = hashlib.sha256(
            json.dumps(
                normalized_result,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        try:
            with self.transaction(tenant) as connection:
                self._lock_idempotency(connection, tenant, "store_ocr_derivative", idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, "store_ocr_derivative", idempotency_key, request_sha256
                )
                if replay is not None:
                    replay_id = replay.get("ocr_id")
                    row = (
                        connection.execute(
                            select(document_ocr_derivatives).where(
                                and_(
                                    document_ocr_derivatives.c.company_id == tenant,
                                    document_ocr_derivatives.c.ocr_id == replay_id,
                                )
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if row is None:
                        raise StorageError("stored ocr receipt points to a missing record")
                    return self._ocr_record(row)
                parent = connection.execute(
                    select(documents.c.document_id).where(
                        and_(
                            documents.c.company_id == tenant,
                            documents.c.document_id == source_document_id,
                        )
                    )
                ).scalar_one_or_none()
                if parent is None:
                    raise StorageError("source document does not exist in the tenant")
                row = (
                    connection.execute(
                        insert(document_ocr_derivatives)
                        .values(
                            company_id=tenant,
                            ocr_id=chosen_id,
                            source_document_id=source_document_id,
                            engine=engine,
                            threshold=threshold,
                            status=status,
                            result=normalized_result,
                            mean_confidence=mean_confidence,
                            created_at=created_at,
                        )
                        .returning(document_ocr_derivatives)
                    )
                    .mappings()
                    .one()
                )
                event = AuditEventRecord(
                    event_id=str(uuid.uuid4()),
                    company_id=tenant,
                    actor_id=actor_id,
                    event_type="document.ocr_stored",
                    object_type="source_document",
                    object_id=source_document_id,
                    basis={
                        "ocr_id": chosen_id,
                        "source_document_id": source_document_id,
                        "engine": engine,
                        "threshold": threshold,
                        "status": status,
                        "result_sha256": result_sha256,
                        "mean_confidence": mean_confidence,
                    },
                    occurred_at=created_at,
                )
                connection.execute(insert(audit_events).values(**event.model_dump(mode="python")))
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation="store_ocr_derivative",
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"ocr_id": chosen_id},
                )
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise OcrDerivativeConflict(
                    f"ocr derivative {chosen_id!r} already exists for tenant"
                ) from error
            raise
        return self._ocr_record(dict(row))

    def get_ocr_derivative(self, company_id: str, ocr_id: str) -> OcrDerivativeRecord | None:
        """Load one visible immutable OCR derivative by its identity."""
        tenant = _require_tenant(company_id)
        if not ocr_id:
            raise ValueError("ocr_id must not be empty")
        with self.transaction(tenant) as connection:
            row = (
                connection.execute(
                    select(document_ocr_derivatives).where(
                        and_(
                            document_ocr_derivatives.c.company_id == tenant,
                            document_ocr_derivatives.c.ocr_id == ocr_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else self._ocr_record(row)

    def get_latest_ocr_for_document(
        self, company_id: str, source_document_id: str
    ) -> OcrDerivativeRecord | None:
        """Load the latest visible OCR derivative for one source document."""
        tenant = _require_tenant(company_id)
        if not source_document_id:
            raise ValueError("source_document_id must not be empty")
        with self.transaction(tenant) as connection:
            row = (
                connection.execute(
                    select(document_ocr_derivatives)
                    .where(
                        and_(
                            document_ocr_derivatives.c.company_id == tenant,
                            document_ocr_derivatives.c.source_document_id == source_document_id,
                        )
                    )
                    .order_by(
                        document_ocr_derivatives.c.created_at.desc(),
                        document_ocr_derivatives.c.ocr_id.desc(),
                    )
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else self._ocr_record(row)

    @staticmethod
    def _bundle_member_ocr_record(row: Any) -> BundleMemberOcrRecord:
        payload = dict(row)
        threshold = payload.get("threshold")
        if threshold is not None:
            payload["threshold"] = float(threshold)
        confidence = payload.get("mean_confidence")
        if confidence is not None:
            payload["mean_confidence"] = float(confidence)
        return BundleMemberOcrRecord.model_validate(payload)

    def store_bundle_member_ocr_derivative(
        self,
        company_id: str,
        actor_id: str,
        source_bundle_id: str,
        member_index: int,
        archive_path: str,
        source_member_sha256: str,
        *,
        engine: str,
        threshold: float,
        status: str,
        result: OcrDerivative | dict[str, Any],
        mean_confidence: float | None,
        idempotency_key: str,
        request_sha256: str,
        ocr_id: str | None = None,
    ) -> BundleMemberOcrRecord:
        """Atomically store OCR evidence for one verified scan-only PDF member."""
        tenant = _require_tenant(company_id)
        if not actor_id.strip():
            raise ValueError("actor_id must not be empty")
        if not source_bundle_id.strip():
            raise ValueError("source_bundle_id must not be empty")
        if member_index < 0:
            raise ValueError("member_index must not be negative")
        if not archive_path.strip():
            raise ValueError("archive_path must not be empty")
        _require_sha256(source_member_sha256, field="source_member_sha256")
        if not engine.strip():
            raise ValueError("engine must not be empty")
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be within [0, 1]")
        if threshold != round(threshold, 2):
            raise ValueError("persisted threshold must have at most two decimal places")
        if status not in ("PASS", "FAIL", "UNKNOWN"):
            raise ValueError("OCR status must be PASS, FAIL, or UNKNOWN")
        if mean_confidence is not None and not 0.0 <= mean_confidence <= 1.0:
            raise ValueError("mean_confidence must be within [0, 1]")
        _require_sha256(request_sha256, field="request_sha256")
        try:
            checked_result = OcrDerivative.model_validate(result)
            normalized_result = checked_result.model_dump(mode="json")
        except (TypeError, ValueError) as error:
            raise ValueError("result must match the typed OCR derivative schema") from error
        chosen_id = ocr_id or str(uuid.uuid4())
        if not chosen_id.strip():
            raise ValueError("ocr_id must not be empty")
        created_at = datetime.now(UTC)
        candidate = BundleMemberOcrRecord(
            company_id=tenant,
            ocr_id=chosen_id,
            source_bundle_id=source_bundle_id,
            member_index=member_index,
            archive_path=archive_path,
            source_member_sha256=source_member_sha256,
            engine=engine,
            threshold=threshold,
            status=status,
            result=checked_result,
            mean_confidence=mean_confidence,
            created_at=created_at,
        )
        result_sha256 = hashlib.sha256(
            json.dumps(
                normalized_result,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

        try:
            with self.transaction(tenant) as connection:
                self._lock_idempotency(
                    connection,
                    tenant,
                    "store_bundle_member_ocr_derivative",
                    idempotency_key,
                )
                replay = self._existing_receipt(
                    connection,
                    tenant,
                    "store_bundle_member_ocr_derivative",
                    idempotency_key,
                    request_sha256,
                )
                if replay is not None:
                    replay_id = replay.get("ocr_id")
                    row = (
                        connection.execute(
                            select(document_bundle_member_ocr_derivatives).where(
                                and_(
                                    document_bundle_member_ocr_derivatives.c.company_id == tenant,
                                    document_bundle_member_ocr_derivatives.c.ocr_id == replay_id,
                                )
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if row is None:
                        raise StorageError(
                            "stored bundle member OCR receipt points to a missing record"
                        )
                    return self._bundle_member_ocr_record(row)

                parent_payload = connection.execute(
                    select(document_bundles.c.result).where(
                        and_(
                            document_bundles.c.company_id == tenant,
                            document_bundles.c.bundle_id == source_bundle_id,
                        )
                    )
                ).scalar_one_or_none()
                if parent_payload is None:
                    raise StorageError("source document bundle does not exist in the tenant")
                parent = DocumentBundleResult.model_validate(parent_payload)
                if member_index >= len(parent.members):
                    raise StorageError("source document bundle member does not exist")
                member = parent.members[member_index]
                if (
                    member.archive_path != archive_path
                    or member.sha256 != source_member_sha256
                    or member.media_type != "application/pdf"
                    or member.extraction.status is not ExtractionStatus.UNKNOWN
                    or ExtractionReason.OCR_REQUIRED not in member.extraction.reasons
                ):
                    raise StorageError("source bundle member is not the verified OCR source")

                row = (
                    connection.execute(
                        insert(document_bundle_member_ocr_derivatives)
                        .values(
                            **(
                                candidate.model_dump(mode="python", exclude={"result"})
                                | {"result": normalized_result}
                            )
                        )
                        .returning(document_bundle_member_ocr_derivatives)
                    )
                    .mappings()
                    .one()
                )
                event = AuditEventRecord(
                    event_id=str(uuid.uuid4()),
                    company_id=tenant,
                    actor_id=actor_id,
                    event_type="document_bundle.member_ocr_stored",
                    object_type="document_bundle",
                    object_id=source_bundle_id,
                    basis={
                        "ocr_id": chosen_id,
                        "member_index": member_index,
                        "archive_path": archive_path,
                        "source_member_sha256": source_member_sha256,
                        "engine": engine,
                        "threshold": threshold,
                        "status": status,
                        "result_sha256": result_sha256,
                        "mean_confidence": mean_confidence,
                    },
                    occurred_at=created_at,
                )
                connection.execute(insert(audit_events).values(**event.model_dump(mode="python")))
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation="store_bundle_member_ocr_derivative",
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"ocr_id": chosen_id},
                )
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise BundleMemberOcrConflict(
                    f"bundle member OCR derivative {chosen_id!r} already exists for tenant"
                ) from error
            raise
        return self._bundle_member_ocr_record(row)

    def get_bundle_member_ocr_derivative(
        self,
        company_id: str,
        ocr_id: str,
    ) -> BundleMemberOcrRecord | None:
        """Load one visible bundle-member OCR derivative by identity."""
        tenant = _require_tenant(company_id)
        if not ocr_id:
            raise ValueError("ocr_id must not be empty")
        with self.transaction(tenant) as connection:
            row = (
                connection.execute(
                    select(document_bundle_member_ocr_derivatives).where(
                        and_(
                            document_bundle_member_ocr_derivatives.c.company_id == tenant,
                            document_bundle_member_ocr_derivatives.c.ocr_id == ocr_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else self._bundle_member_ocr_record(row)

    def get_latest_ocr_for_bundle_member(
        self,
        company_id: str,
        source_bundle_id: str,
        member_index: int,
    ) -> BundleMemberOcrRecord | None:
        """Load the latest visible OCR derivative for one exact bundle member."""
        tenant = _require_tenant(company_id)
        if not source_bundle_id:
            raise ValueError("source_bundle_id must not be empty")
        if member_index < 0:
            raise ValueError("member_index must not be negative")
        with self.transaction(tenant) as connection:
            row = (
                connection.execute(
                    select(document_bundle_member_ocr_derivatives)
                    .where(
                        and_(
                            document_bundle_member_ocr_derivatives.c.company_id == tenant,
                            document_bundle_member_ocr_derivatives.c.source_bundle_id
                            == source_bundle_id,
                            document_bundle_member_ocr_derivatives.c.member_index == member_index,
                        )
                    )
                    .order_by(
                        document_bundle_member_ocr_derivatives.c.created_at.desc(),
                        document_bundle_member_ocr_derivatives.c.ocr_id.desc(),
                    )
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else self._bundle_member_ocr_record(row)

    @staticmethod
    def _docx_media_ocr_record(row: Any) -> DocxMediaOcrRecord:
        payload = dict(row)
        threshold = payload.get("threshold")
        if threshold is not None:
            payload["threshold"] = float(threshold)
        confidence = payload.get("mean_confidence")
        if confidence is not None:
            payload["mean_confidence"] = float(confidence)
        return DocxMediaOcrRecord.model_validate(payload)

    def store_docx_media_ocr_derivative(
        self,
        company_id: str,
        actor_id: str,
        source_document_id: str,
        media_index: int,
        archive_path: str,
        source_document_sha256: str,
        source_media_sha256: str,
        media_type: str,
        *,
        engine: str,
        threshold: float,
        status: str,
        result: OcrDerivative | dict[str, Any],
        mean_confidence: float | None,
        idempotency_key: str,
        request_sha256: str,
        ocr_id: str | None = None,
    ) -> DocxMediaOcrRecord:
        """Atomically store OCR evidence for one verified linked DOCX image."""
        tenant = _require_tenant(company_id)
        if not actor_id.strip():
            raise ValueError("actor_id must not be empty")
        if not source_document_id.strip():
            raise ValueError("source_document_id must not be empty")
        if media_index < 0:
            raise ValueError("media_index must not be negative")
        if not archive_path.strip() or len(archive_path) > 512:
            raise ValueError("archive_path must be between 1 and 512 characters")
        _require_sha256(source_document_sha256, field="source_document_sha256")
        _require_sha256(source_media_sha256, field="source_media_sha256")
        if media_type not in ("image/jpeg", "image/png"):
            raise ValueError("media_type must be image/jpeg or image/png")
        if not engine.strip():
            raise ValueError("engine must not be empty")
        if not 0.0 <= threshold <= 1.0 or threshold != round(threshold, 2):
            raise ValueError("persisted threshold must have at most two decimals within [0, 1]")
        if status not in ("PASS", "FAIL", "UNKNOWN"):
            raise ValueError("OCR status must be PASS, FAIL, or UNKNOWN")
        if mean_confidence is not None and not 0.0 <= mean_confidence <= 1.0:
            raise ValueError("mean_confidence must be within [0, 1]")
        _require_sha256(request_sha256, field="request_sha256")
        try:
            checked_result = OcrDerivative.model_validate(result)
            normalized_result = checked_result.model_dump(mode="json")
        except (TypeError, ValueError) as error:
            raise ValueError("result must match the typed OCR derivative schema") from error
        chosen_id = ocr_id or str(uuid.uuid4())
        if not chosen_id.strip():
            raise ValueError("ocr_id must not be empty")
        created_at = datetime.now(UTC)
        candidate = DocxMediaOcrRecord(
            company_id=tenant,
            ocr_id=chosen_id,
            source_document_id=source_document_id,
            media_index=media_index,
            archive_path=archive_path,
            source_document_sha256=source_document_sha256,
            source_media_sha256=source_media_sha256,
            media_type=media_type,
            engine=engine,
            threshold=threshold,
            status=status,
            result=checked_result,
            mean_confidence=mean_confidence,
            created_at=created_at,
        )
        result_sha256 = hashlib.sha256(
            json.dumps(
                normalized_result,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

        try:
            with self.transaction(tenant) as connection:
                operation = "store_docx_media_ocr_derivative"
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection,
                    tenant,
                    operation,
                    idempotency_key,
                    request_sha256,
                )
                if replay is not None:
                    row = (
                        connection.execute(
                            select(document_docx_media_ocr_derivatives).where(
                                and_(
                                    document_docx_media_ocr_derivatives.c.company_id == tenant,
                                    document_docx_media_ocr_derivatives.c.ocr_id
                                    == replay.get("ocr_id"),
                                )
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if row is None:
                        raise StorageError(
                            "stored DOCX-media OCR receipt points to a missing record"
                        )
                    return self._docx_media_ocr_record(row)

                parent_row = (
                    connection.execute(
                        select(documents).where(
                            and_(
                                documents.c.company_id == tenant,
                                documents.c.document_id == source_document_id,
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if parent_row is None:
                    raise StorageError("source document does not exist in the tenant")
                parent = DocumentRecord.model_validate(parent_row)
                if parent.sha256 != source_document_sha256:
                    raise StorageError("source document digest does not match OCR evidence")
                try:
                    media_extraction = extract_docx_media(
                        DocumentInput(
                            document_id=parent.document_id,
                            filename=parent.original_filename,
                            declared_media_type=parent.media_type,
                            content=parent.content,
                        )
                    )
                except DocxMediaRejected as error:
                    raise StorageError(
                        "source document is not a verified DOCX media source"
                    ) from error
                source_media = next(
                    (item for item in media_extraction.media if item.media_index == media_index),
                    None,
                )
                if source_media is None or (
                    source_media.archive_path != archive_path
                    or source_media.sha256 != source_media_sha256
                    or source_media.media_type != media_type
                ):
                    raise StorageError("DOCX media evidence does not match immutable source")

                row = (
                    connection.execute(
                        insert(document_docx_media_ocr_derivatives)
                        .values(
                            **(
                                candidate.model_dump(mode="python", exclude={"result"})
                                | {"result": normalized_result}
                            )
                        )
                        .returning(document_docx_media_ocr_derivatives)
                    )
                    .mappings()
                    .one()
                )
                event = AuditEventRecord(
                    event_id=str(uuid.uuid4()),
                    company_id=tenant,
                    actor_id=actor_id,
                    event_type="document.docx_media_ocr_stored",
                    object_type="document",
                    object_id=source_document_id,
                    basis={
                        "ocr_id": chosen_id,
                        "media_index": media_index,
                        "archive_path": archive_path,
                        "source_document_sha256": source_document_sha256,
                        "source_media_sha256": source_media_sha256,
                        "media_type": media_type,
                        "engine": engine,
                        "threshold": threshold,
                        "status": status,
                        "result_sha256": result_sha256,
                        "mean_confidence": mean_confidence,
                    },
                    occurred_at=created_at,
                )
                connection.execute(insert(audit_events).values(**event.model_dump(mode="python")))
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"ocr_id": chosen_id},
                )
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise DocxMediaOcrConflict(
                    f"DOCX-media OCR derivative {chosen_id!r} already exists for tenant"
                ) from error
            raise
        return self._docx_media_ocr_record(row)

    def get_docx_media_ocr_derivative(
        self,
        company_id: str,
        ocr_id: str,
    ) -> DocxMediaOcrRecord | None:
        """Load one visible DOCX-media OCR derivative by identity."""
        tenant = _require_tenant(company_id)
        if not ocr_id:
            raise ValueError("ocr_id must not be empty")
        with self.transaction(tenant) as connection:
            row = (
                connection.execute(
                    select(document_docx_media_ocr_derivatives).where(
                        and_(
                            document_docx_media_ocr_derivatives.c.company_id == tenant,
                            document_docx_media_ocr_derivatives.c.ocr_id == ocr_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else self._docx_media_ocr_record(row)

    def get_latest_ocr_for_docx_media(
        self,
        company_id: str,
        source_document_id: str,
        media_index: int,
    ) -> DocxMediaOcrRecord | None:
        """Load the latest visible OCR derivative for one exact DOCX image."""
        tenant = _require_tenant(company_id)
        if not source_document_id:
            raise ValueError("source_document_id must not be empty")
        if media_index < 0:
            raise ValueError("media_index must not be negative")
        with self.transaction(tenant) as connection:
            row = (
                connection.execute(
                    select(document_docx_media_ocr_derivatives)
                    .where(
                        and_(
                            document_docx_media_ocr_derivatives.c.company_id == tenant,
                            document_docx_media_ocr_derivatives.c.source_document_id
                            == source_document_id,
                            document_docx_media_ocr_derivatives.c.media_index == media_index,
                        )
                    )
                    .order_by(
                        document_docx_media_ocr_derivatives.c.created_at.desc(),
                        document_docx_media_ocr_derivatives.c.ocr_id.desc(),
                    )
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else self._docx_media_ocr_record(row)

    def create_case_from_evidence(
        self,
        company_id: str,
        actor_id: str,
        case: ProcurementCase,
        binding_id: str,
        manifest_evidence_sha256: str,
        decision_sha256: str,
        other_checks: tuple[GateCheck, ...],
        idempotency_key: str,
        request_sha256: str,
    ) -> ProcurementCase:
        """Create a case version whose DOCUMENT gate comes from exact persisted evidence."""
        tenant = _require_tenant(company_id)
        _require_sha256(manifest_evidence_sha256, field="manifest_evidence_sha256")
        _require_sha256(decision_sha256, field="decision_sha256")
        _require_sha256(request_sha256, field="request_sha256")
        if not actor_id.strip():
            raise ValueError("actor_id must not be blank")
        if not binding_id.strip():
            raise ValueError("binding_id must not be blank")
        draft = ProcurementCase.model_validate(case.model_dump(mode="python"))
        if draft.company_id != tenant:
            raise ValueError("case company_id does not match repository tenant")
        if draft.assessment is not None:
            raise ValueError("case assessment is server-owned for evidence-bound creation")
        if any(check.kind is GateKind.DOCUMENT for check in other_checks):
            raise ValueError("DOCUMENT check is derived from exact evidence, not caller input")
        if len(other_checks) > 5:
            raise ValueError("evidence-bound case accepts at most five additional checks")
        try:
            with self.transaction(tenant) as connection:
                operation = "create_case_from_evidence"
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, operation, idempotency_key, request_sha256
                )
                if replay is not None:
                    stored = connection.execute(
                        select(case_versions.c.payload).where(
                            and_(
                                case_versions.c.company_id == tenant,
                                case_versions.c.case_id == str(replay["case_id"]),
                                case_versions.c.version == int(replay["version"]),
                            )
                        )
                    ).scalar_one_or_none()
                    if stored is None:
                        raise StorageError(
                            "stored case-from-evidence receipt has an invalid response"
                        )
                    return ProcurementCase.model_validate(stored)
                try:
                    binding = self._load_case_document_evidence_binding(
                        connection,
                        tenant,
                        binding_id,
                    )
                except CaseEvidenceNotFound as error:
                    raise CaseEvidenceNotFound(
                        "selected case evidence binding was not found"
                    ) from error
                except CaseEvidenceSourceMismatch as error:
                    raise CaseEvidenceSourceMismatch(
                        "stored case evidence binding is invalid"
                    ) from error
                if (
                    binding.manifest_evidence_sha256 != manifest_evidence_sha256
                    or binding.decision_sha256 != decision_sha256
                ):
                    raise CaseEvidenceSourceMismatch("selected case evidence digests are stale")
                try:
                    document_check = document_gate_check_from_binding(binding)
                except ValueError as error:
                    raise CaseEvidenceSourceMismatch(
                        "case evidence cannot support a DOCUMENT gate"
                    ) from error
                now = datetime.now(UTC)
                assessment = CaseAssessment(
                    reviewer_id=actor_id,
                    assessed_at=now,
                    input_digest=case_input_digest(draft),
                    checks=(document_check, *other_checks),
                )
                full = ProcurementCase.model_validate(
                    draft.model_dump(mode="python")
                    | {"assessment": assessment.model_dump(mode="python")}
                )
                self._insert_case(
                    connection,
                    tenant,
                    full,
                    allow_exact_replay=False,
                )
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=actor_id,
                            event_type="case.created_from_evidence",
                            object_type="case_version",
                            object_id=f"{full.case_id}:v{full.version}",
                            basis={
                                "binding_id": binding.binding_id,
                                "manifest_id": binding.manifest_id,
                                "manifest_evidence_sha256": binding.manifest_evidence_sha256,
                                "decision_sha256": binding.decision_sha256,
                                "binding_sha256": binding.binding_sha256,
                                "document_gate": document_check.status.value,
                            },
                            occurred_at=now,
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"case_id": full.case_id, "version": full.version},
                )
                return full
        except (
            CaseEvidenceConflict,
            CaseEvidenceNotFound,
            CaseEvidenceSourceMismatch,
            CaseVersionConflict,
        ):
            raise
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise CaseVersionConflict(
                    "case version already exists with a different payload"
                ) from error
            raise

    def get_case(
        self,
        company_id: str,
        case_id: str,
        version: int | None = None,
    ) -> ProcurementCase | None:
        """Load one version, or the latest visible version when omitted."""
        tenant = _require_tenant(company_id)
        if not case_id:
            raise ValueError("case_id must not be empty")
        statement = select(case_versions.c.payload).where(
            and_(case_versions.c.company_id == tenant, case_versions.c.case_id == case_id)
        )
        if version is None:
            statement = statement.order_by(case_versions.c.version.desc()).limit(1)
        else:
            if version < 1:
                raise ValueError("version must be positive")
            statement = statement.where(case_versions.c.version == version)
        with self.transaction(tenant) as connection:
            payload = connection.execute(statement).scalar_one_or_none()
        return None if payload is None else ProcurementCase.model_validate(payload)

    def list_case_versions(self, company_id: str, case_id: str) -> list[ProcurementCase]:
        """List every visible immutable version in ascending version order."""
        tenant = _require_tenant(company_id)
        if not case_id:
            raise ValueError("case_id must not be empty")
        statement = (
            select(case_versions.c.payload)
            .where(and_(case_versions.c.company_id == tenant, case_versions.c.case_id == case_id))
            .order_by(case_versions.c.version)
        )
        with self.transaction(tenant) as connection:
            payloads = connection.execute(statement).scalars().all()
        return [ProcurementCase.model_validate(payload) for payload in payloads]

    def store_reviewed_requirement_set_proposal(
        self,
        company_id: str,
        actor_id: str,
        *,
        set_id: str,
        source_document_id: str,
        source_document_sha256: str,
        declared_scope: str,
        expected_entry_count: int,
        entries: tuple[ReviewedRequirementEntry, ...],
        idempotency_key: str,
        request_sha256: str,
    ) -> ReviewedRequirementSetRecord:
        tenant = _require_tenant(company_id)
        _require_sha256(source_document_sha256, field="source_document_sha256")
        _require_sha256(request_sha256, field="request_sha256")
        if not actor_id.strip() or not set_id.strip() or not source_document_id.strip():
            raise ValueError("actor, set, and source document IDs must not be blank")
        now = datetime.now(UTC)
        operation = "store_reviewed_requirement_set_proposal"
        try:
            with self.transaction(tenant) as connection:
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, operation, idempotency_key, request_sha256
                )
                if replay is not None:
                    return self._load_reviewed_requirement_set(
                        connection, tenant, str(replay["set_id"])
                    )
                source = (
                    connection.execute(
                        select(documents.c.sha256, documents.c.document_role).where(
                            and_(
                                documents.c.company_id == tenant,
                                documents.c.document_id == source_document_id,
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if source is None:
                    raise RequirementSetNotFound("source document was not found")
                if source["sha256"] != source_document_sha256:
                    raise RequirementSetSourceMismatch("source document digest is stale")
                if source["document_role"] != "TENDER_REQUIREMENTS":
                    raise RequirementSetSourceMismatch(
                        "reviewed requirements require a TENDER_REQUIREMENTS source"
                    )
                try:
                    proposal = build_reviewed_requirement_set_proposal(
                        company_id=tenant,
                        set_id=set_id,
                        source_document_id=source_document_id,
                        source_document_sha256=source_document_sha256,
                        declared_scope=declared_scope,
                        expected_entry_count=expected_entry_count,
                        entries=entries,
                        prepared_by=actor_id,
                        prepared_at=now,
                    )
                except ValueError as error:
                    raise RequirementSetSourceMismatch(
                        "requirement-set proposal does not match its source scope"
                    ) from error
                connection.execute(
                    insert(reviewed_requirement_set_proposals).values(
                        company_id=tenant,
                        set_id=set_id,
                        source_document_id=source_document_id,
                        source_document_sha256=source_document_sha256,
                        proposal_sha256=proposal.proposal_sha256,
                        proposal=proposal.model_dump(mode="json"),
                        prepared_by=actor_id,
                        prepared_at=now,
                    )
                )
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=actor_id,
                            event_type="requirements.set_prepared",
                            object_type="reviewed_requirement_set",
                            object_id=set_id,
                            basis={
                                "source_document_id": source_document_id,
                                "source_document_sha256": source_document_sha256,
                                "proposal_sha256": proposal.proposal_sha256,
                                "entry_count": expected_entry_count,
                                "manual_entry_count": len(proposal.manual_entry_ordinals),
                            },
                            occurred_at=now,
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"set_id": set_id},
                )
                return ReviewedRequirementSetRecord(proposal=proposal)
        except (RequirementSetNotFound, RequirementSetSourceMismatch):
            raise
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise RequirementSetConflict("reviewed requirement set conflicts") from error
            raise

    def decide_reviewed_requirement_set(
        self,
        company_id: str,
        reviewer_id: str,
        *,
        set_id: str,
        proposal_sha256: str,
        coverage_assessment: RequirementSetCoverageAssessment,
        normalization_assessment: RequirementSetNormalizationAssessment,
        status: Verdict,
        reason: str,
        idempotency_key: str,
        request_sha256: str,
    ) -> ReviewedRequirementSetRecord:
        tenant = _require_tenant(company_id)
        _require_sha256(proposal_sha256, field="proposal_sha256")
        _require_sha256(request_sha256, field="request_sha256")
        if not reviewer_id.strip() or not set_id.strip():
            raise ValueError("reviewer_id and set_id must not be blank")
        now = datetime.now(UTC)
        operation = "decide_reviewed_requirement_set"
        try:
            with self.transaction(tenant) as connection:
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, operation, idempotency_key, request_sha256
                )
                if replay is not None:
                    return self._load_reviewed_requirement_set(
                        connection, tenant, str(replay["set_id"])
                    )
                record = self._load_reviewed_requirement_set(connection, tenant, set_id)
                if record.proposal.proposal_sha256 != proposal_sha256:
                    raise RequirementSetSourceMismatch("selected proposal digest is stale")
                if record.decision is not None:
                    raise RequirementSetConflict("requirement set already has a decision")
                try:
                    decision = build_reviewed_requirement_set_decision(
                        record.proposal,
                        coverage_assessment=coverage_assessment,
                        normalization_assessment=normalization_assessment,
                        status=status,
                        reason=reason,
                        reviewed_by=reviewer_id,
                        reviewed_at=now,
                    )
                except ValueError as error:
                    raise RequirementSetSourceMismatch(
                        "requirement-set decision is not independent or terminal"
                    ) from error
                connection.execute(
                    insert(reviewed_requirement_set_decisions).values(
                        company_id=tenant,
                        set_id=set_id,
                        proposal_sha256=proposal_sha256,
                        decision_sha256=decision.decision_sha256,
                        status=decision.status.value,
                        decision=decision.model_dump(mode="json"),
                        reviewed_by=reviewer_id,
                        reviewed_at=now,
                    )
                )
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=reviewer_id,
                            event_type="requirements.set_reviewed",
                            object_type="reviewed_requirement_set",
                            object_id=set_id,
                            basis={
                                "proposal_sha256": proposal_sha256,
                                "decision_sha256": decision.decision_sha256,
                                "status": decision.status.value,
                                "manual_entry_ordinals": list(
                                    decision.manual_review_entry_ordinals
                                ),
                            },
                            occurred_at=now,
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"set_id": set_id},
                )
                return ReviewedRequirementSetRecord(proposal=record.proposal, decision=decision)
        except (RequirementSetConflict, RequirementSetNotFound, RequirementSetSourceMismatch):
            raise
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise RequirementSetConflict("requirement-set decision conflicts") from error
            raise

    def bind_reviewed_requirement_set_to_case(
        self,
        company_id: str,
        actor_id: str,
        *,
        binding_id: str,
        case_id: str,
        case_version: int,
        set_id: str,
        proposal_sha256: str,
        decision_sha256: str,
        idempotency_key: str,
        request_sha256: str,
    ) -> CaseRequirementSetBinding:
        tenant = _require_tenant(company_id)
        _require_sha256(proposal_sha256, field="proposal_sha256")
        _require_sha256(decision_sha256, field="decision_sha256")
        _require_sha256(request_sha256, field="request_sha256")
        now = datetime.now(UTC)
        operation = "bind_reviewed_requirement_set_to_case"
        try:
            with self.transaction(tenant) as connection:
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, operation, idempotency_key, request_sha256
                )
                if replay is not None:
                    return self._load_case_requirement_set_binding(
                        connection, tenant, str(replay["binding_id"])
                    )
                case_exists = connection.execute(
                    select(case_versions.c.case_id).where(
                        and_(
                            case_versions.c.company_id == tenant,
                            case_versions.c.case_id == case_id,
                            case_versions.c.version == case_version,
                        )
                    )
                ).scalar_one_or_none()
                if case_exists is None:
                    raise RequirementSetNotFound("case version was not found")
                record = self._load_reviewed_requirement_set(connection, tenant, set_id)
                if record.decision is None:
                    raise RequirementSetNotFound("requirement-set decision was not found")
                if (
                    record.proposal.proposal_sha256 != proposal_sha256
                    or record.decision.decision_sha256 != decision_sha256
                ):
                    raise RequirementSetSourceMismatch("selected requirement-set digest is stale")
                try:
                    binding = build_case_requirement_set_binding(
                        record.proposal,
                        record.decision,
                        binding_id=binding_id,
                        case_id=case_id,
                        case_version=case_version,
                        bound_by=actor_id,
                        bound_at=now,
                    )
                except ValueError as error:
                    raise RequirementSetSourceMismatch(
                        "exact reviewed requirement set cannot be bound"
                    ) from error
                connection.execute(
                    insert(case_requirement_set_bindings).values(
                        company_id=tenant,
                        binding_id=binding_id,
                        case_id=case_id,
                        case_version=case_version,
                        set_id=set_id,
                        proposal_sha256=proposal_sha256,
                        decision_sha256=decision_sha256,
                        binding_sha256=binding.binding_sha256,
                        binding=binding.model_dump(mode="json"),
                        bound_by=actor_id,
                        bound_at=now,
                    )
                )
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=actor_id,
                            event_type="case.requirement_set_bound",
                            object_type="case_requirement_set_binding",
                            object_id=binding_id,
                            object_version=case_version,
                            basis={
                                "case_id": case_id,
                                "set_id": set_id,
                                "proposal_sha256": proposal_sha256,
                                "decision_sha256": decision_sha256,
                                "binding_sha256": binding.binding_sha256,
                            },
                            occurred_at=now,
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"binding_id": binding_id},
                )
                return binding
        except (RequirementSetConflict, RequirementSetNotFound, RequirementSetSourceMismatch):
            raise
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise RequirementSetConflict("case requirement-set binding conflicts") from error
            raise

    def get_reviewed_requirement_set(
        self, company_id: str, set_id: str
    ) -> ReviewedRequirementSetRecord | None:
        tenant = _require_tenant(company_id)
        with self.transaction(tenant) as connection:
            try:
                return self._load_reviewed_requirement_set(connection, tenant, set_id)
            except RequirementSetNotFound:
                return None

    def get_case_requirement_set_binding(
        self, company_id: str, binding_id: str
    ) -> CaseRequirementSetBinding | None:
        tenant = _require_tenant(company_id)
        with self.transaction(tenant) as connection:
            try:
                return self._load_case_requirement_set_binding(connection, tenant, binding_id)
            except RequirementSetNotFound:
                return None

    def store_server_offer_proposal(
        self,
        company_id: str,
        actor_id: str,
        *,
        offer_id: str,
        case_id: str,
        case_version: int,
        requirement_set_binding_id: str,
        requirement_set_binding_sha256: str,
        sourcing_run_id: str,
        lead_id: str,
        source_document_id: str,
        source_document_sha256: str,
        bom_lines: tuple[ServerOfferBomLineInput, ...],
        commercial_terms: ServerOfferCommercialTermsInput,
        idempotency_key: str,
        request_sha256: str,
    ) -> ServerOfferProposal:
        """Persist a pending proposal bound to exact case, requirement, lead and quote bytes."""
        tenant = _require_tenant(company_id)
        _require_sha256(requirement_set_binding_sha256, field="requirement_set_binding_sha256")
        _require_sha256(source_document_sha256, field="source_document_sha256")
        _require_sha256(request_sha256, field="request_sha256")
        if not all(
            value.strip()
            for value in (
                actor_id,
                offer_id,
                case_id,
                requirement_set_binding_id,
                sourcing_run_id,
                lead_id,
                source_document_id,
            )
        ):
            raise ValueError("server-offer identities must not be blank")
        if case_version < 1:
            raise ValueError("case_version must be positive")
        operation = "store_server_offer_proposal"
        now = datetime.now(UTC)
        try:
            with self.transaction(tenant) as connection:
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, operation, idempotency_key, request_sha256
                )
                if replay is not None:
                    return self._load_server_offer_proposal(
                        connection, tenant, str(replay["offer_id"])
                    )
                try:
                    binding = self._load_case_requirement_set_binding(
                        connection, tenant, requirement_set_binding_id
                    )
                except RequirementSetNotFound as error:
                    raise ServerOfferNotFound("requirement-set binding was not found") from error
                except RequirementSetSourceMismatch as error:
                    raise ServerOfferSourceMismatch("requirement-set binding is invalid") from error
                if (
                    binding.case_id != case_id
                    or binding.case_version != case_version
                    or binding.binding_sha256 != requirement_set_binding_sha256
                ):
                    raise ServerOfferSourceMismatch(
                        "requirement-set binding does not match the exact case version"
                    )
                run_payload = connection.execute(
                    select(sourcing_runs.c.result).where(
                        and_(
                            sourcing_runs.c.company_id == tenant,
                            sourcing_runs.c.run_id == sourcing_run_id,
                        )
                    )
                ).scalar_one_or_none()
                if run_payload is None:
                    raise ServerOfferNotFound("sourcing run was not found")
                try:
                    run = SourcingRunRecord.model_validate(run_payload)
                except ValueError as error:
                    raise ServerOfferSourceMismatch("stored sourcing run is invalid") from error
                if (
                    run.case_id != case_id
                    or run.case_version != case_version
                    or run.requirement_set_binding_sha256 != binding.binding_sha256
                    or (
                        run.requirement_set_binding_id is not None
                        and run.requirement_set_binding_id != binding.binding_id
                    )
                ):
                    raise ServerOfferSourceMismatch(
                        "sourcing run is not bound to the selected case requirement set"
                    )
                rejected = next(
                    (
                        entry.lead
                        for entry in run.shortlist.rejected
                        if entry.lead.lead_id == lead_id
                    ),
                    None,
                )
                if rejected is not None:
                    raise ServerOfferSourceMismatch(
                        "mandatory FAIL blocks an offer for the selected sourcing lead"
                    )
                lead = next(
                    (
                        entry.lead
                        for entry in run.shortlist.review_queue
                        if entry.lead.lead_id == lead_id
                    ),
                    None,
                )
                if lead is None:
                    raise ServerOfferNotFound("selected sourcing lead was not found")
                source = (
                    connection.execute(
                        select(documents.c.sha256, documents.c.document_role).where(
                            and_(
                                documents.c.company_id == tenant,
                                documents.c.document_id == source_document_id,
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if source is None:
                    raise ServerOfferNotFound("supplier quote document was not found")
                if (
                    source["sha256"] != source_document_sha256
                    or source["document_role"] != DocumentRole.SUPPLIER_QUOTE.value
                ):
                    raise ServerOfferSourceMismatch(
                        "server offer requires the exact SUPPLIER_QUOTE document"
                    )
                try:
                    proposal = build_server_offer_proposal(
                        company_id=tenant,
                        offer_id=offer_id,
                        case_id=case_id,
                        case_version=case_version,
                        requirement_set_binding_id=binding.binding_id,
                        requirement_set_binding_sha256=binding.binding_sha256,
                        sourcing_run_id=run.run_id,
                        lead_id=lead.lead_id,
                        lead_product_name=lead.product_name,
                        lead_product_url=lead.product_url or lead.source_url,
                        lead_source_sha256=lead.source_sha256,
                        source_document_id=source_document_id,
                        source_document_sha256=source_document_sha256,
                        bom_lines=bom_lines,
                        commercial_terms=commercial_terms,
                        prepared_by=actor_id,
                        prepared_at=now,
                    )
                except ValueError as error:
                    raise ServerOfferSourceMismatch(
                        "server-offer facts do not form a valid exact proposal"
                    ) from error
                connection.execute(
                    insert(server_offer_proposals).values(
                        company_id=tenant,
                        offer_id=proposal.offer_id,
                        case_id=proposal.case_id,
                        case_version=proposal.case_version,
                        requirement_set_binding_id=proposal.requirement_set_binding_id,
                        requirement_set_binding_sha256=proposal.requirement_set_binding_sha256,
                        sourcing_run_id=proposal.sourcing_run_id,
                        lead_id=proposal.lead_id,
                        source_document_id=proposal.source_document_id,
                        source_document_sha256=proposal.source_document_sha256,
                        proposal_sha256=proposal.proposal_sha256,
                        proposal=proposal.model_dump(mode="json"),
                        prepared_by=proposal.prepared_by,
                        prepared_at=proposal.prepared_at,
                    )
                )
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=actor_id,
                            event_type="server_offer.proposal_stored",
                            object_type="server_offer_proposal",
                            object_id=proposal.offer_id,
                            basis={
                                "case_id": case_id,
                                "case_version": case_version,
                                "requirement_set_binding_sha256": binding.binding_sha256,
                                "sourcing_run_id": run.run_id,
                                "lead_id": lead.lead_id,
                                "source_document_sha256": source_document_sha256,
                                "proposal_sha256": proposal.proposal_sha256,
                                "bom_line_count": len(proposal.bom_lines),
                            },
                            occurred_at=now,
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"offer_id": proposal.offer_id},
                )
                return proposal
        except (ServerOfferConflict, ServerOfferNotFound, ServerOfferSourceMismatch):
            raise
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise ServerOfferConflict("server-offer proposal conflicts") from error
            raise

    def _load_server_offer_proposal(
        self, connection: Connection, tenant: str, offer_id: str
    ) -> ServerOfferProposal:
        row = (
            connection.execute(
                select(server_offer_proposals).where(
                    and_(
                        server_offer_proposals.c.company_id == tenant,
                        server_offer_proposals.c.offer_id == offer_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ServerOfferNotFound("server-offer proposal was not found")
        try:
            proposal = ServerOfferProposal.model_validate_json(
                json.dumps(row["proposal"], ensure_ascii=False)
            )
        except (TypeError, ValueError) as error:
            raise ServerOfferSourceMismatch("stored server-offer proposal is invalid") from error
        columns = {
            "company_id": tenant,
            "offer_id": proposal.offer_id,
            "case_id": proposal.case_id,
            "case_version": proposal.case_version,
            "requirement_set_binding_id": proposal.requirement_set_binding_id,
            "requirement_set_binding_sha256": proposal.requirement_set_binding_sha256,
            "sourcing_run_id": proposal.sourcing_run_id,
            "lead_id": proposal.lead_id,
            "source_document_id": proposal.source_document_id,
            "source_document_sha256": proposal.source_document_sha256,
            "proposal_sha256": proposal.proposal_sha256,
            "prepared_by": proposal.prepared_by,
            "prepared_at": proposal.prepared_at,
        }
        if any(row[key] != value for key, value in columns.items()):
            raise ServerOfferSourceMismatch(
                "stored server-offer columns do not match proposal payload"
            )
        return proposal

    def get_server_offer_proposal(
        self, company_id: str, offer_id: str
    ) -> ServerOfferProposal | None:
        tenant = _require_tenant(company_id)
        with self.transaction(tenant) as connection:
            try:
                return self._load_server_offer_proposal(connection, tenant, offer_id)
            except ServerOfferNotFound:
                return None

    def _load_server_offer_review(
        self, connection: Connection, tenant: str, offer_id: str
    ) -> ServerOfferReviewRecord:
        try:
            proposal = self._load_server_offer_proposal(connection, tenant, offer_id)
            binding = self._load_case_requirement_set_binding(
                connection, tenant, proposal.requirement_set_binding_id
            )
            requirement_set = self._load_reviewed_requirement_set(
                connection, tenant, binding.set_id
            )
        except (ServerOfferNotFound, RequirementSetNotFound) as error:
            raise ServerOfferReviewNotFound("server-offer review evidence was not found") from error
        except (ServerOfferSourceMismatch, RequirementSetSourceMismatch) as error:
            raise ServerOfferReviewSourceMismatch(
                "server-offer review evidence cannot be verified"
            ) from error
        requirement_decision = requirement_set.decision
        if (
            binding.case_id != proposal.case_id
            or binding.case_version != proposal.case_version
            or binding.binding_sha256 != proposal.requirement_set_binding_sha256
            or binding.proposal_sha256 != requirement_set.proposal.proposal_sha256
            or requirement_decision is None
            or binding.decision_sha256 != requirement_decision.decision_sha256
            or requirement_decision.status is not Verdict.PASS
        ):
            raise ServerOfferReviewSourceMismatch(
                "offer does not reference the exact approved requirement set"
            )
        try:
            evidence = ServerOfferReviewEvidence(proposal=proposal, requirement_set=requirement_set)
        except ValueError as error:
            raise ServerOfferReviewSourceMismatch(
                "server-offer review evidence is invalid"
            ) from error
        row = (
            connection.execute(
                select(server_offer_review_decisions).where(
                    and_(
                        server_offer_review_decisions.c.company_id == tenant,
                        server_offer_review_decisions.c.offer_id == offer_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return ServerOfferReviewRecord(evidence=evidence)
        try:
            decision = ServerOfferReviewDecision.model_validate_json(
                json.dumps(row["decision"], ensure_ascii=False)
            )
        except (TypeError, ValueError) as error:
            raise ServerOfferReviewSourceMismatch(
                "stored server-offer review decision is invalid"
            ) from error
        expected = {
            "company_id": tenant,
            "offer_id": decision.offer_id,
            "proposal_sha256": decision.proposal_sha256,
            "requirement_set_id": decision.requirement_set_id,
            "requirement_set_proposal_sha256": decision.requirement_set_proposal_sha256,
            "requirement_set_decision_sha256": decision.requirement_set_decision_sha256,
            "status": decision.status.value,
            "decision_sha256": decision.decision_sha256,
            "reviewed_by": decision.reviewed_by,
            "reviewed_at": decision.reviewed_at,
        }
        if any(row[key] != value for key, value in expected.items()):
            raise ServerOfferReviewSourceMismatch(
                "stored server-offer review columns do not match decision payload"
            )
        try:
            return ServerOfferReviewRecord(evidence=evidence, decision=decision)
        except ValueError as error:
            raise ServerOfferReviewSourceMismatch(
                "stored server-offer review does not match its evidence"
            ) from error

    def get_server_offer_review(
        self, company_id: str, offer_id: str
    ) -> ServerOfferReviewRecord | None:
        tenant = _require_tenant(company_id)
        with self.transaction(tenant) as connection:
            try:
                return self._load_server_offer_review(connection, tenant, offer_id)
            except ServerOfferReviewNotFound:
                return None

    def decide_server_offer_proposal(
        self,
        company_id: str,
        reviewer_id: str,
        *,
        offer_id: str,
        proposal_sha256: str,
        requirement_decisions: tuple[ServerOfferRequirementDecision, ...],
        bom_scope_assessment: ServerOfferBomScopeAssessment,
        commercial_terms_assessment: ServerOfferCommercialAssessment,
        reason: str,
        idempotency_key: str,
        request_sha256: str,
    ) -> ServerOfferReviewDecision:
        tenant = _require_tenant(company_id)
        _require_sha256(proposal_sha256, field="proposal_sha256")
        _require_sha256(request_sha256, field="request_sha256")
        if not reviewer_id.strip() or not offer_id.strip():
            raise ValueError("reviewer and offer identities must not be blank")
        operation = "decide_server_offer_proposal"
        now = datetime.now(UTC)
        try:
            with self.transaction(tenant) as connection:
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, operation, idempotency_key, request_sha256
                )
                if replay is not None:
                    record = self._load_server_offer_review(connection, tenant, offer_id)
                    if record.decision is None:
                        raise ServerOfferReviewSourceMismatch(
                            "idempotency receipt references a missing review decision"
                        )
                    return record.decision
                record = self._load_server_offer_review(connection, tenant, offer_id)
                if record.decision is not None:
                    raise ServerOfferReviewConflict(
                        "server-offer proposal already has a terminal review"
                    )
                if record.evidence.proposal.proposal_sha256 != proposal_sha256:
                    raise ServerOfferReviewSourceMismatch(
                        "review request does not match the exact offer proposal"
                    )
                try:
                    decision = build_server_offer_review_decision(
                        record.evidence,
                        requirement_decisions=requirement_decisions,
                        bom_scope_assessment=bom_scope_assessment,
                        commercial_terms_assessment=commercial_terms_assessment,
                        reason=reason,
                        reviewed_by=reviewer_id,
                        reviewed_at=now,
                    )
                except ValueError as error:
                    raise ServerOfferReviewSourceMismatch(
                        "server-offer review request is invalid"
                    ) from error
                connection.execute(
                    insert(server_offer_review_decisions).values(
                        company_id=tenant,
                        offer_id=decision.offer_id,
                        proposal_sha256=decision.proposal_sha256,
                        requirement_set_id=decision.requirement_set_id,
                        requirement_set_proposal_sha256=(decision.requirement_set_proposal_sha256),
                        requirement_set_decision_sha256=(decision.requirement_set_decision_sha256),
                        status=decision.status.value,
                        decision_sha256=decision.decision_sha256,
                        decision=decision.model_dump(mode="json"),
                        reviewed_by=decision.reviewed_by,
                        reviewed_at=decision.reviewed_at,
                    )
                )
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=reviewer_id,
                            event_type="server_offer.review_decided",
                            object_type="server_offer_review_decision",
                            object_id=offer_id,
                            basis={
                                "proposal_sha256": decision.proposal_sha256,
                                "requirement_set_proposal_sha256": (
                                    decision.requirement_set_proposal_sha256
                                ),
                                "requirement_set_decision_sha256": (
                                    decision.requirement_set_decision_sha256
                                ),
                                "decision_sha256": decision.decision_sha256,
                                "status": decision.status.value,
                            },
                            occurred_at=now,
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"offer_id": offer_id},
                )
                return decision
        except (
            ServerOfferReviewConflict,
            ServerOfferReviewNotFound,
            ServerOfferReviewSourceMismatch,
        ):
            raise
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise ServerOfferReviewConflict("server-offer review conflicts") from error
            raise

    def _load_server_offer_economics_record(
        self,
        connection: Connection,
        tenant: str,
        case_id: str,
        case_version: int,
        offer_id: str,
    ) -> ServerOfferEconomicsRecord:
        case_row = (
            connection.execute(
                select(case_versions.c.payload, case_versions.c.input_sha256).where(
                    and_(
                        case_versions.c.company_id == tenant,
                        case_versions.c.case_id == case_id,
                        case_versions.c.version == case_version,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if case_row is None:
            raise ServerOfferEconomicsNotFound("exact case version was not found")
        try:
            case = ProcurementCase.model_validate(case_row["payload"])
        except ValueError as error:
            raise ServerOfferEconomicsSourceMismatch("stored case is invalid") from error
        if case_input_digest(case) != case_row["input_sha256"]:
            raise ServerOfferEconomicsSourceMismatch("stored case digest does not match payload")
        try:
            review = self._load_server_offer_review(connection, tenant, offer_id)
            evidence = ServerOfferEconomicsEvidence(case=case, offer_review=review)
        except ServerOfferReviewNotFound as error:
            raise ServerOfferEconomicsNotFound("reviewed offer was not found") from error
        except (ServerOfferReviewSourceMismatch, ValueError) as error:
            raise ServerOfferEconomicsSourceMismatch(
                "reviewed offer cannot support economics"
            ) from error
        row = (
            connection.execute(
                select(server_offer_economics_packages).where(
                    and_(
                        server_offer_economics_packages.c.company_id == tenant,
                        server_offer_economics_packages.c.case_id == case_id,
                        server_offer_economics_packages.c.case_version == case_version,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return ServerOfferEconomicsRecord(evidence=evidence)
        try:
            package = ServerOfferEconomicsPackage.model_validate_json(
                json.dumps(row["package"], ensure_ascii=False)
            )
        except (TypeError, ValueError) as error:
            raise ServerOfferEconomicsSourceMismatch(
                "stored economics package is invalid"
            ) from error
        expected = {
            "company_id": tenant,
            "economics_id": package.economics_id,
            "case_id": package.case_id,
            "case_version": package.case_version,
            "case_input_sha256": package.case_input_sha256,
            "offer_id": package.offer_id,
            "offer_proposal_sha256": package.offer_proposal_sha256,
            "offer_review_decision_sha256": package.offer_review_decision_sha256,
            "package_sha256": package.package_sha256,
            "prepared_by": package.prepared_by,
            "prepared_at": package.prepared_at,
        }
        if any(row[key] != value for key, value in expected.items()):
            raise ServerOfferEconomicsSourceMismatch(
                "stored economics columns do not match package payload"
            )
        try:
            return ServerOfferEconomicsRecord(evidence=evidence, package=package)
        except ValueError as error:
            raise ServerOfferEconomicsSourceMismatch(
                "stored economics package does not match exact evidence"
            ) from error

    def get_server_offer_economics(
        self,
        company_id: str,
        case_id: str,
        case_version: int,
        offer_id: str,
    ) -> ServerOfferEconomicsRecord | None:
        tenant = _require_tenant(company_id)
        with self.transaction(tenant) as connection:
            try:
                return self._load_server_offer_economics_record(
                    connection, tenant, case_id, case_version, offer_id
                )
            except ServerOfferEconomicsNotFound:
                return None

    def store_server_offer_economics(
        self,
        company_id: str,
        actor_id: str,
        *,
        economics_id: str,
        case_id: str,
        case_version: int,
        offer_id: str,
        offer_proposal_sha256: str,
        offer_review_decision_sha256: str,
        scenarios: tuple[ServerOfferScenarioInput, ...],
        idempotency_key: str,
        request_sha256: str,
    ) -> ServerOfferEconomicsPackage:
        tenant = _require_tenant(company_id)
        _require_sha256(offer_proposal_sha256, field="offer_proposal_sha256")
        _require_sha256(offer_review_decision_sha256, field="offer_review_decision_sha256")
        _require_sha256(request_sha256, field="request_sha256")
        if not all(value.strip() for value in (actor_id, economics_id, case_id, offer_id)):
            raise ValueError("economics identities must not be blank")
        operation = "store_server_offer_economics"
        now = datetime.now(UTC)
        try:
            with self.transaction(tenant) as connection:
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, operation, idempotency_key, request_sha256
                )
                if replay is not None:
                    record = self._load_server_offer_economics_record(
                        connection, tenant, case_id, case_version, offer_id
                    )
                    if record.package is None:
                        raise ServerOfferEconomicsSourceMismatch(
                            "receipt references a missing economics package"
                        )
                    return record.package
                record = self._load_server_offer_economics_record(
                    connection, tenant, case_id, case_version, offer_id
                )
                if record.package is not None:
                    raise ServerOfferEconomicsConflict(
                        "exact case version already has an economics package"
                    )
                decision = record.evidence.offer_review.decision
                assert decision is not None
                if (
                    record.evidence.offer_review.evidence.proposal.proposal_sha256
                    != offer_proposal_sha256
                    or decision.decision_sha256 != offer_review_decision_sha256
                ):
                    raise ServerOfferEconomicsSourceMismatch(
                        "request does not match exact reviewed offer"
                    )
                try:
                    package = build_server_offer_economics_package(
                        record.evidence,
                        economics_id=economics_id,
                        scenarios=scenarios,
                        prepared_by=actor_id,
                        prepared_at=now,
                    )
                except ValueError as error:
                    raise ServerOfferEconomicsSourceMismatch(
                        "economics inputs are invalid"
                    ) from error
                connection.execute(
                    insert(server_offer_economics_packages).values(
                        company_id=tenant,
                        economics_id=package.economics_id,
                        case_id=package.case_id,
                        case_version=package.case_version,
                        case_input_sha256=package.case_input_sha256,
                        offer_id=package.offer_id,
                        offer_proposal_sha256=package.offer_proposal_sha256,
                        offer_review_decision_sha256=(package.offer_review_decision_sha256),
                        package_sha256=package.package_sha256,
                        package=package.model_dump(mode="json"),
                        prepared_by=package.prepared_by,
                        prepared_at=package.prepared_at,
                    )
                )
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=actor_id,
                            event_type="server_offer.economics_stored",
                            object_type="server_offer_economics_package",
                            object_id=package.economics_id,
                            object_version=case_version,
                            basis={
                                "case_id": case_id,
                                "case_input_sha256": package.case_input_sha256,
                                "offer_id": offer_id,
                                "offer_review_decision_sha256": (
                                    package.offer_review_decision_sha256
                                ),
                                "package_sha256": package.package_sha256,
                            },
                            occurred_at=now,
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"economics_id": economics_id},
                )
                return package
        except (
            ServerOfferEconomicsConflict,
            ServerOfferEconomicsNotFound,
            ServerOfferEconomicsSourceMismatch,
        ):
            raise
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise ServerOfferEconomicsConflict("server-offer economics conflicts") from error
            raise

    def materialize_case_from_server_offer_economics(
        self,
        company_id: str,
        actor_id: str,
        *,
        case_id: str,
        case_version: int,
        offer_id: str,
        economics_id: str,
        package_sha256: str,
        idempotency_key: str,
        request_sha256: str,
    ) -> ProcurementCase:
        tenant = _require_tenant(company_id)
        _require_sha256(package_sha256, field="package_sha256")
        _require_sha256(request_sha256, field="request_sha256")
        operation = "materialize_case_from_server_offer_economics"
        try:
            with self.transaction(tenant) as connection:
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, operation, idempotency_key, request_sha256
                )
                if replay is not None:
                    payload = connection.execute(
                        select(case_versions.c.payload).where(
                            and_(
                                case_versions.c.company_id == tenant,
                                case_versions.c.case_id == case_id,
                                case_versions.c.version == int(replay["version"]),
                            )
                        )
                    ).scalar_one()
                    return ProcurementCase.model_validate(payload)
                record = self._load_server_offer_economics_record(
                    connection, tenant, case_id, case_version, offer_id
                )
                if (
                    record.package is None
                    or record.package.economics_id != economics_id
                    or record.package.package_sha256 != package_sha256
                ):
                    raise ServerOfferEconomicsSourceMismatch(
                        "materialization does not match exact economics package"
                    )
                derived = materialize_case_from_server_offer_economics(record)
                self._insert_case(connection, tenant, derived, allow_exact_replay=False)
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=actor_id,
                            event_type="case.materialized_from_server_offer_economics",
                            object_type="procurement_case",
                            object_id=case_id,
                            object_version=derived.version,
                            basis={
                                "source_version": case_version,
                                "case_input_sha256": record.package.case_input_sha256,
                                "economics_id": economics_id,
                                "package_sha256": package_sha256,
                                "offer_id": offer_id,
                                "offer_review_decision_sha256": (
                                    record.package.offer_review_decision_sha256
                                ),
                            },
                            occurred_at=datetime.now(UTC),
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"case_id": case_id, "version": derived.version},
                )
                return derived
        except (
            ServerOfferEconomicsConflict,
            ServerOfferEconomicsNotFound,
            ServerOfferEconomicsSourceMismatch,
            CaseVersionConflict,
        ):
            raise
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise ServerOfferEconomicsConflict("derived case version conflicts") from error
            raise

    def materialize_case_hard_gate_assessment(
        self,
        company_id: str,
        actor_id: str,
        *,
        case_id: str,
        case_version: int,
        source_case_input_sha256: str,
        document_binding_id: str,
        manifest_evidence_sha256: str,
        document_decision_sha256: str,
        decisions: tuple[CaseHardGateDecisionInput, ...],
        idempotency_key: str,
        request_sha256: str,
    ) -> ProcurementCase:
        tenant = _require_tenant(company_id)
        _require_sha256(source_case_input_sha256, field="source_case_input_sha256")
        _require_sha256(manifest_evidence_sha256, field="manifest_evidence_sha256")
        _require_sha256(document_decision_sha256, field="document_decision_sha256")
        _require_sha256(request_sha256, field="request_sha256")
        operation = "materialize_case_hard_gate_assessment"
        try:
            with self.transaction(tenant) as connection:
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, operation, idempotency_key, request_sha256
                )
                if replay is not None:
                    payload = connection.execute(
                        select(case_versions.c.payload).where(
                            and_(
                                case_versions.c.company_id == tenant,
                                case_versions.c.case_id == str(replay["case_id"]),
                                case_versions.c.version == int(replay["version"]),
                            )
                        )
                    ).scalar_one_or_none()
                    if payload is None:
                        raise CaseHardGateAssessmentSourceMismatch(
                            "assessment receipt points to a missing case version"
                        )
                    return ProcurementCase.model_validate(payload)
                source_payload = connection.execute(
                    select(case_versions.c.payload).where(
                        and_(
                            case_versions.c.company_id == tenant,
                            case_versions.c.case_id == case_id,
                            case_versions.c.version == case_version,
                        )
                    )
                ).scalar_one_or_none()
                if source_payload is None:
                    raise CaseHardGateAssessmentNotFound("source case version was not found")
                source = ProcurementCase.model_validate(source_payload)
                if case_input_digest(source) != source_case_input_sha256:
                    raise CaseHardGateAssessmentSourceMismatch(
                        "source case input digest does not match"
                    )
                lineage_rows = (
                    connection.execute(
                        select(audit_events.c.basis).where(
                            and_(
                                audit_events.c.company_id == tenant,
                                audit_events.c.event_type
                                == "case.materialized_from_server_offer_economics",
                                audit_events.c.object_type == "procurement_case",
                                audit_events.c.object_id == case_id,
                                audit_events.c.object_version == case_version,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                if len(lineage_rows) != 1 or not isinstance(lineage_rows[0], Mapping):
                    raise CaseHardGateAssessmentSourceMismatch(
                        "source case lacks unique reviewed-offer lineage"
                    )
                lineage = lineage_rows[0]
                try:
                    source_version = int(lineage["source_version"])
                    offer_id = str(lineage["offer_id"])
                    economics_id = str(lineage["economics_id"])
                    package_sha256 = str(lineage["package_sha256"])
                except (KeyError, TypeError, ValueError) as error:
                    raise CaseHardGateAssessmentSourceMismatch(
                        "source case lineage is incomplete"
                    ) from error
                record = self._load_server_offer_economics_record(
                    connection, tenant, case_id, source_version, offer_id
                )
                if (
                    record.package is None
                    or record.package.economics_id != economics_id
                    or record.package.package_sha256 != package_sha256
                    or materialize_case_from_server_offer_economics(record) != source
                ):
                    raise CaseHardGateAssessmentSourceMismatch(
                        "source case cannot be reconstructed from exact economics"
                    )
                try:
                    binding = self._load_case_document_evidence_binding(
                        connection, tenant, document_binding_id
                    )
                except CaseEvidenceNotFound as error:
                    raise CaseHardGateAssessmentNotFound(
                        "document evidence binding was not found"
                    ) from error
                except CaseEvidenceSourceMismatch as error:
                    raise CaseHardGateAssessmentSourceMismatch(
                        "document evidence binding is invalid"
                    ) from error
                if (
                    binding.manifest_evidence_sha256 != manifest_evidence_sha256
                    or binding.decision_sha256 != document_decision_sha256
                ):
                    raise CaseHardGateAssessmentSourceMismatch(
                        "document evidence binding digests do not match"
                    )
                try:
                    document_check = document_gate_check_from_binding(binding)
                except ValueError as error:
                    raise CaseHardGateAssessmentSourceMismatch(
                        "document evidence cannot support a DOCUMENT gate"
                    ) from error
                document_cache: dict[str, str] = {}
                checks: list[GateCheck] = [document_check]
                for decision in decisions:
                    for reference in decision.evidence:
                        stored_sha = document_cache.get(reference.document_id)
                        if stored_sha is None:
                            stored_sha = connection.execute(
                                select(documents.c.sha256).where(
                                    and_(
                                        documents.c.company_id == tenant,
                                        documents.c.document_id == reference.document_id,
                                    )
                                )
                            ).scalar_one_or_none()
                            if stored_sha is None:
                                raise CaseHardGateAssessmentNotFound(
                                    "hard-gate evidence document was not found"
                                )
                            document_cache[reference.document_id] = str(stored_sha)
                        if stored_sha != reference.document_sha256:
                            raise CaseHardGateAssessmentSourceMismatch(
                                "hard-gate evidence document digest does not match"
                            )
                    checks.append(
                        GateCheck(
                            kind=decision.kind,
                            status=decision.status,
                            reason=decision.reason,
                            evidence=tuple(item.provenance() for item in decision.evidence),
                        )
                    )
                now = datetime.now(UTC)
                derived = materialize_case_hard_gate_assessment(
                    source,
                    tuple(checks),
                    reviewer_id=actor_id,
                    assessed_at=now,
                )
                self._insert_case(connection, tenant, derived, allow_exact_replay=False)
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=actor_id,
                            event_type="case.hard_gates_materialized",
                            object_type="procurement_case",
                            object_id=case_id,
                            object_version=derived.version,
                            basis={
                                "source_version": case_version,
                                "source_case_input_sha256": source_case_input_sha256,
                                "inherited_offer_id": offer_id,
                                "inherited_economics_id": economics_id,
                                "inherited_package_sha256": package_sha256,
                                "document_binding_id": binding.binding_id,
                                "manifest_evidence_sha256": manifest_evidence_sha256,
                                "document_decision_sha256": document_decision_sha256,
                                "decisions": [item.model_dump(mode="json") for item in decisions],
                            },
                            occurred_at=now,
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"case_id": case_id, "version": derived.version},
                )
                return derived
        except (
            CaseHardGateAssessmentConflict,
            CaseHardGateAssessmentNotFound,
            CaseHardGateAssessmentSourceMismatch,
            CaseVersionConflict,
            ServerOfferEconomicsNotFound,
            ServerOfferEconomicsSourceMismatch,
        ):
            raise
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise CaseHardGateAssessmentConflict(
                    "derived hard-gate case version conflicts"
                ) from error
            raise

    def get_bound_requirement_set(
        self, company_id: str, case_id: str, case_version: int
    ) -> tuple[CaseRequirementSetBinding, ReviewedRequirementSetRecord] | None:
        tenant = _require_tenant(company_id)
        with self.transaction(tenant) as connection:
            binding_id = connection.execute(
                select(case_requirement_set_bindings.c.binding_id).where(
                    and_(
                        case_requirement_set_bindings.c.company_id == tenant,
                        case_requirement_set_bindings.c.case_id == case_id,
                        case_requirement_set_bindings.c.case_version == case_version,
                    )
                )
            ).scalar_one_or_none()
            if binding_id is None:
                return None
            binding = self._load_case_requirement_set_binding(connection, tenant, str(binding_id))
            return binding, self._load_reviewed_requirement_set(connection, tenant, binding.set_id)

    def _load_reviewed_requirement_set(
        self, connection: Connection, tenant: str, set_id: str
    ) -> ReviewedRequirementSetRecord:
        proposal_row = (
            connection.execute(
                select(reviewed_requirement_set_proposals).where(
                    and_(
                        reviewed_requirement_set_proposals.c.company_id == tenant,
                        reviewed_requirement_set_proposals.c.set_id == set_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if proposal_row is None:
            raise RequirementSetNotFound("reviewed requirement set was not found")
        try:
            proposal = ReviewedRequirementSetProposal.model_validate_json(
                json.dumps(proposal_row["proposal"], ensure_ascii=False)
            )
            rebuilt_proposal = build_reviewed_requirement_set_proposal(
                company_id=proposal.company_id,
                set_id=proposal.set_id,
                source_document_id=proposal.source_document_id,
                source_document_sha256=proposal.source_document_sha256,
                declared_scope=proposal.declared_scope,
                expected_entry_count=proposal.expected_entry_count,
                entries=proposal.entries,
                prepared_by=proposal.prepared_by,
                prepared_at=proposal.prepared_at,
            )
        except (TypeError, ValueError) as error:
            raise RequirementSetSourceMismatch(
                "stored requirement-set proposal is invalid"
            ) from error
        if rebuilt_proposal != proposal or (
            proposal_row["company_id"] != tenant
            or proposal_row["set_id"] != proposal.set_id
            or proposal_row["source_document_id"] != proposal.source_document_id
            or proposal_row["source_document_sha256"] != proposal.source_document_sha256
            or proposal_row["proposal_sha256"] != proposal.proposal_sha256
            or proposal_row["prepared_by"] != proposal.prepared_by
            or proposal_row["prepared_at"] != proposal.prepared_at
        ):
            raise RequirementSetSourceMismatch(
                "stored requirement-set proposal columns do not match payload"
            )
        decision_row = (
            connection.execute(
                select(reviewed_requirement_set_decisions).where(
                    and_(
                        reviewed_requirement_set_decisions.c.company_id == tenant,
                        reviewed_requirement_set_decisions.c.set_id == set_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if decision_row is None:
            return ReviewedRequirementSetRecord(proposal=proposal)
        try:
            decision = ReviewedRequirementSetDecision.model_validate_json(
                json.dumps(decision_row["decision"], ensure_ascii=False)
            )
            rebuilt_decision = build_reviewed_requirement_set_decision(
                proposal,
                coverage_assessment=decision.coverage_assessment,
                normalization_assessment=decision.normalization_assessment,
                status=decision.status,
                reason=decision.reason,
                reviewed_by=decision.reviewed_by,
                reviewed_at=decision.reviewed_at,
            )
        except (TypeError, ValueError) as error:
            raise RequirementSetSourceMismatch(
                "stored requirement-set decision is invalid"
            ) from error
        if rebuilt_decision != decision or (
            decision_row["proposal_sha256"] != decision.proposal_sha256
            or decision_row["decision_sha256"] != decision.decision_sha256
            or decision_row["status"] != decision.status.value
            or decision_row["reviewed_by"] != decision.reviewed_by
            or decision_row["reviewed_at"] != decision.reviewed_at
        ):
            raise RequirementSetSourceMismatch(
                "stored requirement-set decision columns do not match payload"
            )
        return ReviewedRequirementSetRecord(proposal=proposal, decision=decision)

    def _load_case_requirement_set_binding(
        self, connection: Connection, tenant: str, binding_id: str
    ) -> CaseRequirementSetBinding:
        row = (
            connection.execute(
                select(case_requirement_set_bindings).where(
                    and_(
                        case_requirement_set_bindings.c.company_id == tenant,
                        case_requirement_set_bindings.c.binding_id == binding_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise RequirementSetNotFound("case requirement-set binding was not found")
        try:
            binding = CaseRequirementSetBinding.model_validate_json(
                json.dumps(row["binding"], ensure_ascii=False)
            )
            record = self._load_reviewed_requirement_set(connection, tenant, binding.set_id)
            if record.decision is None:
                raise RequirementSetSourceMismatch("bound requirement-set decision is missing")
            rebuilt = build_case_requirement_set_binding(
                record.proposal,
                record.decision,
                binding_id=binding.binding_id,
                case_id=binding.case_id,
                case_version=binding.case_version,
                bound_by=binding.bound_by,
                bound_at=binding.bound_at,
            )
        except (TypeError, ValueError) as error:
            raise RequirementSetSourceMismatch(
                "stored requirement-set binding is invalid"
            ) from error
        if rebuilt != binding or (
            row["company_id"] != tenant
            or row["binding_id"] != binding.binding_id
            or row["case_id"] != binding.case_id
            or row["case_version"] != binding.case_version
            or row["set_id"] != binding.set_id
            or row["proposal_sha256"] != binding.proposal_sha256
            or row["decision_sha256"] != binding.decision_sha256
            or row["binding_sha256"] != binding.binding_sha256
            or row["bound_by"] != binding.bound_by
            or row["bound_at"] != binding.bound_at
        ):
            raise RequirementSetSourceMismatch(
                "stored requirement-set binding columns do not match payload"
            )
        return binding

    def list_cases(
        self,
        company_id: str,
        *,
        limit: int = 50,
        cursor: str | None = None,
    ) -> CasePage:
        """List latest visible versions with a stable case-id cursor."""
        tenant = _require_tenant(company_id)
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        after_case = _decode_cursor(cursor) if cursor is not None else None
        ranked = (
            select(
                case_versions.c.payload,
                case_versions.c.case_id,
                func.row_number()
                .over(
                    partition_by=(case_versions.c.company_id, case_versions.c.case_id),
                    order_by=case_versions.c.version.desc(),
                )
                .label("row_number"),
            )
            .where(case_versions.c.company_id == tenant)
            .subquery()
        )
        statement = select(ranked.c.payload, ranked.c.case_id).where(ranked.c.row_number == 1)
        if after_case is not None:
            statement = statement.where(ranked.c.case_id > after_case)
        statement = statement.order_by(ranked.c.case_id).limit(limit + 1)
        with self.transaction(tenant) as connection:
            rows = connection.execute(statement).mappings().all()
        has_more = len(rows) > limit
        selected = rows[:limit]
        items = tuple(ProcurementCase.model_validate(row["payload"]) for row in selected)
        next_cursor = _encode_cursor(selected[-1]["case_id"]) if has_more and selected else None
        return CasePage(items=items, next_cursor=next_cursor)

    def store_sourcing_run(
        self,
        company_id: str,
        actor_id: str,
        record: SourcingRunRecord,
        source_content: bytes | None,
        *,
        source_contents: tuple[bytes | None, ...] = (),
        idempotency_key: str,
        request_sha256: str,
    ) -> SourcingRunRecord:
        """Persist one immutable catalog outcome, exact bytes, audit, and receipt."""
        tenant = _require_tenant(company_id)
        _require_sha256(request_sha256, field="request_sha256")
        checked = SourcingRunRecord.model_validate(record.model_dump(mode="python"))
        if checked.company_id != tenant:
            raise ValueError("sourcing run company_id does not match repository tenant")
        if checked.status is SourcingRunStatus.COMPLETED:
            if source_content is None or not 0 < len(source_content) <= MAX_SOURCING_SNAPSHOT_BYTES:
                raise ValueError("completed sourcing run requires a bounded source snapshot")
            if hashlib.sha256(source_content).hexdigest() != checked.source_sha256:
                raise ValueError("source snapshot digest does not match sourcing run")
            if len(source_content) != checked.source_byte_size:
                raise ValueError("source snapshot size does not match sourcing run")
        elif source_content is not None:
            raise ValueError("source error must not persist unvalidated response bytes")
        if checked.sources:
            if len(source_contents) != len(checked.sources):
                raise ValueError("source contents must align with source metadata")
            for source, content in zip(checked.sources, source_contents, strict=True):
                if source.status is SourcingSourceStatus.COMPLETED:
                    if content is None or not 0 < len(content) <= MAX_SOURCING_SOURCE_BYTES:
                        raise ValueError("completed source requires bounded exact bytes")
                    if hashlib.sha256(content).hexdigest() != source.source_sha256:
                        raise ValueError("per-source digest does not match exact bytes")
                    if len(content) != source.source_byte_size:
                        raise ValueError("per-source size does not match exact bytes")
                elif content is not None:
                    raise ValueError("source error must not persist response bytes")
        elif source_contents:
            raise ValueError("legacy sourcing run cannot contain detached source bytes")

        operation = "store_sourcing_run"
        with self.transaction(tenant) as connection:
            self._lock_idempotency(connection, tenant, operation, idempotency_key)
            replay = self._existing_receipt(
                connection, tenant, operation, idempotency_key, request_sha256
            )
            if replay is not None:
                payload = connection.execute(
                    select(sourcing_runs.c.result).where(
                        and_(
                            sourcing_runs.c.company_id == tenant,
                            sourcing_runs.c.run_id == replay.get("run_id"),
                        )
                    )
                ).scalar_one_or_none()
                if payload is None:
                    raise StorageError("stored sourcing receipt points to a missing record")
                return SourcingRunRecord.model_validate(payload)

            case_exists = connection.execute(
                select(case_versions.c.case_id).where(
                    and_(
                        case_versions.c.company_id == tenant,
                        case_versions.c.case_id == checked.case_id,
                        case_versions.c.version == checked.case_version,
                    )
                )
            ).scalar_one_or_none()
            if case_exists is None:
                raise StorageError("case version does not exist in the tenant")

            connection.execute(
                insert(sourcing_runs).values(
                    company_id=tenant,
                    run_id=checked.run_id,
                    case_id=checked.case_id,
                    case_version=checked.case_version,
                    status=checked.status.value,
                    source_sha256=checked.source_sha256,
                    source_content=source_content,
                    result=checked.model_dump(mode="json"),
                    created_at=checked.created_at,
                )
            )
            if checked.sources:
                connection.execute(
                    insert(sourcing_run_sources),
                    [
                        {
                            "company_id": tenant,
                            "run_id": checked.run_id,
                            "ordinal": source.ordinal,
                            "source_name": source.source_name,
                            "source_kind": source.source_kind.value,
                            "source_url": source.source_url,
                            "media_type": source.media_type,
                            "status": source.status.value,
                            "source_sha256": source.source_sha256,
                            "source_content": content,
                            "observed_at": source.observed_at,
                            "error_code": source.error_code,
                        }
                        for source, content in zip(checked.sources, source_contents, strict=True)
                    ],
                )
            event = AuditEventRecord(
                event_id=str(uuid.uuid4()),
                company_id=tenant,
                actor_id=actor_id,
                event_type="sourcing.run_stored",
                object_type="sourcing_run",
                object_id=checked.run_id,
                object_version=1,
                basis={
                    "case_id": checked.case_id,
                    "case_version": checked.case_version,
                    "source": checked.source_name,
                    "source_sha256": checked.source_sha256,
                    "status": checked.status.value,
                    "source_count": len(checked.sources) or 1,
                },
                occurred_at=checked.created_at,
            )
            connection.execute(insert(audit_events).values(**event.model_dump(mode="python")))
            self._insert_receipt(
                connection,
                tenant=tenant,
                operation=operation,
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
                response={"run_id": checked.run_id},
            )
        return checked

    def get_sourcing_run(self, company_id: str, run_id: str) -> SourcingRunRecord | None:
        tenant = _require_tenant(company_id)
        with self.transaction(tenant) as connection:
            payload = connection.execute(
                select(sourcing_runs.c.result).where(
                    and_(
                        sourcing_runs.c.company_id == tenant,
                        sourcing_runs.c.run_id == run_id,
                    )
                )
            ).scalar_one_or_none()
        return None if payload is None else SourcingRunRecord.model_validate(payload)

    def get_latest_sourcing_run(
        self, company_id: str, case_id: str, case_version: int
    ) -> SourcingRunRecord | None:
        tenant = _require_tenant(company_id)
        statement = (
            select(sourcing_runs.c.result)
            .where(
                and_(
                    sourcing_runs.c.company_id == tenant,
                    sourcing_runs.c.case_id == case_id,
                    sourcing_runs.c.case_version == case_version,
                )
            )
            .order_by(sourcing_runs.c.created_at.desc(), sourcing_runs.c.run_id.desc())
            .limit(1)
        )
        with self.transaction(tenant) as connection:
            payload = connection.execute(statement).scalar_one_or_none()
        return None if payload is None else SourcingRunRecord.model_validate(payload)

    def append_audit(self, event: AuditEventRecord) -> AuditEventRecord:
        """Append one event; event identities cannot be silently replayed."""
        statement = insert(audit_events).values(**event.model_dump(mode="python"))
        try:
            with self.transaction(event.company_id) as connection:
                connection.execute(statement)
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise AuditEventConflict(
                    f"audit event {event.event_id!r} already exists for tenant"
                ) from error
            raise
        return event

    def list_audit_events(
        self,
        company_id: str,
        *,
        object_type: str | None = None,
        object_id: str | None = None,
    ) -> list[AuditEventRecord]:
        """List visible audit history in deterministic chronological order."""
        tenant = _require_tenant(company_id)
        statement = select(audit_events).where(audit_events.c.company_id == tenant)
        if object_type is not None:
            statement = statement.where(audit_events.c.object_type == object_type)
        if object_id is not None:
            statement = statement.where(audit_events.c.object_id == object_id)
        statement = statement.order_by(audit_events.c.occurred_at, audit_events.c.event_id)
        with self.transaction(tenant) as connection:
            rows = connection.execute(statement).mappings().all()
        return [AuditEventRecord.model_validate(dict(row)) for row in rows]

    def register_api_key(self, record: ApiKeyRecord) -> ApiKeyRecord:
        """Register already-digested key metadata inside its tenant."""
        values = record.model_dump(mode="python", exclude_none=True)
        try:
            with self.transaction(record.company_id) as connection:
                row = (
                    connection.execute(insert(api_keys).values(**values).returning(api_keys))
                    .mappings()
                    .one()
                )
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise ApiKeyConflict("API key identity or digest already exists") from error
            raise
        return ApiKeyRecord.model_validate(dict(row))

    def authenticate_api_key(self, secret: str) -> Principal | None:
        """Resolve bearer identity without accepting a caller-provided tenant."""
        digest = api_key_digest(secret)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT company_id, actor_id, key_id, access_role "
                        "FROM authenticate_api_key(:key_digest)"
                    ),
                    {"key_digest": digest},
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else Principal.model_validate(dict(row))

    def set_api_key_enabled(self, company_id: str, key_id: str, *, enabled: bool) -> bool:
        """Enable or revoke one key in its tenant; return whether it existed."""
        tenant = _require_tenant(company_id)
        if not key_id:
            raise ValueError("key_id must not be empty")
        with self.transaction(tenant) as connection:
            result = connection.execute(
                update(api_keys)
                .where(and_(api_keys.c.company_id == tenant, api_keys.c.key_id == key_id))
                .values(enabled=enabled)
            )
        return result.rowcount == 1

    def get_evaluation(
        self,
        company_id: str,
        evaluation_id: str,
    ) -> EvaluationRecord | None:
        tenant = _require_tenant(company_id)
        with self.transaction(tenant) as connection:
            row = (
                connection.execute(
                    select(evaluations).where(
                        and_(
                            evaluations.c.company_id == tenant,
                            evaluations.c.evaluation_id == evaluation_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else EvaluationRecord.model_validate(dict(row))

    def _load_participation_decision_record(
        self,
        connection: Connection,
        tenant: str,
        evaluation_id: str,
    ) -> ParticipationDecisionRecord:
        evaluation_row = (
            connection.execute(
                select(evaluations).where(
                    and_(
                        evaluations.c.company_id == tenant,
                        evaluations.c.evaluation_id == evaluation_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if evaluation_row is None:
            raise ParticipationDecisionNotFound("evaluation was not found")
        try:
            evaluation = EvaluationRecord.model_validate(dict(evaluation_row))
        except ValueError as error:
            raise ParticipationDecisionSourceMismatch("stored evaluation is invalid") from error
        event_rows = (
            connection.execute(
                select(audit_events).where(
                    and_(
                        audit_events.c.company_id == tenant,
                        audit_events.c.event_id == evaluation_id,
                        audit_events.c.event_type == "case.evaluated",
                        audit_events.c.object_type == "procurement_case",
                        audit_events.c.object_id == evaluation.case_id,
                        audit_events.c.object_version == evaluation.case_version,
                    )
                )
            )
            .mappings()
            .all()
        )
        if len(event_rows) != 1:
            raise ParticipationDecisionSourceMismatch("evaluation lacks one exact audit event")
        event = AuditEventRecord.model_validate(dict(event_rows[0]))
        if evaluation.created_at is None or event.occurred_at != evaluation.created_at:
            raise ParticipationDecisionSourceMismatch("evaluation and audit timestamps differ")
        expected_basis = {
            "evaluation_id",
            "input_sha256",
            "engine_version",
            "effective_at",
        }
        try:
            basis_effective_at = datetime.fromisoformat(str(event.basis["effective_at"]))
        except (KeyError, ValueError) as error:
            raise ParticipationDecisionSourceMismatch(
                "evaluation audit basis has an invalid effective time"
            ) from error
        if (
            set(event.basis) != expected_basis
            or event.basis["evaluation_id"] != evaluation.evaluation_id
            or event.basis["input_sha256"] != evaluation.input_sha256
            or event.basis["engine_version"] != evaluation.engine_version
            or basis_effective_at.tzinfo is None
            or basis_effective_at.utcoffset() is None
            or basis_effective_at != evaluation.effective_at
        ):
            raise ParticipationDecisionSourceMismatch("evaluation audit basis differs")
        case_row = (
            connection.execute(
                select(case_versions.c.payload, case_versions.c.input_sha256).where(
                    and_(
                        case_versions.c.company_id == tenant,
                        case_versions.c.case_id == evaluation.case_id,
                        case_versions.c.version == evaluation.case_version,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if case_row is None:
            raise ParticipationDecisionNotFound("evaluated case version was not found")
        try:
            case = ProcurementCase.model_validate(case_row["payload"])
        except ValueError as error:
            raise ParticipationDecisionSourceMismatch("stored case is invalid") from error
        if (
            case_row["input_sha256"] != evaluation.input_sha256
            or case_input_digest(case) != evaluation.input_sha256
            or evaluate_case(case, at=evaluation.effective_at) != evaluation.recommendation
        ):
            raise ParticipationDecisionSourceMismatch(
                "evaluation cannot be reconstructed from its exact case"
            )
        try:
            evidence = build_participation_evaluation_evidence(
                company_id=tenant,
                evaluation_id=evaluation.evaluation_id,
                case_id=evaluation.case_id,
                case_version=evaluation.case_version,
                effective_at=evaluation.effective_at,
                case_input_sha256=evaluation.input_sha256,
                engine_version=evaluation.engine_version,
                recommendation=evaluation.recommendation,
                evaluated_by=event.actor_id,
                evaluated_at=event.occurred_at,
            )
        except ValueError as error:
            raise ParticipationDecisionSourceMismatch("evaluation evidence is invalid") from error
        decision_row = (
            connection.execute(
                select(participation_decisions).where(
                    and_(
                        participation_decisions.c.company_id == tenant,
                        participation_decisions.c.evaluation_id == evaluation_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if decision_row is None:
            return ParticipationDecisionRecord(evidence=evidence)
        try:
            decision = ParticipationDecision.model_validate(decision_row["decision"])
        except ValueError as error:
            raise ParticipationDecisionSourceMismatch(
                "stored participation decision is invalid"
            ) from error
        expected_columns = {
            "company_id": decision.company_id,
            "decision_id": decision.decision_id,
            "evaluation_id": decision.evaluation_id,
            "case_id": decision.case_id,
            "case_version": decision.case_version,
            "evaluation_evidence_sha256": decision.evaluation_evidence_sha256,
            "status": decision.status.value,
            "decision_sha256": decision.decision_sha256,
            "decided_by": decision.decided_by,
            "decided_at": decision.decided_at,
        }
        if any(decision_row[key] != value for key, value in expected_columns.items()):
            raise ParticipationDecisionSourceMismatch(
                "stored participation columns differ from payload"
            )
        try:
            return ParticipationDecisionRecord(evidence=evidence, decision=decision)
        except ValueError as error:
            raise ParticipationDecisionSourceMismatch(
                "decision differs from exact evaluation evidence"
            ) from error

    def get_participation_decision(
        self,
        company_id: str,
        evaluation_id: str,
    ) -> ParticipationDecisionRecord | None:
        tenant = _require_tenant(company_id)
        if not evaluation_id.strip():
            raise ValueError("evaluation_id must not be blank")
        with self.transaction(tenant) as connection:
            try:
                return self._load_participation_decision_record(connection, tenant, evaluation_id)
            except ParticipationDecisionNotFound:
                return None

    def decide_participation(
        self,
        company_id: str,
        actor_id: str,
        evaluation_id: str,
        evaluation_evidence_sha256: str,
        status: ParticipationDecisionStatus,
        reason: str,
        idempotency_key: str,
        request_sha256: str,
    ) -> ParticipationDecision:
        tenant = _require_tenant(company_id)
        _require_sha256(evaluation_evidence_sha256, field="evaluation_evidence_sha256")
        _require_sha256(request_sha256, field="request_sha256")
        if not all(value.strip() for value in (actor_id, evaluation_id, reason)):
            raise ValueError("participation decision text must not be blank")
        if not isinstance(status, ParticipationDecisionStatus):
            raise TypeError("status must be ParticipationDecisionStatus")
        operation = "decide_participation"
        try:
            with self.transaction(tenant) as connection:
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, operation, idempotency_key, request_sha256
                )
                if replay is not None:
                    record = self._load_participation_decision_record(
                        connection, tenant, evaluation_id
                    )
                    if record.decision is None or record.decision.decision_id != replay.get(
                        "decision_id"
                    ):
                        raise ParticipationDecisionSourceMismatch(
                            "receipt references a missing participation decision"
                        )
                    return record.decision
                record = self._load_participation_decision_record(connection, tenant, evaluation_id)
                if record.decision is not None:
                    raise ParticipationDecisionConflict(
                        "evaluation already has a terminal participation decision"
                    )
                if record.evidence.evidence_sha256 != evaluation_evidence_sha256:
                    raise ParticipationDecisionSourceMismatch(
                        "request does not match exact evaluation evidence"
                    )
                case_payload = connection.execute(
                    select(case_versions.c.payload).where(
                        and_(
                            case_versions.c.company_id == tenant,
                            case_versions.c.case_id == record.evidence.case_id,
                            case_versions.c.version == record.evidence.case_version,
                        )
                    )
                ).scalar_one_or_none()
                if case_payload is None:
                    raise ParticipationDecisionNotFound("evaluated case version was not found")
                try:
                    case = ProcurementCase.model_validate(case_payload)
                    decided_at = datetime.now(UTC)
                    current = evaluate_case(case, at=decided_at)
                    decision = build_participation_decision(
                        record.evidence,
                        decision_id=str(uuid.uuid4()),
                        status=status,
                        current_recommendation=current,
                        reason=reason,
                        decided_by=actor_id,
                        decided_at=decided_at,
                    )
                except ValueError as error:
                    raise ParticipationDecisionSourceMismatch(
                        "participation decision is not allowed"
                    ) from error
                connection.execute(
                    insert(participation_decisions).values(
                        company_id=tenant,
                        decision_id=decision.decision_id,
                        evaluation_id=decision.evaluation_id,
                        case_id=decision.case_id,
                        case_version=decision.case_version,
                        evaluation_evidence_sha256=(decision.evaluation_evidence_sha256),
                        status=decision.status.value,
                        decision_sha256=decision.decision_sha256,
                        decision=decision.model_dump(mode="json"),
                        decided_by=decision.decided_by,
                        decided_at=decision.decided_at,
                    )
                )
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=actor_id,
                            event_type="case.participation_decided",
                            object_type="procurement_case",
                            object_id=decision.case_id,
                            object_version=decision.case_version,
                            basis={
                                "decision_id": decision.decision_id,
                                "evaluation_id": decision.evaluation_id,
                                "evaluation_evidence_sha256": (decision.evaluation_evidence_sha256),
                                "status": decision.status.value,
                                "decision_sha256": decision.decision_sha256,
                                "external_action_authorized": False,
                            },
                            occurred_at=decision.decided_at,
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={
                        "decision_id": decision.decision_id,
                        "evaluation_id": decision.evaluation_id,
                    },
                )
                return decision
        except (
            ParticipationDecisionConflict,
            ParticipationDecisionNotFound,
            ParticipationDecisionSourceMismatch,
            IdempotencyConflict,
        ):
            raise
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise ParticipationDecisionConflict("participation decision conflicts") from error
            raise

    def _load_application_package_record(
        self,
        connection: Connection,
        tenant: str,
        participation_decision_id: str,
    ) -> ApplicationPackageRecord:
        evaluation_id = connection.execute(
            select(participation_decisions.c.evaluation_id).where(
                and_(
                    participation_decisions.c.company_id == tenant,
                    participation_decisions.c.decision_id == participation_decision_id,
                )
            )
        ).scalar_one_or_none()
        if evaluation_id is None:
            raise ApplicationPackageNotFound("approved participation decision was not found")
        try:
            participation = self._load_participation_decision_record(
                connection, tenant, str(evaluation_id)
            )
        except ParticipationDecisionNotFound as error:
            raise ApplicationPackageNotFound("participation evidence was not found") from error
        except ParticipationDecisionSourceMismatch as error:
            raise ApplicationPackageSourceMismatch("participation evidence is invalid") from error
        decision = participation.decision
        if decision is None or decision.decision_id != participation_decision_id:
            raise ApplicationPackageSourceMismatch("participation decision identity differs")
        case_row = (
            connection.execute(
                select(case_versions.c.payload, case_versions.c.input_sha256).where(
                    and_(
                        case_versions.c.company_id == tenant,
                        case_versions.c.case_id == decision.case_id,
                        case_versions.c.version == decision.case_version,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if case_row is None:
            raise ApplicationPackageNotFound("approved case version was not found")
        try:
            case = ProcurementCase.model_validate(case_row["payload"])
            if (
                case_input_digest(case) != case_row["input_sha256"]
                or case_row["input_sha256"] != participation.evidence.case_input_sha256
            ):
                raise ValueError("case digest differs")
            evidence = ApplicationPackageEvidence(
                case=case,
                participation=participation,
            )
        except ValueError as error:
            raise ApplicationPackageSourceMismatch("approved case evidence is invalid") from error
        package_row = (
            connection.execute(
                select(application_packages).where(
                    and_(
                        application_packages.c.company_id == tenant,
                        application_packages.c.participation_decision_id
                        == participation_decision_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if package_row is None:
            return ApplicationPackageRecord(evidence=evidence)
        try:
            package = ApplicationPackage.model_validate(package_row["package"])
        except ValueError as error:
            raise ApplicationPackageSourceMismatch(
                "stored application package is invalid"
            ) from error
        expected = {
            "company_id": package.company_id,
            "package_id": package.package_id,
            "participation_decision_id": package.participation_decision_id,
            "participation_decision_sha256": package.participation_decision_sha256,
            "evaluation_id": package.evaluation_id,
            "case_id": package.case_id,
            "case_version": package.case_version,
            "case_input_sha256": package.case_input_sha256,
            "package_sha256": package.package_sha256,
            "prepared_by": package.prepared_by,
            "prepared_at": package.prepared_at,
        }
        if any(package_row[key] != value for key, value in expected.items()):
            raise ApplicationPackageSourceMismatch(
                "stored application package columns differ from payload"
            )
        document_ids = {item.source_document_id for item in package.requirements} | {
            item.document_id for item in package.attachments
        }
        document_rows = (
            connection.execute(
                select(
                    documents.c.document_id,
                    documents.c.sha256,
                    documents.c.original_filename,
                    documents.c.media_type,
                    documents.c.document_role,
                ).where(
                    and_(
                        documents.c.company_id == tenant,
                        documents.c.document_id.in_(document_ids),
                    )
                )
            )
            .mappings()
            .all()
        )
        documents_by_id = {str(row["document_id"]): row for row in document_rows}
        if set(documents_by_id) != document_ids:
            raise ApplicationPackageSourceMismatch(
                "stored application package references missing documents"
            )
        for requirement in package.requirements:
            row = documents_by_id[requirement.source_document_id]
            if (
                row["sha256"] != requirement.source_document_sha256
                or row["document_role"] != DocumentRole.TENDER_REQUIREMENTS.value
            ):
                raise ApplicationPackageSourceMismatch(
                    "stored application requirement evidence differs"
                )
        for attachment in package.attachments:
            row = documents_by_id[attachment.document_id]
            if (
                row["sha256"] != attachment.document_sha256
                or row["document_role"] != DocumentRole.APPLICATION_ATTACHMENT.value
                or row["original_filename"] != attachment.original_filename
                or row["media_type"] != attachment.media_type
            ):
                raise ApplicationPackageSourceMismatch(
                    "stored application attachment evidence differs"
                )
        try:
            return ApplicationPackageRecord(evidence=evidence, package=package)
        except ValueError as error:
            raise ApplicationPackageSourceMismatch(
                "application package differs from exact evidence"
            ) from error

    def get_application_package(
        self,
        company_id: str,
        participation_decision_id: str,
    ) -> ApplicationPackageRecord | None:
        tenant = _require_tenant(company_id)
        if not participation_decision_id.strip():
            raise ValueError("participation_decision_id must not be blank")
        with self.transaction(tenant) as connection:
            try:
                return self._load_application_package_record(
                    connection, tenant, participation_decision_id
                )
            except ApplicationPackageNotFound:
                return None

    def store_application_package(
        self,
        company_id: str,
        actor_id: str,
        *,
        package_id: str,
        participation_decision_id: str,
        participation_decision_sha256: str,
        proposed_price_ex_vat: Decimal,
        requirements: tuple[ApplicationDocumentRequirement, ...],
        attachments: tuple[ApplicationAttachmentInput, ...],
        idempotency_key: str,
        request_sha256: str,
    ) -> ApplicationPackage:
        tenant = _require_tenant(company_id)
        _require_sha256(
            participation_decision_sha256,
            field="participation_decision_sha256",
        )
        _require_sha256(request_sha256, field="request_sha256")
        if not all(value.strip() for value in (actor_id, package_id, participation_decision_id)):
            raise ValueError("application package identities must not be blank")
        operation = "store_application_package"
        try:
            with self.transaction(tenant) as connection:
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, operation, idempotency_key, request_sha256
                )
                if replay is not None:
                    record = self._load_application_package_record(
                        connection, tenant, participation_decision_id
                    )
                    if record.package is None or record.package.package_id != replay.get(
                        "package_id"
                    ):
                        raise ApplicationPackageSourceMismatch(
                            "receipt references a missing application package"
                        )
                    return record.package
                record = self._load_application_package_record(
                    connection, tenant, participation_decision_id
                )
                if record.package is not None:
                    raise ApplicationPackageConflict(
                        "participation decision already has an application package"
                    )
                decision = record.evidence.participation.decision
                assert decision is not None
                if decision.decision_sha256 != participation_decision_sha256:
                    raise ApplicationPackageSourceMismatch(
                        "request does not match exact participation decision"
                    )
                document_ids = {item.source_document_id for item in requirements} | {
                    item.document_id for item in attachments
                }
                rows = (
                    connection.execute(
                        select(
                            documents.c.document_id,
                            documents.c.sha256,
                            documents.c.original_filename,
                            documents.c.media_type,
                            documents.c.document_role,
                        ).where(
                            and_(
                                documents.c.company_id == tenant,
                                documents.c.document_id.in_(document_ids),
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                by_id = {str(row["document_id"]): row for row in rows}
                if set(by_id) != document_ids:
                    raise ApplicationPackageNotFound(
                        "one or more application evidence documents were not found"
                    )
                for requirement in requirements:
                    row = by_id[requirement.source_document_id]
                    if (
                        row["sha256"] != requirement.source_document_sha256
                        or row["document_role"] != DocumentRole.TENDER_REQUIREMENTS.value
                    ):
                        raise ApplicationPackageSourceMismatch(
                            "application requirement source is not exact tender evidence"
                        )
                resolved: list[ApplicationAttachment] = []
                for item in attachments:
                    row = by_id[item.document_id]
                    if (
                        row["sha256"] != item.document_sha256
                        or row["document_role"] != DocumentRole.APPLICATION_ATTACHMENT.value
                    ):
                        raise ApplicationPackageSourceMismatch(
                            "application attachment is not exact prepared evidence"
                        )
                    resolved.append(
                        ApplicationAttachment(
                            **item.model_dump(mode="python"),
                            original_filename=str(row["original_filename"]),
                            media_type=str(row["media_type"]),
                        )
                    )
                prepared_at = datetime.now(UTC)
                current = evaluate_case(record.evidence.case, at=prepared_at)
                try:
                    package = build_application_package(
                        record.evidence,
                        package_id=package_id,
                        proposed_price_ex_vat=proposed_price_ex_vat,
                        requirements=requirements,
                        attachments=tuple(resolved),
                        current_recommendation=current,
                        prepared_by=actor_id,
                        prepared_at=prepared_at,
                    )
                except ValueError as error:
                    raise ApplicationPackageSourceMismatch(
                        "application package inputs are invalid"
                    ) from error
                connection.execute(
                    insert(application_packages).values(
                        company_id=tenant,
                        package_id=package.package_id,
                        participation_decision_id=(package.participation_decision_id),
                        participation_decision_sha256=(package.participation_decision_sha256),
                        evaluation_id=package.evaluation_id,
                        case_id=package.case_id,
                        case_version=package.case_version,
                        case_input_sha256=package.case_input_sha256,
                        package_sha256=package.package_sha256,
                        package=package.model_dump(mode="json"),
                        prepared_by=package.prepared_by,
                        prepared_at=package.prepared_at,
                    )
                )
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=actor_id,
                            event_type="application.package_prepared",
                            object_type="application_package",
                            object_id=package.package_id,
                            object_version=package.case_version,
                            basis={
                                "case_id": package.case_id,
                                "case_input_sha256": package.case_input_sha256,
                                "participation_decision_id": (package.participation_decision_id),
                                "participation_decision_sha256": (
                                    package.participation_decision_sha256
                                ),
                                "package_sha256": package.package_sha256,
                                "external_action_authorized": False,
                            },
                            occurred_at=package.prepared_at,
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={
                        "package_id": package.package_id,
                        "participation_decision_id": participation_decision_id,
                    },
                )
                return package
        except (
            ApplicationPackageConflict,
            ApplicationPackageNotFound,
            ApplicationPackageSourceMismatch,
            IdempotencyConflict,
        ):
            raise
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise ApplicationPackageConflict("application package conflicts") from error
            raise

    def _load_application_review_record(
        self,
        connection: Connection,
        tenant: str,
        package_id: str,
    ) -> ApplicationReviewRecord:
        package_row = connection.execute(
            select(application_packages.c.participation_decision_id).where(
                and_(
                    application_packages.c.company_id == tenant,
                    application_packages.c.package_id == package_id,
                )
            )
        ).scalar_one_or_none()
        if package_row is None:
            raise ApplicationReviewNotFound("application package was not found")
        try:
            evidence = self._load_application_package_record(connection, tenant, str(package_row))
        except (ApplicationPackageNotFound, ApplicationPackageSourceMismatch) as error:
            raise ApplicationReviewSourceMismatch(
                "application package evidence is invalid"
            ) from error
        if evidence.package is None or evidence.package.package_id != package_id:
            raise ApplicationReviewSourceMismatch("exact application package differs")
        row = (
            connection.execute(
                select(application_package_reviews).where(
                    and_(
                        application_package_reviews.c.company_id == tenant,
                        application_package_reviews.c.package_id == package_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return ApplicationReviewRecord(evidence=evidence)
        try:
            decision = ApplicationReviewDecision.model_validate(row["decision"])
            expected = {
                "company_id": decision.company_id,
                "package_id": decision.package_id,
                "package_sha256": decision.package_sha256,
                "decision_sha256": decision.decision_sha256,
                "status": decision.status.value,
                "reviewed_by": decision.reviewed_by,
                "reviewed_at": decision.reviewed_at,
            }
            if any(row[key] != value for key, value in expected.items()):
                raise ValueError("stored review columns differ")
            return ApplicationReviewRecord(evidence=evidence, decision=decision)
        except ValueError as error:
            raise ApplicationReviewSourceMismatch(
                "stored application review cannot be reconstructed"
            ) from error

    def get_application_review(
        self,
        company_id: str,
        package_id: str,
    ) -> ApplicationReviewRecord | None:
        tenant = _require_tenant(company_id)
        if not package_id.strip():
            raise ValueError("package_id must not be blank")
        with self.transaction(tenant) as connection:
            try:
                return self._load_application_review_record(connection, tenant, package_id)
            except ApplicationReviewNotFound:
                return None

    def decide_application_review(
        self,
        company_id: str,
        actor_id: str,
        *,
        package_id: str,
        package_sha256: str,
        requirement_reviews: tuple[ApplicationRequirementReview, ...],
        attachment_reviews: tuple[ApplicationAttachmentReview, ...],
        inventory_assessment: ApplicationInventoryAssessment,
        inventory_source_document_ids: tuple[str, ...],
        inventory_reason: str,
        price_assessment: ApplicationPriceAssessment,
        price_reason: str,
        reason: str,
        idempotency_key: str,
        request_sha256: str,
    ) -> ApplicationReviewDecision:
        tenant = _require_tenant(company_id)
        _require_sha256(package_sha256, field="package_sha256")
        _require_sha256(request_sha256, field="request_sha256")
        if not actor_id.strip() or not package_id.strip():
            raise ValueError("application review identities must not be blank")
        operation = "decide_application_review"
        try:
            with self.transaction(tenant) as connection:
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, operation, idempotency_key, request_sha256
                )
                if replay is not None:
                    record = self._load_application_review_record(connection, tenant, package_id)
                    if record.decision is None or record.decision.decision_sha256 != replay.get(
                        "decision_sha256"
                    ):
                        raise ApplicationReviewSourceMismatch(
                            "receipt references missing application review"
                        )
                    return record.decision
                record = self._load_application_review_record(connection, tenant, package_id)
                if record.decision is not None:
                    raise ApplicationReviewConflict("package already has a terminal review")
                package = record.evidence.package
                assert package is not None
                if package.package_sha256 != package_sha256:
                    raise ApplicationReviewSourceMismatch(
                        "review does not match exact package digest"
                    )
                try:
                    decision = build_application_review_decision(
                        record.evidence,
                        requirement_reviews=requirement_reviews,
                        attachment_reviews=attachment_reviews,
                        inventory_assessment=inventory_assessment,
                        inventory_source_document_ids=inventory_source_document_ids,
                        inventory_reason=inventory_reason,
                        price_assessment=price_assessment,
                        price_reason=price_reason,
                        reason=reason,
                        reviewed_by=actor_id,
                        reviewed_at=datetime.now(UTC),
                    )
                except ValueError as error:
                    raise ApplicationReviewSourceMismatch(
                        "application review decision is invalid"
                    ) from error
                connection.execute(
                    insert(application_package_reviews).values(
                        company_id=tenant,
                        package_id=package_id,
                        package_sha256=decision.package_sha256,
                        decision_sha256=decision.decision_sha256,
                        status=decision.status.value,
                        decision=decision.model_dump(mode="json"),
                        reviewed_by=decision.reviewed_by,
                        reviewed_at=decision.reviewed_at,
                    )
                )
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=actor_id,
                            event_type="application.package_reviewed",
                            object_type="application_package",
                            object_id=package_id,
                            object_version=package.case_version,
                            basis={
                                "package_sha256": decision.package_sha256,
                                "decision_sha256": decision.decision_sha256,
                                "status": decision.status.value,
                                "external_action_authorized": False,
                            },
                            occurred_at=decision.reviewed_at,
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={
                        "package_id": package_id,
                        "decision_sha256": decision.decision_sha256,
                    },
                )
                return decision
        except (
            ApplicationReviewConflict,
            ApplicationReviewNotFound,
            ApplicationReviewSourceMismatch,
            IdempotencyConflict,
        ):
            raise
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise ApplicationReviewConflict("application review conflicts") from error
            raise

    def _load_application_submission_record(
        self, connection: Connection, tenant: str, package_id: str
    ) -> ApplicationSubmissionRecord:
        try:
            evidence = self._load_application_review_record(connection, tenant, package_id)
        except ApplicationReviewNotFound as error:
            raise ApplicationSubmissionNotFound("application package was not found") from error
        except ApplicationReviewSourceMismatch as error:
            raise ApplicationSubmissionSourceMismatch("application review is invalid") from error
        row = (
            connection.execute(
                select(application_submission_intents).where(
                    and_(
                        application_submission_intents.c.company_id == tenant,
                        application_submission_intents.c.package_id == package_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return ApplicationSubmissionRecord(evidence=evidence)
        try:
            intent = ApplicationSubmissionIntent.model_validate(row["intent"])
            if (
                intent.request.company_id != tenant
                or intent.package_id != package_id
                or intent.request.action_id != row["action_id"]
                or intent.request.payload_sha256 != row["payload_sha256"]
                or intent.prepared_by != row["prepared_by"]
                or intent.request.created_at != row["prepared_at"]
            ):
                raise ValueError("stored intent columns differ")
            decision_row = (
                connection.execute(
                    select(application_submission_approvals).where(
                        and_(
                            application_submission_approvals.c.company_id == tenant,
                            application_submission_approvals.c.action_id
                            == intent.request.action_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            decision = None
            if decision_row is not None:
                decision = ApplicationSubmissionApproval.model_validate(decision_row["decision"])
                if (
                    decision.company_id != tenant
                    or decision.action_id != intent.request.action_id
                    or decision.payload_sha256 != decision_row["payload_sha256"]
                    or decision.decision_sha256 != decision_row["decision_sha256"]
                    or decision.status.value != decision_row["status"]
                    or decision.decided_by != decision_row["decided_by"]
                    or decision.decided_at != decision_row["decided_at"]
                ):
                    raise ValueError("stored approval columns differ")
            return ApplicationSubmissionRecord(evidence=evidence, intent=intent, decision=decision)
        except (ValueError, KeyError, TypeError) as error:
            raise ApplicationSubmissionSourceMismatch(
                "stored submission record cannot be reconstructed"
            ) from error

    def get_application_submission(
        self, company_id: str, package_id: str
    ) -> ApplicationSubmissionRecord | None:
        tenant = _require_tenant(company_id)
        with self.transaction(tenant) as connection:
            try:
                return self._load_application_submission_record(connection, tenant, package_id)
            except ApplicationSubmissionNotFound:
                return None

    def prepare_application_submission(
        self,
        company_id: str,
        actor_id: str,
        *,
        package_id: str,
        package_sha256: str,
        review_decision_sha256: str,
        destination: str,
        idempotency_key: str,
        request_sha256: str,
    ) -> ApplicationSubmissionIntent:
        tenant = _require_tenant(company_id)
        _require_sha256(package_sha256, field="package_sha256")
        _require_sha256(review_decision_sha256, field="review_decision_sha256")
        _require_sha256(request_sha256, field="request_sha256")
        if not actor_id.strip() or not package_id.strip():
            raise ValueError("submission identities must not be blank")
        operation = "prepare_application_submission"
        try:
            with self.transaction(tenant) as connection:
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, operation, idempotency_key, request_sha256
                )
                if replay is not None:
                    record = self._load_application_submission_record(
                        connection, tenant, package_id
                    )
                    if (
                        record.intent is None
                        or record.intent.request.action_id != replay.get("action_id")
                        or record.intent.request.payload_sha256 != replay.get("payload_sha256")
                    ):
                        raise ApplicationSubmissionSourceMismatch(
                            "receipt references missing intent"
                        )
                    return record.intent
                record = self._load_application_submission_record(connection, tenant, package_id)
                if record.intent is not None:
                    raise ApplicationSubmissionConflict("package already has a submission intent")
                package = record.evidence.evidence.package
                review = record.evidence.decision
                if (
                    package is None
                    or review is None
                    or package.package_sha256 != package_sha256
                    or review.decision_sha256 != review_decision_sha256
                ):
                    raise ApplicationSubmissionSourceMismatch("exact reviewed package differs")
                now = datetime.now(UTC)
                try:
                    intent = build_submission_intent(
                        record.evidence,
                        action_id=str(uuid.uuid4()),
                        destination=destination,
                        prepared_by=actor_id,
                        prepared_at=now,
                    )
                except ValueError as error:
                    raise ApplicationSubmissionSourceMismatch(
                        "submission intent is invalid"
                    ) from error
                connection.execute(
                    insert(application_submission_intents).values(
                        company_id=tenant,
                        package_id=package_id,
                        action_id=intent.request.action_id,
                        payload_sha256=intent.request.payload_sha256,
                        intent=intent.model_dump(mode="json"),
                        prepared_by=actor_id,
                        prepared_at=now,
                    )
                )
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=actor_id,
                            event_type="application.submission_prepared",
                            object_type="application_submission",
                            object_id=intent.request.action_id,
                            object_version=package.case_version,
                            basis={
                                "package_sha256": package_sha256,
                                "review_decision_sha256": review_decision_sha256,
                                "payload_sha256": intent.request.payload_sha256,
                                "external_action_performed": False,
                            },
                            occurred_at=now,
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={
                        "action_id": intent.request.action_id,
                        "payload_sha256": intent.request.payload_sha256,
                    },
                )
                return intent
        except (
            ApplicationSubmissionConflict,
            ApplicationSubmissionNotFound,
            ApplicationSubmissionSourceMismatch,
            IdempotencyConflict,
        ):
            raise
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise ApplicationSubmissionConflict("submission intent conflicts") from error
            raise

    def decide_application_submission(
        self,
        company_id: str,
        actor_id: str,
        *,
        action_id: str,
        payload_sha256: str,
        status: SubmissionApprovalStatus,
        reason: str,
        idempotency_key: str,
        request_sha256: str,
    ) -> ApplicationSubmissionApproval:
        tenant = _require_tenant(company_id)
        _require_sha256(payload_sha256, field="payload_sha256")
        _require_sha256(request_sha256, field="request_sha256")
        if not actor_id.strip() or not action_id.strip():
            raise ValueError("submission identities must not be blank")
        operation = "decide_application_submission"
        try:
            with self.transaction(tenant) as connection:
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                row = connection.execute(
                    select(application_submission_intents.c.package_id).where(
                        and_(
                            application_submission_intents.c.company_id == tenant,
                            application_submission_intents.c.action_id == action_id,
                        )
                    )
                ).scalar_one_or_none()
                if row is None:
                    raise ApplicationSubmissionNotFound("submission intent was not found")
                package_id = str(row)
                replay = self._existing_receipt(
                    connection, tenant, operation, idempotency_key, request_sha256
                )
                record = self._load_application_submission_record(connection, tenant, package_id)
                if replay is not None:
                    if record.decision is None or record.decision.decision_sha256 != replay.get(
                        "decision_sha256"
                    ):
                        raise ApplicationSubmissionSourceMismatch(
                            "receipt references missing approval"
                        )
                    return record.decision
                if record.decision is not None:
                    raise ApplicationSubmissionConflict("intent already has a terminal decision")
                if record.intent is None or record.intent.request.payload_sha256 != payload_sha256:
                    raise ApplicationSubmissionSourceMismatch("exact payload digest differs")
                now = datetime.now(UTC)
                try:
                    decision = build_submission_approval(
                        record,
                        status=status,
                        reason=reason,
                        decided_by=actor_id,
                        decided_at=now,
                    )
                except ValueError as error:
                    raise ApplicationSubmissionSourceMismatch(
                        "submission approval is invalid"
                    ) from error
                connection.execute(
                    insert(application_submission_approvals).values(
                        company_id=tenant,
                        action_id=action_id,
                        payload_sha256=payload_sha256,
                        decision_sha256=decision.decision_sha256,
                        status=decision.status.value,
                        decision=decision.model_dump(mode="json"),
                        decided_by=actor_id,
                        decided_at=decision.decided_at,
                    )
                )
                package = record.evidence.evidence.package
                assert package is not None
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=actor_id,
                            event_type="application.submission_approval_decided",
                            object_type="application_submission",
                            object_id=action_id,
                            object_version=package.case_version,
                            basis={
                                "payload_sha256": payload_sha256,
                                "decision_sha256": decision.decision_sha256,
                                "status": decision.status.value,
                                "expires_at": decision.approval.expires_at.isoformat()
                                if decision.approval
                                else None,
                                "external_action_performed": False,
                            },
                            occurred_at=now,
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={"action_id": action_id, "decision_sha256": decision.decision_sha256},
                )
                return decision
        except (
            ApplicationSubmissionConflict,
            ApplicationSubmissionNotFound,
            ApplicationSubmissionSourceMismatch,
            IdempotencyConflict,
        ):
            raise
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise ApplicationSubmissionConflict("submission approval conflicts") from error
            raise

    @staticmethod
    def _submission_attachment_bytes(
        connection: Connection,
        tenant: str,
        submission: ApplicationSubmissionRecord,
    ) -> dict[str, bytes]:
        package = submission.evidence.evidence.package
        if package is None:
            raise ApplicationSubmissionSourceMismatch("exact package is missing")
        result: dict[str, bytes] = {}
        for attachment in package.attachments:
            row = (
                connection.execute(
                    select(documents).where(
                        and_(
                            documents.c.company_id == tenant,
                            documents.c.document_id == attachment.document_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ApplicationSubmissionSourceMismatch("approved attachment is missing")
            try:
                document = DocumentRecord.model_validate(dict(row))
            except ValueError as error:
                raise ApplicationSubmissionSourceMismatch(
                    "approved attachment bytes are invalid"
                ) from error
            if (
                document.document_role is not DocumentRole.APPLICATION_ATTACHMENT
                or document.sha256 != attachment.document_sha256
                or document.original_filename != attachment.original_filename
                or document.media_type != attachment.media_type
            ):
                raise ApplicationSubmissionSourceMismatch("approved attachment metadata differs")
            result[attachment.document_id] = document.content
        return result

    def _load_application_submission_execution_record(
        self, connection: Connection, tenant: str, package_id: str
    ) -> ApplicationSubmissionExecutionRecord:
        submission = self._load_application_submission_record(connection, tenant, package_id)
        if submission.intent is None:
            return ApplicationSubmissionExecutionRecord(submission=submission)
        row = (
            connection.execute(
                select(application_submission_admissions).where(
                    and_(
                        application_submission_admissions.c.company_id == tenant,
                        application_submission_admissions.c.action_id
                        == submission.intent.request.action_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return ApplicationSubmissionExecutionRecord(submission=submission)
        try:
            admission = ApplicationSubmissionAdmission.model_validate(row["admission"])
            if (
                admission.company_id != tenant
                or admission.action_id != row["action_id"]
                or admission.package_id != row["package_id"]
                or admission.admission_id != row["admission_id"]
                or admission.payload_sha256 != row["payload_sha256"]
                or admission.approval_decision_sha256 != row["approval_decision_sha256"]
                or admission.admission_sha256 != row["admission_sha256"]
                or admission.admitted_by != row["admitted_by"]
                or admission.admitted_at != row["admitted_at"]
            ):
                raise ValueError("stored admission columns differ")
            attachment_bytes = self._submission_attachment_bytes(connection, tenant, submission)
            expected = build_submission_admission(
                submission,
                attachment_bytes=attachment_bytes,
                admission_id=admission.admission_id,
                admitted_by=admission.admitted_by,
                admitted_at=admission.admitted_at,
            )
            if expected != admission:
                raise ValueError("stored admission differs from original bytes")
            return ApplicationSubmissionExecutionRecord(submission=submission, admission=admission)
        except (ValueError, TypeError, KeyError) as error:
            raise ApplicationSubmissionSourceMismatch(
                "stored application admission cannot be reconstructed"
            ) from error

    def get_application_submission_execution(
        self, company_id: str, package_id: str
    ) -> ApplicationSubmissionExecutionRecord | None:
        tenant = _require_tenant(company_id)
        with self.transaction(tenant) as connection:
            try:
                return self._load_application_submission_execution_record(
                    connection, tenant, package_id
                )
            except ApplicationSubmissionNotFound:
                return None

    def claim_application_submission(
        self,
        company_id: str,
        actor_id: str,
        *,
        package_id: str,
        action_id: str,
        payload_sha256: str,
        approval_decision_sha256: str,
        idempotency_key: str,
        request_sha256: str,
    ) -> ApplicationSubmissionAdmission:
        tenant = _require_tenant(company_id)
        _require_sha256(payload_sha256, field="payload_sha256")
        _require_sha256(approval_decision_sha256, field="approval_decision_sha256")
        _require_sha256(request_sha256, field="request_sha256")
        if not actor_id.strip() or not package_id.strip() or not action_id.strip():
            raise ValueError("admission identities must not be blank")
        operation = "claim_application_submission"
        try:
            with self.transaction(tenant) as connection:
                self._lock_idempotency(connection, tenant, operation, idempotency_key)
                replay = self._existing_receipt(
                    connection, tenant, operation, idempotency_key, request_sha256
                )
                record = self._load_application_submission_execution_record(
                    connection, tenant, package_id
                )
                if replay is not None:
                    if (
                        record.admission is None
                        or record.admission.admission_id != replay.get("admission_id")
                        or record.admission.admission_sha256 != replay.get("admission_sha256")
                    ):
                        raise ApplicationSubmissionSourceMismatch(
                            "receipt references missing admission"
                        )
                    return record.admission
                if record.admission is not None:
                    raise ApplicationSubmissionConflict(
                        "approval has already been permanently claimed"
                    )
                submission = record.submission
                if (
                    submission.intent is None
                    or submission.decision is None
                    or submission.intent.request.action_id != action_id
                    or submission.intent.request.payload_sha256 != payload_sha256
                    or submission.decision.decision_sha256 != approval_decision_sha256
                ):
                    raise ApplicationSubmissionSourceMismatch("exact approved command differs")
                attachment_bytes = self._submission_attachment_bytes(connection, tenant, submission)
                now = datetime.now(UTC)
                try:
                    admission = build_submission_admission(
                        submission,
                        attachment_bytes=attachment_bytes,
                        admission_id=str(uuid.uuid4()),
                        admitted_by=actor_id,
                        admitted_at=now,
                    )
                except ValueError as error:
                    raise ApplicationSubmissionSourceMismatch(
                        "admission gates or exact bytes are invalid"
                    ) from error
                connection.execute(
                    insert(application_submission_admissions).values(
                        company_id=tenant,
                        action_id=action_id,
                        package_id=package_id,
                        admission_id=admission.admission_id,
                        payload_sha256=admission.payload_sha256,
                        approval_decision_sha256=admission.approval_decision_sha256,
                        admission_sha256=admission.admission_sha256,
                        admission=admission.model_dump(mode="json"),
                        admitted_by=actor_id,
                        admitted_at=admission.admitted_at,
                    )
                )
                package = submission.evidence.evidence.package
                assert package is not None
                connection.execute(
                    insert(audit_events).values(
                        **AuditEventRecord(
                            event_id=str(uuid.uuid4()),
                            company_id=tenant,
                            actor_id=actor_id,
                            event_type="application.submission_admitted",
                            object_type="application_submission",
                            object_id=action_id,
                            object_version=package.case_version,
                            basis={
                                "payload_sha256": payload_sha256,
                                "approval_decision_sha256": approval_decision_sha256,
                                "admission_sha256": admission.admission_sha256,
                                "attachment_count": len(admission.attachments),
                                "external_action_performed": False,
                            },
                            occurred_at=now,
                        ).model_dump(mode="python")
                    )
                )
                self._insert_receipt(
                    connection,
                    tenant=tenant,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    response={
                        "admission_id": admission.admission_id,
                        "admission_sha256": admission.admission_sha256,
                    },
                )
                return admission
        except (
            ApplicationSubmissionConflict,
            ApplicationSubmissionNotFound,
            ApplicationSubmissionSourceMismatch,
            IdempotencyConflict,
        ):
            raise
        except Exception as error:
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                raise ApplicationSubmissionConflict("admission already exists") from error
            raise

    def get_latest_evaluation(
        self,
        company_id: str,
        case_id: str,
        case_version: int,
    ) -> EvaluationRecord | None:
        """Load the latest persisted evaluation for one tenant-scoped case version."""
        tenant = _require_tenant(company_id)
        if not case_id:
            raise ValueError("case_id must not be empty")
        if case_version < 1:
            raise ValueError("case_version must be positive")
        statement = (
            select(evaluations)
            .where(
                and_(
                    evaluations.c.company_id == tenant,
                    evaluations.c.case_id == case_id,
                    evaluations.c.case_version == case_version,
                )
            )
            .order_by(evaluations.c.created_at.desc(), evaluations.c.evaluation_id.desc())
            .limit(1)
        )
        with self.transaction(tenant) as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return None if row is None else EvaluationRecord.model_validate(dict(row))

    def record_evaluation(
        self,
        company_id: str,
        actor_id: str,
        case_id: str,
        case_version: int,
        effective_at: datetime,
        input_digest: str,
        engine_version: str,
        recommendation: Recommendation,
        idempotency_key: str,
        request_sha256: str,
    ) -> EvaluationRecord:
        """Atomically persist a verified evaluation, audit fact, and replay receipt."""
        tenant = _require_tenant(company_id)
        _require_sha256(input_digest, field="input_digest")
        _require_sha256(request_sha256, field="request_sha256")
        candidate = EvaluationRecord(
            company_id=tenant,
            evaluation_id=str(uuid.uuid4()),
            case_id=case_id,
            case_version=case_version,
            effective_at=effective_at,
            input_sha256=input_digest,
            engine_version=engine_version,
            recommendation=recommendation,
        )
        with self.transaction(tenant) as connection:
            self._lock_idempotency(
                connection,
                tenant,
                "record_evaluation",
                idempotency_key,
            )
            replay = self._existing_receipt(
                connection,
                tenant,
                "record_evaluation",
                idempotency_key,
                request_sha256,
            )
            if replay is not None:
                replay_id = replay.get("evaluation_id")
                row = (
                    connection.execute(
                        select(evaluations).where(
                            and_(
                                evaluations.c.company_id == tenant,
                                evaluations.c.evaluation_id == replay_id,
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    raise StorageError("stored evaluation receipt points to a missing record")
                return EvaluationRecord.model_validate(dict(row))

            case_row = (
                connection.execute(
                    select(case_versions.c.payload, case_versions.c.input_sha256).where(
                        and_(
                            case_versions.c.company_id == tenant,
                            case_versions.c.case_id == case_id,
                            case_versions.c.version == case_version,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if case_row is None:
                raise StorageError("case version does not exist in the tenant")
            if case_row["input_sha256"] != input_digest:
                raise StorageError("input_digest does not match the stored case version")
            stored_case = ProcurementCase.model_validate(case_row["payload"])
            expected = evaluate_case(stored_case, at=effective_at)
            checked_recommendation = Recommendation.model_validate(
                recommendation.model_dump(mode="python")
            )
            if checked_recommendation != expected:
                raise StorageError("recommendation does not match deterministic evaluation")

            created_at = datetime.now(UTC)
            persisted = candidate.model_copy(update={"created_at": created_at})
            evaluation_values = persisted.model_dump(mode="python", exclude_none=True)
            evaluation_values["recommendation"] = persisted.recommendation.model_dump(mode="json")
            row = (
                connection.execute(
                    insert(evaluations).values(**evaluation_values).returning(evaluations)
                )
                .mappings()
                .one()
            )
            event = AuditEventRecord(
                event_id=candidate.evaluation_id,
                company_id=tenant,
                actor_id=actor_id,
                event_type="case.evaluated",
                object_type="procurement_case",
                object_id=case_id,
                object_version=case_version,
                basis={
                    "evaluation_id": candidate.evaluation_id,
                    "input_sha256": input_digest,
                    "engine_version": engine_version,
                    "effective_at": effective_at.isoformat(),
                },
                occurred_at=created_at,
            )
            connection.execute(insert(audit_events).values(**event.model_dump(mode="python")))
            self._insert_receipt(
                connection,
                tenant=tenant,
                operation="record_evaluation",
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
                response={"evaluation_id": candidate.evaluation_id},
            )
        return EvaluationRecord.model_validate(dict(row))
