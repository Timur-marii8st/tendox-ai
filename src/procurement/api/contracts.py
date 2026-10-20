"""Границы API и будущего tenant-scoped хранилища.

Протоколы намеренно асинхронны: PostgreSQL-адаптер может выполнять каждую
операцию без блокировки event loop. ``record_evaluation`` — одна транзакционная
граница для результата, audit event и идемпотентности.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.access import AccessRole
from procurement.documents import (
    AiProcurementItemCandidate,
    AiRequirementAnalysisReport,
    AiRequirementAnalysisReportV2,
    AiRequirementCandidate,
    AiRequirementCandidateDecision,
    AiRequirementReviewRecord,
    AiRequirementRunStatus,
    AiTransferRequirementChunkRejection,
    AiTransferRequirementMaterialization,
    ApplicationAttachmentInput,
    ApplicationAttachmentReview,
    ApplicationDocumentRequirement,
    ApplicationInventoryAssessment,
    ApplicationPackage,
    ApplicationPackageRecord,
    ApplicationPriceAssessment,
    ApplicationRequirementReview,
    ApplicationReviewDecision,
    ApplicationReviewRecord,
    CaseDocumentEvidenceBinding,
    CaseHardGateDecisionInput,
    CaseRequirementSetBinding,
    CompletenessBlockDecision,
    CompletenessReviewRecord,
    CompletenessStatus,
    DocumentBundleResult,
    DocumentRole,
    DocumentSearchEntry,
    DocumentSearchResult,
    DocumentSetCrossAssessment,
    DocumentSetEvidenceManifest,
    DocumentSetFinding,
    DocumentSetInventoryAssessment,
    DocumentSetMemberAttestation,
    DocumentSetReviewDecision,
    DocumentSetReviewEvidence,
    ExecutableRequirementSelection,
    ExtractionResult,
    ModelBrandCatalog,
    ModelBrandReviewProposal,
    ModelBrandReviewStatus,
    OcrDerivative,
    ParticipationDecision,
    ParticipationDecisionRecord,
    ParticipationDecisionStatus,
    RequirementSetCoverageAssessment,
    RequirementSetMaterializationPreview,
    RequirementSetNormalizationAssessment,
    ReviewedRequirementEntry,
    ReviewedRequirementSetRecord,
    ServerOfferBomLineInput,
    ServerOfferBomScopeAssessment,
    ServerOfferCommercialAssessment,
    ServerOfferCommercialTermsInput,
    ServerOfferEconomicsPackage,
    ServerOfferEconomicsRecord,
    ServerOfferProposal,
    ServerOfferRequirementDecision,
    ServerOfferReviewDecision,
    ServerOfferReviewRecord,
    ServerOfferScenarioInput,
    bundle_member_source_id,
    docx_media_source_id,
)
from procurement.documents.ai_transfer import (
    PersistedAiTransferApproval,
    PersistedAiTransferRequest,
)
from procurement.documents.ai_transfer_execution import (
    AiTransferDispatchClaim,
    AiTransferDispatchReceipt,
    AiTransferExecutionAdmission,
)
from procurement.documents.ai_transfer_raw import AiTransferRawMetadata
from procurement.documents.application_submission import (
    ApplicationSubmissionApproval,
    ApplicationSubmissionIntent,
    ApplicationSubmissionRecord,
    SubmissionApprovalStatus,
)
from procurement.documents.application_submission_execution import (
    ApplicationSubmissionAdmission,
    ApplicationSubmissionExecutionRecord,
)
from procurement.domain.cases import GateCheck, ProcurementCase
from procurement.domain.compliance import Verdict
from procurement.domain.decisions import Recommendation
from procurement.domain.sourcing import SourcingRunRecord


class AiTransferDetail(BaseModel):
    """Exact immutable approval payload, visible only to preparer and approver."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    request: PersistedAiTransferRequest
    approval: PersistedAiTransferApproval | None = None


class AiTransferExecutionDetail(BaseModel):
    """Durable execution evidence plus discoverable encrypted raw metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    admission: AiTransferExecutionAdmission
    claim: AiTransferDispatchClaim | None = None
    receipt: AiTransferDispatchReceipt | None = None
    raw_response: AiTransferRawMetadata | None = None

    @model_validator(mode="after")
    def _execution_evidence_is_exact(self) -> Self:
        claim = self.claim
        receipt = self.receipt
        raw = self.raw_response
        if claim is None:
            if receipt is not None or raw is not None:
                raise ValueError("AI transfer execution evidence lacks its claim")
            return self
        if (
            claim.company_id != self.admission.company_id
            or claim.execution_id != self.admission.execution_id
            or claim.transfer_id != self.admission.transfer_id
            or claim.request_payload_sha256 != self.admission.request_payload_sha256
            or claim.admission_payload_sha256 != self.admission.payload_sha256
        ):
            raise ValueError("AI transfer claim differs from execution admission")
        if receipt is None:
            if raw is not None:
                raise ValueError("AI transfer raw metadata lacks terminal receipt")
            return self
        if (
            receipt.company_id != claim.company_id
            or receipt.execution_id != claim.execution_id
            or receipt.transfer_id != claim.transfer_id
            or receipt.ordinal != claim.ordinal
            or receipt.claim_id != claim.claim_id
            or receipt.claim_payload_sha256 != claim.payload_sha256
            or receipt.chunk_id != claim.chunk_id
            or receipt.request_sha256 != claim.request_sha256
        ):
            raise ValueError("AI transfer receipt differs from current claim")
        if raw is not None and (
            raw.company_id != receipt.company_id
            or raw.execution_id != receipt.execution_id
            or raw.transfer_id != receipt.transfer_id
            or raw.ordinal != receipt.ordinal
            or raw.claim_id != receipt.claim_id
            or raw.claim_payload_sha256 != receipt.claim_payload_sha256
            or raw.receipt_id != receipt.receipt_id
            or raw.receipt_payload_sha256 != receipt.payload_sha256
            or raw.chunk_id != receipt.chunk_id
            or raw.request_sha256 != receipt.request_sha256
            or raw.response_body_sha256 != receipt.response_body_sha256
            or raw.response_byte_count != receipt.captured_byte_count
        ):
            raise ValueError("AI transfer raw metadata differs from current receipt")
        return self


class AiTransferRequirementBatchMaterializationDetail(BaseModel):
    """Raw-free recovery outcome for an ordered multi-chunk execution."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    company_id: str = Field(min_length=1, max_length=200)
    execution_id: str = Field(min_length=1, max_length=200)
    status: Literal["PENDING", "MATERIALIZED", "REJECTED"]
    materialized_ordinals: tuple[int, ...] = ()
    run_id: str | None = Field(default=None, min_length=1, max_length=200)
    run_evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    rejection: AiTransferRequirementChunkRejection | None = None

    @model_validator(mode="after")
    def _outcome_is_consistent(self) -> Self:
        if self.materialized_ordinals != tuple(range(1, len(self.materialized_ordinals) + 1)):
            raise ValueError("materialized AI transfer chunk ordinals must be contiguous")
        run_fields = (self.run_id, self.run_evidence_sha256)
        if self.status == "MATERIALIZED":
            if any(value is None for value in run_fields) or self.rejection is not None:
                raise ValueError("materialized AI transfer batch requires exact run evidence")
        elif self.status == "REJECTED":
            if any(value is not None for value in run_fields) or self.rejection is None:
                raise ValueError("rejected AI transfer batch requires one rejection receipt")
        elif any(value is not None for value in run_fields) or self.rejection is not None:
            raise ValueError("pending AI transfer batch cannot expose terminal evidence")
        if self.rejection is not None and (
            self.rejection.company_id != self.company_id
            or self.rejection.execution_id != self.execution_id
        ):
            raise ValueError("AI transfer batch rejection identity differs")
        return self


class AiTransferConflict(Exception):
    """Actor, request digest or terminal approval conflicts."""


class AiTransferNotFound(Exception):
    """Tenant-visible request or source document is absent."""


class InvalidAiTransfer(Exception):
    """Exact stored source/request evidence is invalid."""


class Principal(BaseModel):
    """Идентичность, полученная только из проверенного bearer credential."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    access_role: AccessRole = AccessRole.OPERATOR


class Authenticator(Protocol):
    """Проверяет credential; ``None`` единообразно означает отказ аутентификации."""

    async def authenticate(self, credential: str) -> Principal | None: ...


class CasePage(BaseModel):
    """Одна страница кейсов только одного арендатора."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[ProcurementCase, ...]
    next_cursor: str | None = None


class EvaluationRecord(BaseModel):
    """Долговечный результат вычисления и связанного append-only audit event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evaluation_id: str = Field(min_length=1)
    audit_event_id: str = Field(min_length=1)
    recommendation: Recommendation
    engine_version: str = Field(min_length=1)
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    effective_at: datetime


class DocumentRecord(BaseModel):
    """Public metadata and extraction result; source bytes never leave this boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str = Field(min_length=1)
    original_filename: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    document_role: DocumentRole
    byte_size: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extraction: ExtractionResult
    created_at: datetime


class AiRequirementReviewSummary(BaseModel):
    """Sanitized queue metadata; source extraction and provider payload stay private."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(min_length=1, max_length=200)
    source_document_id: str = Field(min_length=1, max_length=200)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    report_schema_version: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=500)
    execution_status: AiRequirementRunStatus
    completeness_status: CompletenessStatus
    requirement_candidates_total: int = Field(ge=0)
    procurement_item_candidates_total: int = Field(ge=0)
    submitted_by: str = Field(min_length=1, max_length=200)
    submitted_at: datetime
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewed: bool
    reviewed_by: str | None = Field(default=None, min_length=1, max_length=200)
    reviewed_at: datetime | None = None

    @model_validator(mode="after")
    def _review_metadata_is_consistent(self) -> Self:
        if self.submitted_at.utcoffset() is None:
            raise ValueError("AI requirement submission time must include a timezone")
        reviewer_fields_present = (
            self.reviewed_by is not None,
            self.reviewed_at is not None,
        )
        if self.reviewed and not all(reviewer_fields_present):
            raise ValueError("AI requirement review metadata is inconsistent")
        if not self.reviewed and any(reviewer_fields_present):
            raise ValueError("AI requirement review metadata is inconsistent")
        if self.reviewed_at is not None and self.reviewed_at.utcoffset() is None:
            raise ValueError("AI requirement review time must include a timezone")
        return self


class AiRequirementReviewDetail(AiRequirementReviewSummary):
    """Reviewer-only exact candidates and source evidence, without provider transcripts."""

    requirement_candidates: tuple[AiRequirementCandidate, ...]
    procurement_item_candidates: tuple[AiProcurementItemCandidate, ...]
    candidate_decisions: tuple[AiRequirementCandidateDecision, ...] | None = None


class DocumentSearchIndexRecord(BaseModel):
    """Public immutable search index; source bytes remain internal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

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
    def _entry_matches_source(self) -> Self:
        if (
            self.entry.document_id != self.source_document_id
            or self.entry.source_sha256 != self.source_document_sha256
        ):
            raise ValueError("search entry does not match source document")
        return self


class DocumentSearchPage(BaseModel):
    """Tenant-scoped discovery results from latest immutable index versions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str = Field(min_length=1)
    effective_at: datetime
    results: tuple[DocumentSearchResult, ...]

    @field_validator("effective_at")
    @classmethod
    def _effective_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("effective_at must include a timezone")
        return value

    @model_validator(mode="after")
    def _results_match_query(self) -> Self:
        if not self.query.strip() or any(result.query != self.query for result in self.results):
            raise ValueError("search results do not match query")
        return self


class ModelBrandCatalogRecord(BaseModel):
    """Public immutable reviewed catalog visible only to its bearer tenant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    catalog: ModelBrandCatalog
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _created_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value


class ModelBrandSourceArtifactRecord(BaseModel):
    """Public immutable official-source metadata; exact bytes stay internal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: str = Field(min_length=1, max_length=200)
    source_title: str = Field(min_length=1, max_length=500)
    source_url: str = Field(pattern=r"^https://", max_length=2_048)
    original_filename: str = Field(min_length=1, max_length=255)
    media_type: str = Field(pattern=r"^application/pdf$")
    byte_size: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieved_at: datetime
    created_at: datetime

    @field_validator("retrieved_at", "created_at")
    @classmethod
    def _times_are_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("model-brand source artifact times must include a timezone")
        return value


class ModelBrandReviewDecisionRecord(BaseModel):
    """Public terminal decision for one immutable review proposal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_id: str
    status: ModelBrandReviewStatus
    decided_by: str
    reason: str
    catalog_id: str | None = None
    created_at: datetime


class ModelBrandReviewRecord(BaseModel):
    """Public tenant-scoped proposal and its derived state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal: ModelBrandReviewProposal
    status: ModelBrandReviewStatus
    decision: ModelBrandReviewDecisionRecord | None = None


class DocumentBundleRecord(BaseModel):
    """Public ZIP metadata and typed member snapshots; source bytes stay internal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bundle_id: str = Field(min_length=1)
    original_filename: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    document_role: DocumentRole
    byte_size: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result: DocumentBundleResult
    created_at: datetime

    @model_validator(mode="after")
    def _result_matches_source(self) -> Self:
        if self.result.source_document_id != self.bundle_id:
            raise ValueError("bundle result source id does not match bundle_id")
        if self.result.source_sha256 != self.sha256:
            raise ValueError("bundle result SHA-256 does not match source metadata")
        return self


class OcrDerivativeRecord(BaseModel):
    """Public OCR derivative; source bytes never leave this boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ocr_id: str = Field(min_length=1)
    source_document_id: str = Field(min_length=1)
    engine: str = Field(min_length=1)
    threshold: float = Field(ge=0.0, le=1.0, multiple_of=0.01)
    result: OcrDerivative
    mean_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    created_at: datetime


class BundleMemberOcrRecord(BaseModel):
    """Public OCR derivative for one exact member of an immutable ZIP."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ocr_id: str = Field(min_length=1)
    source_bundle_id: str = Field(min_length=1)
    member_index: int = Field(ge=0)
    archive_path: str = Field(min_length=1, max_length=512)
    source_member_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    engine: str = Field(min_length=1)
    threshold: float = Field(ge=0.0, le=1.0, multiple_of=0.01)
    result: OcrDerivative
    mean_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    created_at: datetime

    @model_validator(mode="after")
    def _result_matches_member(self) -> Self:
        if self.result.source_document_id != bundle_member_source_id(
            self.source_bundle_id,
            self.member_index,
        ):
            raise ValueError("OCR result source id does not match bundle member")
        if self.result.source_sha256 != self.source_member_sha256:
            raise ValueError("OCR result SHA-256 does not match bundle member")
        return self


class DocxMediaOcrRecord(BaseModel):
    """Public OCR derivative for one verified image linked by an immutable DOCX."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ocr_id: str = Field(min_length=1)
    source_document_id: str = Field(min_length=1)
    media_index: int = Field(ge=0)
    archive_path: str = Field(min_length=1, max_length=512)
    source_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_media_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str = Field(pattern=r"^image/(jpeg|png)$")
    engine: str = Field(min_length=1)
    threshold: float = Field(ge=0.0, le=1.0, multiple_of=0.01)
    result: OcrDerivative
    mean_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    created_at: datetime

    @model_validator(mode="after")
    def _result_matches_media(self) -> Self:
        if self.result.source_document_id != docx_media_source_id(
            self.source_document_id,
            self.media_index,
        ):
            raise ValueError("OCR result source id does not match DOCX media")
        if self.result.source_sha256 != self.source_media_sha256:
            raise ValueError("OCR result SHA-256 does not match DOCX media")
        if self.result.engine != self.engine or self.result.threshold != self.threshold:
            raise ValueError("OCR result engine or threshold does not match record")
        if self.mean_confidence is not None and self.result.mean_confidence != self.mean_confidence:
            raise ValueError("OCR result mean confidence does not match record")
        return self


class VersionConflict(Exception):
    """Снимок уже существует либо Idempotency-Key использован с другим запросом."""


class InvalidModelBrandEvidence(Exception):
    """Reviewed catalog evidence is not backed by exact stored source bytes."""


class ModelBrandReviewConflict(Exception):
    """Review proposal or decision conflicts with immutable workflow state."""


class ModelBrandReviewNotFound(Exception):
    """Tenant-visible review proposal does not exist."""


class CompletenessReviewConflict(Exception):
    """Completeness review snapshot or decision conflicts with immutable state."""


class CompletenessReviewNotFound(Exception):
    """Tenant-visible source document or completeness review does not exist."""


class InvalidCompletenessReview(Exception):
    """Source evidence or reviewer payload cannot support a safe decision."""


class DocumentSetEvidenceConflict(Exception):
    """The immutable document-set manifest or its idempotency receipt conflicts."""


class DocumentSetEvidenceNotFound(Exception):
    """A tenant-visible manifest or selected completeness review is absent."""


class InvalidDocumentSetEvidence(Exception):
    """Selected review or source evidence cannot safely form a manifest."""


class DocumentSetReviewConflict(Exception):
    """A terminal document-set decision or its idempotency receipt conflicts."""


class DocumentSetReviewNotFound(Exception):
    """A tenant-visible document-set review resource is absent."""


class DocumentSetReviewSourceMismatch(Exception):
    """Exact document-set review evidence is stale or internally inconsistent."""


class InvalidDocumentSetReview(Exception):
    """Reviewer assertions cannot support a safe document-set decision."""


class CaseEvidenceConflict(Exception):
    """A case evidence binding or its idempotency receipt conflicts."""


class CaseEvidenceNotFound(Exception):
    """A tenant-visible manifest, decision, or binding is absent."""


class InvalidCaseEvidence(Exception):
    """Selected manifest/decision evidence cannot safely form a binding."""


class CaseHardGateAssessmentConflict(Exception):
    """The next assessed case version or idempotent request conflicts."""


class CaseHardGateAssessmentNotFound(Exception):
    """The source case or exact hard-gate evidence is absent."""


class InvalidCaseHardGateAssessment(Exception):
    """The source lineage or evidence cannot support hard-gate materialization."""


class RequirementSetConflict(Exception):
    """A requirement-set proposal, decision, binding, or receipt conflicts."""


class RequirementSetNotFound(Exception):
    """A tenant-visible requirement-set resource is absent."""


class InvalidRequirementSet(Exception):
    """Exact source/review evidence cannot safely form the requested resource."""


class ServerOfferConflict(Exception):
    """A server-offer proposal or its idempotency receipt conflicts."""


class ServerOfferNotFound(Exception):
    """A selected server-offer resource or source is absent."""


class InvalidServerOffer(Exception):
    """Exact binding, lead, quote, or BOM evidence cannot form the proposal."""


class ServerOfferReviewConflict(Exception):
    """A terminal offer review or its idempotency receipt conflicts."""


class ServerOfferReviewNotFound(Exception):
    """The exact offer-review evidence is absent."""


class InvalidServerOfferReview(Exception):
    """Exact stored evidence cannot safely support the requested offer review."""


class ServerOfferEconomicsConflict(Exception):
    """An economics package or idempotency receipt conflicts."""


class ServerOfferEconomicsNotFound(Exception):
    """The exact case or PASS offer needed for economics is absent."""


class InvalidServerOfferEconomics(Exception):
    """Exact case, review, or scenario inputs cannot form a package."""


class ParticipationDecisionConflict(Exception):
    """A terminal participation decision or idempotency receipt conflicts."""


class ParticipationDecisionNotFound(Exception):
    """The tenant-visible exact evaluation is absent."""


class InvalidParticipationDecision(Exception):
    """Exact evaluation evidence cannot support the requested decision."""


class ApplicationPackageConflict(Exception):
    """An application package or its idempotency receipt conflicts."""


class ApplicationPackageNotFound(Exception):
    """The tenant-visible approved participation decision is absent."""


class InvalidApplicationPackage(Exception):
    """Exact decision, case, price, requirement, or attachment evidence is invalid."""


class ApplicationReviewConflict(Exception):
    """An application review or its idempotency receipt conflicts."""


class ApplicationReviewNotFound(Exception):
    """The tenant-visible application package is absent."""


class InvalidApplicationReview(Exception):
    """Exact application package cannot support the requested review."""


class ApplicationSubmissionConflict(Exception):
    """Submission intent/approval or idempotency receipt conflicts."""


class ApplicationSubmissionNotFound(Exception):
    """The tenant-visible submission source is absent."""


class InvalidApplicationSubmission(Exception):
    """Exact reviewed package or approval request is invalid."""


class AiRequirementReviewConflict(Exception):
    """The imported AI run or its only terminal review conflicts."""


class AiRequirementRunNotFound(Exception):
    """Tenant-visible imported AI requirement run does not exist."""


class InvalidAiRequirementReview(Exception):
    """Exact stored source evidence cannot support the requested review."""


class InvalidCursor(Exception):
    """Cursor списка не был создан этим сервисом или повреждён."""


class CaseService(Protocol):
    """Tenant-scoped persistence boundary used by the HTTP layer."""

    async def store_ai_transfer_request(
        self,
        *,
        company_id: str,
        actor_id: str,
        source_document_id: str,
        model: str,
        idempotency_key: str,
        request_digest: str,
    ) -> PersistedAiTransferRequest:
        """Prepare exact source-bound payload without provider execution."""

    async def get_ai_transfer_request(
        self,
        *,
        company_id: str,
        transfer_id: str,
    ) -> AiTransferDetail | None:
        """Load and revalidate exactly one request and its optional approval."""

    async def approve_ai_transfer_request(
        self,
        *,
        company_id: str,
        actor_id: str,
        transfer_id: str,
        request_payload_sha256: str,
        idempotency_key: str,
        request_digest: str,
    ) -> PersistedAiTransferApproval:
        """Create the only independent exact-digest approval and audit receipt."""

    async def admit_ai_transfer_execution(
        self,
        *,
        company_id: str,
        actor_id: str,
        transfer_id: str,
        request_payload_sha256: str,
        idempotency_key: str,
        request_digest: str,
    ) -> AiTransferExecutionAdmission:
        """Consume one exact approval into a durable, non-dispatched execution."""

    async def get_ai_transfer_execution(
        self,
        *,
        company_id: str,
        execution_id: str,
    ) -> AiTransferExecutionDetail | None:
        """Load one exact admission and its optional permanent first claim."""

    async def read_ai_transfer_raw_response(
        self,
        *,
        company_id: str,
        actor_id: str,
        access_role: AccessRole,
        raw_response_id: str,
    ) -> tuple[bytes, AiTransferRawMetadata] | None:
        """Read one unexpired encrypted capture after committed access audit."""

    async def materialize_ai_transfer_requirement_run(
        self,
        *,
        company_id: str,
        actor_id: str,
        execution_id: str,
    ) -> tuple[AiTransferRequirementMaterialization, AiRequirementReviewRecord | None]:
        """Idempotently derive a raw-free review run from one exact capture."""

    async def materialize_ai_transfer_requirement_batch(
        self,
        *,
        company_id: str,
        actor_id: str,
        execution_id: str,
    ) -> AiTransferRequirementBatchMaterializationDetail:
        """Recover available chunks without network and publish only a complete batch."""

    async def create_case(
        self,
        *,
        company_id: str,
        case: ProcurementCase,
        idempotency_key: str,
        request_digest: str,
    ) -> ProcurementCase:
        """Создать immutable snapshot или повторить результат того же запроса.

        ``None`` ниже означает отсутствие в пределах ``company_id``; поэтому
        API одинаково отвечает на несуществующий и чужой идентификатор.
        """

    async def get_case(
        self, *, company_id: str, case_id: str, version: int
    ) -> ProcurementCase | None: ...

    async def list_cases(self, *, company_id: str, cursor: str | None, limit: int) -> CasePage: ...

    async def run_server_sourcing(
        self,
        *,
        company_id: str,
        actor_id: str,
        case_id: str,
        version: int,
        query: str,
        idempotency_key: str,
        request_digest: str,
    ) -> SourcingRunRecord:
        """Observe one allowlisted public source and persist the exact case-bound outcome."""

    async def get_latest_sourcing_run(
        self, *, company_id: str, case_id: str, version: int
    ) -> SourcingRunRecord | None:
        """Return the latest persisted run for this tenant-visible case version."""

    async def store_reviewed_requirement_set_proposal(
        self,
        *,
        company_id: str,
        actor_id: str,
        set_id: str,
        source_document_id: str,
        source_document_sha256: str,
        declared_scope: str,
        expected_entry_count: int,
        entries: tuple[ReviewedRequirementEntry, ...],
        idempotency_key: str,
        request_digest: str,
    ) -> ReviewedRequirementSetRecord: ...

    async def preview_reviewed_requirement_set_materialization(
        self,
        *,
        company_id: str,
        source_document_id: str,
        source_document_sha256: str,
        expected_entry_count: int,
    ) -> RequirementSetMaterializationPreview:
        """Derive an exact read-only row preview from persisted source extraction."""

    async def materialize_reviewed_requirement_set_proposal(
        self,
        *,
        company_id: str,
        actor_id: str,
        set_id: str,
        source_document_id: str,
        source_document_sha256: str,
        expected_entry_count: int,
        preview_sha256: str,
        declared_scope: str,
        selections: tuple[ExecutableRequirementSelection, ...],
        idempotency_key: str,
        request_digest: str,
    ) -> ReviewedRequirementSetRecord:
        """Commit exact source rows, promoting only explicit displayed suggestions."""

    async def decide_reviewed_requirement_set(
        self,
        *,
        company_id: str,
        reviewer_id: str,
        set_id: str,
        proposal_sha256: str,
        coverage_assessment: RequirementSetCoverageAssessment,
        normalization_assessment: RequirementSetNormalizationAssessment,
        status: Verdict,
        reason: str,
        idempotency_key: str,
        request_digest: str,
    ) -> ReviewedRequirementSetRecord: ...

    async def get_reviewed_requirement_set(
        self, *, company_id: str, set_id: str
    ) -> ReviewedRequirementSetRecord | None: ...

    async def bind_reviewed_requirement_set_to_case(
        self,
        *,
        company_id: str,
        actor_id: str,
        binding_id: str,
        case_id: str,
        case_version: int,
        set_id: str,
        proposal_sha256: str,
        decision_sha256: str,
        idempotency_key: str,
        request_digest: str,
    ) -> CaseRequirementSetBinding: ...

    async def get_case_requirement_set_binding(
        self, *, company_id: str, binding_id: str
    ) -> CaseRequirementSetBinding | None: ...

    async def store_server_offer_proposal(
        self,
        *,
        company_id: str,
        actor_id: str,
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
        request_digest: str,
    ) -> ServerOfferProposal: ...

    async def get_server_offer_proposal(
        self, *, company_id: str, offer_id: str
    ) -> ServerOfferProposal | None: ...

    async def get_server_offer_review(
        self, *, company_id: str, offer_id: str
    ) -> ServerOfferReviewRecord | None: ...

    async def decide_server_offer_proposal(
        self,
        *,
        company_id: str,
        reviewer_id: str,
        offer_id: str,
        proposal_sha256: str,
        requirement_decisions: tuple[ServerOfferRequirementDecision, ...],
        bom_scope_assessment: ServerOfferBomScopeAssessment,
        commercial_terms_assessment: ServerOfferCommercialAssessment,
        reason: str,
        idempotency_key: str,
        request_digest: str,
    ) -> ServerOfferReviewDecision: ...

    async def get_server_offer_economics(
        self,
        *,
        company_id: str,
        case_id: str,
        case_version: int,
        offer_id: str,
    ) -> ServerOfferEconomicsRecord | None: ...

    async def store_server_offer_economics(
        self,
        *,
        company_id: str,
        actor_id: str,
        economics_id: str,
        case_id: str,
        case_version: int,
        offer_id: str,
        offer_proposal_sha256: str,
        offer_review_decision_sha256: str,
        scenarios: tuple[ServerOfferScenarioInput, ...],
        idempotency_key: str,
        request_digest: str,
    ) -> ServerOfferEconomicsPackage: ...

    async def materialize_case_from_server_offer_economics(
        self,
        *,
        company_id: str,
        actor_id: str,
        case_id: str,
        case_version: int,
        offer_id: str,
        economics_id: str,
        package_sha256: str,
        idempotency_key: str,
        request_digest: str,
    ) -> ProcurementCase: ...

    async def materialize_case_hard_gate_assessment(
        self,
        *,
        company_id: str,
        actor_id: str,
        case_id: str,
        case_version: int,
        source_case_input_sha256: str,
        document_binding_id: str,
        manifest_evidence_sha256: str,
        document_decision_sha256: str,
        decisions: tuple[CaseHardGateDecisionInput, ...],
        idempotency_key: str,
        request_digest: str,
    ) -> ProcurementCase: ...

    async def get_latest_evaluation(
        self,
        *,
        company_id: str,
        case_id: str,
        version: int,
    ) -> EvaluationRecord | None:
        """Return only an already persisted result; absence remains ``None``."""

    async def record_evaluation(
        self,
        *,
        company_id: str,
        actor_id: str,
        case_id: str,
        version: int,
        effective_at: datetime,
        recommendation: Recommendation,
        engine_version: str,
        input_digest: str,
        idempotency_key: str,
        request_digest: str,
    ) -> EvaluationRecord:
        """Atomically persist evaluation, audit fact, and idempotency state.

        Reusing a key with a distinct ``request_digest`` raises
        :class:`VersionConflict`.
        """

    async def get_participation_decision(
        self,
        *,
        company_id: str,
        evaluation_id: str,
    ) -> ParticipationDecisionRecord | None:
        """Return exact evaluation evidence and its optional terminal decision."""

    async def decide_participation(
        self,
        *,
        company_id: str,
        actor_id: str,
        evaluation_id: str,
        evaluation_evidence_sha256: str,
        status: ParticipationDecisionStatus,
        reason: str,
        idempotency_key: str,
        request_digest: str,
    ) -> ParticipationDecision:
        """Atomically persist an internal decision, audit event, and receipt."""

    async def get_application_package(
        self,
        *,
        company_id: str,
        participation_decision_id: str,
    ) -> ApplicationPackageRecord | None:
        """Return approved participation evidence and its optional package."""

    async def store_application_package(
        self,
        *,
        company_id: str,
        actor_id: str,
        package_id: str,
        participation_decision_id: str,
        participation_decision_sha256: str,
        proposed_price_ex_vat: Decimal,
        requirements: tuple[ApplicationDocumentRequirement, ...],
        attachments: tuple[ApplicationAttachmentInput, ...],
        idempotency_key: str,
        request_digest: str,
    ) -> ApplicationPackage:
        """Atomically persist one exact unreviewed application package."""

    async def get_application_review(
        self, *, company_id: str, package_id: str
    ) -> ApplicationReviewRecord | None:
        """Return exact package evidence and optional terminal review."""

    async def decide_application_review(
        self,
        *,
        company_id: str,
        actor_id: str,
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
        request_digest: str,
    ) -> ApplicationReviewDecision:
        """Atomically persist one independent exact-package review."""

    async def get_application_submission(
        self, *, company_id: str, package_id: str
    ) -> ApplicationSubmissionRecord | None:
        """Return exact reviewed package and optional submission intent/decision."""

    async def prepare_application_submission(
        self,
        *,
        company_id: str,
        actor_id: str,
        package_id: str,
        package_sha256: str,
        review_decision_sha256: str,
        destination: str,
        idempotency_key: str,
        request_digest: str,
    ) -> ApplicationSubmissionIntent:
        """Atomically persist one exact internal submission command."""

    async def decide_application_submission(
        self,
        *,
        company_id: str,
        actor_id: str,
        action_id: str,
        payload_sha256: str,
        status: SubmissionApprovalStatus,
        reason: str,
        idempotency_key: str,
        request_digest: str,
    ) -> ApplicationSubmissionApproval:
        """Atomically decide the exact command with an independent actor."""

    async def get_application_submission_execution(
        self, *, company_id: str, package_id: str
    ) -> ApplicationSubmissionExecutionRecord | None:
        """Return exact submission and optional permanent admission."""

    async def claim_application_submission(
        self,
        *,
        company_id: str,
        actor_id: str,
        package_id: str,
        action_id: str,
        payload_sha256: str,
        approval_decision_sha256: str,
        idempotency_key: str,
        request_digest: str,
    ) -> ApplicationSubmissionAdmission:
        """Consume one current approval after verifying original attachment bytes."""

    async def store_document(
        self,
        *,
        company_id: str,
        actor_id: str,
        document_id: str,
        original_filename: str,
        media_type: str,
        document_role: DocumentRole,
        content: bytes,
        extraction: ExtractionResult,
        idempotency_key: str,
        request_digest: str,
    ) -> DocumentRecord:
        """Persist source bytes, typed extraction, audit event, and receipt atomically."""

    async def get_document(
        self,
        *,
        company_id: str,
        document_id: str,
    ) -> DocumentRecord | None:
        """Return only tenant-visible metadata and extraction, never source bytes."""

    async def get_document_content(
        self,
        *,
        company_id: str,
        document_id: str,
    ) -> bytes | None:
        """Return source bytes only to an internal tenant-scoped processing workflow."""

    async def store_completeness_review(
        self,
        *,
        company_id: str,
        actor_id: str,
        review_id: str,
        source_document_id: str,
        idempotency_key: str,
        request_digest: str,
    ) -> CompletenessReviewRecord:
        """Derive and atomically persist one immutable snapshot."""

    async def get_completeness_review(
        self,
        *,
        company_id: str,
        review_id: str,
    ) -> CompletenessReviewRecord | None: ...

    async def store_document_set_evidence_manifest(
        self,
        *,
        company_id: str,
        actor_id: str,
        manifest_id: str,
        scope: str,
        review_refs: tuple[tuple[str, str], ...],
        idempotency_key: str,
        request_digest: str,
    ) -> DocumentSetEvidenceManifest:
        """Persist one explicit ordered evidence set or replay its exact receipt."""

    async def get_document_set_evidence_manifest(
        self,
        *,
        company_id: str,
        manifest_id: str,
    ) -> DocumentSetEvidenceManifest | None: ...

    async def list_completeness_reviews(
        self,
        *,
        company_id: str,
        limit: int,
    ) -> tuple[CompletenessReviewRecord, ...]: ...

    async def decide_completeness_review(
        self,
        *,
        company_id: str,
        reviewer_id: str,
        review_id: str,
        evidence_sha256: str,
        status: CompletenessStatus,
        scope: str,
        reason: str,
        block_decisions: tuple[CompletenessBlockDecision, ...],
        idempotency_key: str,
        request_digest: str,
    ) -> CompletenessReviewRecord:
        """Persist the only decision, its audit event, and receipt atomically."""

    async def get_document_set_review_evidence(
        self,
        *,
        company_id: str,
        manifest_id: str,
    ) -> DocumentSetReviewEvidence | None:
        """Return exact constituent evidence; absence stays tenant-scoped."""

    async def store_document_set_review_decision(
        self,
        *,
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
        request_digest: str,
    ) -> DocumentSetReviewDecision:
        """Persist the only exact-evidence terminal decision for one manifest."""

    async def get_document_set_review_decision(
        self,
        *,
        company_id: str,
        manifest_id: str,
    ) -> DocumentSetReviewDecision | None:
        """Return the already-persisted terminal decision, never a latest selection."""

    async def store_case_document_evidence_binding(
        self,
        *,
        company_id: str,
        actor_id: str,
        binding_id: str,
        manifest_id: str,
        manifest_evidence_sha256: str,
        decision_sha256: str,
        idempotency_key: str,
        request_digest: str,
    ) -> CaseDocumentEvidenceBinding:
        """Bind one exact terminal decision to a case draft or replay its receipt."""

    async def get_case_document_evidence_binding(
        self,
        *,
        company_id: str,
        binding_id: str,
    ) -> CaseDocumentEvidenceBinding | None:
        """Return one tenant-visible binding; absence stays tenant-scoped."""

    async def create_case_from_evidence(
        self,
        *,
        company_id: str,
        actor_id: str,
        case: ProcurementCase,
        binding_id: str,
        manifest_evidence_sha256: str,
        decision_sha256: str,
        other_checks: tuple[GateCheck, ...],
        idempotency_key: str,
        request_digest: str,
    ) -> ProcurementCase:
        """Create a case version with a server-derived DOCUMENT gate or replay it."""

    async def get_ai_requirement_run(
        self,
        *,
        company_id: str,
        run_id: str,
    ) -> AiRequirementReviewRecord | None:
        """Return one tenant-visible imported AI run for reviewer projection."""

    async def store_ai_requirement_run(
        self,
        *,
        company_id: str,
        actor_id: str,
        source_document_id: str,
        report: AiRequirementAnalysisReport | AiRequirementAnalysisReportV2,
        idempotency_key: str,
        request_digest: str,
    ) -> AiRequirementReviewRecord:
        """Import one untrusted report and bind it to exact stored source evidence."""

    async def list_ai_requirement_runs(
        self,
        *,
        company_id: str,
        limit: int,
    ) -> tuple[AiRequirementReviewRecord, ...]:
        """List tenant-visible imported AI runs; API chooses a sanitized projection."""

    async def decide_ai_requirement_review(
        self,
        *,
        company_id: str,
        reviewer_id: str,
        run_id: str,
        evidence_sha256: str,
        candidate_decisions: tuple[AiRequirementCandidateDecision, ...],
        idempotency_key: str,
        request_digest: str,
    ) -> AiRequirementReviewRecord:
        """Persist the exact-evidence terminal decision and receipt atomically."""

    async def store_document_search_index(
        self,
        *,
        company_id: str,
        actor_id: str,
        search_index_id: str,
        source_document_id: str,
        entry: DocumentSearchEntry,
        idempotency_key: str,
        request_digest: str,
    ) -> DocumentSearchIndexRecord:
        """Persist exact search evidence, audit event, and receipt atomically."""

    async def search_document_indexes(
        self,
        *,
        company_id: str,
        query: str,
        limit: int,
        effective_at: datetime,
    ) -> DocumentSearchPage:
        """Search only latest index versions visible to one tenant."""

    async def store_model_brand_source_artifact(
        self,
        *,
        company_id: str,
        actor_id: str,
        artifact_id: str,
        source_title: str,
        source_url: str,
        original_filename: str,
        content: bytes,
        retrieved_at: datetime,
        idempotency_key: str,
        request_digest: str,
    ) -> ModelBrandSourceArtifactRecord:
        """Persist exact official PDF bytes, audit event, and receipt atomically."""

    async def get_model_brand_source_artifact(
        self,
        *,
        company_id: str,
        artifact_id: str,
    ) -> ModelBrandSourceArtifactRecord | None:
        """Return tenant-visible artifact metadata without source bytes."""

    async def store_model_brand_review_proposal(
        self,
        *,
        company_id: str,
        actor_id: str,
        proposal: ModelBrandReviewProposal,
        idempotency_key: str,
        request_digest: str,
    ) -> ModelBrandReviewRecord:
        """Persist an immutable DRAFT after exact artifact verification."""

    async def list_model_brand_reviews(
        self,
        *,
        company_id: str,
        limit: int,
    ) -> tuple[ModelBrandReviewRecord, ...]:
        """List tenant-visible review states."""

    async def decide_model_brand_review(
        self,
        *,
        company_id: str,
        reviewer_id: str,
        proposal_id: str,
        decision: ModelBrandReviewStatus,
        reason: str,
        idempotency_key: str,
        request_digest: str,
    ) -> ModelBrandReviewRecord:
        """Atomically approve and publish, or reject, one DRAFT."""

    async def get_latest_model_brand_catalog(
        self,
        *,
        company_id: str,
        effective_at: datetime,
    ) -> ModelBrandCatalogRecord | None:
        """Return latest catalog visible at an explicit effective time."""

    async def store_document_bundle(
        self,
        *,
        company_id: str,
        actor_id: str,
        bundle_id: str,
        original_filename: str,
        media_type: str,
        document_role: DocumentRole,
        content: bytes,
        result: DocumentBundleResult,
        idempotency_key: str,
        request_digest: str,
    ) -> DocumentBundleRecord:
        """Persist one immutable ZIP, typed member snapshots, audit, and receipt."""

    async def get_document_bundle(
        self,
        *,
        company_id: str,
        bundle_id: str,
    ) -> DocumentBundleRecord | None:
        """Return tenant-visible ZIP metadata and members, never source bytes."""

    async def get_document_bundle_content(
        self,
        *,
        company_id: str,
        bundle_id: str,
    ) -> bytes | None:
        """Return ZIP bytes only to an internal tenant-scoped processing workflow."""

    async def store_ocr_derivative(
        self,
        *,
        company_id: str,
        actor_id: str,
        ocr_id: str,
        source_document_id: str,
        engine: str,
        threshold: float,
        result: OcrDerivative,
        mean_confidence: float | None,
        idempotency_key: str,
        request_digest: str,
    ) -> OcrDerivativeRecord:
        """Persist one immutable OCR derivative, audit fact, and receipt atomically."""

    async def get_ocr_derivative(
        self,
        *,
        company_id: str,
        ocr_id: str,
    ) -> OcrDerivativeRecord | None:
        """Return only a tenant-visible OCR derivative."""

    async def get_latest_ocr_for_document(
        self,
        *,
        company_id: str,
        source_document_id: str,
    ) -> OcrDerivativeRecord | None:
        """Return the latest tenant-visible OCR derivative for one source document."""

    async def store_bundle_member_ocr_derivative(
        self,
        *,
        company_id: str,
        actor_id: str,
        ocr_id: str,
        source_bundle_id: str,
        member_index: int,
        archive_path: str,
        source_member_sha256: str,
        engine: str,
        threshold: float,
        result: OcrDerivative,
        mean_confidence: float | None,
        idempotency_key: str,
        request_digest: str,
    ) -> BundleMemberOcrRecord:
        """Persist immutable OCR evidence for one verified PDF member."""

    async def get_bundle_member_ocr_derivative(
        self,
        *,
        company_id: str,
        ocr_id: str,
    ) -> BundleMemberOcrRecord | None:
        """Return one tenant-visible bundle-member OCR derivative."""

    async def get_latest_ocr_for_bundle_member(
        self,
        *,
        company_id: str,
        source_bundle_id: str,
        member_index: int,
    ) -> BundleMemberOcrRecord | None:
        """Return latest OCR evidence for one exact tenant-visible member."""

    async def store_docx_media_ocr_derivative(
        self,
        *,
        company_id: str,
        actor_id: str,
        ocr_id: str,
        source_document_id: str,
        media_index: int,
        archive_path: str,
        source_document_sha256: str,
        source_media_sha256: str,
        media_type: str,
        engine: str,
        threshold: float,
        result: OcrDerivative,
        mean_confidence: float | None,
        idempotency_key: str,
        request_digest: str,
    ) -> DocxMediaOcrRecord:
        """Persist immutable OCR evidence for one verified linked DOCX image."""

    async def get_docx_media_ocr_derivative(
        self,
        *,
        company_id: str,
        ocr_id: str,
    ) -> DocxMediaOcrRecord | None:
        """Return one tenant-visible DOCX-media OCR derivative."""

    async def get_latest_ocr_for_docx_media(
        self,
        *,
        company_id: str,
        source_document_id: str,
        media_index: int,
    ) -> DocxMediaOcrRecord | None:
        """Return latest OCR evidence for one exact linked DOCX image."""
