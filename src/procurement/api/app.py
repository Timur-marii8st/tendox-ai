"""FastAPI factory with authentication and tenant isolation at the boundary."""

import asyncio
import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from functools import partial
from typing import Annotated, Literal, Self, TypeVar
from urllib.parse import quote

from anyio import to_thread
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy.exc import SQLAlchemyError

from procurement.access import AccessRole
from procurement.api.company_profile import company_profile_router
from procurement.api.comparison import comparison_router
from procurement.api.contracts import (
    AiRequirementReviewConflict,
    AiRequirementReviewDetail,
    AiRequirementReviewSummary,
    AiRequirementRunNotFound,
    AiTransferConflict,
    AiTransferDetail,
    AiTransferExecutionDetail,
    AiTransferNotFound,
    AiTransferRequirementBatchMaterializationDetail,
    ApplicationPackageConflict,
    ApplicationPackageNotFound,
    ApplicationReviewConflict,
    ApplicationReviewNotFound,
    ApplicationSubmissionConflict,
    ApplicationSubmissionNotFound,
    Authenticator,
    BundleMemberOcrRecord,
    CaseEvidenceConflict,
    CaseEvidenceNotFound,
    CaseHardGateAssessmentConflict,
    CaseHardGateAssessmentNotFound,
    CasePage,
    CaseService,
    CompletenessReviewConflict,
    CompletenessReviewNotFound,
    DocumentBundleRecord,
    DocumentRecord,
    DocumentSearchIndexRecord,
    DocumentSearchPage,
    DocumentSetEvidenceConflict,
    DocumentSetEvidenceNotFound,
    DocumentSetReviewConflict,
    DocumentSetReviewNotFound,
    DocumentSetReviewSourceMismatch,
    DocxMediaOcrRecord,
    EvaluationRecord,
    InvalidAiRequirementReview,
    InvalidAiTransfer,
    InvalidApplicationPackage,
    InvalidApplicationReview,
    InvalidApplicationSubmission,
    InvalidCaseEvidence,
    InvalidCaseHardGateAssessment,
    InvalidCompletenessReview,
    InvalidCursor,
    InvalidDocumentSetEvidence,
    InvalidDocumentSetReview,
    InvalidModelBrandEvidence,
    InvalidParticipationDecision,
    InvalidRequirementSet,
    InvalidServerOffer,
    InvalidServerOfferEconomics,
    InvalidServerOfferReview,
    ModelBrandCatalogRecord,
    ModelBrandReviewConflict,
    ModelBrandReviewNotFound,
    ModelBrandReviewRecord,
    ModelBrandSourceArtifactRecord,
    OcrDerivativeRecord,
    ParticipationDecisionConflict,
    ParticipationDecisionNotFound,
    Principal,
    RequirementSetConflict,
    RequirementSetNotFound,
    ServerOfferConflict,
    ServerOfferEconomicsConflict,
    ServerOfferEconomicsNotFound,
    ServerOfferNotFound,
    ServerOfferReviewConflict,
    ServerOfferReviewNotFound,
    VersionConflict,
)
from procurement.api.eis_document_review_runner import (
    ReviewRunnerFailure,
    run_prepare_review_subprocess,
)
from procurement.api.eis_supplier_catalog_runner import (
    SupplierRunnerFailure as SupplierCatalogRunnerFailure,
)
from procurement.api.eis_supplier_catalog_runner import (
    run_prepare_supplier_catalog_subprocess,
)
from procurement.api.eis_supplier_page_runner import (
    SupplierRunnerFailure as SupplierPageRunnerFailure,
)
from procurement.api.eis_supplier_page_runner import (
    run_prepare_supplier_page_subprocess,
)
from procurement.api.eis_supplier_search_runner import (
    SupplierRunnerFailure,
    run_prepare_supplier_subprocess,
)
from procurement.api.eis_supplier_serp_runner import (
    SupplierRunnerFailure as SupplierSerpRunnerFailure,
)
from procurement.api.eis_supplier_serp_runner import (
    run_prepare_supplier_serp_subprocess,
)
from procurement.api.manufacturer_directory import manufacturer_directory_router
from procurement.api.manufacturer_review import manufacturer_review_router
from procurement.api.manufacturer_rfq import manufacturer_rfq_router
from procurement.api.manufacturer_search import manufacturer_search_router
from procurement.documents import (
    MAX_UPLOAD_BYTES,
    AiRequirementAnalysisReport,
    AiRequirementAnalysisReportV2,
    AiRequirementCandidateDecision,
    AiRequirementReviewRecord,
    AiRequirementRunStatus,
    AiRequirementTransferBatchRunSnapshot,
    AiRequirementTransferRunSnapshot,
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
    BundleRejectionCode,
    CaseDocumentEvidenceBinding,
    CaseHardGateDecisionInput,
    CaseRequirementSetBinding,
    CompletenessBlockDecision,
    CompletenessReviewRecord,
    CompletenessStatus,
    DocumentBundleMemberUnavailable,
    DocumentBundleRejected,
    DocumentInput,
    DocumentRejected,
    DocumentRejectionCode,
    DocumentRole,
    DocumentSetCrossAssessment,
    DocumentSetEvidenceManifest,
    DocumentSetFinding,
    DocumentSetFindingOrigin,
    DocumentSetInventoryAssessment,
    DocumentSetMemberAttestation,
    DocumentSetReviewDecision,
    DocumentSetReviewEvidence,
    DocxMediaRejected,
    ExecutableRequirementSelection,
    ExtractionReason,
    ExtractionResult,
    ExtractionStatus,
    ModelBrandCatalogEntry,
    ModelBrandReviewProposal,
    ModelBrandReviewStatus,
    NoopOcrRunner,
    OcrCandidate,
    OcrEngineError,
    OcrRunner,
    OcrSourceRejected,
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
    VisionSearchTagManifest,
    build_document_search_entry,
    build_ocr_derivative,
    canonical_json_sha256,
    extract_document,
    extract_document_bundle,
    extract_docx_media,
    read_document_bundle_member,
)
from procurement.documents.ai_transfer import (
    PersistedAiTransferApproval,
    PersistedAiTransferRequest,
)
from procurement.documents.ai_transfer_execution import AiTransferExecutionAdmission
from procurement.documents.application_handoff import (
    MAX_HANDOFF_BYTES,
    build_application_handoff,
)
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
from procurement.documents.ocr import DEFAULT_OCR_CONFIDENCE_THRESHOLD, OcrEngineInput
from procurement.domain.cases import (
    GateCheck,
    GateKind,
    ProcurementCase,
    case_input_digest,
    evaluate_case,
)
from procurement.domain.compliance import Verdict
from procurement.domain.decisions import GateStatus
from procurement.domain.discovery_economics import DiscoveryCostInput
from procurement.domain.sourcing import SourcingRunRecord
from procurement.sources import eis_workflow
from procurement.sources.browser_catalog import BrowserAttempt, BrowserSite
from procurement.sources.browser_worker import run_browser_source
from procurement.sources.depo_catalog import DepoAttempt, search_depo_catalog
from procurement.sources.direct_catalog import DirectCatalogAttempt, search_direct_catalog
from procurement.sources.document_search_plan import (
    DocumentSupplierSearchPlan,
    SearchMode,
    SearchPlanStatus,
    build_document_supplier_search_plan,
)
from procurement.sources.eaeu_manufacturers import (
    ManufacturerSearchResult,
    search_eaeu_manufacturers,
)
from procurement.sources.eaeu_registry import RegistrySearchResult, search_eaeu_registry
from procurement.sources.eis_223_documents import Notice223DocumentRef
from procurement.sources.eis_analogs import AnalogReport, AnalogRequest
from procurement.sources.eis_analysis import DocumentAnalysis
from procurement.sources.eis_characteristic_compare import (
    CharacteristicPairReport,
    CharacteristicPairRequest,
)
from procurement.sources.eis_discovery import (
    EisDiscoveryResult,
    EisDocumentPreview,
    EisExportError,
    discover_from_export,
    inspect_official_attachment,
)
from procurement.sources.eis_feed_archive import EisFeedArchiveError
from procurement.sources.eis_feed_sync import EisSyncError
from procurement.sources.eis_number_sync import EisNumberSyncResult, sync_eis_number_via_browser
from procurement.sources.eis_position_association import (
    AssociationDetailRequest,
    AssociationListRequest,
    AssociationListResult,
    AssociationRequest,
    SavedAssociation,
)
from procurement.sources.eis_public import (
    EisPublicDocumentsResult,
    EisPublicError,
    EisPublicSearchResult,
    read_public_documents,
    search_public_eis,
)
from procurement.sources.eis_requirement_preview import (
    RequirementPreview,
    RequirementPreviewRequest,
)
from procurement.sources.eis_requirement_review import (
    DecisionRequest,
    ProposalRequest,
    RequirementComparison,
)
from procurement.sources.eis_supplier_product import (
    SavedSupplierProduct,
    SupplierProductRequest,
)
from procurement.sources.graviton_catalog import GravitonAttempt, search_graviton_catalog
from procurement.sources.yandex_business import (
    YandexBusinessAttempt,
    search_yandex_business_category,
)
from procurement.storage.eis_223_comparison import (
    Comparison223Request,
    Comparison223Result,
    get_comparison223,
)
from procurement.storage.eis_223_document_queue import plan_document223_job
from procurement.storage.eis_223_documents import Document223Status, get_document223_status
from procurement.storage.eis_223_index import Eis223SearchResult, search_notice223_index
from procurement.storage.eis_223_regions import Eis223RegionalCoverage, read_region_coverage
from procurement.storage.eis_analogs import read_analog_candidates
from procurement.storage.eis_characteristic_compare import read_characteristic_pair
from procurement.storage.eis_comparison import (
    EisComparisonRequest,
    EisComparisonResult,
    get_eis_comparison,
)
from procurement.storage.eis_document_review import (
    ReviewDocumentRequest,
    SavedReviewDocumentPage,
    read_review_document_page,
)
from procurement.storage.eis_document_store import (
    DocumentCollectionStatus,
    DocumentSelectionRequest,
    DocumentSelectionResult,
    NoticeDocumentRef,
    get_document_analysis,
    get_document_status,
    plan_document_job,
    plan_top_document_jobs,
)
from procurement.storage.eis_evidence_bridge import (
    EisEvidenceBridge,
    EisPreliminaryEstimate,
    estimate_eis_notice,
    get_eis_evidence_bridge,
)
from procurement.storage.eis_freshness_requests import (
    EisRefreshRequestPayload,
    EisRefreshStatus,
    get_refresh_status,
    plan_refresh_request,
)
from procurement.storage.eis_index_query import (
    EisIndexedSearchResult,
    EisIndexSearchScope,
    search_eis_index,
)
from procurement.storage.eis_mixed_comparison import (
    MixedComparisonRequest,
    MixedComparisonResult,
    get_mixed_comparison,
)
from procurement.storage.eis_notice_index import EisIndexConflict
from procurement.storage.eis_position_association import (
    list_position_fragment_associations,
    read_position_fragment_association,
    read_position_fragment_association_detail,
    save_position_fragment_association,
)
from procurement.storage.eis_protocols import EisHistoricalProtocolReport, read_historical_protocols
from procurement.storage.eis_requirement_preview import read_requirement_preview
from procurement.storage.eis_requirement_review import (
    SavedRequirementDecision,
    SavedRequirementProposal,
    create_requirement_decision,
    create_requirement_proposal,
    read_requirement_comparison,
    read_requirement_proposal,
)
from procurement.storage.eis_source_estimate import (
    SourceEstimateRequest,
    SourceEstimateResult,
    SourceLotError,
    get_source_estimate,
)
from procurement.storage.eis_supplier_catalog import (
    SavedSupplierCatalog,
    SupplierCatalogRequest,
    read_supplier_catalog,
)
from procurement.storage.eis_supplier_page import (
    SavedSupplierPage,
    SupplierPageRequest,
    read_supplier_page,
)
from procurement.storage.eis_supplier_product import (
    prepare_supplier_product,
    read_supplier_product,
)
from procurement.storage.eis_supplier_search import (
    SavedSupplierSearch,
    SupplierSearchRequest,
    read_supplier_search,
)
from procurement.storage.eis_supplier_serp import (
    SavedSupplierSerp,
    read_supplier_serp,
)
from procurement.storage.repository import PostgresStorage

ENGINE_VERSION = "s1"
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 50
MAX_AI_REQUIREMENT_IMPORT_BYTES = MAX_UPLOAD_BYTES
MAX_DOCUMENT_SET_EVIDENCE_REQUEST_BYTES = 16 * 1024
MAX_CASE_EVIDENCE_REQUEST_BYTES = 16 * 1024
MAX_CASE_FROM_EVIDENCE_REQUEST_BYTES = 256 * 1024
MAX_DOCUMENT_SET_REVIEW_REQUEST_BYTES = 256 * 1024
MAX_AI_TRANSFER_REQUEST_BYTES = 16 * 1024
MAX_REQUIREMENT_SET_REQUEST_BYTES = 2 * 1024 * 1024
MAX_SERVER_OFFER_REQUEST_BYTES = 2 * 1024 * 1024
_IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9._:-]{1,128}")
_bearer = HTTPBearer(auto_error=False, scheme_name="BearerAuth")


class AiTransferPrepareRequest(BaseModel):
    """Only a reviewed model choice; exact source and transport are server-owned."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    model: Literal["google/gemma-4-31b-it:free", "inclusionai/ling-3.0-flash-vl:free"]


class AiTransferApprovalRequest(BaseModel):
    """Approve exactly the payload displayed by the exact request read."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    request_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AiTransferExecutionAdmissionRequest(BaseModel):
    """Consume only the approval for the exact displayed request digest."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    request_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


_TransferBody = TypeVar("_TransferBody", bound=BaseModel)


async def _read_ai_transfer_body(request: Request, schema: type[_TransferBody]) -> _TransferBody:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(status_code=415, detail="unsupported_media_type")
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            length = int(declared)
            if length < 0:
                raise ValueError
        except ValueError as error:
            raise HTTPException(status_code=422, detail="invalid_ai_transfer") from error
        if length > MAX_AI_TRANSFER_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail="ai_transfer_request_too_large")
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_AI_TRANSFER_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail="ai_transfer_request_too_large")
        content.extend(chunk)
    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
        return schema.model_validate(payload)
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise HTTPException(status_code=422, detail="invalid_ai_transfer") from error


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str


class EvaluationRequest(BaseModel):
    """Only the server evaluates the already persisted immutable case."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    effective_at: datetime

    @model_validator(mode="after")
    def _effective_at_is_aware(self) -> Self:
        if self.effective_at.tzinfo is None or self.effective_at.utcoffset() is None:
            raise ValueError("effective_at must include a timezone")
        return self


class SourcingRunRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    query: str = Field(min_length=1, max_length=80)

    @field_validator("query")
    @classmethod
    def _query_is_bounded(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not 1 <= len(normalized.split()) <= 5:
            raise ValueError("query must contain 1 to 5 words")
        return normalized


class DocumentSupplierSearchApproval(BaseModel):
    """The operator approves the exact server-derived query and destinations."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approve_exact_payload: Literal[True]
    mode: SearchMode = "AUTO"


class DocumentSupplierSearchRun(BaseModel):
    """Ephemeral source results; no indexed content is saved as case evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan: DocumentSupplierSearchPlan
    eaeu_products: RegistrySearchResult
    direct_catalog: DirectCatalogAttempt | None
    yandex_business: YandexBusinessAttempt | None
    browser_attempts: tuple[BrowserAttempt, ...] = ()
    graviton_catalog: GravitonAttempt | None = None
    depo_catalog: DepoAttempt | None = None


class ReviewedRequirementSetProposalRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    source_document_id: str = Field(min_length=1, max_length=200)
    source_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    declared_scope: str = Field(min_length=1, max_length=4_000)
    expected_entry_count: int = Field(ge=1, le=500)
    entries: tuple[ReviewedRequirementEntry, ...] = Field(min_length=1, max_length=500)


class ReviewedRequirementSetDecisionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    coverage_assessment: RequirementSetCoverageAssessment
    normalization_assessment: RequirementSetNormalizationAssessment
    status: Verdict
    reason: str = Field(min_length=1, max_length=4_000)


class CaseRequirementSetBindingRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    case_id: str = Field(min_length=1, max_length=200)
    case_version: int = Field(ge=1)
    set_id: str = Field(min_length=1, max_length=200)
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RequirementSetMaterializationPreviewRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    source_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_entry_count: int = Field(ge=1, le=500)


class RequirementSetMaterializationRequest(RequirementSetMaterializationPreviewRequest):
    preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    declared_scope: str = Field(min_length=1, max_length=4_000)
    selections: tuple[ExecutableRequirementSelection, ...] = Field(default=(), max_length=500)


class ServerOfferProposalRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    requirement_set_binding_id: str = Field(min_length=1, max_length=200)
    requirement_set_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sourcing_run_id: str = Field(min_length=1, max_length=200)
    lead_id: str = Field(min_length=1, max_length=500)
    source_document_id: str = Field(min_length=1, max_length=200)
    source_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bom_lines: tuple[ServerOfferBomLineInput, ...] = Field(min_length=1, max_length=500)
    commercial_terms: ServerOfferCommercialTermsInput


class ServerOfferReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_decisions: tuple[ServerOfferRequirementDecision, ...] = Field(
        min_length=1, max_length=500
    )
    bom_scope_assessment: ServerOfferBomScopeAssessment
    commercial_terms_assessment: ServerOfferCommercialAssessment
    reason: str = Field(min_length=1, max_length=4_000)


class ServerOfferEconomicsRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    offer_id: str = Field(min_length=1, max_length=200)
    offer_proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    offer_review_decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenarios: tuple[ServerOfferScenarioInput, ...] = Field(min_length=3, max_length=3)


class ServerOfferCaseMaterializationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    offer_id: str = Field(min_length=1, max_length=200)
    economics_id: str = Field(min_length=1, max_length=200)
    package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CaseHardGateAssessmentRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_case_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_binding_id: str = Field(min_length=1, max_length=200)
    manifest_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decisions: tuple[CaseHardGateDecisionInput, ...] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def _all_non_technical_gates_are_present(self) -> Self:
        expected = {
            kind for kind in GateKind if kind not in {GateKind.TECHNICAL, GateKind.DOCUMENT}
        }
        actual = {item.kind for item in self.decisions}
        if len(actual) != 4 or actual != expected:
            raise ValueError("all four caller-reviewed gates are required exactly once")
        return self


class ParticipationDecisionRequest(BaseModel):
    """Approve or reject the exact evaluation evidence displayed to the reviewer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evaluation_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: ParticipationDecisionStatus
    reason: str = Field(min_length=1, max_length=4_000)


class ApplicationPackageRequest(BaseModel):
    """Exact manually declared minimum document manifest pending review."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    participation_decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposed_price_ex_vat: Decimal = Field(gt=0)
    requirements: tuple[ApplicationDocumentRequirement, ...] = Field(min_length=1, max_length=500)
    attachments: tuple[ApplicationAttachmentInput, ...] = Field(min_length=1, max_length=500)

    @field_validator("proposed_price_ex_vat", mode="before")
    @classmethod
    def _exact_wire_money(cls, value: object) -> str:
        if not isinstance(value, str) or not re.fullmatch(
            r"(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,2})?", value
        ):
            raise ValueError("proposed price must be an exact RUB decimal string")
        return value


class ApplicationReviewRequest(BaseModel):
    """Independent assessments of every exact package row and full inventory."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_reviews: tuple[ApplicationRequirementReview, ...] = Field(
        min_length=1, max_length=500
    )
    attachment_reviews: tuple[ApplicationAttachmentReview, ...] = Field(
        min_length=1, max_length=500
    )
    inventory_assessment: ApplicationInventoryAssessment
    inventory_source_document_ids: tuple[str, ...] = Field(min_length=1, max_length=500)
    inventory_reason: str = Field(min_length=1, max_length=4_000)
    price_assessment: ApplicationPriceAssessment
    price_reason: str = Field(min_length=1, max_length=4_000)
    reason: str = Field(min_length=1, max_length=4_000)


class ApplicationSubmissionPrepareRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    destination: str = Field(min_length=1, max_length=2_000)


class ApplicationSubmissionDecisionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_id: str = Field(min_length=1, max_length=200)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: SubmissionApprovalStatus
    reason: str = Field(min_length=1, max_length=4_000)


class ApplicationSubmissionClaimRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_id: str = Field(min_length=1, max_length=200)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CaseHardGateAssessmentEvidenceResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case: ProcurementCase
    source_case_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class OcrRequest(BaseModel):
    """Request one OCR derivative for an already stored immutable document."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    threshold: float = Field(
        default=DEFAULT_OCR_CONFIDENCE_THRESHOLD,
        ge=0.0,
        le=1.0,
        multiple_of=0.01,
    )


class DocumentSearchIndexRequest(BaseModel):
    """Metadata and optional vision evidence for one immutable search version."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=500)
    vision_manifest: VisionSearchTagManifest | None = None

    @model_validator(mode="after")
    def _title_is_not_blank(self) -> Self:
        if self.title is not None and not self.title.strip():
            raise ValueError("title must not be blank")
        return self


class ModelBrandReviewProposalRequest(BaseModel):
    """Catalog draft; tenant, submitter, proposal ID, and time are server-owned."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    catalog_id: str = Field(min_length=1, max_length=200)
    approval_reference: str = Field(min_length=1, max_length=500)
    entries: tuple[ModelBrandCatalogEntry, ...] = Field(min_length=1, max_length=10_000)


class ModelBrandReviewDecisionRequest(BaseModel):
    """One terminal human decision; DRAFT is never accepted as a decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: ModelBrandReviewStatus
    reason: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def _decision_is_terminal(self) -> Self:
        if self.decision is ModelBrandReviewStatus.DRAFT or not self.reason.strip():
            raise ValueError("review decision must be APPROVED or REJECTED with a reason")
        return self


class CompletenessReviewDecisionRequest(BaseModel):
    """Reviewer assertions only; identity, source evidence, time, and reference are server-owned."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: CompletenessStatus
    scope: str = Field(min_length=1, max_length=4_000)
    reason: str = Field(min_length=1, max_length=4_000)
    block_decisions: tuple[CompletenessBlockDecision, ...] = Field(default=(), max_length=100_000)

    @model_validator(mode="after")
    def _text_is_not_blank(self) -> Self:
        if not self.scope.strip() or not self.reason.strip():
            raise ValueError("review scope and reason must not be blank")
        return self


class DocumentSetEvidenceReviewReference(BaseModel):
    """One exact review snapshot selected by the caller; no source text is accepted."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    review_id: str = Field(min_length=1, max_length=200)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("review_id")
    @classmethod
    def _review_id_is_not_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("review_id must not be blank")
        return normalized


class DocumentSetEvidenceManifestRequest(BaseModel):
    """Explicit ordered review references; tenant, actor, and manifest ID are server-owned."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    scope: str = Field(min_length=1, max_length=4_000)
    review_refs: tuple[DocumentSetEvidenceReviewReference, ...] = Field(
        min_length=2,
        max_length=10,
    )

    @field_validator("scope")
    @classmethod
    def _scope_is_not_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("scope must not be blank")
        return normalized

    @model_validator(mode="after")
    def _review_ids_are_unique(self) -> Self:
        review_ids = [item.review_id for item in self.review_refs]
        if len(set(review_ids)) != len(review_ids):
            raise ValueError("review_refs review IDs must be unique")
        return self


class DocumentSetReviewDecisionRequest(BaseModel):
    """Reviewer assertions bound to one path-selected immutable manifest."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    manifest_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    attestations: tuple[DocumentSetMemberAttestation, ...] = Field(min_length=2, max_length=10)
    inventory_assessment: DocumentSetInventoryAssessment
    inventory_rationale: str = Field(min_length=1, max_length=2_000)
    cross_document_assessment: DocumentSetCrossAssessment
    cross_document_rationale: str = Field(min_length=1, max_length=4_000)
    reviewer_findings: tuple[DocumentSetFinding, ...] = Field(default=(), max_length=100)
    status: CompletenessStatus
    reason: str = Field(min_length=1, max_length=4_000)

    @field_validator("inventory_rationale", "cross_document_rationale", "reason")
    @classmethod
    def _text_is_not_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("document-set review text must not be blank")
        return normalized

    @model_validator(mode="after")
    def _reviewer_findings_are_reviewer_owned(self) -> Self:
        if any(
            finding.origin is not DocumentSetFindingOrigin.REVIEWER
            for finding in self.reviewer_findings
        ):
            raise ValueError("reviewer findings must have REVIEWER origin")
        return self


DOCUMENT_SET_EVIDENCE_OPENAPI_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["scope", "review_refs"],
    "properties": {
        "scope": {"type": "string", "minLength": 1, "maxLength": 4_000},
        "review_refs": {
            "type": "array",
            "minItems": 2,
            "maxItems": 10,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["review_id", "evidence_sha256"],
                "properties": {
                    "review_id": {"type": "string", "minLength": 1, "maxLength": 200},
                    "evidence_sha256": {
                        "type": "string",
                        "pattern": "^[0-9a-f]{64}$",
                    },
                },
            },
        },
    },
}


def _document_set_review_openapi_schema() -> dict[str, object]:
    schema = DocumentSetReviewDecisionRequest.model_json_schema(mode="validation")
    definitions = schema.get("$defs")
    if not isinstance(definitions, dict):
        raise RuntimeError("document-set review schema definitions are missing")
    origin = definitions.get("DocumentSetFindingOrigin")
    if not isinstance(origin, dict):
        raise RuntimeError("document-set finding origin schema is missing")
    origin["enum"] = [DocumentSetFindingOrigin.REVIEWER.value]

    def inline(value: object, stack: frozenset[str] = frozenset()) -> object:
        if isinstance(value, list):
            return [inline(item, stack) for item in value]
        if not isinstance(value, dict):
            return value
        reference = value.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            name = reference.removeprefix("#/$defs/")
            target = definitions.get(name)
            if not isinstance(target, dict) or name in stack:
                raise RuntimeError("document-set review schema reference is invalid")
            merged = dict(target)
            merged.update({key: item for key, item in value.items() if key != "$ref"})
            return inline(merged, stack | {name})
        result: dict[str, object] = {}
        for key, item in value.items():
            if key == "$defs":
                continue
            if key == "discriminator" and isinstance(item, dict):
                item = {nested: child for nested, child in item.items() if nested != "mapping"}
            result[key] = inline(item, stack)
        return result

    inlined = inline(schema)
    if not isinstance(inlined, dict):
        raise RuntimeError("document-set review schema must be an object")
    return inlined


DOCUMENT_SET_REVIEW_DECISION_OPENAPI_SCHEMA = _document_set_review_openapi_schema()


class CaseEvidenceBindingRequest(BaseModel):
    """Exact manifest/decision digests; binding identity stays server-owned."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    manifest_id: str = Field(min_length=1, max_length=200)
    manifest_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


CASE_EVIDENCE_BINDING_OPENAPI_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["manifest_id", "manifest_evidence_sha256", "decision_sha256"],
    "properties": {
        "manifest_id": {"type": "string", "minLength": 1, "maxLength": 200},
        "manifest_evidence_sha256": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
        },
        "decision_sha256": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
        },
    },
}


class CaseFromEvidenceRequest(BaseModel):
    """Case draft without assessment plus exact evidence refs; DOCUMENT is server-owned."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case: ProcurementCase
    binding_id: str = Field(min_length=1, max_length=200)
    manifest_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    other_checks: tuple[GateCheck, ...] = Field(default=(), max_length=5)

    @model_validator(mode="after")
    def _assessment_is_server_owned(self) -> Self:
        if self.case.assessment is not None:
            raise ValueError("case assessment is derived server-side from exact evidence")
        if any(check.kind is GateKind.DOCUMENT for check in self.other_checks):
            raise ValueError("DOCUMENT check is derived from exact evidence, not caller input")
        return self


CASE_FROM_EVIDENCE_OPENAPI_SCHEMA: dict[str, object] = CaseFromEvidenceRequest.model_json_schema(
    mode="validation"
)


class AiRequirementReviewDecisionRequest(BaseModel):
    """Exact candidate decisions; reviewer identity and time remain server-owned."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_decisions: tuple[AiRequirementCandidateDecision, ...] = Field(
        default=(), max_length=100_000
    )


class AiRequirementRunImportRequest(BaseModel):
    """One exact local report; authority and run identity remain server-owned."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report: Annotated[
        AiRequirementAnalysisReport | AiRequirementAnalysisReportV2,
        Field(discriminator="schema_version"),
    ]


async def _idempotency_key(
    value: Annotated[str, Header(alias="Idempotency-Key")],
) -> str:
    if _IDEMPOTENCY_KEY.fullmatch(value) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="validation_error",
        )
    return value


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(_: str) -> None:
    raise ValueError("non-finite JSON number")


MAX_EIS_DOCUMENT_REVIEW_REQUEST_BYTES = 4_096


class ReviewDocumentPageRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request: ReviewDocumentRequest
    offset: int = Field(default=0, ge=0, le=999, strict=True)
    character_offset: int = Field(default=0, ge=0, le=99_999, strict=True)
    limit: int = Field(default=25, ge=1, le=25, strict=True)


def _eis_document_review_openapi_schema(model: type[BaseModel]) -> dict[str, object]:
    schema = model.model_json_schema(mode="validation")
    definitions = schema.get("$defs", {})
    if not isinstance(definitions, dict):
        raise RuntimeError("document review schema definitions are invalid")

    def inline(value: object, stack: frozenset[str] = frozenset()) -> object:
        if isinstance(value, list):
            return [inline(item, stack) for item in value]
        if not isinstance(value, dict):
            return value
        reference = value.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            name = reference.removeprefix("#/$defs/")
            target = definitions.get(name)
            if not isinstance(target, dict) or name in stack:
                raise RuntimeError("document review schema reference is invalid")
            merged = dict(target)
            merged.update({key: item for key, item in value.items() if key != "$ref"})
            return inline(merged, stack | {name})
        result: dict[str, object] = {}
        for key, item in value.items():
            if key != "$defs":
                result[key] = inline(item, stack)
        return result

    inlined = inline(schema)
    if not isinstance(inlined, dict):
        raise RuntimeError("document review schema must be an object")
    return inlined


EIS_DOCUMENT_REVIEW_PREPARE_OPENAPI_SCHEMA = _eis_document_review_openapi_schema(
    ReviewDocumentRequest
)
EIS_DOCUMENT_REVIEW_PAGE_OPENAPI_SCHEMA = _eis_document_review_openapi_schema(
    ReviewDocumentPageRequest
)


class SupplierSearchPrepareRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request: SupplierSearchRequest
    refresh: bool = Field(default=False, strict=True)


class SupplierSearchReadRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request: SupplierSearchRequest


EIS_SUPPLIER_SEARCH_PREPARE_OPENAPI_SCHEMA = _eis_document_review_openapi_schema(
    SupplierSearchPrepareRequest
)
EIS_SUPPLIER_SEARCH_READ_OPENAPI_SCHEMA = _eis_document_review_openapi_schema(
    SupplierSearchReadRequest
)


class SupplierSerpPrepareRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    request: SupplierSearchRequest
    refresh: bool = Field(default=False, strict=True)


class SupplierSerpReadRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    request: SupplierSearchRequest


EIS_SUPPLIER_SERP_PREPARE_OPENAPI_SCHEMA = _eis_document_review_openapi_schema(
    SupplierSerpPrepareRequest
)
EIS_SUPPLIER_SERP_READ_OPENAPI_SCHEMA = _eis_document_review_openapi_schema(SupplierSerpReadRequest)


class SupplierPagePrepareRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    request: SupplierPageRequest
    refresh: bool = Field(default=False, strict=True)


class SupplierPageReadRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    request: SupplierPageRequest


EIS_SUPPLIER_PAGE_PREPARE_OPENAPI_SCHEMA = _eis_document_review_openapi_schema(
    SupplierPagePrepareRequest
)
EIS_SUPPLIER_PAGE_READ_OPENAPI_SCHEMA = _eis_document_review_openapi_schema(SupplierPageReadRequest)


class SupplierCatalogPrepareRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    request: SupplierCatalogRequest
    refresh: bool = Field(default=False, strict=True)


class SupplierCatalogReadRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    request: SupplierCatalogRequest


EIS_SUPPLIER_CATALOG_PREPARE_OPENAPI_SCHEMA = _eis_document_review_openapi_schema(
    SupplierCatalogPrepareRequest
)
EIS_SUPPLIER_CATALOG_READ_OPENAPI_SCHEMA = _eis_document_review_openapi_schema(
    SupplierCatalogReadRequest
)


class SupplierProductBody(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    request: SupplierProductRequest


EIS_SUPPLIER_PRODUCT_OPENAPI_SCHEMA = _eis_document_review_openapi_schema(SupplierProductBody)


class RequirementPreviewBody(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    request: RequirementPreviewRequest


EIS_REQUIREMENT_PREVIEW_OPENAPI_SCHEMA = _eis_document_review_openapi_schema(RequirementPreviewBody)


class RequirementProposalRead(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    proposal_id: str


class RequirementComparisonRead(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    proposal_id: str


EIS_REQUIREMENT_PROPOSAL_OPENAPI_SCHEMA = _eis_document_review_openapi_schema(ProposalRequest)
EIS_REQUIREMENT_PROPOSAL_READ_OPENAPI_SCHEMA = _eis_document_review_openapi_schema(
    RequirementProposalRead
)
EIS_REQUIREMENT_DECISION_OPENAPI_SCHEMA = _eis_document_review_openapi_schema(DecisionRequest)
EIS_REQUIREMENT_COMPARISON_OPENAPI_SCHEMA = _eis_document_review_openapi_schema(
    RequirementComparisonRead
)


class PositionAssociationBody(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    request: AssociationRequest


class PositionAssociationListBody(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    request: AssociationListRequest


class PositionAssociationDetailBody(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    request: AssociationDetailRequest


EIS_POSITION_ASSOCIATION_OPENAPI_SCHEMA = _eis_document_review_openapi_schema(
    PositionAssociationBody
)
EIS_POSITION_ASSOCIATION_LIST_OPENAPI_SCHEMA = _eis_document_review_openapi_schema(
    PositionAssociationListBody
)
EIS_POSITION_ASSOCIATION_DETAIL_OPENAPI_SCHEMA = _eis_document_review_openapi_schema(
    PositionAssociationDetailBody
)


_ReviewBody = TypeVar("_ReviewBody", bound=BaseModel)


async def _read_eis_document_review_body(
    request: Request, schema: type[_ReviewBody]
) -> _ReviewBody:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(
            status_code=415,
            detail="unsupported_media_type",
            headers={"Cache-Control": "no-store"},
        )
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail="invalid_review_request",
                headers={"Cache-Control": "no-store"},
            ) from error
        if declared_length < 0:
            raise HTTPException(
                status_code=422,
                detail="invalid_review_request",
                headers={"Cache-Control": "no-store"},
            )
        if declared_length > MAX_EIS_DOCUMENT_REVIEW_REQUEST_BYTES:
            raise HTTPException(
                status_code=413,
                detail="review_request_too_large",
                headers={"Cache-Control": "no-store"},
            )
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_EIS_DOCUMENT_REVIEW_REQUEST_BYTES:
            raise HTTPException(
                status_code=413,
                detail="review_request_too_large",
                headers={"Cache-Control": "no-store"},
            )
        content.extend(chunk)
    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
        return schema.model_validate(payload)
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise HTTPException(
            status_code=422,
            detail="invalid_review_request",
            headers={"Cache-Control": "no-store"},
        ) from error


async def _read_eis_supplier_search_body(
    request: Request, schema: type[_ReviewBody]
) -> _ReviewBody:
    try:
        return await _read_eis_document_review_body(request, schema)
    except HTTPException as error:
        detail = {
            "invalid_review_request": "invalid_supplier_search_request",
            "review_request_too_large": "supplier_search_request_too_large",
        }.get(str(error.detail), error.detail)
        raise HTTPException(
            status_code=error.status_code,
            detail=detail,
            headers={**dict(error.headers or {}), "Cache-Control": "no-store"},
        ) from error


async def _read_eis_supplier_serp_body(request: Request, schema: type[_ReviewBody]) -> _ReviewBody:
    try:
        return await _read_eis_document_review_body(request, schema)
    except HTTPException as error:
        detail = {
            "invalid_review_request": "invalid_supplier_serp_request",
            "review_request_too_large": "supplier_serp_request_too_large",
        }.get(str(error.detail), error.detail)
        raise HTTPException(
            status_code=error.status_code,
            detail=detail,
            headers={**dict(error.headers or {}), "Cache-Control": "no-store"},
        ) from error


async def _read_eis_supplier_page_body(request: Request, schema: type[_ReviewBody]) -> _ReviewBody:
    try:
        return await _read_eis_document_review_body(request, schema)
    except HTTPException as error:
        detail = {
            "invalid_review_request": "invalid_supplier_page_request",
            "review_request_too_large": "supplier_page_request_too_large",
        }.get(str(error.detail), error.detail)
        raise HTTPException(
            status_code=error.status_code,
            detail=detail,
            headers={**dict(error.headers or {}), "Cache-Control": "no-store"},
        ) from error


async def _read_eis_supplier_catalog_body(
    request: Request, schema: type[_ReviewBody]
) -> _ReviewBody:
    try:
        return await _read_eis_document_review_body(request, schema)
    except HTTPException as error:
        detail = {
            "invalid_review_request": "invalid_supplier_catalog_request",
            "review_request_too_large": "supplier_catalog_request_too_large",
        }.get(str(error.detail), error.detail)
        raise HTTPException(
            status_code=error.status_code,
            detail=detail,
            headers={**dict(error.headers or {}), "Cache-Control": "no-store"},
        ) from error


async def _read_eis_supplier_product_body(
    request: Request, schema: type[_ReviewBody]
) -> _ReviewBody:
    try:
        return await _read_eis_document_review_body(request, schema)
    except HTTPException as error:
        detail = {
            "invalid_review_request": "invalid_supplier_product_request",
            "review_request_too_large": "supplier_product_request_too_large",
        }.get(str(error.detail), error.detail)
        raise HTTPException(
            status_code=error.status_code,
            detail=detail,
            headers={**dict(error.headers or {}), "Cache-Control": "no-store"},
        ) from error


_RequirementSetBody = TypeVar("_RequirementSetBody", bound=BaseModel)


async def _read_requirement_set_body(
    request: Request, schema: type[_RequirementSetBody]
) -> _RequirementSetBody:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(status_code=415, detail="unsupported_media_type")
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_REQUIREMENT_SET_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail="requirement_set_request_too_large")
        content.extend(chunk)
    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
        return schema.model_validate_json(json.dumps(payload, ensure_ascii=False))
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise HTTPException(status_code=422, detail="invalid_requirement_set") from error


async def _read_server_offer_body(request: Request) -> ServerOfferProposalRequest:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(status_code=415, detail="unsupported_media_type")
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_SERVER_OFFER_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail="server_offer_request_too_large")
        content.extend(chunk)
    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
        return ServerOfferProposalRequest.model_validate_json(
            json.dumps(payload, ensure_ascii=False)
        )
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise HTTPException(status_code=422, detail="invalid_server_offer") from error


async def _read_server_offer_review_body(
    request: Request,
) -> ServerOfferReviewDecisionRequest:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(status_code=415, detail="unsupported_media_type")
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_SERVER_OFFER_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail="server_offer_review_request_too_large")
        content.extend(chunk)
    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
        return ServerOfferReviewDecisionRequest.model_validate_json(
            json.dumps(payload, ensure_ascii=False)
        )
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise HTTPException(status_code=422, detail="invalid_server_offer_review") from error


async def _read_server_offer_economics_body(request: Request) -> ServerOfferEconomicsRequest:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(status_code=415, detail="unsupported_media_type")
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_SERVER_OFFER_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail="server_offer_economics_request_too_large")
        content.extend(chunk)
    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
        return ServerOfferEconomicsRequest.model_validate_json(
            json.dumps(payload, ensure_ascii=False)
        )
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise HTTPException(status_code=422, detail="invalid_server_offer_economics") from error


async def _read_server_offer_case_materialization_body(
    request: Request,
) -> ServerOfferCaseMaterializationRequest:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(status_code=415, detail="unsupported_media_type")
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_SERVER_OFFER_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail="case_materialization_request_too_large")
        content.extend(chunk)
    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
        return ServerOfferCaseMaterializationRequest.model_validate_json(
            json.dumps(payload, ensure_ascii=False)
        )
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise HTTPException(status_code=422, detail="invalid_case_materialization") from error


async def _read_case_hard_gate_assessment_body(
    request: Request,
) -> CaseHardGateAssessmentRequest:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(status_code=415, detail="unsupported_media_type")
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_SERVER_OFFER_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail="hard_gate_assessment_request_too_large")
        content.extend(chunk)
    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
        return CaseHardGateAssessmentRequest.model_validate_json(
            json.dumps(payload, ensure_ascii=False)
        )
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise HTTPException(status_code=422, detail="invalid_hard_gate_assessment") from error


async def _read_document_set_evidence_request(
    request: Request,
) -> DocumentSetEvidenceManifestRequest:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="unsupported_media_type",
        )
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            parsed_length = int(declared_length)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_document_set_evidence",
            ) from error
        if parsed_length < 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_document_set_evidence",
            )
        if parsed_length > MAX_DOCUMENT_SET_EVIDENCE_REQUEST_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="document_set_evidence_request_too_large",
            )

    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_DOCUMENT_SET_EVIDENCE_REQUEST_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="document_set_evidence_request_too_large",
            )
        content.extend(chunk)
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid_document_set_evidence",
        )
    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
        canonical_payload = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return DocumentSetEvidenceManifestRequest.model_validate_json(canonical_payload)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValidationError,
        ValueError,
        TypeError,
        RecursionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid_document_set_evidence",
        ) from error


async def _read_document_set_review_decision_request(
    request: Request,
) -> DocumentSetReviewDecisionRequest:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="unsupported_media_type",
        )
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            parsed_length = int(declared_length)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_document_set_review_decision",
            ) from error
        if parsed_length < 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_document_set_review_decision",
            )
        if parsed_length > MAX_DOCUMENT_SET_REVIEW_REQUEST_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="document_set_review_request_too_large",
            )

    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_DOCUMENT_SET_REVIEW_REQUEST_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="document_set_review_request_too_large",
            )
        content.extend(chunk)
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid_document_set_review_decision",
        )
    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
        canonical_payload = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return DocumentSetReviewDecisionRequest.model_validate_json(canonical_payload)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValidationError,
        ValueError,
        TypeError,
        RecursionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid_document_set_review_decision",
        ) from error


async def _read_case_evidence_binding_request(
    request: Request,
) -> CaseEvidenceBindingRequest:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="unsupported_media_type",
        )
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            parsed_length = int(declared_length)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_case_evidence",
            ) from error
        if parsed_length < 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_case_evidence",
            )
        if parsed_length > MAX_CASE_EVIDENCE_REQUEST_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="case_evidence_request_too_large",
            )

    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_CASE_EVIDENCE_REQUEST_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="case_evidence_request_too_large",
            )
        content.extend(chunk)
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid_case_evidence",
        )
    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
        canonical_payload = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return CaseEvidenceBindingRequest.model_validate_json(canonical_payload)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValidationError,
        ValueError,
        TypeError,
        RecursionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid_case_evidence",
        ) from error


async def _read_case_from_evidence_request(
    request: Request,
) -> CaseFromEvidenceRequest:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="unsupported_media_type",
        )
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            parsed_length = int(declared_length)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_case_evidence",
            ) from error
        if parsed_length < 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_case_evidence",
            )
        if parsed_length > MAX_CASE_FROM_EVIDENCE_REQUEST_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="case_from_evidence_request_too_large",
            )

    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_CASE_FROM_EVIDENCE_REQUEST_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="case_from_evidence_request_too_large",
            )
        content.extend(chunk)
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid_case_evidence",
        )
    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
        canonical_payload = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return CaseFromEvidenceRequest.model_validate_json(canonical_payload)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValidationError,
        ValueError,
        TypeError,
        RecursionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid_case_evidence",
        ) from error


async def _read_ai_requirement_import(request: Request) -> AiRequirementRunImportRequest:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="unsupported_media_type",
        )
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            parsed_length = int(declared_length)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_ai_requirement_run_import",
            ) from error
        if parsed_length < 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_ai_requirement_run_import",
            )
        if parsed_length > MAX_AI_REQUIREMENT_IMPORT_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="ai_requirement_report_too_large",
            )

    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_AI_REQUIREMENT_IMPORT_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="ai_requirement_report_too_large",
            )
        content.extend(chunk)
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid_ai_requirement_run_import",
        )
    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
        validated = AiRequirementRunImportRequest.model_validate(payload)
        if canonical_json_sha256(payload) != canonical_json_sha256(
            validated.model_dump(mode="json")
        ):
            raise ValueError("AI requirement import must not be normalized silently")
        return validated
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValidationError,
        ValueError,
        TypeError,
        RecursionError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid_ai_requirement_run_import",
        ) from error


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")


def _request_digest(*parts: str) -> str:
    """Stable digest used only to bind an Idempotency-Key to one request."""
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _ai_requirement_summary(record: AiRequirementReviewRecord) -> AiRequirementReviewSummary:
    """Project only queue metadata; never serialize extraction or provider transcript fields."""
    snapshot = record.snapshot
    report_schema_version: str
    model: str
    execution_status: AiRequirementRunStatus
    if isinstance(snapshot, AiRequirementTransferBatchRunSnapshot):
        batch_result = snapshot.result
        report_schema_version = batch_result.schema_version
        model = batch_result.chunk_results[0].provider_model
        execution_status = batch_result.execution_status
        candidates = batch_result.candidates
        item_candidates = batch_result.item_candidates
        submitted_by = snapshot.prepared_by
        submitted_at = snapshot.aggregated_at
    elif isinstance(snapshot, AiRequirementTransferRunSnapshot):
        chunk_result = snapshot.result
        report_schema_version = chunk_result.schema_version
        model = chunk_result.provider_model
        execution_status = chunk_result.execution_status
        candidates = chunk_result.candidates
        item_candidates = chunk_result.item_candidates
        submitted_by = snapshot.prepared_by
        submitted_at = snapshot.materialized_at
    else:
        report = snapshot.report
        report_schema_version = report.schema_version
        model = report.model
        execution_status = report.execution_status
        candidates = report.candidates
        item_candidates = getattr(report, "item_candidates", ())
        submitted_by = snapshot.submitted_by
        submitted_at = snapshot.submitted_at
    decision = record.decision
    return AiRequirementReviewSummary(
        run_id=snapshot.run_id,
        source_document_id=snapshot.source_document_id,
        source_sha256=snapshot.source_sha256,
        report_schema_version=report_schema_version,
        model=model,
        execution_status=execution_status,
        completeness_status=snapshot.completeness_status,
        requirement_candidates_total=len(candidates),
        procurement_item_candidates_total=len(item_candidates),
        submitted_by=submitted_by,
        submitted_at=submitted_at,
        evidence_sha256=snapshot.evidence_sha256,
        reviewed=decision is not None,
        reviewed_by=None if decision is None else decision.reviewed_by,
        reviewed_at=None if decision is None else decision.reviewed_at,
    )


def _ai_requirement_detail(record: AiRequirementReviewRecord) -> AiRequirementReviewDetail:
    """Return reviewer evidence only; chunks, extraction, and report transport stay hidden."""
    summary = _ai_requirement_summary(record)
    snapshot = record.snapshot
    if isinstance(
        snapshot,
        (AiRequirementTransferRunSnapshot, AiRequirementTransferBatchRunSnapshot),
    ):
        candidates = snapshot.result.candidates
        item_candidates = snapshot.result.item_candidates
    else:
        report = snapshot.report
        candidates = report.candidates
        item_candidates = getattr(report, "item_candidates", ())
    return AiRequirementReviewDetail(
        **summary.model_dump(),
        requirement_candidates=candidates,
        procurement_item_candidates=item_candidates,
        candidate_decisions=None
        if record.decision is None
        else record.decision.candidate_decisions,
    )


def _invalid_credentials() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid_credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _bundle_member_ocr_candidates(
    candidates: tuple[OcrCandidate, ...],
    archive_path: str,
) -> tuple[OcrCandidate, ...]:
    """Keep archive provenance when OCR candidates become extracted blocks."""
    return tuple(
        candidate.model_copy(
            update={
                "locator": f'archive member "{archive_path}" :: {candidate.locator}',
            }
        )
        for candidate in candidates
    )


def _docx_media_ocr_candidates(
    candidates: tuple[OcrCandidate, ...],
    archive_path: str,
) -> tuple[OcrCandidate, ...]:
    """Keep exact OOXML media provenance when candidates become blocks."""
    if any(candidate.page_number != 1 for candidate in candidates):
        raise OcrEngineError("DOCX media OCR candidate is outside the immutable image")
    return tuple(
        candidate.model_copy(
            update={
                "locator": f'DOCX media "{archive_path}" :: {candidate.locator}',
            }
        )
        for candidate in candidates
    )


async def _read_upload(upload: UploadFile) -> bytes:
    content = bytearray()
    while chunk := await upload.read(min(1024 * 1024, MAX_UPLOAD_BYTES + 1 - len(content))):
        content.extend(chunk)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="document_too_large",
            )
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": DocumentRejectionCode.PARSE_FAILED.value},
        )
    return bytes(content)


def create_app(
    service: CaseService,
    authenticator: Authenticator,
    *,
    ocr_runner: OcrRunner | None = None,
    eis_index_storage: PostgresStorage | None = None,
    eis_number_token: str | None = None,
    profile_storage: PostgresStorage | None = None,
) -> FastAPI:
    """Create an app without database globals or caller-selected tenant identity."""

    app = FastAPI(title="Syurai Procurement API", version="0.1.0", debug=False)
    configured_ocr_runner = ocr_runner or NoopOcrRunner()

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(_: Request, __: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": "validation_error"},
        )

    @app.exception_handler(Exception)
    async def internal_error(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "internal_error"},
        )

    async def current_principal(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    ) -> Principal:
        if (
            credentials is None
            or credentials.scheme.lower() != "bearer"
            or not credentials.credentials
        ):
            raise _invalid_credentials()
        try:
            principal = await authenticator.authenticate(credentials.credentials)
        except Exception:
            principal = None
        if principal is None:
            raise _invalid_credentials()
        return principal

    from procurement.api.public_unit_price import public_unit_price_router

    app.include_router(public_unit_price_router(eis_index_storage, current_principal))
    from procurement.api.tender_navigation import tender_navigation_router

    app.include_router(tender_navigation_router(eis_index_storage, current_principal))

    async def document_review_principal(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    ) -> Principal:
        try:
            return await current_principal(credentials)
        except HTTPException as error:
            headers = dict(error.headers or {})
            headers["Cache-Control"] = "no-store"
            raise HTTPException(
                status_code=error.status_code,
                detail=error.detail,
                headers=headers,
            ) from error

    from procurement.api.beta_procurement import beta_procurement_router

    app.include_router(beta_procurement_router(profile_storage, document_review_principal))
    app.include_router(company_profile_router(profile_storage, document_review_principal))
    app.include_router(comparison_router(profile_storage, document_review_principal))

    async def discovery_reader(
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Principal:
        response.headers["Cache-Control"] = "no-store"
        return principal

    async def discovery_operator(
        principal: Annotated[Principal, Depends(discovery_reader)],
    ) -> Principal:
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=403, detail="operator_role_required")
        return principal

    app.include_router(
        manufacturer_search_router(eis_index_storage, discovery_reader, discovery_operator)
    )
    app.include_router(
        manufacturer_review_router(eis_index_storage, discovery_reader, discovery_operator)
    )
    app.include_router(manufacturer_directory_router(eis_index_storage, discovery_reader))
    app.include_router(
        manufacturer_rfq_router(eis_index_storage, discovery_reader, discovery_operator)
    )

    @app.post("/v1/tender-discovery/runs")
    async def create_discovery_run(
        payload: eis_workflow.DiscoveryRequest,
        principal: Annotated[Principal, Depends(discovery_operator)],
    ) -> dict[str, object]:
        run = await to_thread.run_sync(
            eis_workflow.create_run,
            principal.company_id,
            principal.actor_id,
            payload,
        )
        return eis_workflow.public_run(run)

    @app.get("/v1/tender-discovery/runs")
    async def list_discovery_runs(
        principal: Annotated[Principal, Depends(discovery_reader)],
    ) -> list[dict[str, str]]:
        return await to_thread.run_sync(eis_workflow.list_runs, principal.company_id)

    @app.get("/v1/tender-discovery/runs/{run_id}")
    async def get_discovery_run(
        run_id: str,
        principal: Annotated[Principal, Depends(discovery_reader)],
    ) -> dict[str, object]:
        try:
            run = await to_thread.run_sync(eis_workflow.get_run, principal.company_id, run_id)
            return eis_workflow.public_run(run)
        except eis_workflow.RunNotFound as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/v1/tender-discovery/runs/{run_id}/advance")
    async def advance_discovery_run(
        run_id: str,
        principal: Annotated[Principal, Depends(discovery_operator)],
    ) -> dict[str, object]:
        try:
            run = await to_thread.run_sync(
                eis_workflow.advance_run,
                principal.company_id,
                principal.actor_id,
                run_id,
            )
            return eis_workflow.public_run(run)
        except eis_workflow.RunNotFound as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/v1/tender-discovery/runs/{run_id}/cancel")
    async def cancel_discovery_run(
        run_id: str,
        principal: Annotated[Principal, Depends(discovery_operator)],
    ) -> dict[str, object]:
        try:
            run = await to_thread.run_sync(
                eis_workflow.cancel_run,
                principal.company_id,
                principal.actor_id,
                run_id,
            )
            return eis_workflow.public_run(run)
        except eis_workflow.RunNotFound as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/v1/tender-discovery/runs/{run_id}/analyze/{purchase_number}")
    async def analyze_discovery_candidate(
        run_id: str,
        purchase_number: str,
        principal: Annotated[Principal, Depends(discovery_operator)],
    ) -> dict[str, object]:
        try:
            run = await to_thread.run_sync(
                eis_workflow.analyze_candidate,
                principal.company_id,
                principal.actor_id,
                run_id,
                purchase_number,
            )
            return eis_workflow.public_run(run)
        except eis_workflow.RunNotFound as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except eis_workflow.RunBusy as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/tender-discovery/runs/{run_id}/customer-history/{purchase_number}")
    async def request_discovery_customer_history(
        run_id: str,
        purchase_number: str,
        principal: Annotated[Principal, Depends(discovery_operator)],
    ) -> dict[str, object]:
        try:
            run = await to_thread.run_sync(
                eis_workflow.request_customer_history,
                principal.company_id,
                principal.actor_id,
                run_id,
                purchase_number,
            )
            return eis_workflow.public_run(run)
        except eis_workflow.RunNotFound as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except eis_workflow.RunBusy as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/tender-discovery/runs/{run_id}/costs/{purchase_number}")
    async def save_discovery_costs(
        run_id: str,
        purchase_number: str,
        payload: DiscoveryCostInput,
        principal: Annotated[Principal, Depends(discovery_operator)],
    ) -> dict[str, object]:
        try:
            run = await to_thread.run_sync(
                eis_workflow.set_costs,
                principal.company_id,
                principal.actor_id,
                run_id,
                purchase_number,
                payload,
            )
            return eis_workflow.public_run(run)
        except eis_workflow.RunNotFound as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/v1/tender-discovery/runs/{run_id}/artifacts/{digest}")
    async def get_discovery_artifact(
        run_id: str,
        digest: str,
        principal: Annotated[Principal, Depends(discovery_reader)],
    ) -> Response:
        try:
            filename, content = await to_thread.run_sync(
                eis_workflow.read_artifact,
                principal.company_id,
                run_id,
                digest,
            )
            return Response(
                content,
                media_type="application/octet-stream",
                headers={
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                    "Content-Disposition": "attachment; filename*=UTF-8''"
                    + quote(filename, safe=""),
                },
            )
        except eis_workflow.RunNotFound as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/v1/tender-discovery/eis-export", response_model=EisDiscoveryResult)
    async def discover_eis_export(
        query: Annotated[str, Form(min_length=1, max_length=120)],
        file: Annotated[UploadFile, File()],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> EisDiscoveryResult:
        """Read an operator-supplied official export; no live coverage is implied."""
        del principal
        response.headers["Cache-Control"] = "no-store"
        content = await file.read(20 * 1024 * 1024 + 1)
        if len(content) > 20 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="eis_export_too_large")
        if not file.filename or not file.filename.lower().endswith((".xml", ".zip")):
            raise HTTPException(status_code=422, detail="eis_export_filename_invalid")
        try:
            return await to_thread.run_sync(discover_from_export, content, query)
        except EisExportError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/v1/tender-discovery/eis-index", response_model=EisIndexedSearchResult)
    async def discover_eis_index(
        query: Annotated[str, Query(min_length=1, max_length=120)],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
        search_scope: Annotated[EisIndexSearchScope, Query()] = "NOT_EXPIRED_OR_UNKNOWN",
        page_size: Annotated[int | None, Query(ge=1, le=100)] = None,
        cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
    ) -> EisIndexedSearchResult:
        """Search only tenant-scoped, already indexed official source windows."""
        response.headers["Cache-Control"] = "no-store"
        if eis_index_storage is None:
            raise HTTPException(status_code=503, detail="eis_index_unavailable")
        try:
            page_options = (
                {"paginate": True, "limit": page_size or 100, "cursor": cursor}
                if page_size is not None or cursor is not None
                else {}
            )
            return await to_thread.run_sync(
                partial(
                    search_eis_index,
                    eis_index_storage,
                    principal.company_id,
                    query,
                    now=datetime.now(UTC),
                    search_scope=search_scope,
                    **page_options,
                )
            )
        except ValueError as error:
            if str(error) in {"SEARCH_PAGE_CHANGED", "SEARCH_PAGE_EXPIRED"}:
                raise HTTPException(
                    status_code=409 if str(error) == "SEARCH_PAGE_CHANGED" else 410,
                    detail=str(error),
                ) from error
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/v1/tender-discovery/eis-analog-candidates", response_model=AnalogReport)
    async def historical_analog_candidates(
        payload: AnalogRequest,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> AnalogReport:
        response.headers["Cache-Control"] = "no-store"
        if eis_index_storage is None:
            raise HTTPException(status_code=503, detail="eis_index_unavailable")
        try:
            return await to_thread.run_sync(
                partial(
                    read_analog_candidates,
                    eis_index_storage,
                    principal.company_id,
                    payload,
                    now=datetime.now(UTC),
                )
            )
        except (ValueError, LookupError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        except SQLAlchemyError as error:
            raise HTTPException(status_code=503, detail="analog_read_unavailable") from error

    @app.post(
        "/v1/tender-discovery/eis-characteristic-pair", response_model=CharacteristicPairReport
    )
    async def saved_characteristic_pair(
        payload: CharacteristicPairRequest,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> CharacteristicPairReport:
        response.headers["Cache-Control"] = "no-store"
        if eis_index_storage is None:
            raise HTTPException(status_code=503, detail="eis_index_unavailable")
        try:
            return await to_thread.run_sync(
                partial(
                    read_characteristic_pair,
                    eis_index_storage,
                    principal.company_id,
                    payload,
                    now=datetime.now(UTC),
                )
            )
        except (ValueError, LookupError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except SQLAlchemyError as error:
            raise HTTPException(
                status_code=503, detail="characteristic_read_unavailable"
            ) from error

    @app.post(
        "/v1/tender-discovery/eis-document-review/prepare",
        response_model=SavedReviewDocumentPage,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {"schema": EIS_DOCUMENT_REVIEW_PREPARE_OPENAPI_SCHEMA}
                },
            }
        },
    )
    async def prepare_saved_eis_document_review(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(document_review_principal)],
    ) -> SavedReviewDocumentPage:
        response.headers["Cache-Control"] = "no-store"
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(
                status_code=403,
                detail="operator_role_required",
                headers={"Cache-Control": "no-store"},
            )
        if eis_index_storage is None:
            raise HTTPException(
                status_code=503,
                detail="document_review_unavailable",
                headers={"Cache-Control": "no-store"},
            )
        payload = await _read_eis_document_review_body(request, ReviewDocumentRequest)
        try:
            return await to_thread.run_sync(
                partial(
                    run_prepare_review_subprocess,
                    eis_index_storage,
                    principal.company_id,
                    payload,
                    actor_id=principal.actor_id,
                )
            )
        except ReviewRunnerFailure as error:
            code = error.code
            if error.kind == "unavailable":
                raise HTTPException(
                    status_code=503,
                    detail=code,
                    headers={"Cache-Control": "no-store"},
                ) from error
            if error.kind == "lookup":
                raise HTTPException(
                    status_code=404,
                    detail=code,
                    headers={"Cache-Control": "no-store"},
                ) from error
            conflicts = {
                "NOTICE_DIGEST_CONFLICT",
                "NOTICE_VERSION_STALE",
                "DOCUMENT_RECEIPT_DIGEST_CONFLICT",
                "REVIEW_ANALYSIS_EVIDENCE_CONFLICT",
            }
            raise HTTPException(
                status_code=409 if code in conflicts else 422,
                detail=code,
                headers={"Cache-Control": "no-store"},
            ) from error
        except LookupError as error:
            code = str(error)
            detail = (
                code
                if code
                in {
                    "NOTICE_NOT_FOUND",
                    "DOCUMENT_ATTACHMENT_NOT_FOUND",
                    "DOCUMENT_RECEIPT_NOT_FOUND",
                }
                else "document_review_not_found"
            )
            raise HTTPException(
                status_code=404,
                detail=detail,
                headers={"Cache-Control": "no-store"},
            ) from error
        except ValueError as error:
            code = str(error)
            conflicts = {
                "NOTICE_DIGEST_CONFLICT",
                "NOTICE_VERSION_STALE",
                "DOCUMENT_RECEIPT_DIGEST_CONFLICT",
                "REVIEW_ANALYSIS_EVIDENCE_CONFLICT",
            }
            allowed = conflicts | {
                "NOTICE_VARIANT_REVIEW_REQUIRED",
                "ATTACHMENT_FILENAME_REQUIRES_REVIEW",
                "ATTACHMENT_REFERENCE_REQUIRES_REVIEW",
                "REVIEW_DOCUMENT_FORMAT_UNSUPPORTED",
                "REVIEW_DOCUMENT_BYTES_LIMIT",
                "DOCUMENT_BYTES_NOT_VERIFIABLE",
                "REVIEW_ATTACHMENT_MANIFEST_LIMIT",
                "REVIEW_ANALYSIS_PAYLOAD_LIMIT",
            }
            raise HTTPException(
                status_code=409 if code in conflicts else 422,
                detail=code if code in allowed else "invalid_review_request",
                headers={"Cache-Control": "no-store"},
            ) from error
        except (SQLAlchemyError, RuntimeError) as error:
            raise HTTPException(
                status_code=503,
                detail="document_review_unavailable",
                headers={"Cache-Control": "no-store"},
            ) from error

    @app.post(
        "/v1/tender-discovery/eis-document-review/page",
        response_model=SavedReviewDocumentPage,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {"schema": EIS_DOCUMENT_REVIEW_PAGE_OPENAPI_SCHEMA}
                },
            }
        },
    )
    async def read_saved_eis_document_review_page(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(document_review_principal)],
    ) -> SavedReviewDocumentPage:
        response.headers["Cache-Control"] = "no-store"
        if eis_index_storage is None:
            raise HTTPException(
                status_code=503,
                detail="document_review_unavailable",
                headers={"Cache-Control": "no-store"},
            )
        payload = await _read_eis_document_review_body(request, ReviewDocumentPageRequest)
        try:
            return await to_thread.run_sync(
                partial(
                    read_review_document_page,
                    eis_index_storage,
                    principal.company_id,
                    payload.request,
                    offset=payload.offset,
                    character_offset=payload.character_offset,
                    limit=payload.limit,
                )
            )
        except LookupError as error:
            code = str(error)
            detail = (
                code
                if code
                in {
                    "NOTICE_NOT_FOUND",
                    "DOCUMENT_ATTACHMENT_NOT_FOUND",
                    "DOCUMENT_RECEIPT_NOT_FOUND",
                    "REVIEW_ANALYSIS_NOT_PREPARED",
                }
                else "document_review_not_found"
            )
            raise HTTPException(
                status_code=404,
                detail=detail,
                headers={"Cache-Control": "no-store"},
            ) from error
        except ValueError as error:
            code = str(error)
            conflicts = {
                "NOTICE_DIGEST_CONFLICT",
                "NOTICE_VERSION_STALE",
                "DOCUMENT_RECEIPT_DIGEST_CONFLICT",
                "REVIEW_ANALYSIS_EVIDENCE_CONFLICT",
            }
            allowed = conflicts | {
                "NOTICE_VARIANT_REVIEW_REQUIRED",
                "ATTACHMENT_FILENAME_REQUIRES_REVIEW",
                "ATTACHMENT_REFERENCE_REQUIRES_REVIEW",
                "REVIEW_DOCUMENT_FORMAT_UNSUPPORTED",
                "REVIEW_DOCUMENT_BYTES_LIMIT",
                "REVIEW_ATTACHMENT_MANIFEST_LIMIT",
                "REVIEW_ANALYSIS_PAYLOAD_LIMIT",
                "REVIEW_PAGE_INVALID",
                "REVIEW_PAGE_RESPONSE_LIMIT",
            }
            raise HTTPException(
                status_code=409 if code in conflicts else 422,
                detail=code if code in allowed else "invalid_review_request",
                headers={"Cache-Control": "no-store"},
            ) from error
        except (SQLAlchemyError, RuntimeError) as error:
            raise HTTPException(
                status_code=503,
                detail="document_review_unavailable",
                headers={"Cache-Control": "no-store"},
            ) from error

    @app.post(
        "/v1/tender-discovery/eis-supplier-search/prepare",
        response_model=SavedSupplierSearch,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {"schema": EIS_SUPPLIER_SEARCH_PREPARE_OPENAPI_SCHEMA}
                },
            }
        },
    )
    async def prepare_saved_eis_supplier_search(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(document_review_principal)],
    ) -> SavedSupplierSearch:
        response.headers["Cache-Control"] = "no-store"
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(
                status_code=403,
                detail="operator_role_required",
                headers={"Cache-Control": "no-store"},
            )
        if eis_index_storage is None:
            raise HTTPException(
                status_code=503,
                detail="supplier_search_unavailable",
                headers={"Cache-Control": "no-store"},
            )
        payload = await _read_eis_supplier_search_body(request, SupplierSearchPrepareRequest)
        try:
            return await to_thread.run_sync(
                partial(
                    run_prepare_supplier_subprocess,
                    eis_index_storage,
                    principal.company_id,
                    payload.request,
                    actor_id=principal.actor_id,
                    refresh=payload.refresh,
                )
            )
        except SupplierRunnerFailure as error:
            status_code = (
                503 if error.kind == "unavailable" else 404 if error.kind == "lookup" else 422
            )
            if error.code in {
                "NOTICE_VERSION_STALE",
                "NOTICE_VARIANT_REVIEW_REQUIRED",
                "SUPPLIER_SEARCH_BUSY",
                "SUPPLIER_SEARCH_POSITION_CHANGED",
                "SUPPLIER_SEARCH_REFRESH_COOLDOWN",
            }:
                status_code = 409
            raise HTTPException(
                status_code=status_code,
                detail=error.code,
                headers={"Cache-Control": "no-store"},
            ) from error

    @app.post(
        "/v1/tender-discovery/eis-supplier-search/read",
        response_model=SavedSupplierSearch,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {"schema": EIS_SUPPLIER_SEARCH_READ_OPENAPI_SCHEMA}
                },
            }
        },
    )
    async def read_saved_eis_supplier_search(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(document_review_principal)],
    ) -> SavedSupplierSearch:
        response.headers["Cache-Control"] = "no-store"
        if eis_index_storage is None:
            raise HTTPException(
                status_code=503,
                detail="supplier_search_unavailable",
                headers={"Cache-Control": "no-store"},
            )
        payload = await _read_eis_supplier_search_body(request, SupplierSearchReadRequest)
        try:
            return await to_thread.run_sync(
                partial(
                    read_supplier_search,
                    eis_index_storage,
                    principal.company_id,
                    payload.request,
                )
            )
        except LookupError as error:
            code = str(error)
            raise HTTPException(
                status_code=404,
                detail=code if code == "SUPPLIER_SEARCH_NOT_FOUND" else "supplier_search_not_found",
                headers={"Cache-Control": "no-store"},
            ) from error
        except ValueError as error:
            code = str(error)
            allowed = {
                "NOTICE_VERSION_STALE",
                "NOTICE_VARIANT_REVIEW_REQUIRED",
                "SUPPLIER_SEARCH_TIME_LIMIT",
                "SUPPLIER_SEARCH_REPORT_LIMIT",
                "SUPPLIER_SEARCH_BLOB_LIMIT",
                "SUPPLIER_SEARCH_DIGEST_CONFLICT",
                "SUPPLIER_SEARCH_EVIDENCE_CONFLICT",
                "CHARACTERISTIC_POSITION_NOT_FOUND",
                "CHARACTERISTIC_POSITION_INVALID",
            }
            raise HTTPException(
                status_code=409 if code == "NOTICE_VERSION_STALE" else 422,
                detail=code if code in allowed else "invalid_supplier_search_request",
                headers={"Cache-Control": "no-store"},
            ) from error
        except (SQLAlchemyError, RuntimeError) as error:
            raise HTTPException(
                status_code=503,
                detail="supplier_search_unavailable",
                headers={"Cache-Control": "no-store"},
            ) from error

    @app.post(
        "/v1/tender-discovery/eis-supplier-serp/prepare",
        response_model=SavedSupplierSerp,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {"schema": EIS_SUPPLIER_SERP_PREPARE_OPENAPI_SCHEMA}
                },
            }
        },
    )
    async def prepare_saved_eis_supplier_serp(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(document_review_principal)],
    ) -> SavedSupplierSerp:
        response.headers["Cache-Control"] = "no-store"
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(
                403, "operator_role_required", headers={"Cache-Control": "no-store"}
            )
        if eis_index_storage is None:
            raise HTTPException(
                503, "supplier_serp_unavailable", headers={"Cache-Control": "no-store"}
            )
        payload = await _read_eis_supplier_serp_body(request, SupplierSerpPrepareRequest)
        try:
            result = await to_thread.run_sync(
                partial(
                    run_prepare_supplier_serp_subprocess,
                    eis_index_storage,
                    principal.company_id,
                    payload.request,
                    actor_id=principal.actor_id,
                    refresh=payload.refresh,
                )
            )
            if result.report.request != payload.request or (
                result.created and result.report.status == "STARTED"
            ):
                raise RuntimeError("supplier serp result binding failed")
            return result
        except SupplierSerpRunnerFailure as error:
            status_code = (
                503 if error.kind == "unavailable" else 404 if error.kind == "lookup" else 422
            )
            if error.code in {
                "NOTICE_VERSION_STALE",
                "NOTICE_VARIANT_REVIEW_REQUIRED",
                "SUPPLIER_SERP_BUSY",
                "SUPPLIER_SERP_TENANT_BUSY",
                "SUPPLIER_SERP_REFRESH_COOLDOWN",
                "SUPPLIER_SERP_POSITION_CHANGED",
                "SUPPLIER_SERP_HOURLY_LIMIT",
                "SUPPLIER_SERP_DAILY_BUNDLE_LIMIT",
            }:
                status_code = 409
            raise HTTPException(
                status_code, error.code, headers={"Cache-Control": "no-store"}
            ) from error
        except RuntimeError as error:
            raise HTTPException(
                503, "supplier_serp_unavailable", headers={"Cache-Control": "no-store"}
            ) from error

    @app.post(
        "/v1/tender-discovery/eis-supplier-serp/read",
        response_model=SavedSupplierSerp,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": EIS_SUPPLIER_SERP_READ_OPENAPI_SCHEMA}},
            }
        },
    )
    async def read_saved_eis_supplier_serp(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(document_review_principal)],
    ) -> SavedSupplierSerp:
        response.headers["Cache-Control"] = "no-store"
        if eis_index_storage is None:
            raise HTTPException(
                503, "supplier_serp_unavailable", headers={"Cache-Control": "no-store"}
            )
        payload = await _read_eis_supplier_serp_body(request, SupplierSerpReadRequest)
        try:
            result = await to_thread.run_sync(
                partial(
                    read_supplier_serp, eis_index_storage, principal.company_id, payload.request
                )
            )
            if result.report.request != payload.request or result.created:
                raise RuntimeError("supplier serp result binding failed")
            return result
        except LookupError as error:
            raise HTTPException(
                404, "supplier_serp_not_found", headers={"Cache-Control": "no-store"}
            ) from error
        except ValueError as error:
            code = str(error)
            conflicts = {"NOTICE_VERSION_STALE", "NOTICE_VARIANT_REVIEW_REQUIRED"}
            allowed = conflicts | {
                "SUPPLIER_SERP_REPORT_LIMIT",
                "SUPPLIER_SERP_DIGEST_CONFLICT",
                "SUPPLIER_SERP_EVIDENCE_CONFLICT",
                "CHARACTERISTIC_POSITION_NOT_FOUND",
                "CHARACTERISTIC_POSITION_INVALID",
            }
            raise HTTPException(
                409 if code in conflicts else 422,
                code if code in allowed else "invalid_supplier_serp_request",
                headers={"Cache-Control": "no-store"},
            ) from error
        except (SQLAlchemyError, RuntimeError) as error:
            raise HTTPException(
                503, "supplier_serp_unavailable", headers={"Cache-Control": "no-store"}
            ) from error

    @app.post(
        "/v1/tender-discovery/eis-supplier-page/prepare",
        response_model=SavedSupplierPage,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {"schema": EIS_SUPPLIER_PAGE_PREPARE_OPENAPI_SCHEMA}
                },
            }
        },
    )
    async def prepare_saved_eis_supplier_page(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(document_review_principal)],
    ) -> SavedSupplierPage:
        response.headers["Cache-Control"] = "no-store"
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(
                403, "operator_role_required", headers={"Cache-Control": "no-store"}
            )
        if eis_index_storage is None:
            raise HTTPException(
                503, "supplier_page_unavailable", headers={"Cache-Control": "no-store"}
            )
        payload = await _read_eis_supplier_page_body(request, SupplierPagePrepareRequest)
        try:
            result = await to_thread.run_sync(
                partial(
                    run_prepare_supplier_page_subprocess,
                    eis_index_storage,
                    principal.company_id,
                    payload.request,
                    actor_id=principal.actor_id,
                    refresh=payload.refresh,
                )
            )
            if result.report.request != payload.request or (
                result.created and result.report.status == "STARTED"
            ):
                raise RuntimeError
            return result
        except SupplierPageRunnerFailure as error:
            code = 503 if error.kind == "unavailable" else 404 if error.kind == "lookup" else 422
            if error.code in {
                "NOTICE_VERSION_STALE",
                "NOTICE_VARIANT_REVIEW_REQUIRED",
                "SUPPLIER_PAGE_BUSY",
                "SUPPLIER_PAGE_TENANT_BUSY",
                "SUPPLIER_PAGE_REFRESH_COOLDOWN",
                "SUPPLIER_PAGE_SOURCE_CHANGED",
                "SUPPLIER_PAGE_HOURLY_LIMIT",
                "SUPPLIER_PAGE_DAILY_BODY_LIMIT",
            }:
                code = 409
            raise HTTPException(code, error.code, headers={"Cache-Control": "no-store"}) from error
        except RuntimeError as error:
            raise HTTPException(
                503, "supplier_page_unavailable", headers={"Cache-Control": "no-store"}
            ) from error

    @app.post(
        "/v1/tender-discovery/eis-supplier-page/read",
        response_model=SavedSupplierPage,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": EIS_SUPPLIER_PAGE_READ_OPENAPI_SCHEMA}},
            }
        },
    )
    async def read_saved_eis_supplier_page(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(document_review_principal)],
    ) -> SavedSupplierPage:
        response.headers["Cache-Control"] = "no-store"
        if eis_index_storage is None:
            raise HTTPException(
                503, "supplier_page_unavailable", headers={"Cache-Control": "no-store"}
            )
        payload = await _read_eis_supplier_page_body(request, SupplierPageReadRequest)
        try:
            result = await to_thread.run_sync(
                partial(
                    read_supplier_page, eis_index_storage, principal.company_id, payload.request
                )
            )
            if result.report.request != payload.request or result.created:
                raise RuntimeError
            return result
        except LookupError as error:
            raise HTTPException(
                404, "supplier_page_not_found", headers={"Cache-Control": "no-store"}
            ) from error
        except ValueError as error:
            code = str(error)
            conflicts = {
                "NOTICE_VERSION_STALE",
                "NOTICE_VARIANT_REVIEW_REQUIRED",
                "SUPPLIER_PAGE_SOURCE_CHANGED",
            }
            allowed = conflicts | {
                "SUPPLIER_PAGE_PARENT_LIMIT",
                "SUPPLIER_PAGE_PARENT_DIGEST_CONFLICT",
                "SUPPLIER_PAGE_PARENT_EVIDENCE_CONFLICT",
                "SUPPLIER_PAGE_REPORT_LIMIT",
                "SUPPLIER_PAGE_DIGEST_CONFLICT",
                "SUPPLIER_PAGE_EVIDENCE_CONFLICT",
                "CHARACTERISTIC_POSITION_NOT_FOUND",
                "CHARACTERISTIC_POSITION_INVALID",
            }
            raise HTTPException(
                409 if code in conflicts else 422,
                code if code in allowed else "invalid_supplier_page_request",
                headers={"Cache-Control": "no-store"},
            ) from error
        except (SQLAlchemyError, RuntimeError) as error:
            raise HTTPException(
                503, "supplier_page_unavailable", headers={"Cache-Control": "no-store"}
            ) from error

    @app.post(
        "/v1/tender-discovery/eis-supplier-catalog/prepare",
        response_model=SavedSupplierCatalog,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {"schema": EIS_SUPPLIER_CATALOG_PREPARE_OPENAPI_SCHEMA}
                },
            }
        },
    )
    async def prepare_saved_eis_supplier_catalog(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(document_review_principal)],
    ) -> SavedSupplierCatalog:
        response.headers["Cache-Control"] = "no-store"
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(
                403, "operator_role_required", headers={"Cache-Control": "no-store"}
            )
        if eis_index_storage is None:
            raise HTTPException(
                503, "supplier_catalog_unavailable", headers={"Cache-Control": "no-store"}
            )
        payload = await _read_eis_supplier_catalog_body(request, SupplierCatalogPrepareRequest)
        try:
            result = await to_thread.run_sync(
                partial(
                    run_prepare_supplier_catalog_subprocess,
                    eis_index_storage,
                    principal.company_id,
                    payload.request,
                    actor_id=principal.actor_id,
                    refresh=payload.refresh,
                )
            )
            if result.report.request != payload.request or (
                result.created and result.report.status == "STARTED"
            ):
                raise RuntimeError
            return result
        except SupplierCatalogRunnerFailure as error:
            status = 503 if error.kind == "unavailable" else 404 if error.kind == "lookup" else 422
            if error.code in {
                "NOTICE_VERSION_STALE",
                "NOTICE_VARIANT_REVIEW_REQUIRED",
                "SUPPLIER_CATALOG_BUSY",
                "SUPPLIER_CATALOG_TENANT_BUSY",
                "SUPPLIER_CATALOG_REFRESH_COOLDOWN",
                "SUPPLIER_CATALOG_SOURCE_CHANGED",
                "SUPPLIER_CATALOG_HOURLY_LIMIT",
                "SUPPLIER_CATALOG_DAILY_BODY_LIMIT",
            }:
                status = 409
            raise HTTPException(
                status, error.code, headers={"Cache-Control": "no-store"}
            ) from error
        except RuntimeError as error:
            raise HTTPException(
                503, "supplier_catalog_unavailable", headers={"Cache-Control": "no-store"}
            ) from error

    @app.post(
        "/v1/tender-discovery/eis-supplier-catalog/read",
        response_model=SavedSupplierCatalog,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {"schema": EIS_SUPPLIER_CATALOG_READ_OPENAPI_SCHEMA}
                },
            }
        },
    )
    async def read_saved_eis_supplier_catalog(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(document_review_principal)],
    ) -> SavedSupplierCatalog:
        response.headers["Cache-Control"] = "no-store"
        if eis_index_storage is None:
            raise HTTPException(
                503, "supplier_catalog_unavailable", headers={"Cache-Control": "no-store"}
            )
        payload = await _read_eis_supplier_catalog_body(request, SupplierCatalogReadRequest)
        try:
            result = await to_thread.run_sync(
                partial(
                    read_supplier_catalog, eis_index_storage, principal.company_id, payload.request
                )
            )
            if result.report.request != payload.request or result.created:
                raise RuntimeError
            return result
        except LookupError as error:
            raise HTTPException(
                404, "supplier_catalog_not_found", headers={"Cache-Control": "no-store"}
            ) from error
        except ValueError as error:
            code = str(error)
            conflicts = {
                "NOTICE_VERSION_STALE",
                "NOTICE_VARIANT_REVIEW_REQUIRED",
                "SUPPLIER_CATALOG_SOURCE_CHANGED",
            }
            allowed = conflicts | {
                "SUPPLIER_CATALOG_PARENT_LIMIT",
                "SUPPLIER_CATALOG_PARENT_DIGEST_CONFLICT",
                "SUPPLIER_CATALOG_PARENT_EVIDENCE_CONFLICT",
                "SUPPLIER_CATALOG_SEARCH_EVIDENCE_CONFLICT",
                "SUPPLIER_CATALOG_EVIDENCE_CONFLICT",
            }
            raise HTTPException(
                409 if code in conflicts else 422,
                code if code in allowed else "invalid_supplier_catalog_request",
                headers={"Cache-Control": "no-store"},
            ) from error
        except (SQLAlchemyError, RuntimeError) as error:
            raise HTTPException(
                503, "supplier_catalog_unavailable", headers={"Cache-Control": "no-store"}
            ) from error

    supplier_product_openapi = {
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": EIS_SUPPLIER_PRODUCT_OPENAPI_SCHEMA}},
        }
    }

    async def supplier_product_route(
        request: Request, response: Response, principal: Principal, *, prepare: bool
    ) -> SavedSupplierProduct:
        response.headers["Cache-Control"] = "no-store"
        if prepare and principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(
                403, "operator_role_required", headers={"Cache-Control": "no-store"}
            )
        if eis_index_storage is None:
            raise HTTPException(
                503, "supplier_product_unavailable", headers={"Cache-Control": "no-store"}
            )
        try:
            payload = await _read_eis_supplier_product_body(request, SupplierProductBody)
            operation = (
                partial(
                    prepare_supplier_product,
                    eis_index_storage,
                    principal.company_id,
                    payload.request,
                    actor_id=principal.actor_id,
                )
                if prepare
                else partial(
                    read_supplier_product,
                    eis_index_storage,
                    principal.company_id,
                    payload.request,
                )
            )
            result = await to_thread.run_sync(operation)
            if result.report.request != payload.request or (not prepare and result.created):
                raise RuntimeError("supplier product result binding failed")
            return result
        except HTTPException:
            raise
        except LookupError as error:
            raise HTTPException(
                404, "supplier_product_not_found", headers={"Cache-Control": "no-store"}
            ) from error
        except ValueError as error:
            code = str(error)
            conflicts = {
                "NOTICE_VERSION_STALE",
                "NOTICE_VARIANT_REVIEW_REQUIRED",
                "SUPPLIER_PRODUCT_SOURCE_CHANGED",
                "SUPPLIER_PRODUCT_PARENT_EVIDENCE_CONFLICT",
                "SUPPLIER_PRODUCT_PARENT_DIGEST_CONFLICT",
                "SUPPLIER_PRODUCT_EVIDENCE_CONFLICT",
                "SUPPLIER_PRODUCT_BUSY",
            }
            allowed = conflicts | {
                "SUPPLIER_PRODUCT_REQUEST_INVALID",
                "SUPPLIER_PRODUCT_CATALOG_STAGE_INVALID",
                "SUPPLIER_PRODUCT_PARENT_LIMIT",
            }
            raise HTTPException(
                409 if code in conflicts else 422,
                code if code in allowed else "invalid_supplier_product_request",
                headers={"Cache-Control": "no-store"},
            ) from error
        except (SQLAlchemyError, RuntimeError) as error:
            raise HTTPException(
                503, "supplier_product_unavailable", headers={"Cache-Control": "no-store"}
            ) from error

    @app.post(
        "/v1/tender-discovery/eis-supplier-product/prepare",
        response_model=SavedSupplierProduct,
        openapi_extra=supplier_product_openapi,
    )
    async def prepare_saved_eis_supplier_product(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(document_review_principal)],
    ) -> SavedSupplierProduct:
        return await supplier_product_route(request, response, principal, prepare=True)

    @app.post(
        "/v1/tender-discovery/eis-supplier-product/read",
        response_model=SavedSupplierProduct,
        openapi_extra=supplier_product_openapi,
    )
    async def read_saved_eis_supplier_product(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(document_review_principal)],
    ) -> SavedSupplierProduct:
        return await supplier_product_route(request, response, principal, prepare=False)

    requirement_preview_openapi = {
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": EIS_REQUIREMENT_PREVIEW_OPENAPI_SCHEMA}},
        }
    }

    @app.post(
        "/v1/tender-discovery/eis-requirement-preview/preview",
        response_model=RequirementPreview,
        openapi_extra=requirement_preview_openapi,
    )
    async def preview_eis_requirement_table(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(document_review_principal)],
    ) -> RequirementPreview:
        response.headers["Cache-Control"] = "no-store"
        if eis_index_storage is None:
            raise HTTPException(
                503, "requirement_preview_unavailable", headers={"Cache-Control": "no-store"}
            )
        try:
            payload = await _read_eis_supplier_product_body(request, RequirementPreviewBody)
            result = await to_thread.run_sync(
                read_requirement_preview,
                eis_index_storage,
                principal.company_id,
                payload.request,
            )
            if result.request != payload.request:
                raise RuntimeError("requirement preview result binding failed")
            return result
        except HTTPException:
            raise
        except LookupError as error:
            raise HTTPException(
                404, "requirement_preview_not_found", headers={"Cache-Control": "no-store"}
            ) from error
        except ValueError as error:
            code = str(error)
            conflicts = {
                "NOTICE_VERSION_STALE",
                "NOTICE_VARIANT_REVIEW_REQUIRED",
                "REQUIREMENT_PREVIEW_PRODUCT_EVIDENCE_CONFLICT",
                "SUPPLIER_PRODUCT_PARENT_EVIDENCE_CONFLICT",
                "SUPPLIER_PRODUCT_EVIDENCE_CONFLICT",
                "REVIEW_ANALYSIS_EVIDENCE_CONFLICT",
            }
            allowed = conflicts | {
                "REQUIREMENT_PREVIEW_NOTICE_CONFLICT",
                "REQUIREMENT_PREVIEW_LIMIT",
                "REQUIREMENT_TABLE_INDEX_INVALID",
            }
            raise HTTPException(
                409 if code in conflicts else 422,
                code if code in allowed else "invalid_requirement_preview_request",
                headers={"Cache-Control": "no-store"},
            ) from error
        except (SQLAlchemyError, RuntimeError) as error:
            raise HTTPException(
                503, "requirement_preview_unavailable", headers={"Cache-Control": "no-store"}
            ) from error

    def review_openapi(schema: dict[str, object]) -> dict[str, object]:
        return {
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": schema}},
            }
        }

    async def requirement_review_call(request: Request, schema, operation):
        try:
            payload = await _read_eis_document_review_body(request, schema)
            return await to_thread.run_sync(operation, payload)
        except HTTPException:
            raise
        except LookupError as error:
            raise HTTPException(
                404, "requirement_review_not_found", headers={"Cache-Control": "no-store"}
            ) from error
        except ValueError as error:
            code = str(error)
            conflicts = {
                "NOTICE_VERSION_STALE",
                "NOTICE_VARIANT_REVIEW_REQUIRED",
                "REQUIREMENT_PREVIEW_DIGEST_CONFLICT",
                "REQUIREMENT_PROPOSAL_DIGEST_CONFLICT",
                "REQUIREMENT_DECISION_CONFLICT",
                "REQUIREMENT_PROPOSAL_EVIDENCE_CONFLICT",
                "REQUIREMENT_DECISION_EVIDENCE_CONFLICT",
                "REQUIREMENT_REVIEW_BUSY",
            }
            raise HTTPException(
                409 if code in conflicts else 422,
                code if code in conflicts else "invalid_requirement_review_request",
                headers={"Cache-Control": "no-store"},
            ) from error
        except (SQLAlchemyError, RuntimeError) as error:
            raise HTTPException(
                503, "requirement_review_unavailable", headers={"Cache-Control": "no-store"}
            ) from error

    @app.post(
        "/v1/tender-discovery/eis/index/requirement-review/proposals",
        response_model=SavedRequirementProposal,
        openapi_extra=review_openapi(EIS_REQUIREMENT_PROPOSAL_OPENAPI_SCHEMA),
    )
    async def create_eis_requirement_proposal(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(document_review_principal)],
    ) -> SavedRequirementProposal:
        response.headers["Cache-Control"] = "no-store"
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(
                403, "operator_role_required", headers={"Cache-Control": "no-store"}
            )
        if eis_index_storage is None:
            raise HTTPException(
                503, "requirement_review_unavailable", headers={"Cache-Control": "no-store"}
            )
        return await requirement_review_call(
            request,
            ProposalRequest,
            lambda payload: create_requirement_proposal(
                eis_index_storage,
                principal.company_id,
                payload,
                actor_id=principal.actor_id,
            ),
        )

    @app.post(
        "/v1/tender-discovery/eis/index/requirement-review/proposals/read",
        response_model=SavedRequirementProposal,
        openapi_extra=review_openapi(EIS_REQUIREMENT_PROPOSAL_READ_OPENAPI_SCHEMA),
    )
    async def read_eis_requirement_proposal(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(document_review_principal)],
    ) -> SavedRequirementProposal:
        response.headers["Cache-Control"] = "no-store"
        if eis_index_storage is None:
            raise HTTPException(
                503, "requirement_review_unavailable", headers={"Cache-Control": "no-store"}
            )
        return await requirement_review_call(
            request,
            RequirementProposalRead,
            lambda payload: read_requirement_proposal(
                eis_index_storage, principal.company_id, payload.proposal_id
            ),
        )

    @app.post(
        "/v1/tender-discovery/eis/index/requirement-review/decisions",
        response_model=SavedRequirementDecision,
        openapi_extra=review_openapi(EIS_REQUIREMENT_DECISION_OPENAPI_SCHEMA),
    )
    async def create_eis_requirement_decision(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(document_review_principal)],
    ) -> SavedRequirementDecision:
        response.headers["Cache-Control"] = "no-store"
        if principal.access_role is not AccessRole.COMPLETENESS_REVIEWER:
            raise HTTPException(
                403, "completeness_reviewer_role_required", headers={"Cache-Control": "no-store"}
            )
        if eis_index_storage is None:
            raise HTTPException(
                503, "requirement_review_unavailable", headers={"Cache-Control": "no-store"}
            )
        return await requirement_review_call(
            request,
            DecisionRequest,
            lambda payload: create_requirement_decision(
                eis_index_storage,
                principal.company_id,
                payload,
                actor_id=principal.actor_id,
            ),
        )

    @app.post(
        "/v1/tender-discovery/eis/index/requirement-review/comparison",
        response_model=RequirementComparison,
        openapi_extra=review_openapi(EIS_REQUIREMENT_COMPARISON_OPENAPI_SCHEMA),
    )
    async def read_eis_requirement_comparison(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(document_review_principal)],
    ) -> RequirementComparison:
        response.headers["Cache-Control"] = "no-store"
        if eis_index_storage is None:
            raise HTTPException(
                503, "requirement_review_unavailable", headers={"Cache-Control": "no-store"}
            )
        return await requirement_review_call(
            request,
            RequirementComparisonRead,
            lambda payload: read_requirement_comparison(
                eis_index_storage, principal.company_id, payload.proposal_id
            ),
        )

    async def position_association_route(
        request: Request, response: Response, principal: Principal, *, save: bool
    ) -> SavedAssociation:
        response.headers["Cache-Control"] = "no-store"
        if save and principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(
                status_code=403,
                detail="operator_role_required",
                headers={"Cache-Control": "no-store"},
            )
        if eis_index_storage is None:
            raise HTTPException(
                status_code=503,
                detail="position_association_unavailable",
                headers={"Cache-Control": "no-store"},
            )
        try:
            payload = await _read_eis_document_review_body(request, PositionAssociationBody)
            operation = (
                partial(
                    save_position_fragment_association,
                    eis_index_storage,
                    principal.company_id,
                    payload.request,
                    actor_id=principal.actor_id,
                )
                if save
                else partial(
                    read_position_fragment_association,
                    eis_index_storage,
                    principal.company_id,
                    payload.request,
                )
            )
            result = await to_thread.run_sync(operation)
            if result.report.request != payload.request or (not save and result.created):
                raise RuntimeError("association result binding failed")
            return result
        except HTTPException:
            raise
        except LookupError as error:
            raise HTTPException(
                status_code=404,
                detail="position_association_not_found",
                headers={"Cache-Control": "no-store"},
            ) from error
        except ValueError as error:
            code = str(error)
            raise HTTPException(
                status_code=409
                if code
                in {
                    "NOTICE_VERSION_STALE",
                    "NOTICE_VARIANT_REVIEW_REQUIRED",
                    "POSITION_ASSOCIATION_BUSY",
                }
                else 422,
                detail="position_association_source_or_selection_invalid",
                headers={"Cache-Control": "no-store"},
            ) from error
        except (SQLAlchemyError, RuntimeError) as error:
            raise HTTPException(
                status_code=503,
                detail="position_association_unavailable",
                headers={"Cache-Control": "no-store"},
            ) from error

    association_openapi = {
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": EIS_POSITION_ASSOCIATION_OPENAPI_SCHEMA}},
        }
    }

    @app.post(
        "/v1/tender-discovery/eis-position-association/save",
        response_model=SavedAssociation,
        openapi_extra=association_openapi,
    )
    async def save_eis_position_association(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(document_review_principal)],
    ) -> SavedAssociation:
        return await position_association_route(request, response, principal, save=True)

    @app.post(
        "/v1/tender-discovery/eis-position-association/read",
        response_model=SavedAssociation,
        openapi_extra=association_openapi,
    )
    async def read_eis_position_association(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(document_review_principal)],
    ) -> SavedAssociation:
        return await position_association_route(request, response, principal, save=False)

    association_list_openapi = {
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": EIS_POSITION_ASSOCIATION_LIST_OPENAPI_SCHEMA}
            },
        }
    }
    association_detail_openapi = {
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": EIS_POSITION_ASSOCIATION_DETAIL_OPENAPI_SCHEMA}
            },
        }
    }

    @app.post(
        "/v1/tender-discovery/eis-position-association/list",
        response_model=AssociationListResult,
        openapi_extra=association_list_openapi,
    )
    async def list_eis_position_associations(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(document_review_principal)],
    ) -> AssociationListResult:
        response.headers["Cache-Control"] = "no-store"
        if eis_index_storage is None:
            raise HTTPException(
                status_code=503,
                detail="position_association_unavailable",
                headers={"Cache-Control": "no-store"},
            )
        try:
            payload = await _read_eis_document_review_body(request, PositionAssociationListBody)
            result = await to_thread.run_sync(
                partial(
                    list_position_fragment_associations,
                    eis_index_storage,
                    principal.company_id,
                    payload.request,
                )
            )
            if result.request != payload.request:
                raise RuntimeError("association list binding failed")
            return result
        except HTTPException:
            raise
        except LookupError as error:
            raise HTTPException(
                status_code=404,
                detail="position_association_not_found",
                headers={"Cache-Control": "no-store"},
            ) from error
        except ValueError as error:
            code = str(error)
            raise HTTPException(
                status_code=409
                if code in {"NOTICE_VERSION_STALE", "NOTICE_VARIANT_REVIEW_REQUIRED"}
                else 422,
                detail="position_association_source_or_cursor_invalid",
                headers={"Cache-Control": "no-store"},
            ) from error
        except (SQLAlchemyError, RuntimeError) as error:
            raise HTTPException(
                status_code=503,
                detail="position_association_unavailable",
                headers={"Cache-Control": "no-store"},
            ) from error

    @app.post(
        "/v1/tender-discovery/eis-position-association/detail",
        response_model=SavedAssociation,
        openapi_extra=association_detail_openapi,
    )
    async def detail_eis_position_association(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(document_review_principal)],
    ) -> SavedAssociation:
        response.headers["Cache-Control"] = "no-store"
        if eis_index_storage is None:
            raise HTTPException(
                status_code=503,
                detail="position_association_unavailable",
                headers={"Cache-Control": "no-store"},
            )
        try:
            payload = await _read_eis_document_review_body(request, PositionAssociationDetailBody)
            result = await to_thread.run_sync(
                partial(
                    read_position_fragment_association_detail,
                    eis_index_storage,
                    principal.company_id,
                    payload.request,
                )
            )
            report = result.report
            scope = payload.request.scope
            if (
                result.created
                or report.association_id != payload.request.association_id
                or report.request.position != scope.position
                or report.request.document != scope.document
                or report.request.analyzer_version != scope.analyzer_version
            ):
                raise RuntimeError("association detail binding failed")
            return result
        except HTTPException:
            raise
        except LookupError as error:
            raise HTTPException(
                status_code=404,
                detail="position_association_not_found",
                headers={"Cache-Control": "no-store"},
            ) from error
        except ValueError as error:
            code = str(error)
            raise HTTPException(
                status_code=409
                if code in {"NOTICE_VERSION_STALE", "NOTICE_VARIANT_REVIEW_REQUIRED"}
                else 422,
                detail="position_association_source_or_id_invalid",
                headers={"Cache-Control": "no-store"},
            ) from error
        except (SQLAlchemyError, RuntimeError) as error:
            raise HTTPException(
                status_code=503,
                detail="position_association_unavailable",
                headers={"Cache-Control": "no-store"},
            ) from error

    @app.get("/v1/tender-discovery/eis-protocols", response_model=EisHistoricalProtocolReport)
    async def historical_eis_protocols(
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
        purchase_number: Annotated[str, Query(pattern=r"^[0-9]{19,23}$")],
        version_number: Annotated[int, Query(ge=1)],
        notice_xml_sha256: Annotated[str, Query(pattern=r"^[0-9a-f]{64}$")],
    ) -> EisHistoricalProtocolReport:
        """Исторические документы по номеру закупки, без подтверждения связи с версией."""
        response.headers["Cache-Control"] = "no-store"
        if eis_index_storage is None:
            raise HTTPException(status_code=503, detail="eis_index_unavailable")
        ref = NoticeDocumentRef(
            purchase_number=purchase_number,
            version_number=version_number,
            notice_xml_sha256=notice_xml_sha256,
        )
        try:
            return await to_thread.run_sync(
                partial(
                    read_historical_protocols,
                    eis_index_storage,
                    principal.company_id,
                    ref,
                    now=datetime.now(UTC),
                )
            )
        except (ValueError, LookupError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/v1/tender-discovery/eis-223-index", response_model=Eis223SearchResult)
    async def discover_eis_223_index(
        query: Annotated[str, Query(min_length=1, max_length=120)],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
        page_size: Annotated[int | None, Query(ge=1, le=100)] = None,
        cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
    ) -> Eis223SearchResult:
        """Read the saved 223 projection without source calls or document jobs."""
        response.headers["Cache-Control"] = "no-store"
        if eis_index_storage is None:
            raise HTTPException(status_code=503, detail="eis_index_unavailable")
        try:
            page_options = (
                {"paginate": True, "limit": page_size or 100, "cursor": cursor}
                if page_size is not None or cursor is not None
                else {}
            )
            return await to_thread.run_sync(
                partial(
                    search_notice223_index,
                    eis_index_storage,
                    principal.company_id,
                    query,
                    now=datetime.now(UTC),
                    **page_options,
                )
            )
        except ValueError as error:
            if str(error) in {"SEARCH_PAGE_CHANGED", "SEARCH_PAGE_EXPIRED"}:
                raise HTTPException(
                    status_code=409 if str(error) == "SEARCH_PAGE_CHANGED" else 410,
                    detail=str(error),
                ) from error
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/v1/tender-discovery/eis-223-coverage", response_model=Eis223RegionalCoverage)
    async def discover_eis_223_coverage(
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Eis223RegionalCoverage:
        response.headers["Cache-Control"] = "no-store"
        if eis_index_storage is None:
            raise HTTPException(status_code=503, detail="eis_index_unavailable")
        return await to_thread.run_sync(
            partial(
                read_region_coverage, eis_index_storage, principal.company_id, now=datetime.now(UTC)
            )
        )

    @app.post("/v1/tender-discovery/eis-source-estimate", response_model=SourceEstimateResult)
    async def read_eis_source_estimate(
        payload: SourceEstimateRequest,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> SourceEstimateResult:
        response.headers["Cache-Control"] = "no-store"
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=403, detail="operator_required")
        if eis_index_storage is None:
            raise HTTPException(status_code=503, detail="eis_index_unavailable")
        try:
            return await to_thread.run_sync(
                partial(
                    get_source_estimate,
                    eis_index_storage,
                    principal.company_id,
                    payload,
                    actor_id=principal.actor_id,
                )
            )
        except SourceLotError as error:
            raise HTTPException(status_code=422, detail="selected_lot_not_found") from error
        except LookupError as error:
            raise HTTPException(status_code=404, detail="selected_notice_not_found") from error
        except ValueError as error:
            if str(error) == "NOTICE_VARIANT_REVIEW_REQUIRED":
                raise document_job_error(error) from error
            raise HTTPException(status_code=409, detail="estimate_evidence_conflict") from error

    @app.post("/v1/tender-discovery/eis-mixed-comparison", response_model=MixedComparisonResult)
    async def read_eis_mixed_comparison(
        payload: MixedComparisonRequest,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> MixedComparisonResult:
        response.headers["Cache-Control"] = "no-store"
        if eis_index_storage is None:
            raise HTTPException(status_code=503, detail="eis_index_unavailable")
        try:
            return await to_thread.run_sync(
                get_mixed_comparison, eis_index_storage, principal.company_id, payload
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail="selected_notice_not_found") from error
        except ValueError as error:
            if str(error) == "NOTICE_VARIANT_REVIEW_REQUIRED":
                raise document_job_error(error) from error
            raise HTTPException(status_code=409, detail="comparison_evidence_conflict") from error

    @app.post("/v1/tender-discovery/eis-223-comparison", response_model=Comparison223Result)
    async def read_eis223_comparison(
        payload: Comparison223Request,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Comparison223Result:
        response.headers["Cache-Control"] = "no-store"
        if eis_index_storage is None:
            raise HTTPException(status_code=503, detail="eis_index_unavailable")
        try:
            return await to_thread.run_sync(
                get_comparison223, eis_index_storage, principal.company_id, payload
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail="notice_223_not_found") from error
        except ValueError as error:
            raise HTTPException(
                status_code=409, detail="comparison_223_evidence_conflict"
            ) from error

    @app.post("/v1/tender-discovery/eis-223-document-jobs", response_model=Document223Status)
    async def request_eis223_document_job(
        payload: Notice223DocumentRef,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Document223Status:
        response.headers["Cache-Control"] = "no-store"
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=403, detail="operator_required")
        if eis_index_storage is None:
            raise HTTPException(status_code=503, detail="eis_index_unavailable")
        try:
            return await to_thread.run_sync(
                partial(
                    plan_document223_job,
                    eis_index_storage,
                    principal.company_id,
                    payload,
                    actor_id=principal.actor_id,
                )
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            limited = str(error) in {"DOCUMENT_223_QUEUE_FULL", "DOCUMENT_223_REQUEST_RATE_LIMIT"}
            raise HTTPException(status_code=429 if limited else 409, detail=str(error)) from error

    @app.get("/v1/tender-discovery/eis-223-documents/{number}", response_model=Document223Status)
    async def read_eis223_documents(
        number: str,
        version: Annotated[int, Query(ge=1)],
        xml_sha256: Annotated[str, Query(pattern=r"^[0-9a-f]{64}$")],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Document223Status:
        response.headers["Cache-Control"] = "no-store"
        if eis_index_storage is None:
            raise HTTPException(status_code=503, detail="eis_index_unavailable")
        try:
            ref = Notice223DocumentRef(
                purchase_number=number, version_number=version, notice_xml_sha256=xml_sha256
            )
            return await to_thread.run_sync(
                partial(get_document223_status, eis_index_storage, principal.company_id, ref)
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError:
            raise HTTPException(
                status_code=422, detail="invalid_eis_223_document_reference"
            ) from None

    @app.post("/v1/tender-discovery/eis-refresh-requests", response_model=EisRefreshStatus)
    async def request_eis_refresh(
        payload: EisRefreshRequestPayload,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> EisRefreshStatus:
        response.headers["Cache-Control"] = "no-store"
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=403, detail="operator_required")
        if eis_index_storage is None:
            raise HTTPException(status_code=503, detail="eis_index_unavailable")
        try:
            return await to_thread.run_sync(
                partial(
                    plan_refresh_request,
                    eis_index_storage,
                    principal.company_id,
                    payload,
                    actor_id=principal.actor_id,
                    now=datetime.now(UTC),
                )
            )
        except ValueError as error:
            limited = str(error) in {"REFRESH_QUEUE_FULL", "REFRESH_REQUEST_RATE_LIMIT"}
            raise HTTPException(
                status_code=429 if limited else 422,
                detail=str(error),
                headers={"Retry-After": "60"} if limited else None,
            ) from error

    @app.get(
        "/v1/tender-discovery/eis-refresh-requests/{request_id}", response_model=EisRefreshStatus
    )
    async def read_eis_refresh(
        request_id: str,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> EisRefreshStatus:
        response.headers["Cache-Control"] = "no-store"
        if eis_index_storage is None:
            raise HTTPException(status_code=503, detail="eis_index_unavailable")
        try:
            return await to_thread.run_sync(
                partial(
                    get_refresh_status,
                    eis_index_storage,
                    principal.company_id,
                    request_id,
                    now=datetime.now(UTC),
                )
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    def document_job_error(error: ValueError | LookupError) -> HTTPException:
        if isinstance(error, LookupError):
            return HTTPException(
                status_code=404, detail=str(error), headers={"Cache-Control": "no-store"}
            )
        return HTTPException(
            status_code=(
                409
                if str(error)
                in {
                    "NOTICE_VERSION_STALE",
                    "NOTICE_DIGEST_CONFLICT",
                }
                else 422
            ),
            detail=str(error),
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/v1/tender-discovery/eis-document-jobs", response_model=DocumentCollectionStatus)
    async def request_eis_document_job(
        payload: NoticeDocumentRef,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> DocumentCollectionStatus:
        response.headers["Cache-Control"] = "no-store"
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=403, detail="operator_required")
        if eis_index_storage is None:
            raise HTTPException(status_code=503, detail="eis_index_unavailable")
        try:
            return await to_thread.run_sync(
                partial(
                    plan_document_job,
                    eis_index_storage,
                    principal.company_id,
                    payload,
                    actor_id=principal.actor_id,
                )
            )
        except (ValueError, LookupError) as error:
            raise document_job_error(error) from error

    @app.post("/v1/tender-discovery/eis-document-selection", response_model=DocumentSelectionResult)
    async def request_eis_document_selection(
        payload: DocumentSelectionRequest,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> DocumentSelectionResult:
        response.headers["Cache-Control"] = "no-store"
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=403, detail="operator_required")
        if eis_index_storage is None:
            raise HTTPException(status_code=503, detail="eis_index_unavailable")
        try:
            return await to_thread.run_sync(
                partial(
                    plan_top_document_jobs,
                    eis_index_storage,
                    principal.company_id,
                    payload,
                    actor_id=principal.actor_id,
                )
            )
        except (ValueError, LookupError) as error:
            raise document_job_error(error) from error

    @app.get(
        "/v1/tender-discovery/eis-document-jobs/{purchase_number}",
        response_model=DocumentCollectionStatus,
    )
    async def read_eis_document_job(
        purchase_number: str,
        version_number: Annotated[int, Query(ge=1)],
        notice_xml_sha256: Annotated[str, Query(pattern=r"^[0-9a-f]{64}$")],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> DocumentCollectionStatus:
        response.headers["Cache-Control"] = "no-store"
        if eis_index_storage is None:
            raise HTTPException(status_code=503, detail="eis_index_unavailable")
        try:
            ref = NoticeDocumentRef(
                purchase_number=purchase_number,
                version_number=version_number,
                notice_xml_sha256=notice_xml_sha256,
            )
            return await to_thread.run_sync(
                get_document_status, eis_index_storage, principal.company_id, ref
            )
        except (ValueError, LookupError) as error:
            raise document_job_error(error) from error

    @app.get(
        "/v1/tender-discovery/eis-document-jobs/{purchase_number}/{content_uid}/analysis",
        response_model=DocumentAnalysis,
    )
    async def read_eis_document_analysis(
        purchase_number: str,
        content_uid: str,
        version_number: Annotated[int, Query(ge=1)],
        notice_xml_sha256: Annotated[str, Query(pattern=r"^[0-9a-f]{64}$")],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> DocumentAnalysis:
        response.headers["Cache-Control"] = "no-store"
        if eis_index_storage is None:
            raise HTTPException(status_code=503, detail="eis_index_unavailable")
        try:
            ref = NoticeDocumentRef(
                purchase_number=purchase_number,
                version_number=version_number,
                notice_xml_sha256=notice_xml_sha256,
            )
            return await to_thread.run_sync(
                get_document_analysis, eis_index_storage, principal.company_id, ref, content_uid
            )
        except (ValueError, LookupError) as error:
            raise document_job_error(error) from error

    @app.post("/v1/tender-discovery/eis-comparison", response_model=EisComparisonResult)
    async def read_eis_comparison(
        payload: EisComparisonRequest,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> EisComparisonResult:
        response.headers["Cache-Control"] = "no-store"
        if eis_index_storage is None:
            raise HTTPException(status_code=503, detail="eis_index_unavailable")
        try:
            return await to_thread.run_sync(
                get_eis_comparison, eis_index_storage, principal.company_id, payload
            )
        except (ValueError, LookupError) as error:
            raise document_job_error(error) from error

    @app.get(
        "/v1/tender-discovery/eis-document-jobs/{purchase_number}/evidence",
        response_model=EisEvidenceBridge,
    )
    async def read_eis_evidence_bridge(
        purchase_number: str,
        version_number: Annotated[int, Query(ge=1)],
        notice_xml_sha256: Annotated[str, Query(pattern=r"^[0-9a-f]{64}$")],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> EisEvidenceBridge:
        response.headers["Cache-Control"] = "no-store"
        if eis_index_storage is None:
            raise HTTPException(status_code=503, detail="eis_index_unavailable")
        try:
            ref = NoticeDocumentRef(
                purchase_number=purchase_number,
                version_number=version_number,
                notice_xml_sha256=notice_xml_sha256,
            )
            return await to_thread.run_sync(
                get_eis_evidence_bridge, eis_index_storage, principal.company_id, ref
            )
        except (ValueError, LookupError) as error:
            raise document_job_error(error) from error

    @app.post(
        "/v1/tender-discovery/eis-document-jobs/{purchase_number}/estimate",
        response_model=EisPreliminaryEstimate,
    )
    async def estimate_eis_document_job(
        purchase_number: str,
        version_number: Annotated[int, Query(ge=1)],
        notice_xml_sha256: Annotated[str, Query(pattern=r"^[0-9a-f]{64}$")],
        payload: DiscoveryCostInput,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> EisPreliminaryEstimate:
        response.headers["Cache-Control"] = "no-store"
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=403, detail="operator_required")
        if eis_index_storage is None:
            raise HTTPException(status_code=503, detail="eis_index_unavailable")
        try:
            ref = NoticeDocumentRef(
                purchase_number=purchase_number,
                version_number=version_number,
                notice_xml_sha256=notice_xml_sha256,
            )
            return await to_thread.run_sync(
                estimate_eis_notice, eis_index_storage, principal.company_id, ref, payload
            )
        except (ValueError, LookupError) as error:
            raise document_job_error(error) from error

    class EisAttachmentRequest(BaseModel):
        url: str = Field(min_length=1, max_length=2048)
        filename: str = Field(min_length=1, max_length=255)

    @app.post("/v1/tender-discovery/eis-attachment", response_model=EisDocumentPreview)
    async def inspect_eis_attachment(
        payload: EisAttachmentRequest,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> EisDocumentPreview:
        """Download one HTTPS EIS attachment and show a bounded extraction preview."""
        del principal
        response.headers["Cache-Control"] = "no-store"
        try:
            return await to_thread.run_sync(
                inspect_official_attachment, payload.url, payload.filename
            )
        except EisExportError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/v1/tender-discovery/eis-live", response_model=EisPublicSearchResult)
    async def discover_eis_live(
        query: Annotated[str, Query(min_length=1, max_length=120)],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> EisPublicSearchResult:
        """One public EIS browser page, with a host-wide crawl delay."""
        del principal
        response.headers["Cache-Control"] = "no-store"
        try:
            return await to_thread.run_sync(search_public_eis, query)
        except EisPublicError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    class EisLiveVerification(BaseModel):
        source: EisNumberSyncResult
        document_job: DocumentCollectionStatus | None = None
        document_queue_reason: str | None = None

    @app.post(
        "/v1/tender-discovery/eis-live/{purchase_number}/verify",
        response_model=EisLiveVerification,
    )
    async def verify_eis_live_number(
        purchase_number: str,
        response: Response,
        principal: Annotated[Principal, Depends(discovery_operator)],
    ) -> EisLiveVerification:
        """Read one exact official XML set and queue its version-bound documents."""
        response.headers["Cache-Control"] = "no-store"
        if not re.fullmatch(r"[0-9]{19,23}", purchase_number):
            raise HTTPException(status_code=422, detail="purchase_number_invalid")
        if eis_index_storage is None or not eis_number_token:
            raise HTTPException(status_code=503, detail="eis_number_source_unavailable")
        try:
            source = await sync_eis_number_via_browser(
                eis_index_storage,
                principal.company_id,
                principal.actor_id,
                purchase_number,
                eis_number_token,
            )
        except (EisSyncError, EisFeedArchiveError, EisIndexConflict) as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        except ValueError as error:
            if str(error) == "NOTICE_VARIANT_REVIEW_REQUIRED":
                raise document_job_error(error) from error
            raise
        if source.status != "SYNCED":
            return EisLiveVerification(source=source)
        if source.latest_version_number is None or source.latest_xml_sha256 is None:
            return EisLiveVerification(
                source=source, document_queue_reason="NOTICE_VERSION_UNKNOWN"
            )
        ref = NoticeDocumentRef(
            purchase_number=purchase_number,
            version_number=source.latest_version_number,
            notice_xml_sha256=source.latest_xml_sha256,
        )
        try:
            job = await to_thread.run_sync(
                partial(
                    plan_document_job,
                    eis_index_storage,
                    principal.company_id,
                    ref,
                    actor_id=principal.actor_id,
                )
            )
        except (ValueError, LookupError) as error:
            return EisLiveVerification(source=source, document_queue_reason=str(error))
        return EisLiveVerification(source=source, document_job=job)

    class EisDocumentsRequest(BaseModel):
        url: str = Field(min_length=1, max_length=2048)

    @app.post("/v1/tender-discovery/eis-documents", response_model=EisPublicDocumentsResult)
    async def list_eis_documents(
        payload: EisDocumentsRequest,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> EisPublicDocumentsResult:
        """List supported file links from one public EIS notice documents page."""
        del principal
        response.headers["Cache-Control"] = "no-store"
        try:
            return await to_thread.run_sync(read_public_documents, payload.url)
        except EisPublicError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/v1/supplier-discovery/eaeu", response_model=RegistrySearchResult)
    async def discover_eaeu_manufacturers(
        query: Annotated[str, Query(min_length=1, max_length=80)],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> RegistrySearchResult:
        """Authenticated live preview; no case fact or quote is persisted."""
        del principal
        response.headers["Cache-Control"] = "no-store"
        if not 1 <= len(query.split()) <= 5:
            raise HTTPException(status_code=422, detail="invalid_supplier_query")
        try:
            return await to_thread.run_sync(search_eaeu_registry, query)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="invalid_supplier_query") from error

    @app.get("/v1/supplier-discovery/eaeu-manufacturers", response_model=ManufacturerSearchResult)
    async def discover_eaeu_manufacturer_names(
        query: Annotated[str, Query(min_length=1, max_length=80)],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> ManufacturerSearchResult:
        """Authenticated company-name lookup in the published manufacturer collection."""
        del principal
        response.headers["Cache-Control"] = "no-store"
        if not 1 <= len(query.split()) <= 5:
            raise HTTPException(status_code=422, detail="invalid_supplier_query")
        try:
            return await to_thread.run_sync(search_eaeu_manufacturers, query)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="invalid_supplier_query") from error

    @app.get("/v1/supplier-discovery/direct-catalog", response_model=DirectCatalogAttempt)
    async def discover_supplier_direct_catalog(
        query: Annotated[str, Query(min_length=1, max_length=80)],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> DirectCatalogAttempt:
        """Ephemeral direct marketplace catalog lookup, never persisted as case evidence."""
        del principal
        response.headers["Cache-Control"] = "no-store"
        if not 1 <= len(query.split()) <= 5:
            raise HTTPException(status_code=422, detail="invalid_supplier_query")
        try:
            return await to_thread.run_sync(search_direct_catalog, query)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="invalid_supplier_query") from error

    @app.get("/v1/supplier-discovery/yandex-business", response_model=YandexBusinessAttempt)
    async def discover_yandex_business_category(
        query: Annotated[str, Query(min_length=1, max_length=80)],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> YandexBusinessAttempt:
        """Read-only first page of a verified public category, when the query matches."""
        del principal
        response.headers["Cache-Control"] = "no-store"
        if not 1 <= len(query.split()) <= 5:
            raise HTTPException(status_code=422, detail="invalid_supplier_query")
        try:
            return await to_thread.run_sync(search_yandex_business_category, query)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="invalid_supplier_query") from error

    @app.get(
        "/v1/documents/{document_id}/supplier-search-plan",
        response_model=DocumentSupplierSearchPlan,
    )
    async def get_document_supplier_search_plan(
        document_id: Annotated[str, Field(min_length=1, max_length=200)],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
        mode: SearchMode = "AUTO",
    ) -> DocumentSupplierSearchPlan:
        document = await service.get_document(
            company_id=principal.company_id, document_id=document_id
        )
        if document is None:
            raise _not_found()
        response.headers["Cache-Control"] = "no-store"
        return build_document_supplier_search_plan(document, mode=mode)

    @app.post(
        "/v1/documents/{document_id}/supplier-search-runs",
        response_model=DocumentSupplierSearchRun,
    )
    async def run_document_supplier_search(
        document_id: Annotated[str, Field(min_length=1, max_length=200)],
        approval: DocumentSupplierSearchApproval,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> DocumentSupplierSearchRun:
        if principal.access_role is AccessRole.AUDITOR:
            raise HTTPException(status_code=403, detail="auditor_read_only")
        document = await service.get_document(
            company_id=principal.company_id, document_id=document_id
        )
        if document is None:
            raise _not_found()
        plan = build_document_supplier_search_plan(document, mode=approval.mode)
        if plan.status is not SearchPlanStatus.READY:
            raise HTTPException(status_code=409, detail="supplier_search_plan_not_ready")
        if plan.plan_sha256 != approval.plan_sha256:
            raise HTTPException(status_code=409, detail="supplier_search_plan_changed")
        assert plan.query is not None
        catalog_query = plan.query
        response.headers["Cache-Control"] = "no-store"

        async def catalog_sources() -> tuple[
            DirectCatalogAttempt | None, YandexBusinessAttempt | None, tuple[BrowserAttempt, ...]
        ]:
            direct: DirectCatalogAttempt | None = None
            yandex: YandexBusinessAttempt | None = None
            use_servermall = any(d.site_id == "servermall_hpe_gen12" for d in plan.destinations)
            use_yandex = any(d.site_id == "yandex_market_business" for d in plan.destinations)
            use_supl = any(d.site_id == "supl_biz_pumps" for d in plan.destinations)
            if plan.mode != "BROWSER":
                direct, yandex = await asyncio.gather(
                    to_thread.run_sync(search_direct_catalog, catalog_query)
                    if use_servermall
                    else asyncio.sleep(0, result=None),
                    to_thread.run_sync(search_yandex_business_category, catalog_query)
                    if use_yandex
                    else asyncio.sleep(0, result=None),
                )
            sites: list[BrowserSite] = []
            if plan.mode != "HTTP":
                if use_servermall and (direct is None or direct.fetch_status == "SOURCE_ERROR"):
                    sites.append(BrowserSite.SERVERMALL)
                if use_yandex and (yandex is None or yandex.fetch_status == "SOURCE_ERROR"):
                    sites.append(BrowserSite.YANDEX_BUSINESS)
                if use_supl:
                    sites.append(BrowserSite.SUPL_BIZ)
            attempts = await asyncio.gather(
                *(
                    run_browser_source(
                        company_id=principal.company_id, site=site, query=catalog_query
                    )
                    for site in sites
                )
            )
            return direct, yandex, tuple(attempts)

        eaeu_products, catalogs, graviton_catalog, depo_catalog = await asyncio.gather(
            to_thread.run_sync(search_eaeu_registry, plan.query),
            catalog_sources(),
            to_thread.run_sync(search_graviton_catalog, plan.query)
            if any(d.site_id == "graviton_catalog" for d in plan.destinations)
            else asyncio.sleep(0, result=None),
            to_thread.run_sync(search_depo_catalog, plan.query)
            if any(d.site_id == "depo_servers" for d in plan.destinations)
            else asyncio.sleep(0, result=None),
        )
        direct_catalog, yandex_business, browser_attempts = catalogs
        return DocumentSupplierSearchRun(
            plan=plan,
            eaeu_products=eaeu_products,
            direct_catalog=direct_catalog,
            yandex_business=yandex_business,
            browser_attempts=browser_attempts,
            graviton_catalog=graviton_catalog,
            depo_catalog=depo_catalog,
        )

    @app.post(
        "/v1/documents/{document_id}/ai-transfer-requests",
        status_code=201,
        response_model=PersistedAiTransferRequest,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {"schema": AiTransferPrepareRequest.model_json_schema()}
                },
            }
        },
    )
    async def prepare_ai_transfer(
        document_id: Annotated[str, Field(min_length=1, max_length=200)],
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> PersistedAiTransferRequest:
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=403, detail="operator_required")
        body = await _read_ai_transfer_body(request, AiTransferPrepareRequest)
        try:
            prepared = await service.store_ai_transfer_request(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                source_document_id=document_id,
                model=body.model,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    principal.actor_id,
                    "store_ai_transfer_request",
                    principal.company_id,
                    document_id,
                    canonical_json_sha256(body),
                ),
            )
        except AiTransferNotFound as error:
            raise _not_found() from error
        except AiTransferConflict as error:
            raise HTTPException(status_code=409, detail="ai_transfer_conflict") from error
        except InvalidAiTransfer as error:
            raise HTTPException(status_code=422, detail="invalid_ai_transfer") from error
        if (
            prepared.company_id != principal.company_id
            or prepared.source_document_id != document_id
            or prepared.prepared_by != principal.actor_id
        ):
            raise RuntimeError("storage returned an AI transfer for another identity")
        response.headers["Cache-Control"] = "no-store"
        return prepared

    @app.get("/v1/ai-transfer-requests/{transfer_id}", response_model=AiTransferDetail)
    async def get_ai_transfer(
        transfer_id: Annotated[str, Field(min_length=1, max_length=200)],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> AiTransferDetail:
        if principal.access_role not in {
            AccessRole.OPERATOR,
            AccessRole.AI_TRANSFER_APPROVER,
        }:
            raise HTTPException(status_code=403, detail="ai_transfer_access_required")
        try:
            detail = await service.get_ai_transfer_request(
                company_id=principal.company_id, transfer_id=transfer_id
            )
        except InvalidAiTransfer as error:
            raise HTTPException(status_code=422, detail="invalid_ai_transfer") from error
        if detail is None:
            raise _not_found()
        if (
            detail.request.company_id != principal.company_id
            or detail.request.transfer_id != transfer_id
        ):
            raise RuntimeError("storage returned an AI transfer for another identity")
        if (
            principal.access_role is AccessRole.OPERATOR
            and detail.request.prepared_by != principal.actor_id
        ):
            raise _not_found()
        response.headers["Cache-Control"] = "no-store"
        return detail

    @app.post(
        "/v1/ai-transfer-requests/{transfer_id}/approval",
        status_code=201,
        response_model=PersistedAiTransferApproval,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {"schema": AiTransferApprovalRequest.model_json_schema()}
                },
            }
        },
    )
    async def approve_ai_transfer(
        transfer_id: Annotated[str, Field(min_length=1, max_length=200)],
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> PersistedAiTransferApproval:
        if principal.access_role is not AccessRole.AI_TRANSFER_APPROVER:
            raise HTTPException(status_code=403, detail="ai_transfer_approver_required")
        body = await _read_ai_transfer_body(request, AiTransferApprovalRequest)
        try:
            approval = await service.approve_ai_transfer_request(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                transfer_id=transfer_id,
                request_payload_sha256=body.request_payload_sha256,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    principal.actor_id,
                    "approve_ai_transfer_request",
                    principal.company_id,
                    transfer_id,
                    canonical_json_sha256(body),
                ),
            )
        except AiTransferNotFound as error:
            raise _not_found() from error
        except AiTransferConflict as error:
            raise HTTPException(status_code=409, detail="ai_transfer_conflict") from error
        except InvalidAiTransfer as error:
            raise HTTPException(status_code=422, detail="invalid_ai_transfer") from error
        if (
            approval.company_id != principal.company_id
            or approval.transfer_id != transfer_id
            or approval.approved_by != principal.actor_id
            or approval.request_payload_sha256 != body.request_payload_sha256
        ):
            raise RuntimeError("storage returned an AI transfer approval for another identity")
        response.headers["Cache-Control"] = "no-store"
        return approval

    @app.post(
        "/v1/ai-transfer-requests/{transfer_id}/execution-admissions",
        status_code=201,
        response_model=AiTransferExecutionAdmission,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": AiTransferExecutionAdmissionRequest.model_json_schema()
                    }
                },
            }
        },
    )
    async def admit_ai_transfer_execution(
        transfer_id: Annotated[str, Field(min_length=1, max_length=200)],
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> AiTransferExecutionAdmission:
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=403, detail="operator_required")
        body = await _read_ai_transfer_body(request, AiTransferExecutionAdmissionRequest)
        try:
            admission = await service.admit_ai_transfer_execution(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                transfer_id=transfer_id,
                request_payload_sha256=body.request_payload_sha256,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    principal.actor_id,
                    "admit_ai_transfer_execution",
                    principal.company_id,
                    transfer_id,
                    canonical_json_sha256(body),
                ),
            )
        except AiTransferNotFound as error:
            raise _not_found() from error
        except AiTransferConflict as error:
            raise HTTPException(status_code=409, detail="ai_transfer_conflict") from error
        except InvalidAiTransfer as error:
            raise HTTPException(status_code=422, detail="invalid_ai_transfer") from error
        if (
            admission.company_id != principal.company_id
            or admission.transfer_id != transfer_id
            or admission.request_payload_sha256 != body.request_payload_sha256
            or admission.admitted_by != principal.actor_id
        ):
            raise RuntimeError("storage returned an AI transfer admission for another identity")
        response.headers["Cache-Control"] = "no-store"
        return admission

    @app.get("/v1/ai-transfer-executions/{execution_id}", response_model=AiTransferExecutionDetail)
    async def get_ai_transfer_execution(
        execution_id: Annotated[str, Field(min_length=1, max_length=200)],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> AiTransferExecutionDetail:
        if principal.access_role not in {
            AccessRole.OPERATOR,
            AccessRole.AI_TRANSFER_APPROVER,
            AccessRole.AI_REQUIREMENTS_REVIEWER,
            AccessRole.AUDITOR,
        }:
            raise HTTPException(status_code=403, detail="ai_transfer_access_required")
        try:
            detail = await service.get_ai_transfer_execution(
                company_id=principal.company_id, execution_id=execution_id
            )
        except InvalidAiTransfer as error:
            raise HTTPException(status_code=422, detail="invalid_ai_transfer") from error
        if detail is None:
            raise _not_found()
        if (
            detail.admission.company_id != principal.company_id
            or detail.admission.execution_id != execution_id
        ):
            raise RuntimeError("storage returned an AI transfer execution for another identity")
        if (
            principal.access_role is AccessRole.OPERATOR
            and detail.admission.admitted_by != principal.actor_id
        ):
            raise _not_found()
        response.headers["Cache-Control"] = "no-store"
        return detail

    @app.post(
        "/v1/ai-transfer-executions/{execution_id}/requirement-materializations",
        response_model=AiTransferRequirementMaterialization,
    )
    async def materialize_ai_transfer_requirement_run(
        execution_id: Annotated[str, Field(min_length=1, max_length=200)],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> AiTransferRequirementMaterialization:
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=403, detail="operator_required")
        try:
            execution = await service.get_ai_transfer_execution(
                company_id=principal.company_id,
                execution_id=execution_id,
            )
        except InvalidAiTransfer as error:
            raise HTTPException(status_code=422, detail="invalid_ai_transfer") from error
        if execution is None or execution.admission.admitted_by != principal.actor_id:
            raise _not_found()
        if (
            execution.admission.company_id != principal.company_id
            or execution.admission.execution_id != execution_id
        ):
            raise RuntimeError("storage returned an AI transfer execution for another identity")
        try:
            materialization, _ = await service.materialize_ai_transfer_requirement_run(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                execution_id=execution_id,
            )
        except AiTransferNotFound as error:
            raise _not_found() from error
        except AiTransferConflict as error:
            raise HTTPException(status_code=409, detail="ai_transfer_conflict") from error
        except InvalidAiTransfer as error:
            raise HTTPException(status_code=422, detail="invalid_ai_transfer") from error
        if (
            materialization.company_id != principal.company_id
            or materialization.execution_id != execution_id
        ):
            raise RuntimeError(
                "storage returned an AI transfer materialization for another identity"
            )
        response.headers["Cache-Control"] = "no-store"
        return materialization

    @app.post(
        "/v1/ai-transfer-executions/{execution_id}/requirement-batch-materializations",
        response_model=AiTransferRequirementBatchMaterializationDetail,
    )
    async def materialize_ai_transfer_requirement_batch(
        execution_id: Annotated[str, Field(min_length=1, max_length=200)],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> AiTransferRequirementBatchMaterializationDetail:
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=403, detail="operator_required")
        try:
            execution = await service.get_ai_transfer_execution(
                company_id=principal.company_id,
                execution_id=execution_id,
            )
        except InvalidAiTransfer as error:
            raise HTTPException(status_code=422, detail="invalid_ai_transfer") from error
        if execution is None or execution.admission.admitted_by != principal.actor_id:
            raise _not_found()
        if (
            execution.admission.company_id != principal.company_id
            or execution.admission.execution_id != execution_id
        ):
            raise RuntimeError("storage returned an AI transfer execution for another identity")
        try:
            detail = await service.materialize_ai_transfer_requirement_batch(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                execution_id=execution_id,
            )
        except AiTransferNotFound as error:
            raise _not_found() from error
        except AiTransferConflict as error:
            raise HTTPException(status_code=409, detail="ai_transfer_conflict") from error
        except InvalidAiTransfer as error:
            raise HTTPException(status_code=422, detail="invalid_ai_transfer") from error
        if detail.company_id != principal.company_id or detail.execution_id != execution_id:
            raise RuntimeError(
                "storage returned an AI transfer batch materialization for another identity"
            )
        response.headers["Cache-Control"] = "no-store"
        return detail

    @app.get(
        "/v1/ai-transfer-raw-responses/{raw_response_id}",
        response_class=Response,
        responses={200: {"content": {"application/octet-stream": {}}}},
    )
    async def read_ai_transfer_raw_response(
        raw_response_id: Annotated[str, Field(min_length=1, max_length=200)],
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Response:
        if principal.access_role not in {
            AccessRole.AI_REQUIREMENTS_REVIEWER,
            AccessRole.AUDITOR,
        }:
            raise HTTPException(status_code=403, detail="ai_transfer_raw_access_required")
        try:
            result = await service.read_ai_transfer_raw_response(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                access_role=principal.access_role,
                raw_response_id=raw_response_id,
            )
        except InvalidAiTransfer as error:
            raise HTTPException(status_code=422, detail="invalid_ai_transfer") from error
        if result is None:
            raise _not_found()
        content, metadata = result
        if (
            metadata.company_id != principal.company_id
            or metadata.raw_response_id != raw_response_id
        ):
            raise RuntimeError("storage returned an AI transfer raw response for another identity")
        return Response(
            content=content,
            media_type="application/octet-stream",
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": 'attachment; filename="ai-transfer-response.json"',
            },
        )

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.post("/v1/cases", status_code=status.HTTP_201_CREATED, response_model=ProcurementCase)
    async def create_case(
        case: ProcurementCase,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> ProcurementCase:
        if principal.access_role is AccessRole.AUDITOR:
            raise HTTPException(status_code=403, detail="auditor_read_only")
        if case.company_id != principal.company_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant_mismatch")
        try:
            saved = await service.create_case(
                company_id=principal.company_id,
                case=case,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(case.model_dump_json()),
            )
        except VersionConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="version_conflict",
            ) from error
        if saved.company_id != principal.company_id:
            raise RuntimeError("storage returned a case for a different tenant")
        return saved

    @app.get("/v1/cases/{case_id}/versions/{version}", response_model=ProcurementCase)
    async def get_case(
        case_id: Annotated[str, Field(min_length=1)],
        version: Annotated[int, Field(ge=1)],
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> ProcurementCase:
        case = await service.get_case(
            company_id=principal.company_id,
            case_id=case_id,
            version=version,
        )
        if case is None or case.company_id != principal.company_id:
            raise _not_found()
        return case

    @app.get("/v1/cases", response_model=CasePage)
    async def list_cases(
        principal: Annotated[Principal, Depends(current_principal)],
        cursor: Annotated[str | None, Query(max_length=200)] = None,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    ) -> CasePage:
        try:
            page = await service.list_cases(
                company_id=principal.company_id,
                cursor=cursor,
                limit=limit,
            )
        except InvalidCursor as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="validation_error",
            ) from error
        if any(case.company_id != principal.company_id for case in page.items):
            raise RuntimeError("storage returned a case for a different tenant")
        return page

    @app.post(
        "/v1/cases/{case_id}/versions/{version}/sourcing-runs",
        status_code=status.HTTP_201_CREATED,
        response_model=SourcingRunRecord,
    )
    async def run_server_sourcing(
        request: SourcingRunRequest,
        case_id: Annotated[str, Field(min_length=1)],
        version: Annotated[int, Field(ge=1)],
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> SourcingRunRecord:
        if principal.access_role is AccessRole.AUDITOR:
            raise HTTPException(status_code=403, detail="auditor_read_only")
        case = await service.get_case(
            company_id=principal.company_id, case_id=case_id, version=version
        )
        if case is None or case.company_id != principal.company_id:
            raise _not_found()
        try:
            result = await service.run_server_sourcing(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                case_id=case_id,
                version=version,
                query=request.query,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(case_id, str(version), request.model_dump_json()),
            )
        except VersionConflict as error:
            raise HTTPException(status_code=409, detail="version_conflict") from error
        except InvalidRequirementSet as error:
            raise HTTPException(status_code=422, detail="invalid_requirement_set") from error
        if result.company_id != principal.company_id:
            raise RuntimeError("storage returned a sourcing run for a different tenant")
        return result

    @app.get(
        "/v1/cases/{case_id}/versions/{version}/sourcing-runs/latest",
        response_model=SourcingRunRecord,
    )
    async def get_latest_server_sourcing(
        case_id: Annotated[str, Field(min_length=1)],
        version: Annotated[int, Field(ge=1)],
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> SourcingRunRecord:
        case = await service.get_case(
            company_id=principal.company_id, case_id=case_id, version=version
        )
        if case is None or case.company_id != principal.company_id:
            raise _not_found()
        result = await service.get_latest_sourcing_run(
            company_id=principal.company_id, case_id=case_id, version=version
        )
        if result is None or result.company_id != principal.company_id:
            raise _not_found()
        return result

    @app.post(
        "/v1/documents/{document_id}/reviewed-requirement-set-preview",
        response_model=RequirementSetMaterializationPreview,
    )
    async def preview_reviewed_requirement_set_materialization(
        document_id: Annotated[str, Field(min_length=1, max_length=200)],
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> RequirementSetMaterializationPreview:
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=403, detail="operator_required")
        payload = await _read_requirement_set_body(
            request, RequirementSetMaterializationPreviewRequest
        )
        try:
            preview = await service.preview_reviewed_requirement_set_materialization(
                company_id=principal.company_id,
                source_document_id=document_id,
                source_document_sha256=payload.source_document_sha256,
                expected_entry_count=payload.expected_entry_count,
            )
        except RequirementSetNotFound as error:
            raise _not_found() from error
        except InvalidRequirementSet as error:
            raise HTTPException(status_code=422, detail="invalid_requirement_set") from error
        if preview.company_id != principal.company_id:
            raise RuntimeError("storage returned a requirement preview for another tenant")
        response.headers["Cache-Control"] = "no-store"
        return preview

    @app.post(
        "/v1/documents/{document_id}/reviewed-requirement-set-materializations",
        status_code=status.HTTP_201_CREATED,
        response_model=ReviewedRequirementSetRecord,
    )
    async def materialize_reviewed_requirement_set_proposal(
        document_id: Annotated[str, Field(min_length=1, max_length=200)],
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> ReviewedRequirementSetRecord:
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=403, detail="operator_required")
        payload = await _read_requirement_set_body(request, RequirementSetMaterializationRequest)
        try:
            record = await service.materialize_reviewed_requirement_set_proposal(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                set_id=str(uuid.uuid4()),
                source_document_id=document_id,
                source_document_sha256=payload.source_document_sha256,
                expected_entry_count=payload.expected_entry_count,
                preview_sha256=payload.preview_sha256,
                declared_scope=payload.declared_scope,
                selections=payload.selections,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    principal.actor_id,
                    document_id,
                    "materialize_reviewed_requirement_set_proposal",
                    canonical_json_sha256(payload),
                ),
            )
        except RequirementSetNotFound as error:
            raise _not_found() from error
        except RequirementSetConflict as error:
            raise HTTPException(status_code=409, detail="requirement_set_conflict") from error
        except InvalidRequirementSet as error:
            raise HTTPException(status_code=422, detail="invalid_requirement_set") from error
        if record.proposal.company_id != principal.company_id:
            raise RuntimeError("storage returned a requirement set for another tenant")
        response.headers["Cache-Control"] = "no-store"
        return record

    @app.post(
        "/v1/reviewed-requirement-sets",
        status_code=status.HTTP_201_CREATED,
        response_model=ReviewedRequirementSetRecord,
    )
    async def create_reviewed_requirement_set(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> ReviewedRequirementSetRecord:
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=403, detail="operator_required")
        payload = await _read_requirement_set_body(request, ReviewedRequirementSetProposalRequest)
        try:
            record = await service.store_reviewed_requirement_set_proposal(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                set_id=str(uuid.uuid4()),
                source_document_id=payload.source_document_id,
                source_document_sha256=payload.source_document_sha256,
                declared_scope=payload.declared_scope,
                expected_entry_count=payload.expected_entry_count,
                entries=payload.entries,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    principal.actor_id,
                    "store_reviewed_requirement_set_proposal",
                    canonical_json_sha256(payload),
                ),
            )
        except RequirementSetNotFound as error:
            raise _not_found() from error
        except RequirementSetConflict as error:
            raise HTTPException(status_code=409, detail="requirement_set_conflict") from error
        except InvalidRequirementSet as error:
            raise HTTPException(status_code=422, detail="invalid_requirement_set") from error
        if record.proposal.company_id != principal.company_id:
            raise RuntimeError("storage returned a requirement set for another tenant")
        response.headers["Cache-Control"] = "no-store"
        return record

    @app.get(
        "/v1/reviewed-requirement-sets/{set_id}",
        response_model=ReviewedRequirementSetRecord,
    )
    async def get_reviewed_requirement_set(
        set_id: Annotated[str, Field(min_length=1, max_length=200)],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> ReviewedRequirementSetRecord:
        try:
            record = await service.get_reviewed_requirement_set(
                company_id=principal.company_id,
                set_id=set_id,
            )
        except InvalidRequirementSet as error:
            raise HTTPException(status_code=422, detail="invalid_requirement_set") from error
        if record is None or record.proposal.company_id != principal.company_id:
            raise _not_found()
        response.headers["Cache-Control"] = "no-store"
        return record

    @app.post(
        "/v1/reviewed-requirement-sets/{set_id}/decision",
        response_model=ReviewedRequirementSetRecord,
    )
    async def decide_reviewed_requirement_set(
        set_id: Annotated[str, Field(min_length=1, max_length=200)],
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> ReviewedRequirementSetRecord:
        if principal.access_role is not AccessRole.COMPLETENESS_REVIEWER:
            raise HTTPException(status_code=403, detail="reviewer_required")
        payload = await _read_requirement_set_body(request, ReviewedRequirementSetDecisionRequest)
        try:
            record = await service.decide_reviewed_requirement_set(
                company_id=principal.company_id,
                reviewer_id=principal.actor_id,
                set_id=set_id,
                proposal_sha256=payload.proposal_sha256,
                coverage_assessment=payload.coverage_assessment,
                normalization_assessment=payload.normalization_assessment,
                status=payload.status,
                reason=payload.reason,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    principal.actor_id,
                    set_id,
                    "decide_reviewed_requirement_set",
                    canonical_json_sha256(payload),
                ),
            )
        except RequirementSetNotFound as error:
            raise _not_found() from error
        except RequirementSetConflict as error:
            raise HTTPException(status_code=409, detail="requirement_set_conflict") from error
        except InvalidRequirementSet as error:
            raise HTTPException(status_code=422, detail="invalid_requirement_set") from error
        response.headers["Cache-Control"] = "no-store"
        return record

    @app.post(
        "/v1/case-requirement-set-bindings",
        status_code=status.HTTP_201_CREATED,
        response_model=CaseRequirementSetBinding,
    )
    async def bind_reviewed_requirement_set_to_case(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> CaseRequirementSetBinding:
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=403, detail="operator_required")
        payload = await _read_requirement_set_body(request, CaseRequirementSetBindingRequest)
        try:
            binding = await service.bind_reviewed_requirement_set_to_case(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                binding_id=str(uuid.uuid4()),
                case_id=payload.case_id,
                case_version=payload.case_version,
                set_id=payload.set_id,
                proposal_sha256=payload.proposal_sha256,
                decision_sha256=payload.decision_sha256,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    principal.actor_id,
                    "bind_reviewed_requirement_set_to_case",
                    canonical_json_sha256(payload),
                ),
            )
        except RequirementSetNotFound as error:
            raise _not_found() from error
        except RequirementSetConflict as error:
            raise HTTPException(status_code=409, detail="requirement_set_conflict") from error
        except InvalidRequirementSet as error:
            raise HTTPException(status_code=422, detail="invalid_requirement_set") from error
        response.headers["Cache-Control"] = "no-store"
        return binding

    @app.get(
        "/v1/case-requirement-set-bindings/{binding_id}",
        response_model=CaseRequirementSetBinding,
    )
    async def get_case_requirement_set_binding(
        binding_id: Annotated[str, Field(min_length=1, max_length=200)],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> CaseRequirementSetBinding:
        try:
            binding = await service.get_case_requirement_set_binding(
                company_id=principal.company_id,
                binding_id=binding_id,
            )
        except InvalidRequirementSet as error:
            raise HTTPException(status_code=422, detail="invalid_requirement_set") from error
        if binding is None or binding.company_id != principal.company_id:
            raise _not_found()
        response.headers["Cache-Control"] = "no-store"
        return binding

    @app.post(
        "/v1/cases/{case_id}/versions/{version}/server-offer-proposals",
        status_code=status.HTTP_201_CREATED,
        response_model=ServerOfferProposal,
    )
    async def create_server_offer_proposal(
        case_id: Annotated[str, Field(min_length=1, max_length=200)],
        version: Annotated[int, Field(ge=1)],
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> ServerOfferProposal:
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=403, detail="operator_required")
        payload = await _read_server_offer_body(request)
        try:
            proposal = await service.store_server_offer_proposal(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                offer_id=str(uuid.uuid4()),
                case_id=case_id,
                case_version=version,
                requirement_set_binding_id=payload.requirement_set_binding_id,
                requirement_set_binding_sha256=payload.requirement_set_binding_sha256,
                sourcing_run_id=payload.sourcing_run_id,
                lead_id=payload.lead_id,
                source_document_id=payload.source_document_id,
                source_document_sha256=payload.source_document_sha256,
                bom_lines=payload.bom_lines,
                commercial_terms=payload.commercial_terms,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    principal.actor_id,
                    case_id,
                    str(version),
                    "store_server_offer_proposal",
                    canonical_json_sha256(payload),
                ),
            )
        except ServerOfferNotFound as error:
            raise _not_found() from error
        except ServerOfferConflict as error:
            raise HTTPException(status_code=409, detail="server_offer_conflict") from error
        except InvalidServerOffer as error:
            raise HTTPException(status_code=422, detail="invalid_server_offer") from error
        response.headers["Cache-Control"] = "no-store"
        return proposal

    @app.get(
        "/v1/server-offer-proposals/{offer_id}",
        response_model=ServerOfferProposal,
    )
    async def get_server_offer_proposal(
        offer_id: Annotated[str, Field(min_length=1, max_length=200)],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> ServerOfferProposal:
        try:
            proposal = await service.get_server_offer_proposal(
                company_id=principal.company_id,
                offer_id=offer_id,
            )
        except InvalidServerOffer as error:
            raise HTTPException(status_code=422, detail="invalid_server_offer") from error
        if proposal is None or proposal.company_id != principal.company_id:
            raise _not_found()
        response.headers["Cache-Control"] = "no-store"
        return proposal

    @app.get(
        "/v1/server-offer-proposals/{offer_id}/review",
        response_model=ServerOfferReviewRecord,
    )
    async def get_server_offer_review(
        offer_id: Annotated[str, Field(min_length=1, max_length=200)],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> ServerOfferReviewRecord:
        if principal.access_role is not AccessRole.COMPLETENESS_REVIEWER:
            raise HTTPException(status_code=403, detail="reviewer_required")
        try:
            record = await service.get_server_offer_review(
                company_id=principal.company_id, offer_id=offer_id
            )
        except InvalidServerOfferReview as error:
            raise HTTPException(status_code=422, detail="invalid_server_offer_review") from error
        if record is None or record.evidence.proposal.company_id != principal.company_id:
            raise _not_found()
        response.headers["Cache-Control"] = "no-store"
        return record

    @app.post(
        "/v1/server-offer-proposals/{offer_id}/review-decision",
        response_model=ServerOfferReviewDecision,
    )
    async def decide_server_offer_proposal(
        offer_id: Annotated[str, Field(min_length=1, max_length=200)],
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> ServerOfferReviewDecision:
        if principal.access_role is not AccessRole.COMPLETENESS_REVIEWER:
            raise HTTPException(status_code=403, detail="reviewer_required")
        payload = await _read_server_offer_review_body(request)
        try:
            decision = await service.decide_server_offer_proposal(
                company_id=principal.company_id,
                reviewer_id=principal.actor_id,
                offer_id=offer_id,
                proposal_sha256=payload.proposal_sha256,
                requirement_decisions=payload.requirement_decisions,
                bom_scope_assessment=payload.bom_scope_assessment,
                commercial_terms_assessment=payload.commercial_terms_assessment,
                reason=payload.reason,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    principal.actor_id,
                    offer_id,
                    "decide_server_offer_proposal",
                    canonical_json_sha256(payload),
                ),
            )
        except ServerOfferReviewNotFound as error:
            raise _not_found() from error
        except ServerOfferReviewConflict as error:
            raise HTTPException(status_code=409, detail="server_offer_review_conflict") from error
        except InvalidServerOfferReview as error:
            raise HTTPException(status_code=422, detail="invalid_server_offer_review") from error
        response.headers["Cache-Control"] = "no-store"
        return decision

    @app.get(
        "/v1/cases/{case_id}/versions/{version}/server-offer-economics",
        response_model=ServerOfferEconomicsRecord,
    )
    async def get_server_offer_economics(
        case_id: Annotated[str, Field(min_length=1, max_length=200)],
        version: Annotated[int, Field(ge=1)],
        offer_id: Annotated[str, Query(min_length=1, max_length=200)],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> ServerOfferEconomicsRecord:
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=403, detail="operator_required")
        try:
            record = await service.get_server_offer_economics(
                company_id=principal.company_id,
                case_id=case_id,
                case_version=version,
                offer_id=offer_id,
            )
        except InvalidServerOfferEconomics as error:
            raise HTTPException(status_code=422, detail="invalid_server_offer_economics") from error
        if record is None or record.evidence.case.company_id != principal.company_id:
            raise _not_found()
        response.headers["Cache-Control"] = "no-store"
        return record

    @app.post(
        "/v1/cases/{case_id}/versions/{version}/server-offer-economics",
        status_code=status.HTTP_201_CREATED,
        response_model=ServerOfferEconomicsPackage,
    )
    async def create_server_offer_economics(
        case_id: Annotated[str, Field(min_length=1, max_length=200)],
        version: Annotated[int, Field(ge=1)],
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> ServerOfferEconomicsPackage:
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=403, detail="operator_required")
        payload = await _read_server_offer_economics_body(request)
        try:
            package = await service.store_server_offer_economics(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                economics_id=str(uuid.uuid4()),
                case_id=case_id,
                case_version=version,
                offer_id=payload.offer_id,
                offer_proposal_sha256=payload.offer_proposal_sha256,
                offer_review_decision_sha256=payload.offer_review_decision_sha256,
                scenarios=payload.scenarios,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    principal.actor_id,
                    case_id,
                    str(version),
                    "store_server_offer_economics",
                    canonical_json_sha256(payload),
                ),
            )
        except ServerOfferEconomicsNotFound as error:
            raise _not_found() from error
        except ServerOfferEconomicsConflict as error:
            raise HTTPException(
                status_code=409, detail="server_offer_economics_conflict"
            ) from error
        except InvalidServerOfferEconomics as error:
            raise HTTPException(status_code=422, detail="invalid_server_offer_economics") from error
        response.headers["Cache-Control"] = "no-store"
        return package

    @app.post(
        "/v1/cases/{case_id}/versions/{version}/server-offer-economics/materialize",
        status_code=status.HTTP_201_CREATED,
        response_model=ProcurementCase,
    )
    async def materialize_server_offer_economics_case(
        case_id: Annotated[str, Field(min_length=1, max_length=200)],
        version: Annotated[int, Field(ge=1)],
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> ProcurementCase:
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=403, detail="operator_required")
        payload = await _read_server_offer_case_materialization_body(request)
        try:
            case = await service.materialize_case_from_server_offer_economics(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                case_id=case_id,
                case_version=version,
                offer_id=payload.offer_id,
                economics_id=payload.economics_id,
                package_sha256=payload.package_sha256,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    principal.actor_id,
                    case_id,
                    str(version),
                    "materialize_case_from_server_offer_economics",
                    canonical_json_sha256(payload),
                ),
            )
        except ServerOfferEconomicsNotFound as error:
            raise _not_found() from error
        except ServerOfferEconomicsConflict as error:
            raise HTTPException(status_code=409, detail="case_version_conflict") from error
        except InvalidServerOfferEconomics as error:
            raise HTTPException(status_code=422, detail="invalid_case_materialization") from error
        response.headers["Cache-Control"] = "no-store"
        return case

    @app.post(
        "/v1/cases/{case_id}/versions/{version}/hard-gate-assessments/materialize",
        status_code=status.HTTP_201_CREATED,
        response_model=ProcurementCase,
    )
    async def materialize_case_hard_gate_assessment(
        case_id: Annotated[str, Field(min_length=1, max_length=200)],
        version: Annotated[int, Field(ge=1)],
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> ProcurementCase:
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=403, detail="operator_required")
        payload = await _read_case_hard_gate_assessment_body(request)
        try:
            case = await service.materialize_case_hard_gate_assessment(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                case_id=case_id,
                case_version=version,
                source_case_input_sha256=payload.source_case_input_sha256,
                document_binding_id=payload.document_binding_id,
                manifest_evidence_sha256=payload.manifest_evidence_sha256,
                document_decision_sha256=payload.document_decision_sha256,
                decisions=payload.decisions,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    principal.actor_id,
                    case_id,
                    str(version),
                    "materialize_case_hard_gate_assessment",
                    canonical_json_sha256(payload),
                ),
            )
        except CaseHardGateAssessmentNotFound as error:
            raise _not_found() from error
        except CaseHardGateAssessmentConflict as error:
            raise HTTPException(status_code=409, detail="case_version_conflict") from error
        except InvalidCaseHardGateAssessment as error:
            raise HTTPException(status_code=422, detail="invalid_hard_gate_assessment") from error
        response.headers["Cache-Control"] = "no-store"
        return case

    @app.get(
        "/v1/cases/{case_id}/versions/{version}/hard-gate-assessments/evidence",
        response_model=CaseHardGateAssessmentEvidenceResponse,
    )
    async def get_case_hard_gate_assessment_evidence(
        case_id: Annotated[str, Field(min_length=1, max_length=200)],
        version: Annotated[int, Field(ge=1)],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> CaseHardGateAssessmentEvidenceResponse:
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=403, detail="operator_required")
        case = await service.get_case(
            company_id=principal.company_id,
            case_id=case_id,
            version=version,
        )
        if case is None or case.company_id != principal.company_id:
            raise _not_found()
        assessment = case.assessment
        if (
            assessment is None
            or assessment.input_digest != case_input_digest(case)
            or len(assessment.checks) != 1
            or assessment.checks[0].kind is not GateKind.TECHNICAL
            or assessment.checks[0].status is not GateStatus.PASS
        ):
            raise HTTPException(status_code=422, detail="invalid_hard_gate_source_case")
        response.headers["Cache-Control"] = "no-store"
        return CaseHardGateAssessmentEvidenceResponse(
            case=case,
            source_case_input_sha256=case_input_digest(case),
        )

    @app.post(
        "/v1/documents",
        status_code=status.HTTP_201_CREATED,
        response_model=DocumentRecord,
    )
    async def upload_document(
        file: Annotated[UploadFile, File()],
        document_role: Annotated[DocumentRole, Form()],
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> DocumentRecord:
        if principal.access_role is AccessRole.AUDITOR:
            raise HTTPException(status_code=403, detail="auditor_read_only")
        filename = file.filename or ""
        media_type = (file.content_type or "").strip().lower()
        if (
            not filename
            or len(filename) > 255
            or any(character in filename for character in ("/", "\\", "\x00"))
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": DocumentRejectionCode.FILENAME_INVALID.value},
            )
        content = await _read_upload(file)
        document_id = str(uuid.uuid4())
        try:
            extraction = await to_thread.run_sync(
                extract_document,
                DocumentInput(
                    document_id=document_id,
                    filename=filename,
                    declared_media_type=media_type,
                    content=content,
                ),
            )
        except DocumentRejected as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": error.code.value},
            ) from error
        if ExtractionReason.UNSUPPORTED_FORMAT in extraction.reasons:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail={"code": ExtractionReason.UNSUPPORTED_FORMAT.value},
            )
        content_sha256 = hashlib.sha256(content).hexdigest()
        try:
            return await service.store_document(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                document_id=document_id,
                original_filename=filename,
                media_type=media_type,
                document_role=document_role,
                content=content,
                extraction=extraction,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    filename,
                    media_type,
                    document_role.value,
                    content_sha256,
                ),
            )
        except VersionConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="version_conflict",
            ) from error

    @app.get("/v1/documents/{document_id}", response_model=DocumentRecord)
    async def get_document(
        document_id: Annotated[str, Field(min_length=1)],
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> DocumentRecord:
        document = await service.get_document(
            company_id=principal.company_id,
            document_id=document_id,
        )
        if document is None:
            raise _not_found()
        return document

    @app.post(
        "/v1/documents/{document_id}/completeness-reviews",
        status_code=status.HTTP_201_CREATED,
        response_model=CompletenessReviewRecord,
    )
    async def create_completeness_review(
        document_id: Annotated[str, Field(min_length=1, max_length=200)],
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> CompletenessReviewRecord:
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="operator_required")
        review_id = str(uuid.uuid4())
        try:
            return await service.store_completeness_review(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                review_id=review_id,
                source_document_id=document_id,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    principal.actor_id,
                    "store_document_completeness_review",
                    principal.company_id,
                    document_id,
                    "{}",
                ),
            )
        except CompletenessReviewNotFound as error:
            raise _not_found() from error
        except CompletenessReviewConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="completeness_review_conflict",
            ) from error
        except InvalidCompletenessReview as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_completeness_review_source",
            ) from error

    @app.get(
        "/v1/completeness-reviews",
        response_model=tuple[CompletenessReviewRecord, ...],
    )
    async def list_completeness_reviews(
        principal: Annotated[Principal, Depends(current_principal)],
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> tuple[CompletenessReviewRecord, ...]:
        records = await service.list_completeness_reviews(
            company_id=principal.company_id,
            limit=limit,
        )
        if any(record.snapshot.company_id != principal.company_id for record in records):
            raise RuntimeError("storage returned a completeness review for another tenant")
        return records

    @app.get(
        "/v1/completeness-reviews/{review_id}",
        response_model=CompletenessReviewRecord,
    )
    async def get_completeness_review(
        review_id: Annotated[str, Field(min_length=1, max_length=200)],
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> CompletenessReviewRecord:
        record = await service.get_completeness_review(
            company_id=principal.company_id,
            review_id=review_id,
        )
        if record is None:
            raise _not_found()
        if record.snapshot.company_id != principal.company_id:
            raise RuntimeError("storage returned a completeness review for another tenant")
        return record

    @app.post(
        "/v1/document-set-evidence-manifests",
        status_code=status.HTTP_201_CREATED,
        response_model=DocumentSetEvidenceManifest,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": DOCUMENT_SET_EVIDENCE_OPENAPI_SCHEMA}},
            }
        },
    )
    async def create_document_set_evidence_manifest(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> DocumentSetEvidenceManifest:
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="operator_required")
        payload = await _read_document_set_evidence_request(request)
        canonical_request = canonical_json_sha256(payload)
        try:
            manifest = await service.store_document_set_evidence_manifest(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                manifest_id=str(uuid.uuid4()),
                scope=payload.scope,
                review_refs=tuple(
                    (item.review_id, item.evidence_sha256) for item in payload.review_refs
                ),
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    principal.actor_id,
                    "store_document_set_evidence_manifest",
                    principal.company_id,
                    canonical_request,
                ),
            )
        except DocumentSetEvidenceNotFound as error:
            raise _not_found() from error
        except DocumentSetEvidenceConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="document_set_evidence_conflict",
            ) from error
        except InvalidDocumentSetEvidence as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_document_set_evidence",
            ) from error
        if manifest.company_id != principal.company_id:
            raise RuntimeError("storage returned document-set evidence for another tenant")
        response.headers["Cache-Control"] = "no-store"
        return manifest

    @app.get(
        "/v1/document-set-evidence-manifests/{manifest_id}",
        response_model=DocumentSetEvidenceManifest,
    )
    async def get_document_set_evidence_manifest(
        manifest_id: Annotated[str, Field(min_length=1, max_length=200)],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> DocumentSetEvidenceManifest:
        try:
            manifest = await service.get_document_set_evidence_manifest(
                company_id=principal.company_id,
                manifest_id=manifest_id,
            )
        except InvalidDocumentSetEvidence as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_document_set_evidence",
            ) from error
        if manifest is None:
            raise _not_found()
        if manifest.company_id != principal.company_id:
            raise RuntimeError("storage returned document-set evidence for another tenant")
        response.headers["Cache-Control"] = "no-store"
        return manifest

    @app.get(
        "/v1/document-sets/{manifest_id}/completeness-evidence",
        response_model=DocumentSetReviewEvidence,
    )
    async def get_document_set_review_evidence(
        manifest_id: Annotated[str, Field(min_length=1, max_length=200)],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> DocumentSetReviewEvidence:
        if principal.access_role is not AccessRole.COMPLETENESS_REVIEWER:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="reviewer_required")
        try:
            evidence = await service.get_document_set_review_evidence(
                company_id=principal.company_id,
                manifest_id=manifest_id,
            )
        except DocumentSetReviewNotFound as error:
            raise _not_found() from error
        except DocumentSetReviewSourceMismatch as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="document_set_review_source_mismatch",
            ) from error
        if evidence is None:
            raise _not_found()
        if evidence.manifest.company_id != principal.company_id:
            raise RuntimeError("storage returned document-set review evidence for another tenant")
        response.headers["Cache-Control"] = "no-store"
        return evidence

    @app.post(
        "/v1/document-sets/{manifest_id}/completeness-decisions",
        response_model=DocumentSetReviewDecision,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {"schema": DOCUMENT_SET_REVIEW_DECISION_OPENAPI_SCHEMA}
                },
            }
        },
    )
    async def create_document_set_review_decision(
        manifest_id: Annotated[str, Field(min_length=1, max_length=200)],
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> DocumentSetReviewDecision:
        if principal.access_role is not AccessRole.COMPLETENESS_REVIEWER:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="reviewer_required")
        payload = await _read_document_set_review_decision_request(request)
        canonical_request = canonical_json_sha256(payload)
        try:
            decision = await service.store_document_set_review_decision(
                company_id=principal.company_id,
                reviewer_id=principal.actor_id,
                manifest_id=manifest_id,
                manifest_evidence_sha256=payload.manifest_evidence_sha256,
                attestations=payload.attestations,
                inventory_assessment=payload.inventory_assessment,
                inventory_rationale=payload.inventory_rationale,
                cross_document_assessment=payload.cross_document_assessment,
                cross_document_rationale=payload.cross_document_rationale,
                reviewer_findings=payload.reviewer_findings,
                status=payload.status,
                reason=payload.reason,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    principal.actor_id,
                    "store_document_set_review_decision",
                    principal.company_id,
                    manifest_id,
                    canonical_request,
                ),
            )
        except DocumentSetReviewNotFound as error:
            raise _not_found() from error
        except (DocumentSetReviewConflict, DocumentSetReviewSourceMismatch) as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="document_set_review_conflict",
            ) from error
        except InvalidDocumentSetReview as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_document_set_review_decision",
            ) from error
        if decision.company_id != principal.company_id:
            raise RuntimeError("storage returned a document-set decision for another tenant")
        response.headers["Cache-Control"] = "no-store"
        return decision

    @app.get(
        "/v1/document-sets/{manifest_id}/completeness-decisions",
        response_model=DocumentSetReviewDecision,
    )
    async def get_document_set_review_decision(
        manifest_id: Annotated[str, Field(min_length=1, max_length=200)],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> DocumentSetReviewDecision:
        if principal.access_role is not AccessRole.COMPLETENESS_REVIEWER:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="reviewer_required")
        try:
            decision = await service.get_document_set_review_decision(
                company_id=principal.company_id,
                manifest_id=manifest_id,
            )
        except DocumentSetReviewNotFound as error:
            raise _not_found() from error
        except DocumentSetReviewSourceMismatch as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="document_set_review_source_mismatch",
            ) from error
        if decision is None:
            raise _not_found()
        if decision.company_id != principal.company_id:
            raise RuntimeError("storage returned a document-set decision for another tenant")
        response.headers["Cache-Control"] = "no-store"
        return decision

    @app.post(
        "/v1/case-document-evidence-bindings",
        status_code=status.HTTP_201_CREATED,
        response_model=CaseDocumentEvidenceBinding,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": CASE_EVIDENCE_BINDING_OPENAPI_SCHEMA}},
            }
        },
    )
    async def create_case_document_evidence_binding(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> CaseDocumentEvidenceBinding:
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="operator_required")
        payload = await _read_case_evidence_binding_request(request)
        canonical_request = canonical_json_sha256(payload)
        try:
            binding = await service.store_case_document_evidence_binding(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                binding_id=str(uuid.uuid4()),
                manifest_id=payload.manifest_id,
                manifest_evidence_sha256=payload.manifest_evidence_sha256,
                decision_sha256=payload.decision_sha256,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    principal.actor_id,
                    "store_case_document_evidence_binding",
                    principal.company_id,
                    canonical_request,
                ),
            )
        except CaseEvidenceNotFound as error:
            raise _not_found() from error
        except CaseEvidenceConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="case_evidence_conflict",
            ) from error
        except InvalidCaseEvidence as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_case_evidence",
            ) from error
        if binding.company_id != principal.company_id:
            raise RuntimeError("storage returned case evidence for another tenant")
        response.headers["Cache-Control"] = "no-store"
        return binding

    @app.get(
        "/v1/case-document-evidence-bindings/{binding_id}",
        response_model=CaseDocumentEvidenceBinding,
    )
    async def get_case_document_evidence_binding(
        binding_id: Annotated[str, Field(min_length=1, max_length=200)],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> CaseDocumentEvidenceBinding:
        try:
            binding = await service.get_case_document_evidence_binding(
                company_id=principal.company_id,
                binding_id=binding_id,
            )
        except InvalidCaseEvidence as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_case_evidence",
            ) from error
        if binding is None:
            raise _not_found()
        if binding.company_id != principal.company_id:
            raise RuntimeError("storage returned case evidence for another tenant")
        response.headers["Cache-Control"] = "no-store"
        return binding

    @app.post(
        "/v1/cases/from-evidence",
        status_code=status.HTTP_201_CREATED,
        response_model=ProcurementCase,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": CASE_FROM_EVIDENCE_OPENAPI_SCHEMA}},
            }
        },
    )
    async def create_case_from_evidence(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> ProcurementCase:
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="operator_required")
        payload = await _read_case_from_evidence_request(request)
        if payload.case.company_id != principal.company_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant_mismatch")
        canonical_request = canonical_json_sha256(payload)
        try:
            created = await service.create_case_from_evidence(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                case=payload.case,
                binding_id=payload.binding_id,
                manifest_evidence_sha256=payload.manifest_evidence_sha256,
                decision_sha256=payload.decision_sha256,
                other_checks=payload.other_checks,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    principal.actor_id,
                    "create_case_from_evidence",
                    principal.company_id,
                    canonical_request,
                ),
            )
        except CaseEvidenceNotFound as error:
            raise _not_found() from error
        except VersionConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="version_conflict",
            ) from error
        except InvalidCaseEvidence as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_case_evidence",
            ) from error
        if created.company_id != principal.company_id:
            raise RuntimeError("storage returned a case for a different tenant")
        response.headers["Cache-Control"] = "no-store"
        return created

    @app.post(
        "/v1/completeness-reviews/{review_id}/decision",
        response_model=CompletenessReviewRecord,
    )
    async def decide_completeness_review(
        review_id: Annotated[str, Field(min_length=1, max_length=200)],
        request: CompletenessReviewDecisionRequest,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> CompletenessReviewRecord:
        if principal.access_role is not AccessRole.COMPLETENESS_REVIEWER:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="reviewer_required")
        canonical_request = canonical_json_sha256(request)
        try:
            return await service.decide_completeness_review(
                company_id=principal.company_id,
                reviewer_id=principal.actor_id,
                review_id=review_id,
                evidence_sha256=request.evidence_sha256,
                status=request.status,
                scope=request.scope.strip(),
                reason=request.reason.strip(),
                block_decisions=request.block_decisions,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    principal.actor_id,
                    "decide_document_completeness_review",
                    principal.company_id,
                    review_id,
                    canonical_request,
                ),
            )
        except CompletenessReviewNotFound as error:
            raise _not_found() from error
        except CompletenessReviewConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="completeness_review_conflict",
            ) from error
        except InvalidCompletenessReview as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_completeness_review_decision",
            ) from error

    @app.post(
        "/v1/documents/{document_id}/ai-requirement-runs",
        status_code=status.HTTP_201_CREATED,
        response_model=AiRequirementReviewSummary,
    )
    async def import_ai_requirement_run(
        document_id: Annotated[str, Field(min_length=1, max_length=200)],
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> AiRequirementReviewSummary:
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="operator_required",
            )
        imported = await _read_ai_requirement_import(request)
        canonical_request = canonical_json_sha256(imported)
        try:
            record = await service.store_ai_requirement_run(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                source_document_id=document_id,
                report=imported.report,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    principal.actor_id,
                    "store_document_ai_requirement_run",
                    principal.company_id,
                    document_id,
                    canonical_request,
                ),
            )
        except AiRequirementRunNotFound as error:
            raise _not_found() from error
        except AiRequirementReviewConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="ai_requirement_run_import_conflict",
            ) from error
        except InvalidAiRequirementReview as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_ai_requirement_run_import",
            ) from error
        if record.snapshot.company_id != principal.company_id:
            raise RuntimeError("storage returned an AI requirement run for another tenant")
        response.headers["Cache-Control"] = "no-store"
        return _ai_requirement_summary(record)

    @app.get(
        "/v1/ai-requirement-runs",
        response_model=tuple[AiRequirementReviewSummary, ...],
    )
    async def list_ai_requirement_runs(
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> tuple[AiRequirementReviewSummary, ...]:
        if principal.access_role not in {
            AccessRole.OPERATOR,
            AccessRole.AI_REQUIREMENTS_REVIEWER,
        }:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="reviewer_required")
        records = await service.list_ai_requirement_runs(
            company_id=principal.company_id,
            limit=limit,
        )
        if any(record.snapshot.company_id != principal.company_id for record in records):
            raise RuntimeError("storage returned an AI requirement run for another tenant")
        response.headers["Cache-Control"] = "no-store"
        return tuple(_ai_requirement_summary(record) for record in records)

    @app.get(
        "/v1/ai-requirement-runs/{run_id}",
        response_model=AiRequirementReviewDetail,
    )
    async def get_ai_requirement_run(
        run_id: Annotated[str, Field(min_length=1, max_length=200)],
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> AiRequirementReviewDetail:
        if principal.access_role is not AccessRole.AI_REQUIREMENTS_REVIEWER:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="reviewer_required")
        record = await service.get_ai_requirement_run(
            company_id=principal.company_id,
            run_id=run_id,
        )
        if record is None:
            raise _not_found()
        if record.snapshot.company_id != principal.company_id:
            raise RuntimeError("storage returned an AI requirement run for another tenant")
        response.headers["Cache-Control"] = "no-store"
        return _ai_requirement_detail(record)

    @app.post(
        "/v1/ai-requirement-runs/{run_id}/decision",
        response_model=AiRequirementReviewDetail,
    )
    async def decide_ai_requirement_review(
        run_id: Annotated[str, Field(min_length=1, max_length=200)],
        request: AiRequirementReviewDecisionRequest,
        response: Response,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> AiRequirementReviewDetail:
        if principal.access_role is not AccessRole.AI_REQUIREMENTS_REVIEWER:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="reviewer_required")
        canonical_request = canonical_json_sha256(request)
        try:
            record = await service.decide_ai_requirement_review(
                company_id=principal.company_id,
                reviewer_id=principal.actor_id,
                run_id=run_id,
                evidence_sha256=request.evidence_sha256,
                candidate_decisions=request.candidate_decisions,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    principal.actor_id,
                    "decide_document_ai_requirement_review",
                    principal.company_id,
                    run_id,
                    canonical_request,
                ),
            )
        except AiRequirementRunNotFound as error:
            raise _not_found() from error
        except AiRequirementReviewConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="ai_requirement_review_conflict",
            ) from error
        except InvalidAiRequirementReview as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_ai_requirement_review",
            ) from error
        if record.snapshot.company_id != principal.company_id:
            raise RuntimeError("storage returned an AI requirement run for another tenant")
        response.headers["Cache-Control"] = "no-store"
        return _ai_requirement_detail(record)

    @app.post(
        "/v1/documents/{document_id}/search-indexes",
        status_code=status.HTTP_201_CREATED,
        response_model=DocumentSearchIndexRecord,
    )
    async def create_document_search_index(
        document_id: Annotated[str, Field(min_length=1)],
        request: DocumentSearchIndexRequest,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> DocumentSearchIndexRecord:
        if principal.access_role is AccessRole.AUDITOR:
            raise HTTPException(status_code=403, detail="auditor_read_only")
        document = await service.get_document(
            company_id=principal.company_id,
            document_id=document_id,
        )
        content = await service.get_document_content(
            company_id=principal.company_id,
            document_id=document_id,
        )
        if document is None or content is None:
            raise _not_found()
        if hashlib.sha256(content).hexdigest() != document.sha256:
            raise RuntimeError("stored document bytes do not match public metadata")
        try:
            entry = await to_thread.run_sync(
                partial(
                    build_document_search_entry,
                    DocumentInput(
                        document_id=document.document_id,
                        filename=document.original_filename,
                        declared_media_type=document.media_type,
                        content=content,
                    ),
                    document.extraction,
                    company_id=principal.company_id,
                    title=request.title,
                    vision_manifest=request.vision_manifest,
                )
            )
        except (DocumentRejected, DocxMediaRejected, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_search_evidence",
            ) from error
        search_index_id = str(uuid.uuid4())
        try:
            stored = await service.store_document_search_index(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                search_index_id=search_index_id,
                source_document_id=document_id,
                entry=entry,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    document.sha256,
                    request.model_dump_json(exclude_none=False),
                ),
            )
        except VersionConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="version_conflict",
            ) from error
        if (
            stored.source_document_id != document_id
            or stored.entry.company_id != principal.company_id
        ):
            raise RuntimeError("storage returned a search index for another tenant/document")
        return stored

    @app.get("/v1/document-search", response_model=DocumentSearchPage)
    async def search_indexed_documents(
        principal: Annotated[Principal, Depends(current_principal)],
        query: Annotated[str, Query(min_length=1, max_length=200)],
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        effective_at: Annotated[datetime | None, Query()] = None,
    ) -> DocumentSearchPage:
        at = effective_at or datetime.now(UTC)
        if at.utcoffset() is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="effective_at_requires_timezone",
            )
        try:
            page = await service.search_document_indexes(
                company_id=principal.company_id,
                query=query,
                limit=limit,
                effective_at=at,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="validation_error",
            ) from error
        if any(result.company_id != principal.company_id for result in page.results):
            raise RuntimeError("storage returned search results for another tenant")
        return page

    @app.post(
        "/v1/model-brand-source-artifacts",
        status_code=status.HTTP_201_CREATED,
        response_model=ModelBrandSourceArtifactRecord,
    )
    async def upload_model_brand_source_artifact(
        file: Annotated[UploadFile, File()],
        source_title: Annotated[str, Form(min_length=1, max_length=500)],
        source_url: Annotated[AnyHttpUrl, Form(max_length=2_048)],
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> ModelBrandSourceArtifactRecord:
        if principal.access_role is AccessRole.AUDITOR:
            raise HTTPException(status_code=403, detail="auditor_read_only")
        filename = file.filename or ""
        media_type = (file.content_type or "").strip().lower()
        if (
            not filename
            or len(filename) > 255
            or any(character in filename for character in ("/", "\\", "\x00"))
            or not filename.casefold().endswith(".pdf")
            or media_type != "application/pdf"
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_model_brand_source_artifact",
            )
        if source_url.scheme != "https" or not source_title.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_model_brand_source_artifact",
            )
        content = await _read_upload(file)
        if not content.startswith(b"%PDF-"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_model_brand_source_artifact",
            )
        retrieved_at = datetime.now(UTC)
        artifact_id = str(uuid.uuid4())
        try:
            stored = await service.store_model_brand_source_artifact(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                artifact_id=artifact_id,
                source_title=source_title.strip(),
                source_url=str(source_url),
                original_filename=filename,
                content=content,
                retrieved_at=retrieved_at,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    filename,
                    media_type,
                    source_title.strip(),
                    str(source_url),
                    hashlib.sha256(content).hexdigest(),
                ),
            )
        except VersionConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="version_conflict",
            ) from error
        return stored

    @app.get(
        "/v1/model-brand-source-artifacts/{artifact_id}",
        response_model=ModelBrandSourceArtifactRecord,
    )
    async def get_model_brand_source_artifact(
        artifact_id: Annotated[str, Field(min_length=1, max_length=200)],
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> ModelBrandSourceArtifactRecord:
        artifact = await service.get_model_brand_source_artifact(
            company_id=principal.company_id,
            artifact_id=artifact_id,
        )
        if artifact is None:
            raise _not_found()
        return artifact

    @app.post(
        "/v1/model-brand-reviews",
        status_code=status.HTTP_201_CREATED,
        response_model=ModelBrandReviewRecord,
    )
    async def create_model_brand_review(
        request: ModelBrandReviewProposalRequest,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> ModelBrandReviewRecord:
        if principal.access_role is AccessRole.AUDITOR:
            raise HTTPException(status_code=403, detail="auditor_read_only")
        proposal = ModelBrandReviewProposal(
            proposal_id=str(uuid.uuid4()),
            company_id=principal.company_id,
            submitted_by=principal.actor_id,
            submitted_at=datetime.now(UTC),
            catalog_id=request.catalog_id,
            approval_reference=request.approval_reference,
            entries=request.entries,
        )
        try:
            return await service.store_model_brand_review_proposal(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                proposal=proposal,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(request.model_dump_json(exclude_none=False)),
            )
        except ModelBrandReviewConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="review_conflict"
            ) from error
        except InvalidModelBrandEvidence as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_model_brand_source_evidence",
            ) from error

    @app.get("/v1/model-brand-reviews", response_model=tuple[ModelBrandReviewRecord, ...])
    async def list_model_brand_reviews(
        principal: Annotated[Principal, Depends(current_principal)],
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> tuple[ModelBrandReviewRecord, ...]:
        records = await service.list_model_brand_reviews(
            company_id=principal.company_id,
            limit=limit,
        )
        if any(record.proposal.company_id != principal.company_id for record in records):
            raise RuntimeError("storage returned a model-brand review for another tenant")
        return records

    @app.post(
        "/v1/model-brand-reviews/{proposal_id}/decision",
        response_model=ModelBrandReviewRecord,
    )
    async def decide_model_brand_review(
        proposal_id: Annotated[str, Field(min_length=1, max_length=200)],
        request: ModelBrandReviewDecisionRequest,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> ModelBrandReviewRecord:
        if principal.access_role is not AccessRole.MODEL_BRAND_REVIEWER:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="reviewer_required")
        try:
            return await service.decide_model_brand_review(
                company_id=principal.company_id,
                reviewer_id=principal.actor_id,
                proposal_id=proposal_id,
                decision=request.decision,
                reason=request.reason.strip(),
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    proposal_id,
                    request.model_dump_json(exclude_none=False),
                ),
            )
        except ModelBrandReviewNotFound as error:
            raise _not_found() from error
        except ModelBrandReviewConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="review_conflict"
            ) from error
        except InvalidModelBrandEvidence as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_model_brand_source_evidence",
            ) from error

    @app.get(
        "/v1/model-brand-catalogs/latest",
        response_model=ModelBrandCatalogRecord,
    )
    async def get_latest_model_brand_catalog(
        principal: Annotated[Principal, Depends(current_principal)],
        effective_at: Annotated[datetime | None, Query()] = None,
    ) -> ModelBrandCatalogRecord:
        at = effective_at or datetime.now(UTC)
        if at.utcoffset() is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="effective_at_requires_timezone",
            )
        catalog = await service.get_latest_model_brand_catalog(
            company_id=principal.company_id,
            effective_at=at,
        )
        if catalog is None:
            raise _not_found()
        if catalog.catalog.company_id != principal.company_id:
            raise RuntimeError("storage returned a model-brand catalog for another tenant")
        return catalog

    @app.post(
        "/v1/document-bundles",
        status_code=status.HTTP_201_CREATED,
        response_model=DocumentBundleRecord,
    )
    async def upload_document_bundle(
        file: Annotated[UploadFile, File()],
        document_role: Annotated[DocumentRole, Form()],
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> DocumentBundleRecord:
        if principal.access_role is AccessRole.AUDITOR:
            raise HTTPException(status_code=403, detail="auditor_read_only")
        filename = file.filename or ""
        media_type = (file.content_type or "").strip().lower()
        if (
            not filename
            or len(filename) > 255
            or any(character in filename for character in ("/", "\\", "\x00"))
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": BundleRejectionCode.FILENAME_INVALID.value},
            )
        content = await _read_upload(file)
        bundle_id = str(uuid.uuid4())
        try:
            result = await to_thread.run_sync(
                extract_document_bundle,
                DocumentInput(
                    document_id=bundle_id,
                    filename=filename,
                    declared_media_type=media_type,
                    content=content,
                ),
            )
        except DocumentBundleRejected as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": error.code.value},
            ) from error
        content_sha256 = hashlib.sha256(content).hexdigest()
        try:
            return await service.store_document_bundle(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                bundle_id=bundle_id,
                original_filename=filename,
                media_type=media_type,
                document_role=document_role,
                content=content,
                result=result,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    filename,
                    media_type,
                    document_role.value,
                    content_sha256,
                ),
            )
        except VersionConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="version_conflict",
            ) from error

    @app.get("/v1/document-bundles/{bundle_id}", response_model=DocumentBundleRecord)
    async def get_document_bundle(
        bundle_id: Annotated[str, Field(min_length=1)],
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> DocumentBundleRecord:
        bundle = await service.get_document_bundle(
            company_id=principal.company_id,
            bundle_id=bundle_id,
        )
        if bundle is None:
            raise _not_found()
        return bundle

    @app.post(
        "/v1/document-bundles/{bundle_id}/members/{member_index}/ocr",
        status_code=status.HTTP_201_CREATED,
        response_model=BundleMemberOcrRecord,
    )
    async def create_bundle_member_ocr(
        bundle_id: Annotated[str, Field(min_length=1)],
        member_index: Annotated[int, Field(ge=0)],
        request: OcrRequest,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> BundleMemberOcrRecord:
        if principal.access_role is AccessRole.AUDITOR:
            raise HTTPException(status_code=403, detail="auditor_read_only")
        bundle = await service.get_document_bundle(
            company_id=principal.company_id,
            bundle_id=bundle_id,
        )
        if bundle is None or member_index >= len(bundle.result.members):
            raise _not_found()
        member = bundle.result.members[member_index]
        if member.media_type != "application/pdf":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="ocr_source_unsupported",
            )
        if (
            member.extraction.status is not ExtractionStatus.UNKNOWN
            or ExtractionReason.OCR_REQUIRED not in member.extraction.reasons
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="ocr_not_required",
            )
        content = await service.get_document_bundle_content(
            company_id=principal.company_id,
            bundle_id=bundle_id,
        )
        if content is None:
            raise RuntimeError("stored bundle metadata has no matching source bytes")
        try:
            source_member = read_document_bundle_member(
                DocumentInput(
                    document_id=bundle.bundle_id,
                    filename=bundle.original_filename,
                    declared_media_type=bundle.media_type,
                    content=content,
                ),
                bundle.result,
                member_index,
            )
        except DocumentBundleMemberUnavailable as error:
            raise RuntimeError("stored bundle member evidence cannot be verified") from error
        source = OcrEngineInput(
            source_document_id=source_member.source_document_id,
            source_sha256=source_member.sha256,
            page_count=source_member.extraction.source_units_total,
        )
        try:
            candidates = await to_thread.run_sync(
                partial(
                    configured_ocr_runner.recognize,
                    source,
                    content=source_member.content,
                    media_type=source_member.media_type,
                )
            )
            derivative = build_ocr_derivative(
                source,
                source_member.extraction,
                _bundle_member_ocr_candidates(candidates, source_member.archive_path),
                engine=configured_ocr_runner.engine,
                threshold=request.threshold,
            )
        except OcrSourceRejected as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="ocr_source_unsupported",
            ) from error
        except OcrEngineError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="ocr_unavailable",
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="validation_error",
            ) from error
        ocr_id = str(uuid.uuid4())
        try:
            return await service.store_bundle_member_ocr_derivative(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                ocr_id=ocr_id,
                source_bundle_id=bundle.bundle_id,
                member_index=member_index,
                archive_path=source_member.archive_path,
                source_member_sha256=source_member.sha256,
                engine=configured_ocr_runner.engine,
                threshold=request.threshold,
                result=derivative,
                mean_confidence=derivative.mean_confidence,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    bundle.bundle_id,
                    str(member_index),
                    source_member.sha256,
                    configured_ocr_runner.engine,
                    str(request.threshold),
                ),
            )
        except VersionConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="version_conflict",
            ) from error

    @app.get(
        "/v1/document-bundles/{bundle_id}/members/{member_index}/ocr/latest",
        response_model=BundleMemberOcrRecord,
    )
    async def get_latest_bundle_member_ocr(
        bundle_id: Annotated[str, Field(min_length=1)],
        member_index: Annotated[int, Field(ge=0)],
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> BundleMemberOcrRecord:
        bundle = await service.get_document_bundle(
            company_id=principal.company_id,
            bundle_id=bundle_id,
        )
        if bundle is None or member_index >= len(bundle.result.members):
            raise _not_found()
        derivative = await service.get_latest_ocr_for_bundle_member(
            company_id=principal.company_id,
            source_bundle_id=bundle_id,
            member_index=member_index,
        )
        if derivative is None:
            raise _not_found()
        return derivative

    @app.get(
        "/v1/document-bundle-member-ocr/{ocr_id}",
        response_model=BundleMemberOcrRecord,
    )
    async def get_bundle_member_ocr_derivative(
        ocr_id: Annotated[str, Field(min_length=1)],
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> BundleMemberOcrRecord:
        derivative = await service.get_bundle_member_ocr_derivative(
            company_id=principal.company_id,
            ocr_id=ocr_id,
        )
        if derivative is None:
            raise _not_found()
        return derivative

    @app.post(
        "/v1/documents/{document_id}/media/{media_index}/ocr",
        status_code=status.HTTP_201_CREATED,
        response_model=DocxMediaOcrRecord,
    )
    async def create_docx_media_ocr(
        document_id: Annotated[str, Field(min_length=1)],
        media_index: Annotated[int, Field(ge=0)],
        request: OcrRequest,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> DocxMediaOcrRecord:
        if principal.access_role is AccessRole.AUDITOR:
            raise HTTPException(status_code=403, detail="auditor_read_only")
        document = await service.get_document(
            company_id=principal.company_id,
            document_id=document_id,
        )
        if document is None:
            raise _not_found()
        content = await service.get_document_content(
            company_id=principal.company_id,
            document_id=document_id,
        )
        if content is None:
            raise RuntimeError("stored document metadata has no matching source bytes")
        if hashlib.sha256(content).hexdigest() != document.sha256:
            raise RuntimeError("stored document bytes do not match immutable metadata")
        source_input = DocumentInput(
            document_id=document.document_id,
            filename=document.original_filename,
            declared_media_type=document.media_type,
            content=content,
        )
        try:
            media_extraction = await to_thread.run_sync(extract_docx_media, source_input)
        except DocxMediaRejected as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": error.code.value},
            ) from error
        if media_extraction.source_sha256 != document.sha256:
            raise RuntimeError("DOCX media extraction does not match immutable metadata")
        source_media = next(
            (item for item in media_extraction.media if item.media_index == media_index),
            None,
        )
        if source_media is None:
            raise _not_found()
        source = OcrEngineInput(
            source_document_id=source_media.source_media_id,
            source_sha256=source_media.sha256,
            page_count=1,
        )
        native_media = ExtractionResult(
            status=ExtractionStatus.UNKNOWN,
            reasons=(ExtractionReason.EMBEDDED_MEDIA_IGNORED,),
            source_units_total=1,
            source_units_extracted=0,
            characters_extracted=0,
        )
        try:
            candidates = await to_thread.run_sync(
                partial(
                    configured_ocr_runner.recognize,
                    source,
                    content=source_media.content,
                    media_type=source_media.media_type,
                )
            )
            derivative = build_ocr_derivative(
                source,
                native_media,
                _docx_media_ocr_candidates(candidates, source_media.archive_path),
                engine=configured_ocr_runner.engine,
                threshold=request.threshold,
            )
        except OcrSourceRejected as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="ocr_source_unsupported",
            ) from error
        except OcrEngineError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="ocr_unavailable",
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="validation_error",
            ) from error
        try:
            return await service.store_docx_media_ocr_derivative(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                ocr_id=str(uuid.uuid4()),
                source_document_id=document.document_id,
                media_index=source_media.media_index,
                archive_path=source_media.archive_path,
                source_document_sha256=document.sha256,
                source_media_sha256=source_media.sha256,
                media_type=source_media.media_type,
                engine=configured_ocr_runner.engine,
                threshold=request.threshold,
                result=derivative,
                mean_confidence=derivative.mean_confidence,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    document.document_id,
                    str(source_media.media_index),
                    document.sha256,
                    source_media.sha256,
                    configured_ocr_runner.engine,
                    str(request.threshold),
                ),
            )
        except VersionConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="version_conflict",
            ) from error

    @app.get(
        "/v1/documents/{document_id}/media/{media_index}/ocr/latest",
        response_model=DocxMediaOcrRecord,
    )
    async def get_latest_docx_media_ocr(
        document_id: Annotated[str, Field(min_length=1)],
        media_index: Annotated[int, Field(ge=0)],
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> DocxMediaOcrRecord:
        document = await service.get_document(
            company_id=principal.company_id,
            document_id=document_id,
        )
        if document is None:
            raise _not_found()
        derivative = await service.get_latest_ocr_for_docx_media(
            company_id=principal.company_id,
            source_document_id=document_id,
            media_index=media_index,
        )
        if derivative is None:
            raise _not_found()
        return derivative

    @app.get(
        "/v1/document-docx-media-ocr/{ocr_id}",
        response_model=DocxMediaOcrRecord,
    )
    async def get_docx_media_ocr_derivative(
        ocr_id: Annotated[str, Field(min_length=1)],
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> DocxMediaOcrRecord:
        derivative = await service.get_docx_media_ocr_derivative(
            company_id=principal.company_id,
            ocr_id=ocr_id,
        )
        if derivative is None:
            raise _not_found()
        return derivative

    @app.post(
        "/v1/documents/{document_id}/ocr",
        status_code=status.HTTP_201_CREATED,
        response_model=OcrDerivativeRecord,
    )
    async def create_ocr_derivative(
        document_id: Annotated[str, Field(min_length=1)],
        request: OcrRequest,
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> OcrDerivativeRecord:
        if principal.access_role is AccessRole.AUDITOR:
            raise HTTPException(status_code=403, detail="auditor_read_only")
        document = await service.get_document(
            company_id=principal.company_id,
            document_id=document_id,
        )
        if document is None:
            raise _not_found()
        source = OcrEngineInput(
            source_document_id=document.document_id,
            source_sha256=document.sha256,
            page_count=document.extraction.source_units_total,
        )
        content = await service.get_document_content(
            company_id=principal.company_id,
            document_id=document.document_id,
        )
        if content is None:
            raise RuntimeError("stored document metadata has no matching source bytes")
        try:
            candidates = await to_thread.run_sync(
                partial(
                    configured_ocr_runner.recognize,
                    source,
                    content=content,
                    media_type=document.media_type,
                )
            )
            derivative = build_ocr_derivative(
                source,
                document.extraction,
                candidates,
                engine=configured_ocr_runner.engine,
                threshold=request.threshold,
            )
        except OcrSourceRejected as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="ocr_source_unsupported",
            ) from error
        except OcrEngineError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="ocr_unavailable",
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="validation_error",
            ) from error
        ocr_id = str(uuid.uuid4())
        try:
            return await service.store_ocr_derivative(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                ocr_id=ocr_id,
                source_document_id=document.document_id,
                engine=configured_ocr_runner.engine,
                threshold=request.threshold,
                result=derivative,
                mean_confidence=derivative.mean_confidence,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    document.document_id,
                    configured_ocr_runner.engine,
                    str(request.threshold),
                    document.sha256,
                ),
            )
        except VersionConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="version_conflict",
            ) from error

    @app.get(
        "/v1/documents/{document_id}/ocr/latest",
        response_model=OcrDerivativeRecord,
    )
    async def get_latest_ocr(
        document_id: Annotated[str, Field(min_length=1)],
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> OcrDerivativeRecord:
        document = await service.get_document(
            company_id=principal.company_id,
            document_id=document_id,
        )
        if document is None:
            raise _not_found()
        derivative = await service.get_latest_ocr_for_document(
            company_id=principal.company_id,
            source_document_id=document_id,
        )
        if derivative is None:
            raise _not_found()
        return derivative

    @app.get("/v1/document-ocr/{ocr_id}", response_model=OcrDerivativeRecord)
    async def get_ocr_derivative(
        ocr_id: Annotated[str, Field(min_length=1)],
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> OcrDerivativeRecord:
        derivative = await service.get_ocr_derivative(
            company_id=principal.company_id,
            ocr_id=ocr_id,
        )
        if derivative is None:
            raise _not_found()
        return derivative

    @app.post(
        "/v1/cases/{case_id}/versions/{version}/evaluations",
        status_code=status.HTTP_201_CREATED,
        response_model=EvaluationRecord,
    )
    async def evaluate(
        request: EvaluationRequest,
        case_id: Annotated[str, Field(min_length=1)],
        version: Annotated[int, Field(ge=1)],
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> EvaluationRecord:
        if principal.access_role is AccessRole.AUDITOR:
            raise HTTPException(status_code=403, detail="auditor_read_only")
        case = await service.get_case(
            company_id=principal.company_id,
            case_id=case_id,
            version=version,
        )
        if case is None or case.company_id != principal.company_id:
            raise _not_found()
        recommendation = evaluate_case(case, at=request.effective_at)
        try:
            return await service.record_evaluation(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                case_id=case.case_id,
                version=case.version,
                effective_at=request.effective_at,
                recommendation=recommendation,
                engine_version=ENGINE_VERSION,
                input_digest=case_input_digest(case),
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    case.case_id,
                    str(case.version),
                    request.effective_at.isoformat(),
                ),
            )
        except VersionConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="version_conflict",
            ) from error

    @app.get(
        "/v1/cases/{case_id}/versions/{version}/evaluations/latest",
        response_model=EvaluationRecord,
    )
    async def get_latest_evaluation(
        case_id: Annotated[str, Field(min_length=1)],
        version: Annotated[int, Field(ge=1)],
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> EvaluationRecord:
        evaluation = await service.get_latest_evaluation(
            company_id=principal.company_id,
            case_id=case_id,
            version=version,
        )
        if evaluation is None:
            raise _not_found()
        return evaluation

    @app.get(
        "/v1/evaluations/{evaluation_id}/participation-decision",
        response_model=ParticipationDecisionRecord,
    )
    async def get_participation_decision(
        evaluation_id: Annotated[str, Field(min_length=1, max_length=200)],
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> ParticipationDecisionRecord:
        if principal.access_role not in {
            AccessRole.PARTICIPATION_APPROVER,
            AccessRole.AUDITOR,
        }:
            raise HTTPException(status_code=403, detail="participation_reviewer_required")
        try:
            record = await service.get_participation_decision(
                company_id=principal.company_id,
                evaluation_id=evaluation_id,
            )
        except InvalidParticipationDecision as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_participation_evidence",
            ) from error
        if record is None:
            raise _not_found()
        return record

    @app.post(
        "/v1/evaluations/{evaluation_id}/participation-decision",
        status_code=status.HTTP_201_CREATED,
        response_model=ParticipationDecision,
    )
    async def decide_participation(
        request: ParticipationDecisionRequest,
        evaluation_id: Annotated[str, Field(min_length=1, max_length=200)],
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> ParticipationDecision:
        if principal.access_role is not AccessRole.PARTICIPATION_APPROVER:
            raise HTTPException(status_code=403, detail="participation_approver_required")
        try:
            return await service.decide_participation(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                evaluation_id=evaluation_id,
                evaluation_evidence_sha256=request.evaluation_evidence_sha256,
                status=request.status,
                reason=request.reason,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    evaluation_id,
                    request.evaluation_evidence_sha256,
                    request.status.value,
                    request.reason,
                ),
            )
        except ParticipationDecisionConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="participation_decision_conflict",
            ) from error
        except ParticipationDecisionNotFound as error:
            raise _not_found() from error
        except InvalidParticipationDecision as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_participation_decision",
            ) from error

    @app.get(
        "/v1/participation-decisions/{decision_id}/application-package",
        response_model=ApplicationPackageRecord,
    )
    async def get_application_package(
        decision_id: Annotated[str, Field(min_length=1, max_length=200)],
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> ApplicationPackageRecord:
        if principal.access_role not in {AccessRole.OPERATOR, AccessRole.AUDITOR}:
            raise HTTPException(status_code=403, detail="application_operator_required")
        try:
            record = await service.get_application_package(
                company_id=principal.company_id,
                participation_decision_id=decision_id,
            )
        except InvalidApplicationPackage as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_application_package_evidence",
            ) from error
        if record is None:
            raise _not_found()
        return record

    @app.post(
        "/v1/participation-decisions/{decision_id}/application-package",
        status_code=status.HTTP_201_CREATED,
        response_model=ApplicationPackage,
    )
    async def store_application_package(
        request: ApplicationPackageRequest,
        decision_id: Annotated[str, Field(min_length=1, max_length=200)],
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> ApplicationPackage:
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=403, detail="application_operator_required")
        try:
            return await service.store_application_package(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                package_id=str(uuid.uuid4()),
                participation_decision_id=decision_id,
                participation_decision_sha256=(request.participation_decision_sha256),
                proposed_price_ex_vat=request.proposed_price_ex_vat,
                requirements=request.requirements,
                attachments=request.attachments,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    decision_id,
                    canonical_json_sha256(request.model_dump(mode="json")),
                ),
            )
        except ApplicationPackageConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="application_package_conflict",
            ) from error
        except ApplicationPackageNotFound as error:
            raise _not_found() from error
        except InvalidApplicationPackage as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_application_package",
            ) from error

    @app.get(
        "/v1/application-packages/{package_id}/review",
        response_model=ApplicationReviewRecord,
    )
    async def get_application_review(
        package_id: Annotated[str, Field(min_length=1, max_length=200)],
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> ApplicationReviewRecord:
        if principal.access_role not in {
            AccessRole.APPLICATION_REVIEWER,
            AccessRole.AUDITOR,
        }:
            raise HTTPException(status_code=403, detail="application_reviewer_required")
        try:
            record = await service.get_application_review(
                company_id=principal.company_id, package_id=package_id
            )
        except InvalidApplicationReview as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_application_review_evidence",
            ) from error
        if record is None:
            raise _not_found()
        return record

    @app.get("/v1/application-packages/{package_id}/review/documents/{document_id}/content")
    async def get_application_review_document_content(
        package_id: Annotated[str, Field(min_length=1, max_length=200)],
        document_id: Annotated[str, Field(min_length=1, max_length=200)],
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Response:
        if principal.access_role not in {
            AccessRole.APPLICATION_REVIEWER,
            AccessRole.AUDITOR,
        }:
            raise HTTPException(status_code=403, detail="application_reviewer_required")
        try:
            record = await service.get_application_review(
                company_id=principal.company_id, package_id=package_id
            )
        except InvalidApplicationReview as error:
            raise HTTPException(
                status_code=422, detail="invalid_application_review_evidence"
            ) from error
        if record is None or record.evidence.package is None:
            raise _not_found()
        package = record.evidence.package
        sources = {
            item.source_document_id: (item.source_document_sha256, DocumentRole.TENDER_REQUIREMENTS)
            for item in package.requirements
        }
        attachments = {
            item.document_id: (item.document_sha256, DocumentRole.APPLICATION_ATTACHMENT)
            for item in package.attachments
        }
        allowed = sources | attachments
        if document_id not in allowed:
            raise _not_found()
        document = await service.get_document(
            company_id=principal.company_id, document_id=document_id
        )
        content = await service.get_document_content(
            company_id=principal.company_id, document_id=document_id
        )
        if document is None or content is None:
            raise _not_found()
        expected_sha, expected_role = allowed[document_id]
        if (
            document.sha256 != expected_sha
            or document.document_role is not expected_role
            or hashlib.sha256(content).hexdigest() != expected_sha
        ):
            raise HTTPException(status_code=422, detail="invalid_application_document")
        return Response(
            content=content,
            media_type=document.media_type,
            headers={
                "Content-Disposition": (
                    "attachment; filename*=UTF-8''" + quote(document.original_filename)
                ),
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.post(
        "/v1/application-packages/{package_id}/review",
        status_code=status.HTTP_201_CREATED,
        response_model=ApplicationReviewDecision,
    )
    async def decide_application_review(
        request: ApplicationReviewRequest,
        package_id: Annotated[str, Field(min_length=1, max_length=200)],
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> ApplicationReviewDecision:
        if principal.access_role is not AccessRole.APPLICATION_REVIEWER:
            raise HTTPException(status_code=403, detail="application_reviewer_required")
        try:
            return await service.decide_application_review(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                package_id=package_id,
                package_sha256=request.package_sha256,
                requirement_reviews=request.requirement_reviews,
                attachment_reviews=request.attachment_reviews,
                inventory_assessment=request.inventory_assessment,
                inventory_source_document_ids=request.inventory_source_document_ids,
                inventory_reason=request.inventory_reason,
                price_assessment=request.price_assessment,
                price_reason=request.price_reason,
                reason=request.reason,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    package_id,
                    canonical_json_sha256(request.model_dump(mode="json")),
                ),
            )
        except ApplicationReviewConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="application_review_conflict",
            ) from error
        except ApplicationReviewNotFound as error:
            raise _not_found() from error
        except InvalidApplicationReview as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="invalid_application_review",
            ) from error

    @app.get(
        "/v1/application-packages/{package_id}/submission",
        response_model=ApplicationSubmissionRecord,
    )
    async def get_application_submission(
        package_id: Annotated[str, Field(min_length=1, max_length=200)],
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> ApplicationSubmissionRecord:
        if principal.access_role not in {
            AccessRole.OPERATOR,
            AccessRole.APPLICATION_SUBMISSION_APPROVER,
            AccessRole.AUDITOR,
        }:
            raise HTTPException(status_code=403, detail="application_submission_role_required")
        try:
            record = await service.get_application_submission(
                company_id=principal.company_id, package_id=package_id
            )
        except InvalidApplicationSubmission as error:
            raise HTTPException(
                status_code=422, detail="invalid_application_submission_evidence"
            ) from error
        if record is None:
            raise _not_found()
        return record

    @app.post(
        "/v1/application-packages/{package_id}/submission",
        status_code=status.HTTP_201_CREATED,
        response_model=ApplicationSubmissionIntent,
    )
    async def prepare_application_submission(
        request: ApplicationSubmissionPrepareRequest,
        package_id: Annotated[str, Field(min_length=1, max_length=200)],
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> ApplicationSubmissionIntent:
        if principal.access_role is not AccessRole.OPERATOR:
            raise HTTPException(status_code=403, detail="operator_required")
        try:
            return await service.prepare_application_submission(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                package_id=package_id,
                package_sha256=request.package_sha256,
                review_decision_sha256=request.review_decision_sha256,
                destination=request.destination,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    package_id,
                    principal.actor_id,
                    canonical_json_sha256(request.model_dump(mode="json")),
                ),
            )
        except ApplicationSubmissionConflict as error:
            raise HTTPException(
                status_code=409, detail="application_submission_conflict"
            ) from error
        except ApplicationSubmissionNotFound as error:
            raise _not_found() from error
        except InvalidApplicationSubmission as error:
            raise HTTPException(status_code=422, detail="invalid_application_submission") from error

    @app.post(
        "/v1/application-packages/{package_id}/submission/approval",
        status_code=status.HTTP_201_CREATED,
        response_model=ApplicationSubmissionApproval,
    )
    async def decide_application_submission(
        request: ApplicationSubmissionDecisionRequest,
        package_id: Annotated[str, Field(min_length=1, max_length=200)],
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> ApplicationSubmissionApproval:
        if principal.access_role is not AccessRole.APPLICATION_SUBMISSION_APPROVER:
            raise HTTPException(status_code=403, detail="application_submission_approver_required")
        try:
            record = await service.get_application_submission(
                company_id=principal.company_id, package_id=package_id
            )
            if (
                record is None
                or record.intent is None
                or record.intent.request.action_id != request.action_id
            ):
                raise _not_found()
            return await service.decide_application_submission(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                action_id=request.action_id,
                payload_sha256=request.payload_sha256,
                status=request.status,
                reason=request.reason,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    package_id,
                    principal.actor_id,
                    canonical_json_sha256(request.model_dump(mode="json")),
                ),
            )
        except ApplicationSubmissionConflict as error:
            raise HTTPException(
                status_code=409, detail="application_submission_conflict"
            ) from error
        except ApplicationSubmissionNotFound as error:
            raise _not_found() from error
        except InvalidApplicationSubmission as error:
            raise HTTPException(status_code=422, detail="invalid_application_submission") from error

    @app.get(
        "/v1/application-packages/{package_id}/submission/admission",
        response_model=ApplicationSubmissionExecutionRecord,
    )
    async def get_application_submission_admission(
        package_id: Annotated[str, Field(min_length=1, max_length=200)],
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> ApplicationSubmissionExecutionRecord:
        if principal.access_role not in {
            AccessRole.APPLICATION_SUBMISSION_EXECUTOR,
            AccessRole.AUDITOR,
        }:
            raise HTTPException(status_code=403, detail="application_executor_required")
        try:
            record = await service.get_application_submission_execution(
                company_id=principal.company_id, package_id=package_id
            )
        except InvalidApplicationSubmission as error:
            raise HTTPException(
                status_code=422, detail="invalid_application_admission_evidence"
            ) from error
        if record is None:
            raise _not_found()
        return record

    @app.get("/v1/application-packages/{package_id}/submission/handoff")
    async def download_application_handoff(
        package_id: Annotated[str, Field(min_length=1, max_length=200)],
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Response:
        if principal.access_role is not AccessRole.APPLICATION_SUBMISSION_EXECUTOR:
            raise HTTPException(status_code=403, detail="application_executor_required")
        try:
            execution = await service.get_application_submission_execution(
                company_id=principal.company_id, package_id=package_id
            )
        except InvalidApplicationSubmission as error:
            raise HTTPException(
                status_code=422, detail="invalid_application_submission_evidence"
            ) from error
        if execution is None or execution.submission.evidence.evidence.package is None:
            raise _not_found()
        if execution.admission is not None:
            raise HTTPException(status_code=409, detail="application_already_admitted")
        submission = execution.submission
        package = submission.evidence.evidence.package
        assert package is not None
        originals: dict[str, bytes] = {}
        total_bytes = 0
        for item in package.attachments:
            document = await service.get_document(
                company_id=principal.company_id, document_id=item.document_id
            )
            content = await service.get_document_content(
                company_id=principal.company_id, document_id=item.document_id
            )
            if document is None or content is None:
                raise _not_found()
            if (
                document.document_role is not DocumentRole.APPLICATION_ATTACHMENT
                or document.sha256 != item.document_sha256
                or document.media_type != item.media_type
                or document.byte_size != len(content)
            ):
                raise HTTPException(status_code=422, detail="invalid_application_handoff_document")
            total_bytes += len(content)
            if total_bytes > MAX_HANDOFF_BYTES:
                raise HTTPException(status_code=413, detail="application_handoff_too_large")
            originals[item.document_id] = content
        try:
            manifest, content = build_application_handoff(
                submission, attachment_bytes=originals, at=datetime.now(UTC)
            )
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail="invalid_application_handoff") from error
        return Response(
            content=content,
            media_type="application/zip",
            headers={
                "Content-Disposition": "attachment; filename*=UTF-8''application-handoff.zip",
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Manifest-SHA256": manifest.manifest_sha256,
            },
        )

    @app.post(
        "/v1/application-packages/{package_id}/submission/admission",
        status_code=status.HTTP_201_CREATED,
        response_model=ApplicationSubmissionAdmission,
    )
    async def claim_application_submission(
        request: ApplicationSubmissionClaimRequest,
        package_id: Annotated[str, Field(min_length=1, max_length=200)],
        principal: Annotated[Principal, Depends(current_principal)],
        idempotency_key: Annotated[str, Depends(_idempotency_key)],
    ) -> ApplicationSubmissionAdmission:
        if principal.access_role is not AccessRole.APPLICATION_SUBMISSION_EXECUTOR:
            raise HTTPException(status_code=403, detail="application_executor_required")
        try:
            return await service.claim_application_submission(
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                package_id=package_id,
                action_id=request.action_id,
                payload_sha256=request.payload_sha256,
                approval_decision_sha256=request.approval_decision_sha256,
                idempotency_key=idempotency_key,
                request_digest=_request_digest(
                    package_id,
                    principal.actor_id,
                    canonical_json_sha256(request.model_dump(mode="json")),
                ),
            )
        except ApplicationSubmissionConflict as error:
            raise HTTPException(status_code=409, detail="application_admission_conflict") from error
        except ApplicationSubmissionNotFound as error:
            raise _not_found() from error
        except InvalidApplicationSubmission as error:
            raise HTTPException(status_code=422, detail="invalid_application_admission") from error

    return app
