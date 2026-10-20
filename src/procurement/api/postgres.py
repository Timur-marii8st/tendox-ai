"""PostgreSQL adapters for the asynchronous HTTP contracts."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from functools import partial

from anyio import to_thread

from procurement.access import AccessRole
from procurement.api.contracts import (
    AiRequirementReviewConflict as ApiAiRequirementReviewConflict,
)
from procurement.api.contracts import (
    AiRequirementRunNotFound as ApiAiRequirementRunNotFound,
)
from procurement.api.contracts import AiTransferConflict as ApiAiTransferConflict
from procurement.api.contracts import (
    AiTransferDetail,
    AiTransferExecutionDetail,
    AiTransferRequirementBatchMaterializationDetail,
    BundleMemberOcrRecord,
    CasePage,
    DocumentBundleRecord,
    DocumentRecord,
    DocumentSearchIndexRecord,
    DocumentSearchPage,
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
    ModelBrandReviewDecisionRecord,
    ModelBrandReviewRecord,
    ModelBrandSourceArtifactRecord,
    OcrDerivativeRecord,
    Principal,
    VersionConflict,
)
from procurement.api.contracts import AiTransferNotFound as ApiAiTransferNotFound
from procurement.api.contracts import (
    ApplicationPackageConflict as ApiApplicationPackageConflict,
)
from procurement.api.contracts import (
    ApplicationPackageNotFound as ApiApplicationPackageNotFound,
)
from procurement.api.contracts import (
    ApplicationReviewConflict as ApiApplicationReviewConflict,
)
from procurement.api.contracts import (
    ApplicationReviewNotFound as ApiApplicationReviewNotFound,
)
from procurement.api.contracts import (
    ApplicationSubmissionConflict as ApiApplicationSubmissionConflict,
)
from procurement.api.contracts import (
    ApplicationSubmissionNotFound as ApiApplicationSubmissionNotFound,
)
from procurement.api.contracts import (
    CaseEvidenceConflict as ApiCaseEvidenceConflict,
)
from procurement.api.contracts import (
    CaseEvidenceNotFound as ApiCaseEvidenceNotFound,
)
from procurement.api.contracts import (
    CaseHardGateAssessmentConflict as ApiCaseHardGateAssessmentConflict,
)
from procurement.api.contracts import (
    CaseHardGateAssessmentNotFound as ApiCaseHardGateAssessmentNotFound,
)
from procurement.api.contracts import (
    CompletenessReviewConflict as ApiCompletenessReviewConflict,
)
from procurement.api.contracts import (
    CompletenessReviewNotFound as ApiCompletenessReviewNotFound,
)
from procurement.api.contracts import (
    DocumentSetEvidenceConflict as ApiDocumentSetEvidenceConflict,
)
from procurement.api.contracts import (
    DocumentSetEvidenceNotFound as ApiDocumentSetEvidenceNotFound,
)
from procurement.api.contracts import (
    DocumentSetReviewConflict as ApiDocumentSetReviewConflict,
)
from procurement.api.contracts import (
    DocumentSetReviewNotFound as ApiDocumentSetReviewNotFound,
)
from procurement.api.contracts import (
    DocumentSetReviewSourceMismatch as ApiDocumentSetReviewSourceMismatch,
)
from procurement.api.contracts import (
    ModelBrandReviewConflict as ApiModelBrandReviewConflict,
)
from procurement.api.contracts import (
    ModelBrandReviewNotFound as ApiModelBrandReviewNotFound,
)
from procurement.api.contracts import (
    ParticipationDecisionConflict as ApiParticipationDecisionConflict,
)
from procurement.api.contracts import (
    ParticipationDecisionNotFound as ApiParticipationDecisionNotFound,
)
from procurement.api.contracts import (
    RequirementSetConflict as ApiRequirementSetConflict,
)
from procurement.api.contracts import (
    RequirementSetNotFound as ApiRequirementSetNotFound,
)
from procurement.api.contracts import ServerOfferConflict as ApiServerOfferConflict
from procurement.api.contracts import (
    ServerOfferEconomicsConflict as ApiServerOfferEconomicsConflict,
)
from procurement.api.contracts import (
    ServerOfferEconomicsNotFound as ApiServerOfferEconomicsNotFound,
)
from procurement.api.contracts import ServerOfferNotFound as ApiServerOfferNotFound
from procurement.api.contracts import (
    ServerOfferReviewConflict as ApiServerOfferReviewConflict,
)
from procurement.api.contracts import (
    ServerOfferReviewNotFound as ApiServerOfferReviewNotFound,
)
from procurement.documents import (
    AiRequirementAnalysisReport,
    AiRequirementAnalysisReportV2,
    AiRequirementCandidateDecision,
    AiRequirementReviewRecord,
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
    DocumentSetCrossAssessment,
    DocumentSetEvidenceManifest,
    DocumentSetFinding,
    DocumentSetInventoryAssessment,
    DocumentSetMemberAttestation,
    DocumentSetReviewDecision,
    DocumentSetReviewEvidence,
    ExecutableRequirementSelection,
    ExtractionResult,
    ModelBrandReviewProposal,
    ModelBrandReviewStatus,
    ParticipationDecision,
    ParticipationDecisionRecord,
    ParticipationDecisionStatus,
    RequirementSetCoverageAssessment,
    RequirementSetMaterializationError,
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
    build_requirement_set_materialization_preview,
    materialize_reviewed_requirement_entries,
    search_documents,
)
from procurement.documents.ai_transfer import (
    PersistedAiTransferApproval,
    PersistedAiTransferRequest,
)
from procurement.documents.ai_transfer_execution import AiTransferExecutionAdmission
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
from procurement.documents.ocr import OcrDerivative
from procurement.domain.cases import GateCheck, ProcurementCase
from procurement.domain.compliance import Verdict
from procurement.domain.decisions import Recommendation
from procurement.domain.requirements import Requirement
from procurement.domain.sourcing import (
    ServerShortlist,
    SourcingRunRecord,
    SourcingRunStatus,
    SourcingSourceSnapshot,
    SourcingSourceStatus,
    shortlist_server_leads,
)
from procurement.sources.catalog_search import fetch_server_catalog_sources
from procurement.storage import (
    AiRequirementReviewConflict as StorageAiRequirementReviewConflict,
)
from procurement.storage import (
    AiRequirementRunNotFound as StorageAiRequirementRunNotFound,
)
from procurement.storage import (
    AiRequirementRunSourceMismatch,
    AiTransferConflict,
    AiTransferNotFound,
    AiTransferSourceMismatch,
    ApplicationPackageConflict,
    ApplicationPackageNotFound,
    ApplicationPackageSourceMismatch,
    ApplicationReviewConflict,
    ApplicationReviewNotFound,
    ApplicationReviewSourceMismatch,
    BundleMemberOcrConflict,
    CaseEvidenceConflict,
    CaseEvidenceNotFound,
    CaseEvidenceSourceMismatch,
    CaseHardGateAssessmentConflict,
    CaseHardGateAssessmentNotFound,
    CaseHardGateAssessmentSourceMismatch,
    CaseVersionConflict,
    CompletenessReviewConflict,
    CompletenessReviewNotFound,
    CompletenessReviewSourceMismatch,
    DocumentBundleConflict,
    DocumentConflict,
    DocumentSearchIndexConflict,
    DocumentSetEvidenceConflict,
    DocumentSetEvidenceNotFound,
    DocumentSetEvidenceSourceMismatch,
    DocumentSetReviewConflict,
    DocumentSetReviewNotFound,
    DocumentSetReviewSourceMismatch,
    DocxMediaOcrConflict,
    IdempotencyConflict,
    ModelBrandReviewConflict,
    ModelBrandReviewNotFound,
    ModelBrandSourceArtifactConflict,
    ModelBrandSourceEvidenceMismatch,
    OcrDerivativeConflict,
    ParticipationDecisionConflict,
    ParticipationDecisionNotFound,
    ParticipationDecisionSourceMismatch,
    PostgresStorage,
    RequirementSetConflict,
    RequirementSetNotFound,
    RequirementSetSourceMismatch,
    ServerOfferConflict,
    ServerOfferEconomicsConflict,
    ServerOfferEconomicsNotFound,
    ServerOfferEconomicsSourceMismatch,
    ServerOfferNotFound,
    ServerOfferReviewConflict,
    ServerOfferReviewNotFound,
    ServerOfferReviewSourceMismatch,
    ServerOfferSourceMismatch,
)
from procurement.storage.repository import (
    ApplicationSubmissionConflict,
    ApplicationSubmissionNotFound,
    ApplicationSubmissionSourceMismatch,
)


class PostgresAuthenticator:
    """Resolve a bearer secret without accepting a caller-selected tenant."""

    def __init__(self, storage: PostgresStorage) -> None:
        self._storage = storage

    async def authenticate(self, credential: str) -> Principal | None:
        stored = await to_thread.run_sync(self._storage.authenticate_api_key, credential)
        if stored is None:
            return None
        return Principal(
            company_id=stored.company_id,
            actor_id=stored.actor_id,
            access_role=stored.access_role,
        )


class PostgresCaseService:
    """Keep blocking SQLAlchemy work outside the FastAPI event loop."""

    def __init__(self, storage: PostgresStorage) -> None:
        self._storage = storage

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
        try:
            return await to_thread.run_sync(
                self._storage.store_ai_transfer_request,
                company_id,
                actor_id,
                source_document_id,
                model,
                idempotency_key,
                request_digest,
            )
        except (AiTransferConflict, IdempotencyConflict) as error:
            raise ApiAiTransferConflict from error
        except AiTransferNotFound as error:
            raise ApiAiTransferNotFound from error
        except AiTransferSourceMismatch as error:
            raise InvalidAiTransfer from error

    async def get_ai_transfer_request(
        self,
        *,
        company_id: str,
        transfer_id: str,
    ) -> AiTransferDetail | None:
        try:
            record = await to_thread.run_sync(
                self._storage.get_ai_transfer_request, company_id, transfer_id
            )
            return (
                None if record is None else AiTransferDetail(request=record[0], approval=record[1])
            )
        except AiTransferSourceMismatch as error:
            raise InvalidAiTransfer from error

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
        try:
            return await to_thread.run_sync(
                self._storage.approve_ai_transfer_request,
                company_id,
                actor_id,
                transfer_id,
                request_payload_sha256,
                idempotency_key,
                request_digest,
            )
        except (AiTransferConflict, IdempotencyConflict) as error:
            raise ApiAiTransferConflict from error
        except AiTransferNotFound as error:
            raise ApiAiTransferNotFound from error
        except AiTransferSourceMismatch as error:
            raise InvalidAiTransfer from error

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
        try:
            return await to_thread.run_sync(
                self._storage.admit_ai_transfer_execution,
                company_id,
                actor_id,
                transfer_id,
                request_payload_sha256,
                idempotency_key,
                request_digest,
            )
        except (AiTransferConflict, IdempotencyConflict) as error:
            raise ApiAiTransferConflict from error
        except AiTransferNotFound as error:
            raise ApiAiTransferNotFound from error
        except AiTransferSourceMismatch as error:
            raise InvalidAiTransfer from error

    async def get_ai_transfer_execution(
        self,
        *,
        company_id: str,
        execution_id: str,
    ) -> AiTransferExecutionDetail | None:
        try:
            record = await to_thread.run_sync(
                self._storage.get_ai_transfer_execution, company_id, execution_id
            )
            raw_response = (
                None
                if record is None or record[2] is None
                else await to_thread.run_sync(
                    self._storage.get_ai_transfer_raw_metadata_for_execution,
                    company_id,
                    execution_id,
                )
            )
            return (
                None
                if record is None
                else AiTransferExecutionDetail(
                    admission=record[0],
                    claim=record[1],
                    receipt=record[2],
                    raw_response=raw_response,
                )
            )
        except AiTransferSourceMismatch as error:
            raise InvalidAiTransfer from error

    async def read_ai_transfer_raw_response(
        self,
        *,
        company_id: str,
        actor_id: str,
        access_role: AccessRole,
        raw_response_id: str,
    ) -> tuple[bytes, AiTransferRawMetadata] | None:
        try:
            return await to_thread.run_sync(
                self._storage.read_ai_transfer_raw_response,
                company_id,
                actor_id,
                access_role,
                raw_response_id,
            )
        except AiTransferNotFound:
            return None
        except AiTransferSourceMismatch as error:
            raise InvalidAiTransfer from error

    async def materialize_ai_transfer_requirement_run(
        self,
        *,
        company_id: str,
        actor_id: str,
        execution_id: str,
    ) -> tuple[AiTransferRequirementMaterialization, AiRequirementReviewRecord | None]:
        try:
            return await to_thread.run_sync(
                self._storage.materialize_ai_transfer_requirement_run,
                company_id,
                actor_id,
                execution_id,
            )
        except AiTransferConflict as error:
            raise ApiAiTransferConflict from error
        except AiTransferNotFound as error:
            raise ApiAiTransferNotFound from error
        except AiTransferSourceMismatch as error:
            raise InvalidAiTransfer from error

    async def materialize_ai_transfer_requirement_batch(
        self,
        *,
        company_id: str,
        actor_id: str,
        execution_id: str,
    ) -> AiTransferRequirementBatchMaterializationDetail:
        try:
            results, record, rejection = await to_thread.run_sync(
                self._storage.materialize_ai_transfer_requirement_batch,
                company_id,
                actor_id,
                execution_id,
            )
        except AiTransferConflict as error:
            raise ApiAiTransferConflict from error
        except AiTransferNotFound as error:
            raise ApiAiTransferNotFound from error
        except AiTransferSourceMismatch as error:
            raise InvalidAiTransfer from error
        snapshot = None if record is None else record.snapshot
        return AiTransferRequirementBatchMaterializationDetail(
            company_id=company_id,
            execution_id=execution_id,
            status=(
                "REJECTED"
                if rejection is not None
                else "MATERIALIZED"
                if snapshot is not None
                else "PENDING"
            ),
            materialized_ordinals=tuple(result.ordinal for result in results),
            run_id=None if snapshot is None else snapshot.run_id,
            run_evidence_sha256=None if snapshot is None else snapshot.evidence_sha256,
            rejection=rejection,
        )

    async def create_case(
        self,
        *,
        company_id: str,
        case: ProcurementCase,
        idempotency_key: str,
        request_digest: str,
    ) -> ProcurementCase:
        operation = partial(
            self._storage.save_case,
            company_id,
            case,
            idempotency_key=idempotency_key,
            request_sha256=request_digest,
        )
        try:
            return await to_thread.run_sync(operation)
        except (CaseVersionConflict, IdempotencyConflict) as error:
            raise VersionConflict from error

    async def get_case(
        self,
        *,
        company_id: str,
        case_id: str,
        version: int,
    ) -> ProcurementCase | None:
        return await to_thread.run_sync(
            partial(self._storage.get_case, company_id, case_id, version)
        )

    async def list_cases(
        self,
        *,
        company_id: str,
        cursor: str | None,
        limit: int,
    ) -> CasePage:
        try:
            stored = await to_thread.run_sync(
                partial(self._storage.list_cases, company_id, cursor=cursor, limit=limit)
            )
        except ValueError as error:
            raise InvalidCursor from error
        return CasePage(items=stored.items, next_cursor=stored.next_cursor)

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
        created_at = datetime.now(UTC)
        source_content: bytes | None = None
        source_contents: tuple[bytes | None, ...] = ()
        try:
            bound = await to_thread.run_sync(
                self._storage.get_bound_requirement_set,
                company_id,
                case_id,
                version,
            )
        except RequirementSetSourceMismatch as error:
            raise InvalidRequirementSet from error
        requirements: tuple[Requirement, ...] = ()
        requirement_refs: dict[str, str] = {}
        if bound is None:
            technical_scope_reason = (
                "К версии кейса ещё не привязан независимо проверенный набор технических "
                "требований; карточки требуют проверки exact BOM."
            )
        else:
            binding, requirement_record = bound
            requirements = requirement_record.proposal.executable_requirements
            requirement_refs = {
                "requirement_set_binding_id": binding.binding_id,
                "requirement_set_id": binding.set_id,
                "requirement_set_proposal_sha256": binding.proposal_sha256,
                "requirement_set_decision_sha256": binding.decision_sha256,
                "requirement_set_binding_sha256": binding.binding_sha256,
            }
            technical_scope_reason = (
                f"Применён exact reviewed set {binding.set_id}: "
                f"{len(requirements)} исполнимых условий; "
                f"{len(requirement_record.proposal.manual_entry_ordinals)} строк остаются "
                "обязательными для ручной проверки exact BOM."
            )
        attempts = await to_thread.run_sync(fetch_server_catalog_sources, query)
        sources = tuple(
            SourcingSourceSnapshot(
                ordinal=ordinal,
                source_name=attempt.source_name,
                source_kind=attempt.source_kind,
                source_url=attempt.source_url,
                media_type=attempt.media_type,
                status=attempt.status,
                source_sha256=attempt.sha256,
                source_byte_size=None if attempt.content is None else len(attempt.content),
                observed_at=attempt.observed_at,
                error_code=attempt.error_code,
            )
            for ordinal, attempt in enumerate(attempts, start=1)
        )
        source_contents = tuple(attempt.content for attempt in attempts)
        successful = tuple(
            attempt for attempt in attempts if attempt.status is SourcingSourceStatus.COMPLETED
        )
        observed_at = max(attempt.observed_at for attempt in attempts)
        if successful:
            manifest_payload = {
                "schema_version": "sourcing-source-manifest-v1",
                "sources": tuple(source.model_dump(mode="json") for source in sources),
            }
            source_content = json.dumps(
                manifest_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            leads = tuple(lead for attempt in successful for lead in attempt.leads)
            record = SourcingRunRecord(
                company_id=company_id,
                run_id=str(uuid.uuid4()),
                case_id=case_id,
                case_version=version,
                query=query,
                source_name="Manufacturer and supplier catalogs",
                source_url=sources[0].source_url,
                status=SourcingRunStatus.COMPLETED,
                source_sha256=hashlib.sha256(source_content).hexdigest(),
                source_byte_size=len(source_content),
                observed_at=observed_at,
                sources=sources,
                shortlist=shortlist_server_leads(leads, requirements),
                **requirement_refs,
                technical_scope_reason=technical_scope_reason,
                created_at=created_at,
            )
        else:
            record = SourcingRunRecord(
                company_id=company_id,
                run_id=str(uuid.uuid4()),
                case_id=case_id,
                case_version=version,
                query=query,
                source_name="Manufacturer and supplier catalogs",
                source_url=sources[0].source_url,
                status=SourcingRunStatus.SOURCE_ERROR,
                observed_at=observed_at,
                sources=sources,
                shortlist=ServerShortlist(review_queue=(), rejected=()),
                **requirement_refs,
                technical_scope_reason=(
                    "Источник не дал проверяемый снимок; техническое соответствие не оценивалось."
                ),
                error_code="ALL_SOURCES_UNAVAILABLE_OR_CHANGED",
                created_at=created_at,
            )
        operation = partial(
            self._storage.store_sourcing_run,
            company_id,
            actor_id,
            record,
            source_content,
            source_contents=source_contents,
            idempotency_key=idempotency_key,
            request_sha256=request_digest,
        )
        try:
            return await to_thread.run_sync(operation)
        except IdempotencyConflict as error:
            raise VersionConflict from error

    async def get_latest_sourcing_run(
        self, *, company_id: str, case_id: str, version: int
    ) -> SourcingRunRecord | None:
        return await to_thread.run_sync(
            self._storage.get_latest_sourcing_run, company_id, case_id, version
        )

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
    ) -> ReviewedRequirementSetRecord:
        operation = partial(
            self._storage.store_reviewed_requirement_set_proposal,
            company_id,
            actor_id,
            set_id=set_id,
            source_document_id=source_document_id,
            source_document_sha256=source_document_sha256,
            declared_scope=declared_scope,
            expected_entry_count=expected_entry_count,
            entries=entries,
            idempotency_key=idempotency_key,
            request_sha256=request_digest,
        )
        try:
            return await to_thread.run_sync(operation)
        except (RequirementSetConflict, IdempotencyConflict) as error:
            raise ApiRequirementSetConflict from error
        except RequirementSetNotFound as error:
            raise ApiRequirementSetNotFound from error
        except RequirementSetSourceMismatch as error:
            raise InvalidRequirementSet from error

    async def preview_reviewed_requirement_set_materialization(
        self,
        *,
        company_id: str,
        source_document_id: str,
        source_document_sha256: str,
        expected_entry_count: int,
    ) -> RequirementSetMaterializationPreview:
        stored = await to_thread.run_sync(
            self._storage.get_document,
            company_id,
            source_document_id,
        )
        if stored is None:
            raise ApiRequirementSetNotFound
        if (
            stored.sha256 != source_document_sha256
            or stored.document_role is not DocumentRole.TENDER_REQUIREMENTS
        ):
            raise InvalidRequirementSet
        try:
            return build_requirement_set_materialization_preview(
                company_id=company_id,
                source_document_id=source_document_id,
                source_document_sha256=source_document_sha256,
                extraction=stored.extraction,
                expected_entry_count=expected_entry_count,
            )
        except RequirementSetMaterializationError as error:
            raise InvalidRequirementSet from error

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
        preview = await self.preview_reviewed_requirement_set_materialization(
            company_id=company_id,
            source_document_id=source_document_id,
            source_document_sha256=source_document_sha256,
            expected_entry_count=expected_entry_count,
        )
        if preview.preview_sha256 != preview_sha256:
            raise InvalidRequirementSet
        try:
            entries = materialize_reviewed_requirement_entries(preview, selections)
        except RequirementSetMaterializationError as error:
            raise InvalidRequirementSet from error
        return await self.store_reviewed_requirement_set_proposal(
            company_id=company_id,
            actor_id=actor_id,
            set_id=set_id,
            source_document_id=source_document_id,
            source_document_sha256=source_document_sha256,
            declared_scope=declared_scope,
            expected_entry_count=expected_entry_count,
            entries=entries,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )

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
    ) -> ReviewedRequirementSetRecord:
        operation = partial(
            self._storage.decide_reviewed_requirement_set,
            company_id,
            reviewer_id,
            set_id=set_id,
            proposal_sha256=proposal_sha256,
            coverage_assessment=coverage_assessment,
            normalization_assessment=normalization_assessment,
            status=status,
            reason=reason,
            idempotency_key=idempotency_key,
            request_sha256=request_digest,
        )
        try:
            return await to_thread.run_sync(operation)
        except (RequirementSetConflict, IdempotencyConflict) as error:
            raise ApiRequirementSetConflict from error
        except RequirementSetNotFound as error:
            raise ApiRequirementSetNotFound from error
        except RequirementSetSourceMismatch as error:
            raise InvalidRequirementSet from error

    async def get_reviewed_requirement_set(
        self, *, company_id: str, set_id: str
    ) -> ReviewedRequirementSetRecord | None:
        try:
            return await to_thread.run_sync(
                self._storage.get_reviewed_requirement_set,
                company_id,
                set_id,
            )
        except RequirementSetSourceMismatch as error:
            raise InvalidRequirementSet from error

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
    ) -> CaseRequirementSetBinding:
        operation = partial(
            self._storage.bind_reviewed_requirement_set_to_case,
            company_id,
            actor_id,
            binding_id=binding_id,
            case_id=case_id,
            case_version=case_version,
            set_id=set_id,
            proposal_sha256=proposal_sha256,
            decision_sha256=decision_sha256,
            idempotency_key=idempotency_key,
            request_sha256=request_digest,
        )
        try:
            return await to_thread.run_sync(operation)
        except (RequirementSetConflict, IdempotencyConflict) as error:
            raise ApiRequirementSetConflict from error
        except RequirementSetNotFound as error:
            raise ApiRequirementSetNotFound from error
        except RequirementSetSourceMismatch as error:
            raise InvalidRequirementSet from error

    async def get_case_requirement_set_binding(
        self, *, company_id: str, binding_id: str
    ) -> CaseRequirementSetBinding | None:
        try:
            return await to_thread.run_sync(
                self._storage.get_case_requirement_set_binding,
                company_id,
                binding_id,
            )
        except RequirementSetSourceMismatch as error:
            raise InvalidRequirementSet from error

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
    ) -> ServerOfferProposal:
        operation = partial(
            self._storage.store_server_offer_proposal,
            company_id,
            actor_id,
            offer_id=offer_id,
            case_id=case_id,
            case_version=case_version,
            requirement_set_binding_id=requirement_set_binding_id,
            requirement_set_binding_sha256=requirement_set_binding_sha256,
            sourcing_run_id=sourcing_run_id,
            lead_id=lead_id,
            source_document_id=source_document_id,
            source_document_sha256=source_document_sha256,
            bom_lines=bom_lines,
            commercial_terms=commercial_terms,
            idempotency_key=idempotency_key,
            request_sha256=request_digest,
        )
        try:
            return await to_thread.run_sync(operation)
        except (ServerOfferConflict, IdempotencyConflict) as error:
            raise ApiServerOfferConflict from error
        except ServerOfferNotFound as error:
            raise ApiServerOfferNotFound from error
        except ServerOfferSourceMismatch as error:
            raise InvalidServerOffer from error

    async def get_server_offer_proposal(
        self, *, company_id: str, offer_id: str
    ) -> ServerOfferProposal | None:
        try:
            return await to_thread.run_sync(
                self._storage.get_server_offer_proposal, company_id, offer_id
            )
        except ServerOfferSourceMismatch as error:
            raise InvalidServerOffer from error

    async def get_server_offer_review(
        self, *, company_id: str, offer_id: str
    ) -> ServerOfferReviewRecord | None:
        try:
            return await to_thread.run_sync(
                self._storage.get_server_offer_review, company_id, offer_id
            )
        except ServerOfferReviewSourceMismatch as error:
            raise InvalidServerOfferReview from error

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
    ) -> ServerOfferReviewDecision:
        operation = partial(
            self._storage.decide_server_offer_proposal,
            company_id,
            reviewer_id,
            offer_id=offer_id,
            proposal_sha256=proposal_sha256,
            requirement_decisions=requirement_decisions,
            bom_scope_assessment=bom_scope_assessment,
            commercial_terms_assessment=commercial_terms_assessment,
            reason=reason,
            idempotency_key=idempotency_key,
            request_sha256=request_digest,
        )
        try:
            return await to_thread.run_sync(operation)
        except (ServerOfferReviewConflict, IdempotencyConflict) as error:
            raise ApiServerOfferReviewConflict from error
        except ServerOfferReviewNotFound as error:
            raise ApiServerOfferReviewNotFound from error
        except ServerOfferReviewSourceMismatch as error:
            raise InvalidServerOfferReview from error

    async def get_server_offer_economics(
        self,
        *,
        company_id: str,
        case_id: str,
        case_version: int,
        offer_id: str,
    ) -> ServerOfferEconomicsRecord | None:
        try:
            return await to_thread.run_sync(
                self._storage.get_server_offer_economics,
                company_id,
                case_id,
                case_version,
                offer_id,
            )
        except ServerOfferEconomicsSourceMismatch as error:
            raise InvalidServerOfferEconomics from error

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
    ) -> ServerOfferEconomicsPackage:
        operation = partial(
            self._storage.store_server_offer_economics,
            company_id,
            actor_id,
            economics_id=economics_id,
            case_id=case_id,
            case_version=case_version,
            offer_id=offer_id,
            offer_proposal_sha256=offer_proposal_sha256,
            offer_review_decision_sha256=offer_review_decision_sha256,
            scenarios=scenarios,
            idempotency_key=idempotency_key,
            request_sha256=request_digest,
        )
        try:
            return await to_thread.run_sync(operation)
        except (ServerOfferEconomicsConflict, IdempotencyConflict) as error:
            raise ApiServerOfferEconomicsConflict from error
        except ServerOfferEconomicsNotFound as error:
            raise ApiServerOfferEconomicsNotFound from error
        except ServerOfferEconomicsSourceMismatch as error:
            raise InvalidServerOfferEconomics from error

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
    ) -> ProcurementCase:
        operation = partial(
            self._storage.materialize_case_from_server_offer_economics,
            company_id,
            actor_id,
            case_id=case_id,
            case_version=case_version,
            offer_id=offer_id,
            economics_id=economics_id,
            package_sha256=package_sha256,
            idempotency_key=idempotency_key,
            request_sha256=request_digest,
        )
        try:
            return await to_thread.run_sync(operation)
        except (ServerOfferEconomicsConflict, CaseVersionConflict, IdempotencyConflict) as error:
            raise ApiServerOfferEconomicsConflict from error
        except ServerOfferEconomicsNotFound as error:
            raise ApiServerOfferEconomicsNotFound from error
        except ServerOfferEconomicsSourceMismatch as error:
            raise InvalidServerOfferEconomics from error

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
    ) -> ProcurementCase:
        operation = partial(
            self._storage.materialize_case_hard_gate_assessment,
            company_id,
            actor_id,
            case_id=case_id,
            case_version=case_version,
            source_case_input_sha256=source_case_input_sha256,
            document_binding_id=document_binding_id,
            manifest_evidence_sha256=manifest_evidence_sha256,
            document_decision_sha256=document_decision_sha256,
            decisions=decisions,
            idempotency_key=idempotency_key,
            request_sha256=request_digest,
        )
        try:
            return await to_thread.run_sync(operation)
        except (
            CaseHardGateAssessmentConflict,
            CaseVersionConflict,
            IdempotencyConflict,
        ) as error:
            raise ApiCaseHardGateAssessmentConflict from error
        except CaseHardGateAssessmentNotFound as error:
            raise ApiCaseHardGateAssessmentNotFound from error
        except (
            CaseHardGateAssessmentSourceMismatch,
            ServerOfferEconomicsNotFound,
            ServerOfferEconomicsSourceMismatch,
            TypeError,
            ValueError,
        ) as error:
            raise InvalidCaseHardGateAssessment from error

    async def get_latest_evaluation(
        self,
        *,
        company_id: str,
        case_id: str,
        version: int,
    ) -> EvaluationRecord | None:
        stored = await to_thread.run_sync(
            partial(
                self._storage.get_latest_evaluation,
                company_id,
                case_id,
                version,
            )
        )
        if stored is None:
            return None
        return EvaluationRecord(
            evaluation_id=stored.evaluation_id,
            audit_event_id=stored.evaluation_id,
            recommendation=stored.recommendation,
            engine_version=stored.engine_version,
            input_digest=stored.input_sha256,
            effective_at=stored.effective_at,
        )

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
        operation = partial(
            self._storage.record_evaluation,
            company_id,
            actor_id,
            case_id,
            version,
            effective_at,
            input_digest,
            engine_version,
            recommendation,
            idempotency_key,
            request_digest,
        )
        try:
            stored = await to_thread.run_sync(operation)
        except IdempotencyConflict as error:
            raise VersionConflict from error
        return EvaluationRecord(
            evaluation_id=stored.evaluation_id,
            audit_event_id=stored.evaluation_id,
            recommendation=stored.recommendation,
            engine_version=stored.engine_version,
            input_digest=stored.input_sha256,
            effective_at=stored.effective_at,
        )

    async def get_participation_decision(
        self,
        *,
        company_id: str,
        evaluation_id: str,
    ) -> ParticipationDecisionRecord | None:
        try:
            return await to_thread.run_sync(
                self._storage.get_participation_decision,
                company_id,
                evaluation_id,
            )
        except ParticipationDecisionSourceMismatch as error:
            raise InvalidParticipationDecision from error

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
        try:
            return await to_thread.run_sync(
                self._storage.decide_participation,
                company_id,
                actor_id,
                evaluation_id,
                evaluation_evidence_sha256,
                status,
                reason,
                idempotency_key,
                request_digest,
            )
        except (ParticipationDecisionConflict, IdempotencyConflict) as error:
            raise ApiParticipationDecisionConflict from error
        except ParticipationDecisionNotFound as error:
            raise ApiParticipationDecisionNotFound from error
        except ParticipationDecisionSourceMismatch as error:
            raise InvalidParticipationDecision from error

    async def get_application_package(
        self,
        *,
        company_id: str,
        participation_decision_id: str,
    ) -> ApplicationPackageRecord | None:
        try:
            return await to_thread.run_sync(
                self._storage.get_application_package,
                company_id,
                participation_decision_id,
            )
        except ApplicationPackageSourceMismatch as error:
            raise InvalidApplicationPackage from error

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
        try:
            return await to_thread.run_sync(
                partial(
                    self._storage.store_application_package,
                    company_id,
                    actor_id,
                    package_id=package_id,
                    participation_decision_id=participation_decision_id,
                    participation_decision_sha256=participation_decision_sha256,
                    proposed_price_ex_vat=proposed_price_ex_vat,
                    requirements=requirements,
                    attachments=attachments,
                    idempotency_key=idempotency_key,
                    request_sha256=request_digest,
                )
            )
        except (ApplicationPackageConflict, IdempotencyConflict) as error:
            raise ApiApplicationPackageConflict from error
        except ApplicationPackageNotFound as error:
            raise ApiApplicationPackageNotFound from error
        except ApplicationPackageSourceMismatch as error:
            raise InvalidApplicationPackage from error

    async def get_application_review(
        self,
        *,
        company_id: str,
        package_id: str,
    ) -> ApplicationReviewRecord | None:
        try:
            return await to_thread.run_sync(
                self._storage.get_application_review, company_id, package_id
            )
        except ApplicationReviewSourceMismatch as error:
            raise InvalidApplicationReview from error

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
        try:
            return await to_thread.run_sync(
                partial(
                    self._storage.decide_application_review,
                    company_id,
                    actor_id,
                    package_id=package_id,
                    package_sha256=package_sha256,
                    requirement_reviews=requirement_reviews,
                    attachment_reviews=attachment_reviews,
                    inventory_assessment=inventory_assessment,
                    inventory_source_document_ids=inventory_source_document_ids,
                    inventory_reason=inventory_reason,
                    price_assessment=price_assessment,
                    price_reason=price_reason,
                    reason=reason,
                    idempotency_key=idempotency_key,
                    request_sha256=request_digest,
                )
            )
        except (ApplicationReviewConflict, IdempotencyConflict) as error:
            raise ApiApplicationReviewConflict from error
        except ApplicationReviewNotFound as error:
            raise ApiApplicationReviewNotFound from error
        except ApplicationReviewSourceMismatch as error:
            raise InvalidApplicationReview from error

    async def get_application_submission(
        self,
        *,
        company_id: str,
        package_id: str,
    ) -> ApplicationSubmissionRecord | None:
        try:
            return await to_thread.run_sync(
                self._storage.get_application_submission, company_id, package_id
            )
        except ApplicationSubmissionSourceMismatch as error:
            raise InvalidApplicationSubmission from error

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
        try:
            return await to_thread.run_sync(
                partial(
                    self._storage.prepare_application_submission,
                    company_id,
                    actor_id,
                    package_id=package_id,
                    package_sha256=package_sha256,
                    review_decision_sha256=review_decision_sha256,
                    destination=destination,
                    idempotency_key=idempotency_key,
                    request_sha256=request_digest,
                )
            )
        except (ApplicationSubmissionConflict, IdempotencyConflict) as error:
            raise ApiApplicationSubmissionConflict from error
        except ApplicationSubmissionNotFound as error:
            raise ApiApplicationSubmissionNotFound from error
        except ApplicationSubmissionSourceMismatch as error:
            raise InvalidApplicationSubmission from error

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
        try:
            return await to_thread.run_sync(
                partial(
                    self._storage.decide_application_submission,
                    company_id,
                    actor_id,
                    action_id=action_id,
                    payload_sha256=payload_sha256,
                    status=status,
                    reason=reason,
                    idempotency_key=idempotency_key,
                    request_sha256=request_digest,
                )
            )
        except (ApplicationSubmissionConflict, IdempotencyConflict) as error:
            raise ApiApplicationSubmissionConflict from error
        except ApplicationSubmissionNotFound as error:
            raise ApiApplicationSubmissionNotFound from error
        except ApplicationSubmissionSourceMismatch as error:
            raise InvalidApplicationSubmission from error

    async def get_application_submission_execution(
        self,
        *,
        company_id: str,
        package_id: str,
    ) -> ApplicationSubmissionExecutionRecord | None:
        try:
            return await to_thread.run_sync(
                self._storage.get_application_submission_execution,
                company_id,
                package_id,
            )
        except ApplicationSubmissionSourceMismatch as error:
            raise InvalidApplicationSubmission from error

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
        try:
            return await to_thread.run_sync(
                partial(
                    self._storage.claim_application_submission,
                    company_id,
                    actor_id,
                    package_id=package_id,
                    action_id=action_id,
                    payload_sha256=payload_sha256,
                    approval_decision_sha256=approval_decision_sha256,
                    idempotency_key=idempotency_key,
                    request_sha256=request_digest,
                )
            )
        except (ApplicationSubmissionConflict, IdempotencyConflict) as error:
            raise ApiApplicationSubmissionConflict from error
        except ApplicationSubmissionNotFound as error:
            raise ApiApplicationSubmissionNotFound from error
        except ApplicationSubmissionSourceMismatch as error:
            raise InvalidApplicationSubmission from error

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
        operation = partial(
            self._storage.store_document,
            company_id,
            actor_id,
            original_filename,
            media_type,
            document_role,
            content,
            extraction.model_dump(mode="json"),
            idempotency_key,
            request_digest,
            document_id=document_id,
        )
        try:
            stored = await to_thread.run_sync(operation)
        except (DocumentConflict, IdempotencyConflict) as error:
            raise VersionConflict from error
        return self._document_record(stored)

    async def get_document(
        self,
        *,
        company_id: str,
        document_id: str,
    ) -> DocumentRecord | None:
        stored = await to_thread.run_sync(
            partial(self._storage.get_document, company_id, document_id)
        )
        return None if stored is None else self._document_record(stored)

    async def get_document_content(
        self,
        *,
        company_id: str,
        document_id: str,
    ) -> bytes | None:
        stored = await to_thread.run_sync(
            partial(self._storage.get_document, company_id, document_id)
        )
        return None if stored is None else stored.content

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
        try:
            return await to_thread.run_sync(
                partial(
                    self._storage.store_completeness_review,
                    company_id,
                    actor_id,
                    source_document_id,
                    idempotency_key,
                    request_digest,
                    review_id=review_id,
                )
            )
        except (CompletenessReviewConflict, IdempotencyConflict) as error:
            raise ApiCompletenessReviewConflict from error
        except CompletenessReviewNotFound as error:
            raise ApiCompletenessReviewNotFound from error
        except CompletenessReviewSourceMismatch as error:
            raise InvalidCompletenessReview from error

    async def get_completeness_review(
        self,
        *,
        company_id: str,
        review_id: str,
    ) -> CompletenessReviewRecord | None:
        return await to_thread.run_sync(
            self._storage.get_completeness_review,
            company_id,
            review_id,
        )

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
        try:
            return await to_thread.run_sync(
                partial(
                    self._storage.store_document_set_evidence_manifest,
                    company_id,
                    actor_id,
                    scope,
                    review_refs,
                    idempotency_key,
                    request_digest,
                    manifest_id=manifest_id,
                )
            )
        except (DocumentSetEvidenceConflict, IdempotencyConflict) as error:
            raise ApiDocumentSetEvidenceConflict from error
        except DocumentSetEvidenceNotFound as error:
            raise ApiDocumentSetEvidenceNotFound from error
        except DocumentSetEvidenceSourceMismatch as error:
            raise InvalidDocumentSetEvidence from error

    async def get_document_set_evidence_manifest(
        self,
        *,
        company_id: str,
        manifest_id: str,
    ) -> DocumentSetEvidenceManifest | None:
        try:
            return await to_thread.run_sync(
                self._storage.get_document_set_evidence_manifest,
                company_id,
                manifest_id,
            )
        except DocumentSetEvidenceSourceMismatch as error:
            raise InvalidDocumentSetEvidence from error

    async def get_document_set_review_evidence(
        self,
        *,
        company_id: str,
        manifest_id: str,
    ) -> DocumentSetReviewEvidence | None:
        try:
            return await to_thread.run_sync(
                self._storage.get_document_set_review_evidence,
                company_id,
                manifest_id,
            )
        except DocumentSetReviewSourceMismatch as error:
            raise ApiDocumentSetReviewSourceMismatch from error

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
        try:
            return await to_thread.run_sync(
                self._storage.store_document_set_review_decision,
                company_id,
                reviewer_id,
                manifest_id,
                manifest_evidence_sha256,
                attestations,
                inventory_assessment,
                inventory_rationale,
                cross_document_assessment,
                cross_document_rationale,
                reviewer_findings,
                status,
                reason,
                idempotency_key,
                request_digest,
            )
        except (DocumentSetReviewConflict, IdempotencyConflict) as error:
            raise ApiDocumentSetReviewConflict from error
        except DocumentSetReviewNotFound as error:
            raise ApiDocumentSetReviewNotFound from error
        except DocumentSetReviewSourceMismatch as error:
            raise ApiDocumentSetReviewSourceMismatch from error
        except (TypeError, ValueError) as error:
            raise InvalidDocumentSetReview from error

    async def get_document_set_review_decision(
        self,
        *,
        company_id: str,
        manifest_id: str,
    ) -> DocumentSetReviewDecision | None:
        try:
            return await to_thread.run_sync(
                self._storage.get_document_set_review_decision,
                company_id,
                manifest_id,
            )
        except DocumentSetReviewSourceMismatch as error:
            raise ApiDocumentSetReviewSourceMismatch from error

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
        try:
            return await to_thread.run_sync(
                partial(
                    self._storage.store_case_document_evidence_binding,
                    company_id,
                    actor_id,
                    manifest_id,
                    manifest_evidence_sha256,
                    decision_sha256,
                    idempotency_key,
                    request_digest,
                    binding_id=binding_id,
                )
            )
        except (CaseEvidenceConflict, IdempotencyConflict) as error:
            raise ApiCaseEvidenceConflict from error
        except CaseEvidenceNotFound as error:
            raise ApiCaseEvidenceNotFound from error
        except CaseEvidenceSourceMismatch as error:
            raise InvalidCaseEvidence from error

    async def get_case_document_evidence_binding(
        self,
        *,
        company_id: str,
        binding_id: str,
    ) -> CaseDocumentEvidenceBinding | None:
        try:
            return await to_thread.run_sync(
                self._storage.get_case_document_evidence_binding,
                company_id,
                binding_id,
            )
        except CaseEvidenceSourceMismatch as error:
            raise InvalidCaseEvidence from error

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
        try:
            return await to_thread.run_sync(
                partial(
                    self._storage.create_case_from_evidence,
                    company_id,
                    actor_id,
                    case,
                    binding_id,
                    manifest_evidence_sha256,
                    decision_sha256,
                    other_checks,
                    idempotency_key,
                    request_digest,
                )
            )
        except (CaseVersionConflict, IdempotencyConflict) as error:
            raise VersionConflict from error
        except CaseEvidenceNotFound as error:
            raise ApiCaseEvidenceNotFound from error
        except CaseEvidenceSourceMismatch as error:
            raise InvalidCaseEvidence from error
        except (TypeError, ValueError) as error:
            raise InvalidCaseEvidence from error

    async def list_completeness_reviews(
        self,
        *,
        company_id: str,
        limit: int,
    ) -> tuple[CompletenessReviewRecord, ...]:
        return await to_thread.run_sync(
            partial(self._storage.list_completeness_reviews, company_id, limit=limit)
        )

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
        try:
            return await to_thread.run_sync(
                self._storage.decide_completeness_review,
                company_id,
                reviewer_id,
                review_id,
                evidence_sha256,
                status,
                scope,
                reason,
                block_decisions,
                idempotency_key,
                request_digest,
            )
        except (CompletenessReviewConflict, IdempotencyConflict) as error:
            raise ApiCompletenessReviewConflict from error
        except CompletenessReviewNotFound as error:
            raise ApiCompletenessReviewNotFound from error
        except CompletenessReviewSourceMismatch as error:
            raise InvalidCompletenessReview from error

    async def get_ai_requirement_run(
        self,
        *,
        company_id: str,
        run_id: str,
    ) -> AiRequirementReviewRecord | None:
        return await to_thread.run_sync(
            self._storage.get_ai_requirement_run,
            company_id,
            run_id,
        )

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
        try:
            return await to_thread.run_sync(
                partial(
                    self._storage.store_ai_requirement_run,
                    company_id,
                    actor_id,
                    source_document_id,
                    report,
                    idempotency_key,
                    request_digest,
                )
            )
        except (StorageAiRequirementReviewConflict, IdempotencyConflict) as error:
            raise ApiAiRequirementReviewConflict from error
        except StorageAiRequirementRunNotFound as error:
            raise ApiAiRequirementRunNotFound from error
        except AiRequirementRunSourceMismatch as error:
            raise InvalidAiRequirementReview from error

    async def list_ai_requirement_runs(
        self,
        *,
        company_id: str,
        limit: int,
    ) -> tuple[AiRequirementReviewRecord, ...]:
        return await to_thread.run_sync(
            partial(self._storage.list_ai_requirement_runs, company_id, limit=limit)
        )

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
        try:
            return await to_thread.run_sync(
                self._storage.decide_ai_requirement_review,
                company_id,
                reviewer_id,
                run_id,
                evidence_sha256,
                candidate_decisions,
                idempotency_key,
                request_digest,
            )
        except (StorageAiRequirementReviewConflict, IdempotencyConflict) as error:
            raise ApiAiRequirementReviewConflict from error
        except StorageAiRequirementRunNotFound as error:
            raise ApiAiRequirementRunNotFound from error
        except AiRequirementRunSourceMismatch as error:
            raise InvalidAiRequirementReview from error

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
        operation = partial(
            self._storage.store_document_search_index,
            company_id,
            actor_id,
            source_document_id,
            entry,
            idempotency_key,
            request_digest,
            search_index_id=search_index_id,
        )
        try:
            stored = await to_thread.run_sync(operation)
        except (DocumentSearchIndexConflict, IdempotencyConflict) as error:
            raise VersionConflict from error
        return self._document_search_index_record(stored)

    async def search_document_indexes(
        self,
        *,
        company_id: str,
        query: str,
        limit: int,
        effective_at: datetime,
    ) -> DocumentSearchPage:
        stored, catalog_record = await to_thread.run_sync(
            lambda: (
                self._storage.list_latest_document_search_indexes(company_id, limit=limit),
                self._storage.get_latest_model_brand_catalog(company_id, at=effective_at),
            )
        )
        entries = tuple(item.entry for item in stored)
        return DocumentSearchPage(
            query=query,
            effective_at=effective_at,
            results=search_documents(
                entries,
                company_id=company_id,
                query=query,
                model_brand_catalog=(
                    catalog_record.catalog if catalog_record is not None else None
                ),
                at=effective_at if catalog_record is not None else None,
            ),
        )

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
        operation = partial(
            self._storage.store_model_brand_source_artifact,
            company_id,
            actor_id,
            artifact_id,
            source_title,
            source_url,
            original_filename,
            content,
            retrieved_at,
            idempotency_key,
            request_digest,
        )
        try:
            stored = await to_thread.run_sync(operation)
        except (ModelBrandSourceArtifactConflict, IdempotencyConflict) as error:
            raise VersionConflict from error
        return self._model_brand_source_artifact_record(stored)

    async def get_model_brand_source_artifact(
        self,
        *,
        company_id: str,
        artifact_id: str,
    ) -> ModelBrandSourceArtifactRecord | None:
        stored = await to_thread.run_sync(
            self._storage.get_model_brand_source_artifact,
            company_id,
            artifact_id,
        )
        if stored is None:
            return None
        return self._model_brand_source_artifact_record(stored)

    async def store_model_brand_review_proposal(
        self,
        *,
        company_id: str,
        actor_id: str,
        proposal: ModelBrandReviewProposal,
        idempotency_key: str,
        request_digest: str,
    ) -> ModelBrandReviewRecord:
        try:
            stored = await to_thread.run_sync(
                self._storage.store_model_brand_review_proposal,
                company_id,
                actor_id,
                proposal,
                idempotency_key,
                request_digest,
            )
        except (ModelBrandReviewConflict, IdempotencyConflict) as error:
            raise ApiModelBrandReviewConflict from error
        except ModelBrandSourceEvidenceMismatch as error:
            raise InvalidModelBrandEvidence from error
        return self._model_brand_review_record(stored)

    async def list_model_brand_reviews(
        self,
        *,
        company_id: str,
        limit: int,
    ) -> tuple[ModelBrandReviewRecord, ...]:
        stored = await to_thread.run_sync(
            partial(self._storage.list_model_brand_reviews, company_id, limit=limit)
        )
        return tuple(self._model_brand_review_record(item) for item in stored)

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
        try:
            stored = await to_thread.run_sync(
                self._storage.decide_model_brand_review,
                company_id,
                reviewer_id,
                proposal_id,
                decision,
                reason,
                idempotency_key,
                request_digest,
            )
        except (ModelBrandReviewConflict, IdempotencyConflict) as error:
            raise ApiModelBrandReviewConflict from error
        except ModelBrandReviewNotFound as error:
            raise ApiModelBrandReviewNotFound from error
        except ModelBrandSourceEvidenceMismatch as error:
            raise InvalidModelBrandEvidence from error
        return self._model_brand_review_record(stored)

    @staticmethod
    def _model_brand_review_record(stored: object) -> ModelBrandReviewRecord:
        from procurement.storage import ModelBrandReviewRecord as StoredModelBrandReviewRecord

        checked = StoredModelBrandReviewRecord.model_validate(stored)
        decision = checked.decision
        return ModelBrandReviewRecord(
            proposal=checked.proposal,
            status=checked.status,
            decision=(
                None
                if decision is None
                else ModelBrandReviewDecisionRecord(
                    proposal_id=decision.proposal_id,
                    status=decision.status,
                    decided_by=decision.decided_by,
                    reason=decision.reason,
                    catalog_id=decision.catalog_id,
                    created_at=decision.created_at,
                )
            ),
        )

    @staticmethod
    def _model_brand_source_artifact_record(stored: object) -> ModelBrandSourceArtifactRecord:
        from procurement.storage import (
            ModelBrandSourceArtifactRecord as StoredModelBrandSourceArtifactRecord,
        )

        checked = StoredModelBrandSourceArtifactRecord.model_validate(stored)
        return ModelBrandSourceArtifactRecord(
            artifact_id=checked.artifact_id,
            source_title=checked.source_title,
            source_url=checked.source_url,
            original_filename=checked.original_filename,
            media_type=checked.media_type,
            byte_size=checked.byte_size,
            sha256=checked.sha256,
            retrieved_at=checked.retrieved_at,
            created_at=checked.created_at,
        )

    async def get_latest_model_brand_catalog(
        self,
        *,
        company_id: str,
        effective_at: datetime,
    ) -> ModelBrandCatalogRecord | None:
        stored = await to_thread.run_sync(
            partial(
                self._storage.get_latest_model_brand_catalog,
                company_id,
                at=effective_at,
            )
        )
        if stored is None:
            return None
        return ModelBrandCatalogRecord(catalog=stored.catalog, created_at=stored.created_at)

    @staticmethod
    def _document_search_index_record(stored: object) -> DocumentSearchIndexRecord:
        from procurement.storage import DocumentSearchIndexRecord as StoredSearchIndexRecord

        checked = StoredSearchIndexRecord.model_validate(stored)
        return DocumentSearchIndexRecord(
            search_index_id=checked.search_index_id,
            source_document_id=checked.source_document_id,
            source_document_sha256=checked.source_document_sha256,
            entry=checked.entry,
            created_at=checked.created_at,
        )

    @staticmethod
    def _document_record(stored: object) -> DocumentRecord:
        from procurement.storage import DocumentRecord as StoredDocumentRecord

        checked = StoredDocumentRecord.model_validate(stored)
        return DocumentRecord(
            document_id=checked.document_id,
            original_filename=checked.original_filename,
            media_type=checked.media_type,
            document_role=checked.document_role,
            byte_size=checked.byte_size,
            sha256=checked.sha256,
            extraction=ExtractionResult.model_validate(checked.extraction),
            created_at=checked.created_at,
        )

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
        operation = partial(
            self._storage.store_document_bundle,
            company_id,
            actor_id,
            original_filename,
            media_type,
            document_role,
            content,
            result.model_dump(mode="json"),
            idempotency_key,
            request_digest,
            bundle_id=bundle_id,
        )
        try:
            stored = await to_thread.run_sync(operation)
        except (DocumentBundleConflict, IdempotencyConflict) as error:
            raise VersionConflict from error
        return self._document_bundle_record(stored)

    async def get_document_bundle(
        self,
        *,
        company_id: str,
        bundle_id: str,
    ) -> DocumentBundleRecord | None:
        stored = await to_thread.run_sync(
            partial(self._storage.get_document_bundle, company_id, bundle_id)
        )
        return None if stored is None else self._document_bundle_record(stored)

    async def get_document_bundle_content(
        self,
        *,
        company_id: str,
        bundle_id: str,
    ) -> bytes | None:
        stored = await to_thread.run_sync(
            partial(self._storage.get_document_bundle, company_id, bundle_id)
        )
        return None if stored is None else stored.content

    @staticmethod
    def _document_bundle_record(stored: object) -> DocumentBundleRecord:
        from procurement.storage import DocumentBundleRecord as StoredDocumentBundleRecord

        checked = StoredDocumentBundleRecord.model_validate(stored)
        return DocumentBundleRecord(
            bundle_id=checked.bundle_id,
            original_filename=checked.original_filename,
            media_type=checked.media_type,
            document_role=checked.document_role,
            byte_size=checked.byte_size,
            sha256=checked.sha256,
            result=DocumentBundleResult.model_validate(checked.result),
            created_at=checked.created_at,
        )

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
        operation = partial(
            self._storage.store_ocr_derivative,
            company_id,
            actor_id,
            source_document_id,
            engine=engine,
            threshold=threshold,
            status=result.status.value,
            result=result.model_dump(mode="json"),
            mean_confidence=mean_confidence,
            idempotency_key=idempotency_key,
            request_sha256=request_digest,
            ocr_id=ocr_id,
        )
        try:
            stored = await to_thread.run_sync(operation)
        except (OcrDerivativeConflict, IdempotencyConflict) as error:
            raise VersionConflict from error
        return self._ocr_record(stored)

    async def get_ocr_derivative(
        self,
        *,
        company_id: str,
        ocr_id: str,
    ) -> OcrDerivativeRecord | None:
        stored = await to_thread.run_sync(
            partial(self._storage.get_ocr_derivative, company_id, ocr_id)
        )
        return None if stored is None else self._ocr_record(stored)

    async def get_latest_ocr_for_document(
        self,
        *,
        company_id: str,
        source_document_id: str,
    ) -> OcrDerivativeRecord | None:
        stored = await to_thread.run_sync(
            partial(self._storage.get_latest_ocr_for_document, company_id, source_document_id)
        )
        return None if stored is None else self._ocr_record(stored)

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
        operation = partial(
            self._storage.store_bundle_member_ocr_derivative,
            company_id,
            actor_id,
            source_bundle_id,
            member_index,
            archive_path,
            source_member_sha256,
            engine=engine,
            threshold=threshold,
            status=result.status.value,
            result=result.model_dump(mode="json"),
            mean_confidence=mean_confidence,
            idempotency_key=idempotency_key,
            request_sha256=request_digest,
            ocr_id=ocr_id,
        )
        try:
            stored = await to_thread.run_sync(operation)
        except (BundleMemberOcrConflict, IdempotencyConflict) as error:
            raise VersionConflict from error
        return self._bundle_member_ocr_record(stored)

    async def get_bundle_member_ocr_derivative(
        self,
        *,
        company_id: str,
        ocr_id: str,
    ) -> BundleMemberOcrRecord | None:
        stored = await to_thread.run_sync(
            partial(self._storage.get_bundle_member_ocr_derivative, company_id, ocr_id)
        )
        return None if stored is None else self._bundle_member_ocr_record(stored)

    async def get_latest_ocr_for_bundle_member(
        self,
        *,
        company_id: str,
        source_bundle_id: str,
        member_index: int,
    ) -> BundleMemberOcrRecord | None:
        stored = await to_thread.run_sync(
            partial(
                self._storage.get_latest_ocr_for_bundle_member,
                company_id,
                source_bundle_id,
                member_index,
            )
        )
        return None if stored is None else self._bundle_member_ocr_record(stored)

    @staticmethod
    def _bundle_member_ocr_record(stored: object) -> BundleMemberOcrRecord:
        from procurement.storage import BundleMemberOcrRecord as StoredBundleMemberOcrRecord

        checked = StoredBundleMemberOcrRecord.model_validate(stored)
        return BundleMemberOcrRecord(
            ocr_id=checked.ocr_id,
            source_bundle_id=checked.source_bundle_id,
            member_index=checked.member_index,
            archive_path=checked.archive_path,
            source_member_sha256=checked.source_member_sha256,
            engine=checked.engine,
            threshold=checked.threshold,
            result=OcrDerivative.model_validate(checked.result),
            mean_confidence=checked.mean_confidence,
            created_at=checked.created_at,
        )

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
        operation = partial(
            self._storage.store_docx_media_ocr_derivative,
            company_id,
            actor_id,
            source_document_id,
            media_index,
            archive_path,
            source_document_sha256,
            source_media_sha256,
            media_type,
            engine=engine,
            threshold=threshold,
            status=result.status.value,
            result=result,
            mean_confidence=mean_confidence,
            idempotency_key=idempotency_key,
            request_sha256=request_digest,
            ocr_id=ocr_id,
        )
        try:
            stored = await to_thread.run_sync(operation)
        except (DocxMediaOcrConflict, IdempotencyConflict) as error:
            raise VersionConflict from error
        return self._docx_media_ocr_record(stored)

    async def get_docx_media_ocr_derivative(
        self,
        *,
        company_id: str,
        ocr_id: str,
    ) -> DocxMediaOcrRecord | None:
        stored = await to_thread.run_sync(
            partial(self._storage.get_docx_media_ocr_derivative, company_id, ocr_id)
        )
        return None if stored is None else self._docx_media_ocr_record(stored)

    async def get_latest_ocr_for_docx_media(
        self,
        *,
        company_id: str,
        source_document_id: str,
        media_index: int,
    ) -> DocxMediaOcrRecord | None:
        stored = await to_thread.run_sync(
            partial(
                self._storage.get_latest_ocr_for_docx_media,
                company_id,
                source_document_id,
                media_index,
            )
        )
        return None if stored is None else self._docx_media_ocr_record(stored)

    @staticmethod
    def _docx_media_ocr_record(stored: object) -> DocxMediaOcrRecord:
        from procurement.storage import DocxMediaOcrRecord as StoredDocxMediaOcrRecord

        checked = StoredDocxMediaOcrRecord.model_validate(stored)
        return DocxMediaOcrRecord(
            ocr_id=checked.ocr_id,
            source_document_id=checked.source_document_id,
            media_index=checked.media_index,
            archive_path=checked.archive_path,
            source_document_sha256=checked.source_document_sha256,
            source_media_sha256=checked.source_media_sha256,
            media_type=checked.media_type,
            engine=checked.engine,
            threshold=checked.threshold,
            result=checked.result,
            mean_confidence=checked.mean_confidence,
            created_at=checked.created_at,
        )

    @staticmethod
    def _ocr_record(stored: object) -> OcrDerivativeRecord:
        from procurement.storage import OcrDerivativeRecord as StoredOcrRecord

        checked = StoredOcrRecord.model_validate(stored)
        return OcrDerivativeRecord(
            ocr_id=checked.ocr_id,
            source_document_id=checked.source_document_id,
            engine=checked.engine,
            threshold=checked.threshold,
            result=OcrDerivative.model_validate(checked.result),
            mean_confidence=checked.mean_confidence,
            created_at=checked.created_at,
        )
