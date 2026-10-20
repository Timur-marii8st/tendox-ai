"""API boundary regressions: auth derives tenant identity and errors stay safe."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
import pytest
from docx import Document as DocxDocument
from pypdf import PdfWriter

from procurement.access import AccessRole
from procurement.api import create_app
from procurement.api.contracts import (
    AiRequirementReviewConflict,
    AiRequirementRunNotFound,
    AiTransferConflict,
    AiTransferDetail,
    AiTransferExecutionDetail,
    AiTransferNotFound,
    AiTransferRequirementBatchMaterializationDetail,
    CasePage,
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
    EvaluationRecord,
    InvalidAiRequirementReview,
    InvalidAiTransfer,
    InvalidCompletenessReview,
    InvalidDocumentSetEvidence,
    InvalidDocumentSetReview,
    InvalidModelBrandEvidence,
    ModelBrandCatalogRecord,
    ModelBrandReviewConflict,
    ModelBrandReviewDecisionRecord,
    ModelBrandReviewNotFound,
    ModelBrandReviewRecord,
    ModelBrandSourceArtifactRecord,
    Principal,
    VersionConflict,
)
from procurement.documents import (
    AiRequirementAnalysisReport,
    AiRequirementAnalysisReportV2,
    AiRequirementCandidateDecision,
    AiRequirementReviewRecord,
    AiRequirementTransferRunSnapshot,
    AiTransferRequirementMaterialization,
    AiTransferRequirementResult,
    CompletenessBlockDecision,
    CompletenessReviewRecord,
    CompletenessReviewSourceInvalid,
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
    ExtractionResult,
    ModelBrandCatalog,
    ModelBrandReviewProposal,
    ModelBrandReviewStatus,
    build_ai_requirement_review_decision,
    build_ai_requirement_run_snapshot,
    build_completeness_review_decision,
    build_completeness_review_snapshot,
    build_document_set_evidence_manifest,
    build_document_set_review_decision,
    build_document_set_review_evidence,
    canonical_json_sha256,
    search_documents,
)
from procurement.documents.ai_requirements import (
    DEFAULT_OPENROUTER_MODEL,
    AiRequirementError,
    OpenRouterJsonResponse,
    analyze_requirements_with_model,
    prepare_ai_requirements_transfer,
)
from procurement.documents.ai_transfer import (
    PersistedAiTransferApproval,
    PersistedAiTransferRequest,
    build_persisted_ai_transfer_approval,
    build_persisted_ai_transfer_request,
)
from procurement.documents.ai_transfer_execution import (
    AiTransferExecutionAdmission,
    build_ai_transfer_execution_admission,
)
from procurement.documents.ai_transfer_raw import AiTransferRawMetadata
from procurement.documents.extraction import ExtractedBlock, ExtractionStatus
from procurement.domain.cases import ProcurementCase
from procurement.domain.decisions import Recommendation
from procurement.domain.provenance import Extractor, Provenance
from procurement.domain.sourcing import (
    LeadStatus,
    ServerLead,
    ServerShortlist,
    ShortlistEntry,
    SourcingRunRecord,
    SourcingRunStatus,
)

PAPER_CASE = Path(__file__).parent.parent / "examples" / "paper_case.json"
AUTH_A = {"Authorization": "Bearer tenant-a-token"}
WRITE_HEADERS = {**AUTH_A, "Idempotency-Key": "request-001"}


class FakeAuthenticator:
    async def authenticate(self, credential: str) -> Principal | None:
        return {
            "transfer-approver": Principal(
                company_id="demo-company",
                actor_id="approver-a",
                access_role=AccessRole.AI_TRANSFER_APPROVER,
            ),
            "transfer-self-approver": Principal(
                company_id="demo-company",
                actor_id="proposal-author-a",
                access_role=AccessRole.AI_TRANSFER_APPROVER,
            ),
            "transfer-other-operator": Principal(
                company_id="demo-company", actor_id="other-operator"
            ),
            "transfer-foreign-approver": Principal(
                company_id="other-company",
                actor_id="approver-b",
                access_role=AccessRole.AI_TRANSFER_APPROVER,
            ),
            "tenant-a-token": Principal(
                company_id="demo-company",
                actor_id="operator-a",
                access_role=AccessRole.MODEL_BRAND_REVIEWER,
            ),
            "tenant-a-operator-token": Principal(
                company_id="demo-company",
                actor_id="proposal-author-a",
                access_role=AccessRole.OPERATOR,
            ),
            "tenant-a-completeness-reviewer-token": Principal(
                company_id="demo-company",
                actor_id="completeness-reviewer-a",
                access_role=AccessRole.COMPLETENESS_REVIEWER,
            ),
            "tenant-a-self-reviewer-token": Principal(
                company_id="demo-company",
                actor_id="proposal-author-a",
                access_role=AccessRole.COMPLETENESS_REVIEWER,
            ),
            "tenant-a-ai-reviewer-token": Principal(
                company_id="demo-company",
                actor_id="ai-reviewer-a",
                access_role=AccessRole.AI_REQUIREMENTS_REVIEWER,
            ),
            "tenant-a-ai-self-reviewer-token": Principal(
                company_id="demo-company",
                actor_id="ai-submitter-a",
                access_role=AccessRole.AI_REQUIREMENTS_REVIEWER,
            ),
            "tenant-b-ai-reviewer-token": Principal(
                company_id="other-company",
                actor_id="ai-reviewer-b",
                access_role=AccessRole.AI_REQUIREMENTS_REVIEWER,
            ),
            "tenant-a-auditor-token": Principal(
                company_id="demo-company",
                actor_id="auditor-a",
                access_role=AccessRole.AUDITOR,
            ),
            "tenant-b-auditor-token": Principal(
                company_id="other-company",
                actor_id="auditor-b",
                access_role=AccessRole.AUDITOR,
            ),
            "tenant-b-completeness-reviewer-token": Principal(
                company_id="other-company",
                actor_id="completeness-reviewer-b",
                access_role=AccessRole.COMPLETENESS_REVIEWER,
            ),
            "tenant-b-token": Principal(company_id="other-company", actor_id="operator-b"),
        }.get(credential)


class FakeCaseService:
    def __init__(self) -> None:
        self.ai_transfers: dict[tuple[str, str], AiTransferDetail] = {}
        self.ai_transfer_receipts: dict[tuple[str, str, str], tuple[str, str]] = {}
        self.ai_transfer_executions: dict[tuple[str, str], AiTransferExecutionDetail] = {}
        self.ai_transfer_raw_responses: dict[
            tuple[str, str], tuple[bytes, AiTransferRawMetadata]
        ] = {}
        self.ai_transfer_materializations: dict[
            tuple[str, str], AiTransferRequirementMaterialization
        ] = {}
        self.ai_transfer_materialize_calls: list[tuple[str, str, str]] = []
        self.ai_transfer_batch_materialize_calls: list[tuple[str, str, str]] = []
        self.cases: dict[tuple[str, str, int], ProcurementCase] = {}
        self.evaluations: dict[tuple[str, str, int], EvaluationRecord] = {}
        self.sourcing_runs: dict[tuple[str, str, int], SourcingRunRecord] = {}
        self.sourcing_calls: list[dict[str, object]] = []
        self.evaluation_calls: list[dict[str, object]] = []
        self.created_with: list[dict[str, object]] = []
        self.documents: dict[tuple[str, str], DocumentRecord] = {}
        self.document_contents: dict[tuple[str, str], bytes] = {}
        self.document_calls: list[dict[str, object]] = []
        self.completeness_reviews: dict[tuple[str, str], CompletenessReviewRecord] = {}
        self.completeness_review_receipts: dict[
            tuple[str, str, str], tuple[str, CompletenessReviewRecord]
        ] = {}
        self.document_set_evidence_manifests: dict[
            tuple[str, str], DocumentSetEvidenceManifest
        ] = {}
        self.document_set_evidence_receipts: dict[
            tuple[str, str], tuple[str, DocumentSetEvidenceManifest]
        ] = {}
        self.document_set_review_decisions: dict[tuple[str, str], DocumentSetReviewDecision] = {}
        self.document_set_review_receipts: dict[
            tuple[str, str], tuple[str, DocumentSetReviewDecision]
        ] = {}
        self.ai_requirement_runs: dict[tuple[str, str], AiRequirementReviewRecord] = {}
        self.ai_requirement_review_receipts: dict[
            tuple[str, str, str], tuple[str, AiRequirementReviewRecord]
        ] = {}
        self.ai_requirement_import_receipts: dict[
            tuple[str, str, str], tuple[str, AiRequirementReviewRecord]
        ] = {}
        self.document_search_indexes: dict[tuple[str, str], DocumentSearchIndexRecord] = {}
        self.document_search_receipts: dict[
            tuple[str, str], tuple[str, DocumentSearchIndexRecord]
        ] = {}
        self.model_brand_catalogs: dict[str, list[ModelBrandCatalogRecord]] = {}
        self.model_brand_receipts: dict[tuple[str, str], tuple[str, ModelBrandCatalogRecord]] = {}
        self.model_brand_source_artifacts: dict[
            tuple[str, str], ModelBrandSourceArtifactRecord
        ] = {}
        self.model_brand_source_contents: dict[tuple[str, str], bytes] = {}
        self.model_brand_source_receipts: dict[
            tuple[str, str], tuple[str, ModelBrandSourceArtifactRecord]
        ] = {}
        self.model_brand_reviews: dict[tuple[str, str], ModelBrandReviewRecord] = {}
        self.model_brand_review_receipts: dict[
            tuple[str, str, str], tuple[str, ModelBrandReviewRecord]
        ] = {}
        self.document_bundles: dict[tuple[str, str], DocumentBundleRecord] = {}
        self.document_bundle_contents: dict[tuple[str, str], bytes] = {}
        self.document_bundle_calls: list[dict[str, object]] = []
        self.document_bundle_receipts: dict[tuple[str, str], tuple[str, DocumentBundleRecord]] = {}

    async def create_case(
        self,
        *,
        company_id: str,
        case: ProcurementCase,
        idempotency_key: str,
        request_digest: str,
    ) -> ProcurementCase:
        key = (company_id, case.case_id, case.version)
        if key in self.cases:
            raise VersionConflict
        self.cases[key] = case
        self.created_with.append(
            {
                "company_id": company_id,
                "idempotency_key": idempotency_key,
                "request_digest": request_digest,
            }
        )
        return case

    async def get_case(
        self, *, company_id: str, case_id: str, version: int
    ) -> ProcurementCase | None:
        return self.cases.get((company_id, case_id, version))

    async def list_cases(self, *, company_id: str, cursor: str | None, limit: int) -> CasePage:
        items = tuple(case for (tenant, _, _), case in self.cases.items() if tenant == company_id)
        return CasePage(items=items[:limit])

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
        self.sourcing_calls.append(
            {
                "company_id": company_id,
                "actor_id": actor_id,
                "case_id": case_id,
                "version": version,
                "query": query,
                "idempotency_key": idempotency_key,
                "request_digest": request_digest,
            }
        )
        now = datetime.now(UTC)
        lead = ServerLead(
            lead_id="https://servermall.ru/catalog/servers/dl360/",
            supplier="ServerMall",
            product_name="HPE DL360 Gen12 8SFF",
            source_url="https://servermall.ru/sets/servery-hp-proliant-gen12/",
            product_url="https://servermall.ru/catalog/servers/dl360/",
            source_sha256="a" * 64,
            observed_at=now,
        )
        record = SourcingRunRecord(
            company_id=company_id,
            run_id=f"run-{len(self.sourcing_calls)}",
            case_id=case_id,
            case_version=version,
            query=query,
            source_name="ServerMall",
            source_url=lead.source_url,
            status=SourcingRunStatus.COMPLETED,
            source_sha256=lead.source_sha256,
            source_byte_size=123,
            observed_at=now,
            shortlist=ServerShortlist(
                review_queue=(
                    ShortlistEntry(
                        lead=lead,
                        status=LeadStatus.NEEDS_TECHNICAL_REVIEW,
                        assessment=None,
                        open_properties=(),
                    ),
                ),
                rejected=(),
            ),
            technical_scope_reason="Проверенный набор требований ещё не привязан.",
            created_at=now,
        )
        self.sourcing_runs[(company_id, case_id, version)] = record
        return record

    async def get_latest_sourcing_run(
        self, *, company_id: str, case_id: str, version: int
    ) -> SourcingRunRecord | None:
        return self.sourcing_runs.get((company_id, case_id, version))

    async def get_latest_evaluation(
        self,
        *,
        company_id: str,
        case_id: str,
        version: int,
    ) -> EvaluationRecord | None:
        return self.evaluations.get((company_id, case_id, version))

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
        self.evaluation_calls.append(
            {
                "company_id": company_id,
                "actor_id": actor_id,
                "case_id": case_id,
                "version": version,
                "idempotency_key": idempotency_key,
                "request_digest": request_digest,
            }
        )
        record = EvaluationRecord(
            evaluation_id=f"evaluation-{len(self.evaluation_calls)}",
            audit_event_id=f"audit-{len(self.evaluation_calls)}",
            recommendation=recommendation,
            engine_version=engine_version,
            input_digest=input_digest,
            effective_at=effective_at,
        )
        self.evaluations[(company_id, case_id, version)] = record
        return record

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
        record = DocumentRecord(
            document_id=document_id,
            original_filename=original_filename,
            media_type=media_type,
            document_role=document_role,
            byte_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            extraction=extraction,
            created_at=datetime.now(UTC),
        )
        self.documents[(company_id, document_id)] = record
        self.document_contents[(company_id, document_id)] = content
        self.document_calls.append(
            {
                "company_id": company_id,
                "actor_id": actor_id,
                "document_role": document_role,
                "idempotency_key": idempotency_key,
                "request_digest": request_digest,
                "content": content,
            }
        )
        return record

    async def get_document(
        self,
        *,
        company_id: str,
        document_id: str,
    ) -> DocumentRecord | None:
        return self.documents.get((company_id, document_id))

    async def get_document_content(
        self,
        *,
        company_id: str,
        document_id: str,
    ) -> bytes | None:
        return self.document_contents.get((company_id, document_id))

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
        receipt_key = (company_id, "create", idempotency_key)
        replay = self.completeness_review_receipts.get(receipt_key)
        if replay is not None:
            if replay[0] != request_digest:
                raise CompletenessReviewConflict
            return replay[1]
        document = self.documents.get((company_id, source_document_id))
        content = self.document_contents.get((company_id, source_document_id))
        if document is None or content is None:
            raise CompletenessReviewNotFound
        if hashlib.sha256(content).hexdigest() != document.sha256:
            raise InvalidCompletenessReview
        try:
            snapshot = build_completeness_review_snapshot(
                company_id=company_id,
                review_id=review_id,
                source_document_id=source_document_id,
                source_document_sha256=document.sha256,
                document_role=document.document_role,
                extraction=document.extraction,
                created_by=actor_id,
                created_at=datetime.now(UTC),
            )
        except CompletenessReviewSourceInvalid as error:
            raise InvalidCompletenessReview from error
        record = CompletenessReviewRecord(snapshot=snapshot)
        self.completeness_reviews[(company_id, review_id)] = record
        self.completeness_review_receipts[receipt_key] = (request_digest, record)
        return record

    async def get_completeness_review(
        self,
        *,
        company_id: str,
        review_id: str,
    ) -> CompletenessReviewRecord | None:
        return self.completeness_reviews.get((company_id, review_id))

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
        receipt_key = (company_id, idempotency_key)
        replay = self.document_set_evidence_receipts.get(receipt_key)
        if replay is not None:
            if replay[0] != request_digest:
                raise DocumentSetEvidenceConflict
            return replay[1]
        snapshots = []
        for review_id, evidence_sha256 in review_refs:
            record = self.completeness_reviews.get((company_id, review_id))
            if record is None:
                raise DocumentSetEvidenceNotFound
            if record.snapshot.evidence_sha256 != evidence_sha256:
                raise InvalidDocumentSetEvidence
            snapshots.append(record.snapshot)
        try:
            manifest = build_document_set_evidence_manifest(
                tuple(snapshots),
                company_id=company_id,
                manifest_id=manifest_id,
                scope=scope,
                created_by=actor_id,
                created_at=datetime.now(UTC),
            )
        except ValueError as error:
            raise InvalidDocumentSetEvidence from error
        self.document_set_evidence_manifests[(company_id, manifest_id)] = manifest
        self.document_set_evidence_receipts[receipt_key] = (request_digest, manifest)
        return manifest

    async def get_document_set_evidence_manifest(
        self,
        *,
        company_id: str,
        manifest_id: str,
    ) -> DocumentSetEvidenceManifest | None:
        return self.document_set_evidence_manifests.get((company_id, manifest_id))

    async def get_document_set_review_evidence(
        self,
        *,
        company_id: str,
        manifest_id: str,
    ) -> DocumentSetReviewEvidence | None:
        manifest = self.document_set_evidence_manifests.get((company_id, manifest_id))
        if manifest is None:
            return None
        records = tuple(
            self.completeness_reviews.get((company_id, member.completeness_review_id))
            for member in manifest.members
        )
        if any(record is None for record in records):
            raise DocumentSetReviewSourceMismatch
        try:
            return build_document_set_review_evidence(
                manifest,
                tuple(record for record in records if record is not None),
            )
        except ValueError as error:
            raise DocumentSetReviewSourceMismatch from error

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
        receipt_key = (company_id, idempotency_key)
        replay = self.document_set_review_receipts.get(receipt_key)
        if replay is not None:
            if replay[0] != request_digest:
                raise DocumentSetReviewConflict
            return replay[1]
        evidence = await self.get_document_set_review_evidence(
            company_id=company_id,
            manifest_id=manifest_id,
        )
        if evidence is None:
            raise DocumentSetReviewNotFound
        if evidence.manifest.evidence_sha256 != manifest_evidence_sha256:
            raise DocumentSetReviewConflict
        if (company_id, manifest_id) in self.document_set_review_decisions:
            raise DocumentSetReviewConflict
        try:
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
                decided_at=datetime.now(UTC),
            )
        except ValueError as error:
            raise InvalidDocumentSetReview from error
        self.document_set_review_decisions[(company_id, manifest_id)] = decision
        self.document_set_review_receipts[receipt_key] = (request_digest, decision)
        return decision

    async def get_document_set_review_decision(
        self,
        *,
        company_id: str,
        manifest_id: str,
    ) -> DocumentSetReviewDecision | None:
        return self.document_set_review_decisions.get((company_id, manifest_id))

    async def list_completeness_reviews(
        self,
        *,
        company_id: str,
        limit: int,
    ) -> tuple[CompletenessReviewRecord, ...]:
        return tuple(
            record
            for (tenant, _), record in self.completeness_reviews.items()
            if tenant == company_id
        )[:limit]

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
        receipt_key = (company_id, "decision", idempotency_key)
        replay = self.completeness_review_receipts.get(receipt_key)
        if replay is not None:
            if replay[0] != request_digest:
                raise CompletenessReviewConflict
            return replay[1]
        current = self.completeness_reviews.get((company_id, review_id))
        if current is None:
            raise CompletenessReviewNotFound
        if current.decision is not None or current.snapshot.created_by == reviewer_id:
            raise CompletenessReviewConflict
        if current.snapshot.evidence_sha256 != evidence_sha256:
            raise CompletenessReviewConflict
        document = self.documents.get((company_id, current.snapshot.source_document_id))
        content = self.document_contents.get((company_id, current.snapshot.source_document_id))
        if (
            document is None
            or content is None
            or hashlib.sha256(content).hexdigest() != current.snapshot.source_document_sha256
        ):
            raise InvalidCompletenessReview
        try:
            decision = build_completeness_review_decision(
                current.snapshot,
                status=status,
                scope=scope,
                reason=reason,
                block_decisions=block_decisions,
                decided_by=reviewer_id,
                decided_at=datetime.now(UTC),
                review_reference=f"document-completeness-review:{review_id}",
            )
        except ValueError as error:
            raise InvalidCompletenessReview from error
        record = CompletenessReviewRecord(snapshot=current.snapshot, decision=decision)
        self.completeness_reviews[(company_id, review_id)] = record
        self.completeness_review_receipts[receipt_key] = (request_digest, record)
        return record

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
        key = (company_id, "prepare", idempotency_key)
        replay = self.ai_transfer_receipts.get(key)
        if replay is not None:
            if replay[0] != request_digest:
                raise AiTransferConflict
            return self.ai_transfers[(company_id, replay[1])].request
        source = self.documents.get((company_id, source_document_id))
        if source is None:
            raise AiTransferNotFound
        if source.document_role is not DocumentRole.TENDER_REQUIREMENTS:
            raise InvalidAiTransfer
        try:
            prepared = build_persisted_ai_transfer_request(
                prepare_ai_requirements_transfer(
                    source.extraction,
                    company_id=company_id,
                    source_document_id=source_document_id,
                    source_sha256=source.sha256,
                    model=model,
                ),
                transfer_id=str(uuid.uuid4()),
                prepared_by=actor_id,
                prepared_at=datetime.now(UTC),
            )
        except (ValueError, AiRequirementError) as error:
            raise InvalidAiTransfer from error
        self.ai_transfers[(company_id, prepared.transfer_id)] = AiTransferDetail(request=prepared)
        self.ai_transfer_receipts[key] = (request_digest, prepared.transfer_id)
        return prepared

    async def get_ai_transfer_request(
        self,
        *,
        company_id: str,
        transfer_id: str,
    ) -> AiTransferDetail | None:
        return self.ai_transfers.get((company_id, transfer_id))

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
        current = self.ai_transfers.get((company_id, transfer_id))
        if current is None:
            raise AiTransferNotFound
        key = (company_id, "approve", idempotency_key)
        replay = self.ai_transfer_receipts.get(key)
        if replay is not None:
            if replay[0] != request_digest:
                raise AiTransferConflict
            assert current.approval is not None
            return current.approval
        if current.approval is not None or current.request.payload_sha256 != request_payload_sha256:
            raise AiTransferConflict
        try:
            approval = build_persisted_ai_transfer_approval(
                current.request, approved_by=actor_id, approved_at=datetime.now(UTC)
            )
        except ValueError as error:
            raise AiTransferConflict from error
        self.ai_transfers[(company_id, transfer_id)] = AiTransferDetail(
            request=current.request, approval=approval
        )
        self.ai_transfer_receipts[key] = (request_digest, transfer_id)
        return approval

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
        current = self.ai_transfers.get((company_id, transfer_id))
        if current is None:
            raise AiTransferNotFound
        if current.approval is None:
            raise AiTransferConflict
        key = (company_id, "admit", idempotency_key)
        replay = self.ai_transfer_receipts.get(key)
        if replay is not None:
            if replay[0] != request_digest:
                raise AiTransferConflict
            detail = self.ai_transfer_executions[(company_id, replay[1])]
            return detail.admission
        if (
            current.request.payload_sha256 != request_payload_sha256
            or current.request.prepared_by != actor_id
            or any(
                detail.admission.transfer_id == transfer_id
                for (tenant, _), detail in self.ai_transfer_executions.items()
                if tenant == company_id
            )
        ):
            raise AiTransferConflict
        try:
            admission = build_ai_transfer_execution_admission(
                current.request,
                current.approval,
                company_id=company_id,
                transfer_id=transfer_id,
                execution_id=str(uuid.uuid4()),
                admitted_by=actor_id,
                admitted_at=datetime.now(UTC),
                existing_admission=None,
            )
        except ValueError as error:
            raise AiTransferConflict from error
        self.ai_transfer_executions[(company_id, admission.execution_id)] = (
            AiTransferExecutionDetail(admission=admission)
        )
        self.ai_transfer_receipts[key] = (request_digest, admission.execution_id)
        return admission

    async def get_ai_transfer_execution(
        self,
        *,
        company_id: str,
        execution_id: str,
    ) -> AiTransferExecutionDetail | None:
        detail = self.ai_transfer_executions.get((company_id, execution_id))
        if detail is None:
            return None
        raw_response = next(
            (
                metadata
                for (tenant, _), (_, metadata) in self.ai_transfer_raw_responses.items()
                if tenant == company_id and metadata.execution_id == execution_id
            ),
            None,
        )
        return AiTransferExecutionDetail(
            admission=detail.admission,
            claim=detail.claim,
            receipt=detail.receipt,
            raw_response=raw_response,
        )

    async def read_ai_transfer_raw_response(
        self,
        *,
        company_id: str,
        actor_id: str,
        access_role: AccessRole,
        raw_response_id: str,
    ) -> tuple[bytes, AiTransferRawMetadata] | None:
        del actor_id, access_role
        return self.ai_transfer_raw_responses.get((company_id, raw_response_id))

    async def materialize_ai_transfer_requirement_run(
        self,
        *,
        company_id: str,
        actor_id: str,
        execution_id: str,
    ) -> tuple[AiTransferRequirementMaterialization, None]:
        execution = self.ai_transfer_executions.get((company_id, execution_id))
        if execution is None:
            raise AiTransferNotFound
        self.ai_transfer_materialize_calls.append((company_id, actor_id, execution_id))
        key = (company_id, execution_id)
        existing = self.ai_transfer_materializations.get(key)
        if existing is not None:
            return existing, None
        fields = {
            "company_id": company_id,
            "materialization_id": f"materialization-{execution_id}",
            "transfer_id": execution.admission.transfer_id,
            "execution_id": execution_id,
            "ordinal": 1,
            "claim_id": "claim-for-materialization",
            "receipt_id": "receipt-for-materialization",
            "raw_response_id": "raw-for-materialization",
            "request_payload_sha256": execution.admission.request_payload_sha256,
            "claim_payload_sha256": "a" * 64,
            "receipt_payload_sha256": "b" * 64,
            "raw_metadata_sha256": "c" * 64,
            "parser_version": "ai-transfer-requirement-parser-v1",
            "status": "REJECTED",
            "reason": "INVALID_CANDIDATE_EVIDENCE",
            "result_id": None,
            "result_payload_sha256": None,
            "run_id": None,
            "run_evidence_sha256": None,
            "materialized_by": actor_id,
            "materialized_at": datetime.now(UTC),
        }
        materialization = AiTransferRequirementMaterialization.model_validate(
            {
                **fields,
                "payload_sha256": canonical_json_sha256(
                    {"schema_version": "ai-transfer-requirement-materialization-v1", **fields}
                ),
            },
            strict=True,
        )
        self.ai_transfer_materializations[key] = materialization
        return materialization, None

    async def materialize_ai_transfer_requirement_batch(
        self,
        *,
        company_id: str,
        actor_id: str,
        execution_id: str,
    ) -> AiTransferRequirementBatchMaterializationDetail:
        if (company_id, execution_id) not in self.ai_transfer_executions:
            raise AiTransferNotFound
        self.ai_transfer_batch_materialize_calls.append((company_id, actor_id, execution_id))
        return AiTransferRequirementBatchMaterializationDetail(
            company_id=company_id,
            execution_id=execution_id,
            status="PENDING",
            materialized_ordinals=(),
        )

    async def get_ai_requirement_run(
        self, *, company_id: str, run_id: str
    ) -> AiRequirementReviewRecord | None:
        return self.ai_requirement_runs.get((company_id, run_id))

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
        receipt_key = (company_id, "import", idempotency_key)
        replay = self.ai_requirement_import_receipts.get(receipt_key)
        if replay is not None:
            if replay[0] != request_digest:
                raise AiRequirementReviewConflict
            return AiRequirementReviewRecord(snapshot=replay[1].snapshot)
        document = self.documents.get((company_id, source_document_id))
        content = self.document_contents.get((company_id, source_document_id))
        if document is None or content is None:
            raise AiRequirementRunNotFound
        if (
            document.document_role is not DocumentRole.TENDER_REQUIREMENTS
            or document.sha256 != hashlib.sha256(content).hexdigest()
            or document.byte_size != len(content)
        ):
            raise InvalidAiRequirementReview
        try:
            snapshot = build_ai_requirement_run_snapshot(
                company_id=company_id,
                run_id=str(uuid.uuid4()),
                source_document_id=source_document_id,
                source_sha256=document.sha256,
                extraction=document.extraction,
                report=report,
                submitted_by=actor_id,
                submitted_at=datetime.now(UTC),
            )
        except ValueError as error:
            raise InvalidAiRequirementReview from error
        record = AiRequirementReviewRecord(snapshot=snapshot)
        self.ai_requirement_runs[(company_id, snapshot.run_id)] = record
        self.ai_requirement_import_receipts[receipt_key] = (request_digest, record)
        return record

    async def list_ai_requirement_runs(
        self, *, company_id: str, limit: int
    ) -> tuple[AiRequirementReviewRecord, ...]:
        return tuple(
            record
            for (tenant, _), record in self.ai_requirement_runs.items()
            if tenant == company_id
        )[:limit]

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
        receipt_key = (company_id, "decision", idempotency_key)
        replay = self.ai_requirement_review_receipts.get(receipt_key)
        if replay is not None:
            if replay[0] != request_digest:
                raise AiRequirementReviewConflict
            return replay[1]
        current = self.ai_requirement_runs.get((company_id, run_id))
        if current is None:
            raise AiRequirementRunNotFound
        snapshot = current.snapshot
        if current.decision is not None or snapshot.submitted_by == reviewer_id:
            raise AiRequirementReviewConflict
        if snapshot.evidence_sha256 != evidence_sha256:
            raise AiRequirementReviewConflict
        document = self.documents.get((company_id, snapshot.source_document_id))
        content = self.document_contents.get((company_id, snapshot.source_document_id))
        if (
            document is None
            or content is None
            or document.sha256 != snapshot.source_sha256
            or hashlib.sha256(content).hexdigest() != snapshot.source_sha256
            or document.extraction != snapshot.extraction
        ):
            raise InvalidAiRequirementReview
        try:
            decision = build_ai_requirement_review_decision(
                snapshot,
                evidence_sha256=evidence_sha256,
                candidate_decisions=candidate_decisions,
                reviewed_by=reviewer_id,
                reviewed_at=datetime.now(UTC),
            )
        except ValueError as error:
            raise AiRequirementReviewConflict from error
        record = AiRequirementReviewRecord(snapshot=snapshot, decision=decision)
        self.ai_requirement_runs[(company_id, run_id)] = record
        self.ai_requirement_review_receipts[receipt_key] = (request_digest, record)
        return record

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
        receipt_key = (company_id, idempotency_key)
        replay = self.document_search_receipts.get(receipt_key)
        if replay is not None:
            if replay[0] != request_digest:
                raise VersionConflict
            return replay[1]
        record = DocumentSearchIndexRecord(
            search_index_id=search_index_id,
            source_document_id=source_document_id,
            source_document_sha256=entry.source_sha256,
            entry=entry,
            created_at=datetime.now(UTC),
        )
        self.document_search_indexes[(company_id, search_index_id)] = record
        self.document_search_receipts[receipt_key] = (request_digest, record)
        return record

    async def search_document_indexes(
        self,
        *,
        company_id: str,
        query: str,
        limit: int,
        effective_at: datetime,
    ) -> DocumentSearchPage:
        latest: dict[str, DocumentSearchIndexRecord] = {}
        for (tenant, _), record in self.document_search_indexes.items():
            if tenant == company_id:
                latest[record.source_document_id] = record
        entries = tuple(record.entry for record in tuple(latest.values())[:limit])
        catalogs = tuple(
            record
            for record in self.model_brand_catalogs.get(company_id, [])
            if record.created_at <= effective_at
        )
        catalog = catalogs[-1].catalog if catalogs else None
        return DocumentSearchPage(
            query=query,
            effective_at=effective_at,
            results=search_documents(
                entries,
                company_id=company_id,
                query=query,
                model_brand_catalog=catalog,
                at=effective_at if catalog is not None else None,
            ),
        )

    async def store_model_brand_catalog(
        self,
        *,
        company_id: str,
        actor_id: str,
        catalog: ModelBrandCatalog,
        idempotency_key: str,
        request_digest: str,
    ) -> ModelBrandCatalogRecord:
        receipt_key = (company_id, idempotency_key)
        replay = self.model_brand_receipts.get(receipt_key)
        if replay is not None:
            if replay[0] != request_digest:
                raise VersionConflict
            return replay[1]
        for entry in catalog.entries:
            artifact_id = entry.evidence.source_artifact_id
            artifact = (
                self.model_brand_source_artifacts.get((company_id, artifact_id))
                if artifact_id is not None
                else None
            )
            content = (
                self.model_brand_source_contents.get((company_id, artifact_id))
                if artifact_id is not None
                else None
            )
            if (
                artifact is None
                or content is None
                or artifact.source_title != entry.evidence.source_title
                or artifact.source_url != str(entry.evidence.source_url)
                or artifact.sha256 != entry.evidence.source_document_sha256
                or artifact.retrieved_at != entry.evidence.retrieved_at
                or hashlib.sha256(content).hexdigest() != artifact.sha256
            ):
                raise InvalidModelBrandEvidence
        record = ModelBrandCatalogRecord(catalog=catalog, created_at=catalog.created_at)
        self.model_brand_catalogs.setdefault(company_id, []).append(record)
        self.model_brand_receipts[receipt_key] = (request_digest, record)
        return record

    async def get_latest_model_brand_catalog(
        self,
        *,
        company_id: str,
        effective_at: datetime,
    ) -> ModelBrandCatalogRecord | None:
        records = tuple(
            record
            for record in self.model_brand_catalogs.get(company_id, [])
            if record.created_at <= effective_at
        )
        return records[-1] if records else None

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
        del actor_id
        receipt_key = (company_id, idempotency_key)
        replay = self.model_brand_source_receipts.get(receipt_key)
        if replay is not None:
            if replay[0] != request_digest:
                raise VersionConflict
            return replay[1]
        now = datetime.now(UTC)
        record = ModelBrandSourceArtifactRecord(
            artifact_id=artifact_id,
            source_title=source_title,
            source_url=source_url,
            original_filename=original_filename,
            media_type="application/pdf",
            byte_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            retrieved_at=retrieved_at,
            created_at=now,
        )
        self.model_brand_source_artifacts[(company_id, artifact_id)] = record
        self.model_brand_source_contents[(company_id, artifact_id)] = content
        self.model_brand_source_receipts[receipt_key] = (request_digest, record)
        return record

    async def get_model_brand_source_artifact(
        self,
        *,
        company_id: str,
        artifact_id: str,
    ) -> ModelBrandSourceArtifactRecord | None:
        return self.model_brand_source_artifacts.get((company_id, artifact_id))

    def _model_brand_evidence_is_valid(
        self,
        company_id: str,
        proposal: ModelBrandReviewProposal,
    ) -> bool:
        for entry in proposal.entries:
            artifact_id = entry.evidence.source_artifact_id
            if artifact_id is None:
                return False
            artifact = self.model_brand_source_artifacts.get((company_id, artifact_id))
            content = self.model_brand_source_contents.get((company_id, artifact_id))
            if (
                artifact is None
                or content is None
                or artifact.source_title != entry.evidence.source_title
                or artifact.source_url != str(entry.evidence.source_url)
                or artifact.sha256 != entry.evidence.source_document_sha256
                or artifact.retrieved_at != entry.evidence.retrieved_at
                or hashlib.sha256(content).hexdigest() != artifact.sha256
            ):
                return False
        return True

    async def store_model_brand_review_proposal(
        self,
        *,
        company_id: str,
        actor_id: str,
        proposal: ModelBrandReviewProposal,
        idempotency_key: str,
        request_digest: str,
    ) -> ModelBrandReviewRecord:
        del actor_id
        receipt_key = (company_id, "submit", idempotency_key)
        replay = self.model_brand_review_receipts.get(receipt_key)
        if replay is not None:
            if replay[0] != request_digest:
                raise ModelBrandReviewConflict
            return replay[1]
        if not self._model_brand_evidence_is_valid(company_id, proposal):
            raise InvalidModelBrandEvidence
        record = ModelBrandReviewRecord(proposal=proposal, status=ModelBrandReviewStatus.DRAFT)
        self.model_brand_reviews[(company_id, proposal.proposal_id)] = record
        self.model_brand_review_receipts[receipt_key] = (request_digest, record)
        return record

    async def list_model_brand_reviews(
        self,
        *,
        company_id: str,
        limit: int,
    ) -> tuple[ModelBrandReviewRecord, ...]:
        return tuple(
            record
            for (tenant, _), record in self.model_brand_reviews.items()
            if tenant == company_id
        )[:limit]

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
        receipt_key = (company_id, "decision", idempotency_key)
        replay = self.model_brand_review_receipts.get(receipt_key)
        if replay is not None:
            if replay[0] != request_digest:
                raise ModelBrandReviewConflict
            return replay[1]
        current = self.model_brand_reviews.get((company_id, proposal_id))
        if current is None:
            raise ModelBrandReviewNotFound
        if current.status is not ModelBrandReviewStatus.DRAFT:
            raise ModelBrandReviewConflict
        if current.proposal.submitted_by == reviewer_id:
            raise ModelBrandReviewConflict
        if not self._model_brand_evidence_is_valid(company_id, current.proposal):
            raise InvalidModelBrandEvidence
        catalog_id = (
            current.proposal.catalog_id if decision is ModelBrandReviewStatus.APPROVED else None
        )
        if catalog_id is not None:
            catalog = ModelBrandCatalog(
                catalog_id=catalog_id,
                company_id=company_id,
                created_at=datetime.now(UTC),
                approved_by=reviewer_id,
                approval_reference=current.proposal.approval_reference,
                entries=current.proposal.entries,
            )
            self.model_brand_catalogs.setdefault(company_id, []).append(
                ModelBrandCatalogRecord(catalog=catalog, created_at=catalog.created_at)
            )
        decision_record = ModelBrandReviewDecisionRecord(
            proposal_id=proposal_id,
            status=decision,
            decided_by=reviewer_id,
            reason=reason,
            catalog_id=catalog_id,
            created_at=datetime.now(UTC),
        )
        record = ModelBrandReviewRecord(
            proposal=current.proposal,
            status=decision,
            decision=decision_record,
        )
        self.model_brand_reviews[(company_id, proposal_id)] = record
        self.model_brand_review_receipts[receipt_key] = (request_digest, record)
        return record

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
        receipt_key = (company_id, idempotency_key)
        replay = self.document_bundle_receipts.get(receipt_key)
        if replay is not None:
            if replay[0] != request_digest:
                raise VersionConflict
            return replay[1]
        record = DocumentBundleRecord(
            bundle_id=bundle_id,
            original_filename=original_filename,
            media_type=media_type,
            document_role=document_role,
            byte_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            result=result,
            created_at=datetime.now(UTC),
        )
        self.document_bundles[(company_id, bundle_id)] = record
        self.document_bundle_contents[(company_id, bundle_id)] = content
        self.document_bundle_calls.append(
            {
                "company_id": company_id,
                "actor_id": actor_id,
                "document_role": document_role,
                "idempotency_key": idempotency_key,
                "request_digest": request_digest,
                "content": content,
            }
        )
        self.document_bundle_receipts[receipt_key] = (request_digest, record)
        return record

    async def get_document_bundle(
        self,
        *,
        company_id: str,
        bundle_id: str,
    ) -> DocumentBundleRecord | None:
        return self.document_bundles.get((company_id, bundle_id))

    async def get_document_bundle_content(
        self,
        *,
        company_id: str,
        bundle_id: str,
    ) -> bytes | None:
        return self.document_bundle_contents.get((company_id, bundle_id))


def paper_case_payload() -> dict[str, Any]:
    return json.loads(PAPER_CASE.read_text(encoding="utf-8"))


def other_tenant_case() -> ProcurementCase:
    payload = paper_case_payload()
    payload["case_id"] = "other-case"
    payload["company_id"] = "other-company"
    payload["profile"]["company_id"] = "other-company"
    payload["selected_quote"]["company_id"] = "other-company"
    return ProcurementCase.model_validate(payload)


@pytest.fixture
def service() -> FakeCaseService:
    service = FakeCaseService()
    case = other_tenant_case()
    service.cases[(case.company_id, case.case_id, case.version)] = case
    return service


@pytest.fixture
def app(service: FakeCaseService):
    return create_app(service, FakeAuthenticator())


def request(app: object, method: str, url: str, **kwargs: object) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, url, **kwargs)

    return asyncio.run(send())


def docx_bytes(text: str) -> bytes:
    document = DocxDocument()
    document.add_paragraph(text)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def blank_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def zip_bytes(entries: tuple[tuple[str, bytes], ...]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return output.getvalue()


class _AiRequirementApiClient:
    def complete_json(self, **kwargs: object) -> OpenRouterJsonResponse:
        model = kwargs["model"]
        assert isinstance(model, str)
        return OpenRouterJsonResponse(
            request_sha256="a" * 64,
            response_id="provider-response-private",
            model=model,
            content=json.dumps(
                {
                    "items": [],
                    "requirements": [
                        {
                            "item_name": None,
                            "property": "warranty",
                            "operator": ">=",
                            "value": "24",
                            "unit": "мес",
                            "mandatory": True,
                            "source_block_ids": ["b000001"],
                            "uncertainty": None,
                        }
                    ],
                    "unresolved_block_ids": [],
                    "document_notes": [],
                },
                ensure_ascii=False,
            ),
        )


def _seed_ai_requirement_run(
    service: FakeCaseService,
    *,
    company_id: str = "demo-company",
    run_id: str = "ai-run-1",
    submitted_by: str = "ai-submitter-a",
) -> AiRequirementReviewRecord:
    content = b"Warranty not less than 24 months"
    source_sha256 = hashlib.sha256(content).hexdigest()
    document_id = f"source-{run_id}"
    block = ExtractedBlock(
        text="Warranty not less than 24 months",
        provenance=Provenance(
            document_id=document_id,
            locator="paragraph 1",
            extractor=Extractor.NATIVE_DOCX,
            confidence=1,
        ),
    )
    extraction = ExtractionResult(
        status=ExtractionStatus.PASS,
        blocks=(block,),
        reasons=(),
        source_units_total=1,
        source_units_extracted=1,
        characters_extracted=len(block.text),
    )
    report = analyze_requirements_with_model(
        extraction,
        company_id=company_id,
        source_sha256=source_sha256,
        authorization_reference="private-external-transfer-approval",
        client=_AiRequirementApiClient(),
        created_at=datetime(2026, 9, 17, 10, tzinfo=UTC),
    )
    snapshot = build_ai_requirement_run_snapshot(
        company_id=company_id,
        run_id=run_id,
        source_document_id=document_id,
        source_sha256=source_sha256,
        extraction=extraction,
        report=report,
        submitted_by=submitted_by,
        submitted_at=datetime(2026, 9, 17, 11, tzinfo=UTC),
    )
    service.documents[(company_id, document_id)] = DocumentRecord(
        document_id=document_id,
        original_filename="requirements.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        document_role=DocumentRole.TENDER_REQUIREMENTS,
        byte_size=len(content),
        sha256=source_sha256,
        extraction=extraction,
        created_at=datetime.now(UTC),
    )
    service.document_contents[(company_id, document_id)] = content
    record = AiRequirementReviewRecord(snapshot=snapshot)
    service.ai_requirement_runs[(company_id, run_id)] = record
    return record


def _importable_ai_report(
    service: FakeCaseService,
    *,
    run_id: str,
    schema_version: str = "ai-requirement-analysis-v2",
) -> tuple[str, AiRequirementAnalysisReport | AiRequirementAnalysisReportV2]:
    seeded = _seed_ai_requirement_run(service, run_id=run_id)
    service.ai_requirement_runs.pop(("demo-company", run_id))
    report = seeded.snapshot.report
    if schema_version == "ai-requirement-analysis-v2":
        assert isinstance(report, AiRequirementAnalysisReportV2)
        return seeded.snapshot.source_document_id, report
    payload = report.model_dump(mode="json")
    payload["schema_version"] = "ai-requirement-analysis-v1"
    payload["prompt_version"] = "ai-requirements-v1"
    payload.pop("item_candidates", None)
    for chunk in payload["chunks"]:
        chunk.pop("item_candidates", None)
    payload["evidence_sha256"] = canonical_json_sha256(
        {key: value for key, value in payload.items() if key != "evidence_sha256"}
    )
    return seeded.snapshot.source_document_id, AiRequirementAnalysisReport.model_validate(payload)


def test_health_is_public_and_openapi_has_no_tenant_auth_header(app: object) -> None:
    assert request(app, "GET", "/health").json() == {"status": "ok"}

    schema = request(app, "GET", "/openapi.json").json()
    parameters = schema["paths"]["/v1/cases"]["post"].get("parameters", [])
    tenant_headers = {"company", "company-id", "x-company-id"}
    assert not any(parameter["name"].lower() in tenant_headers for parameter in parameters)
    manifest_body = schema["paths"]["/v1/document-set-evidence-manifests"]["post"]["requestBody"]
    assert manifest_body["required"] is True
    manifest_schema = manifest_body["content"]["application/json"]["schema"]
    assert set(manifest_schema["required"]) == {"scope", "review_refs"}
    assert "$ref" not in json.dumps(manifest_schema)
    assert manifest_schema["properties"]["review_refs"]["items"]["required"] == [
        "review_id",
        "evidence_sha256",
    ]
    review_body = schema["paths"]["/v1/document-sets/{manifest_id}/completeness-decisions"]["post"][
        "requestBody"
    ]
    review_schema = review_body["content"]["application/json"]["schema"]
    assert "$ref" not in json.dumps(review_schema)
    assert "$defs" not in review_schema
    attestation = review_schema["properties"]["attestations"]["items"]
    assert set(attestation["required"]) == {"reference", "assessment", "rationale"}
    assert set(attestation["properties"]["reference"]["required"]) == {
        "member_ordinal",
        "review_id",
        "review_evidence_sha256",
        "decision_sha256",
    }
    assert review_schema["properties"]["inventory_assessment"]["enum"] == [
        "CONFIRMED_FOR_DECLARED_SCOPE",
        "UNRESOLVED",
    ]
    assert review_schema["properties"]["cross_document_assessment"]["enum"] == [
        "CHECKED_NO_OPEN_ISSUES",
        "OPEN_ISSUES",
        "UNRESOLVED",
    ]
    finding = review_schema["properties"]["reviewer_findings"]["items"]
    assert finding["properties"]["origin"]["enum"] == ["REVIEWER"]
    assert finding["properties"]["evidence"]["items"]["oneOf"]


def test_missing_and_invalid_bearer_have_identical_safe_error(app: object) -> None:
    missing = request(app, "GET", "/v1/cases")
    invalid = request(app, "GET", "/v1/cases", headers={"Authorization": "Bearer wrong-secret"})

    assert missing.status_code == invalid.status_code == 401
    assert missing.json() == invalid.json() == {"detail": "invalid_credentials"}
    assert missing.headers["www-authenticate"] == invalid.headers["www-authenticate"] == "Bearer"
    assert "wrong-secret" not in invalid.text


def test_create_rejects_body_tenant_mismatch_even_with_tenant_header(
    app: object, service: FakeCaseService
) -> None:
    payload = paper_case_payload()
    payload["company_id"] = "other-company"
    payload["profile"]["company_id"] = "other-company"
    payload["selected_quote"]["company_id"] = "other-company"

    response = request(
        app,
        "POST",
        "/v1/cases",
        headers={**WRITE_HEADERS, "X-Company-ID": "other-company"},
        json=payload,
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "tenant_mismatch"}
    assert not service.created_with


def test_case_bound_sourcing_run_is_persisted_and_tenant_scoped(
    app: object, service: FakeCaseService
) -> None:
    case = ProcurementCase.model_validate(paper_case_payload())
    service.cases[(case.company_id, case.case_id, case.version)] = case
    path = f"/v1/cases/{case.case_id}/versions/{case.version}/sourcing-runs"

    created = request(
        app,
        "POST",
        path,
        headers=WRITE_HEADERS,
        json={"query": "DL360   Gen12"},
    )

    assert created.status_code == 201
    assert created.json()["query"] == "DL360 Gen12"
    assert created.json()["status"] == "COMPLETED"
    assert created.json()["technical_scope_status"] == "UNKNOWN"
    assert len(created.json()["shortlist"]["review_queue"]) == 1
    assert service.sourcing_calls[0]["company_id"] == "demo-company"

    latest = request(app, "GET", f"{path}/latest", headers=AUTH_A)
    foreign = request(
        app,
        "GET",
        f"{path}/latest",
        headers={"Authorization": "Bearer tenant-b-token"},
    )
    assert latest.status_code == 200
    assert latest.json()["run_id"] == created.json()["run_id"]
    assert foreign.status_code == 404


def test_sourcing_query_is_bounded_before_service_call(
    app: object, service: FakeCaseService
) -> None:
    case = ProcurementCase.model_validate(paper_case_payload())
    service.cases[(case.company_id, case.case_id, case.version)] = case
    path = f"/v1/cases/{case.case_id}/versions/{case.version}/sourcing-runs"

    response = request(
        app,
        "POST",
        path,
        headers=WRITE_HEADERS,
        json={"query": "one two three four five six"},
    )

    assert response.status_code == 422
    assert service.sourcing_calls == []


def test_cross_tenant_guessed_path_is_indistinguishable_from_missing(app: object) -> None:
    guessed = request(app, "GET", "/v1/cases/other-case/versions/1", headers=AUTH_A)
    missing = request(app, "GET", "/v1/cases/not-there/versions/1", headers=AUTH_A)

    assert guessed.status_code == missing.status_code == 404
    assert guessed.json() == missing.json() == {"detail": "not_found"}


def test_list_is_scoped_and_duplicate_immutable_version_conflicts(app: object) -> None:
    payload = paper_case_payload()
    created = request(app, "POST", "/v1/cases", headers=WRITE_HEADERS, json=payload)
    duplicate = request(
        app,
        "POST",
        "/v1/cases",
        headers={**AUTH_A, "Idempotency-Key": "request-002"},
        json=payload,
    )
    listed = request(app, "GET", "/v1/cases?limit=1", headers=AUTH_A)

    assert created.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "version_conflict"}
    assert [item["case_id"] for item in listed.json()["items"]] == ["synthetic-case-001"]


def test_evaluation_uses_authenticated_actor_and_rejects_client_actor(
    app: object, service: FakeCaseService
) -> None:
    payload = paper_case_payload()
    assert request(app, "POST", "/v1/cases", headers=WRITE_HEADERS, json=payload).status_code == 201

    path = "/v1/cases/synthetic-case-001/versions/1/evaluations"
    malformed = request(
        app,
        "POST",
        path,
        headers={**AUTH_A, "Idempotency-Key": "evaluation-001"},
        json={"effective_at": "2026-09-08T12:00:00+03:00", "actor_id": "attacker"},
    )
    assert malformed.status_code == 422
    assert malformed.json() == {"detail": "validation_error"}
    assert not service.evaluation_calls

    response = request(
        app,
        "POST",
        path,
        headers={**AUTH_A, "Idempotency-Key": "evaluation-002"},
        json={"effective_at": "2026-10-01T12:00:00+03:00"},
    )

    assert response.status_code == 201
    assert response.json()["recommendation"]["decision"] == "do_not_participate"
    assert response.json()["engine_version"] == "s1"
    assert response.json()["audit_event_id"] == "audit-1"
    assert len(response.json()["input_digest"]) == 64
    assert len(service.evaluation_calls) == 1
    call = service.evaluation_calls[0]
    assert call["company_id"] == "demo-company"
    assert call["actor_id"] == "operator-a"
    assert call["case_id"] == "synthetic-case-001"
    assert call["version"] == 1
    assert call["idempotency_key"] == "evaluation-002"
    assert isinstance(call["request_digest"], str) and len(call["request_digest"]) == 64


def test_naive_time_float_and_invalid_idempotency_are_sanitized(app: object) -> None:
    path = "/v1/cases/synthetic-case-001/versions/1/evaluations"
    naive = request(
        app,
        "POST",
        path,
        headers={**AUTH_A, "Idempotency-Key": "evaluation-003"},
        json={"effective_at": "2026-09-08T12:00:00"},
    )
    assert naive.status_code == 422
    assert naive.json() == {"detail": "validation_error"}

    invalid_money = paper_case_payload()
    invalid_money["nmck_ex_vat"] = 1.5
    invalid = request(app, "POST", "/v1/cases", headers=WRITE_HEADERS, json=invalid_money)
    assert invalid.status_code == 422
    assert invalid.json() == {"detail": "validation_error"}

    bad_key = request(
        app,
        "POST",
        "/v1/cases",
        headers={**AUTH_A, "Idempotency-Key": "contains space"},
        json=paper_case_payload(),
    )
    assert bad_key.status_code == 422
    assert bad_key.json() == {"detail": "validation_error"}


def test_latest_evaluation_returns_only_the_persisted_record(
    app: object,
    service: FakeCaseService,
) -> None:
    case = ProcurementCase.model_validate(paper_case_payload())
    service.cases[(case.company_id, case.case_id, case.version)] = case
    latest_path = f"/v1/cases/{case.case_id}/versions/{case.version}/evaluations/latest"

    absent = request(app, "GET", latest_path, headers=AUTH_A)
    assert absent.status_code == 404
    assert absent.json() == {"detail": "not_found"}
    assert not service.evaluation_calls

    created = request(
        app,
        "POST",
        f"/v1/cases/{case.case_id}/versions/{case.version}/evaluations",
        headers={**AUTH_A, "Idempotency-Key": "latest-evaluation"},
        json={"effective_at": "2026-09-08T12:00:00+03:00"},
    )
    latest = request(app, "GET", latest_path, headers=AUTH_A)

    assert created.status_code == 201
    assert latest.status_code == 200
    assert latest.json() == created.json()
    assert len(service.evaluation_calls) == 1


def test_latest_evaluation_cross_tenant_and_absent_are_identical(
    app: object,
    service: FakeCaseService,
) -> None:
    created = request(
        app,
        "POST",
        "/v1/cases/other-case/versions/1/evaluations",
        headers={
            "Authorization": "Bearer tenant-b-token",
            "Idempotency-Key": "tenant-b-eval",
        },
        json={"effective_at": "2026-09-08T12:00:00+03:00"},
    )
    assert created.status_code == 201

    guessed = request(
        app,
        "GET",
        "/v1/cases/other-case/versions/1/evaluations/latest",
        headers={**AUTH_A, "X-Company-ID": "other-company"},
    )
    missing = request(
        app,
        "GET",
        "/v1/cases/not-there/versions/1/evaluations/latest",
        headers=AUTH_A,
    )
    assert guessed.status_code == missing.status_code == 404
    assert guessed.json() == missing.json() == {"detail": "not_found"}


def test_document_upload_extracts_provenance_and_never_returns_source_bytes(
    app: object,
    service: FakeCaseService,
) -> None:
    response = request(
        app,
        "POST",
        "/v1/documents",
        headers={**AUTH_A, "Idempotency-Key": "document-001"},
        files={
            "file": (
                "technical-specification.docx",
                docx_bytes("Paper A4, 500 sheets"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"document_role": DocumentRole.TENDER_REQUIREMENTS.value},
    )

    assert response.status_code == 201
    payload = response.json()
    assert "content" not in payload
    assert payload["extraction"]["status"] == "PASS"
    assert payload["document_role"] == "TENDER_REQUIREMENTS"
    assert payload["extraction"]["blocks"][0]["text"] == "Paper A4, 500 sheets"
    assert payload["extraction"]["blocks"][0]["provenance"]["document_id"] == payload["document_id"]
    assert service.document_calls[0]["actor_id"] == "operator-a"
    assert service.document_calls[0]["document_role"] is DocumentRole.TENDER_REQUIREMENTS
    assert len(str(service.document_calls[0]["request_digest"])) == 64

    loaded = request(
        app,
        "GET",
        f"/v1/documents/{payload['document_id']}",
        headers=AUTH_A,
    )
    assert loaded.status_code == 200
    assert loaded.json() == payload


def test_document_search_index_is_idempotent_searchable_and_tenant_scoped(
    app: object,
) -> None:
    uploaded = request(
        app,
        "POST",
        "/v1/documents",
        headers={**AUTH_A, "Idempotency-Key": "search-source"},
        files={
            "file": (
                "ТЗ_ремонт_кондиционеров.docx",
                docx_bytes("Выполнение работ по кондиционированию здания"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"document_role": DocumentRole.TENDER_REQUIREMENTS.value},
    )
    assert uploaded.status_code == 201
    document_id = uploaded.json()["document_id"]
    path = f"/v1/documents/{document_id}/search-indexes"
    headers = {**AUTH_A, "Idempotency-Key": "search-index-1"}
    body = {"title": "Ремонт систем кондиционирования"}

    created = request(app, "POST", path, headers=headers, json=body)
    replay = request(app, "POST", path, headers=headers, json=body)

    assert created.status_code == replay.status_code == 201
    assert replay.json() == created.json()
    assert "content" not in created.json()
    assert created.json()["entry"]["company_id"] == "demo-company"

    found = request(
        app,
        "GET",
        "/v1/document-search",
        headers=AUTH_A,
        params={"query": "кондиционирование"},
    )
    foreign = request(
        app,
        "GET",
        "/v1/document-search",
        headers={"Authorization": "Bearer tenant-b-token"},
        params={"query": "кондиционирование"},
    )

    assert found.status_code == foreign.status_code == 200
    assert found.json()["results"][0]["document_id"] == document_id
    assert found.json()["results"][0]["status"] == "PASS"
    assert {hit["source_kind"] for hit in found.json()["results"][0]["hits"]} == {
        "TITLE",
        "FILENAME",
        "NATIVE_TEXT",
    }
    assert foreign.json()["results"] == []

    conflict = request(
        app,
        "POST",
        path,
        headers=headers,
        json={"title": "Другое название"},
    )
    assert conflict.status_code == 409


def test_document_search_index_hides_foreign_and_missing_sources(app: object) -> None:
    foreign_headers = {
        "Authorization": "Bearer tenant-b-token",
        "Idempotency-Key": "foreign-search-index",
    }
    foreign = request(
        app,
        "POST",
        "/v1/documents/unknown-document/search-indexes",
        headers=foreign_headers,
        json={},
    )
    missing = request(
        app,
        "POST",
        "/v1/documents/unknown-document/search-indexes",
        headers={**AUTH_A, "Idempotency-Key": "missing-search-index"},
        json={},
    )

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == {"detail": "not_found"}


def test_reviewed_model_brand_catalog_requires_workflow_and_is_searchable(
    app: object,
) -> None:
    source_pdf = blank_pdf_bytes()
    artifact_headers = {**AUTH_A, "Idempotency-Key": "model-brand-artifact-1"}
    artifact_upload = {"file": ("official-manual.pdf", source_pdf, "application/pdf")}
    artifact_data = {
        "source_title": "Official installation manual",
        "source_url": "https://manufacturer.example/manual.pdf",
    }
    artifact_created = request(
        app,
        "POST",
        "/v1/model-brand-source-artifacts",
        headers=artifact_headers,
        files=artifact_upload,
        data=artifact_data,
    )
    artifact_replay = request(
        app,
        "POST",
        "/v1/model-brand-source-artifacts",
        headers=artifact_headers,
        files=artifact_upload,
        data=artifact_data,
    )
    assert artifact_created.status_code == artifact_replay.status_code == 201
    assert artifact_created.json() == artifact_replay.json()
    artifact = artifact_created.json()
    assert "content" not in artifact
    assert artifact["sha256"] == hashlib.sha256(source_pdf).hexdigest()
    changed_artifact = request(
        app,
        "POST",
        "/v1/model-brand-source-artifacts",
        headers=artifact_headers,
        files=artifact_upload,
        data=artifact_data | {"source_title": "Changed title"},
    )
    invalid_artifact = request(
        app,
        "POST",
        "/v1/model-brand-source-artifacts",
        headers={**AUTH_A, "Idempotency-Key": "model-brand-artifact-invalid"},
        files={"file": ("not-a-pdf.pdf", b"not a PDF", "application/pdf")},
        data=artifact_data,
    )
    assert changed_artifact.status_code == 409
    assert invalid_artifact.status_code == 422
    assert (
        request(
            app,
            "GET",
            f"/v1/model-brand-source-artifacts/{artifact['artifact_id']}",
            headers={"Authorization": "Bearer tenant-b-token"},
        ).status_code
        == 404
    )

    entry = {
        "entry_id": "general-climate-gw-g140-n1a1",
        "model": "GW-G140/N1A1",
        "brand": "General Climate",
        "valid_from": "2026-01-01T00:00:00Z",
        "valid_to": None,
        "evidence": {
            "source_kind": "OFFICIAL_MANUFACTURER",
            "source_artifact_id": artifact["artifact_id"],
            "source_title": "Official installation manual",
            "source_url": "https://manufacturer.example/manual.pdf",
            "source_document_sha256": artifact["sha256"],
            "locator": "model table, row 140",
            "retrieved_at": artifact["retrieved_at"],
        },
    }
    body = {
        "catalog_id": "catalog-20260916-01",
        "approval_reference": "review/model-brand/20260916-01",
        "entries": [entry],
    }
    direct = request(
        app,
        "POST",
        "/v1/model-brand-catalogs",
        headers={**AUTH_A, "Idempotency-Key": "model-brand-direct"},
        json=body,
    )
    assert direct.status_code == 404

    operator_auth = {"Authorization": "Bearer tenant-a-operator-token"}
    submitted = request(
        app,
        "POST",
        "/v1/model-brand-reviews",
        headers={**operator_auth, "Idempotency-Key": "model-brand-submit"},
        json=body,
    )
    assert submitted.status_code == 201
    proposal_id = submitted.json()["proposal"]["proposal_id"]
    decision_headers = {**AUTH_A, "Idempotency-Key": "model-brand-approve"}
    approved = request(
        app,
        "POST",
        f"/v1/model-brand-reviews/{proposal_id}/decision",
        headers=decision_headers,
        json={"decision": "APPROVED", "reason": "Exact source verified"},
    )
    replay = request(
        app,
        "POST",
        f"/v1/model-brand-reviews/{proposal_id}/decision",
        headers=decision_headers,
        json={"decision": "APPROVED", "reason": "Exact source verified"},
    )
    assert approved.status_code == replay.status_code == 200
    assert replay.json() == approved.json()

    changed_submission = request(
        app,
        "POST",
        "/v1/model-brand-reviews",
        headers={**operator_auth, "Idempotency-Key": "model-brand-submit"},
        json=body | {"entries": [entry | {"brand": "Another Brand"}]},
    )
    assert changed_submission.status_code == 409

    unverified_entry = entry | {
        "evidence": entry["evidence"] | {"source_document_sha256": "a" * 64}
    }
    unverified = request(
        app,
        "POST",
        "/v1/model-brand-reviews",
        headers={**operator_auth, "Idempotency-Key": "model-brand-unverified"},
        json=body | {"catalog_id": "catalog-unverified", "entries": [unverified_entry]},
    )
    assert unverified.status_code == 422
    assert unverified.json() == {"detail": "invalid_model_brand_source_evidence"}

    latest = request(app, "GET", "/v1/model-brand-catalogs/latest", headers=AUTH_A)
    foreign = request(
        app,
        "GET",
        "/v1/model-brand-catalogs/latest",
        headers={"Authorization": "Bearer tenant-b-token"},
    )
    assert latest.status_code == 200
    assert latest.json()["catalog"]["company_id"] == "demo-company"
    assert latest.json()["catalog"]["approved_by"] == "operator-a"
    assert foreign.status_code == 404

    uploaded = request(
        app,
        "POST",
        "/v1/documents",
        headers={**AUTH_A, "Idempotency-Key": "model-brand-source"},
        files={
            "file": (
                "specification.docx",
                docx_bytes("Наружный блок GW-G140/N1A1"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"document_role": DocumentRole.TENDER_REQUIREMENTS.value},
    )
    document_id = uploaded.json()["document_id"]
    indexed = request(
        app,
        "POST",
        f"/v1/documents/{document_id}/search-indexes",
        headers={**AUTH_A, "Idempotency-Key": "model-brand-index"},
        json={},
    )
    assert indexed.status_code == 201

    found = request(
        app,
        "GET",
        "/v1/document-search",
        headers=AUTH_A,
        params={"query": "General Climate"},
    )
    assert found.status_code == 200
    assert found.json()["effective_at"].endswith("Z")
    assert found.json()["results"][0]["status"] == "PASS"
    hit = found.json()["results"][0]["hits"][0]
    assert hit["source_kind"] == "MODEL_BRAND_CATALOG"
    assert hit["model_brand_evidence"]["catalog_id"] == body["catalog_id"]


def test_model_brand_review_requires_reviewer_and_publishes_atomically(app: object) -> None:
    operator_auth = {"Authorization": "Bearer tenant-a-operator-token"}
    source_pdf = blank_pdf_bytes()
    artifact_response = request(
        app,
        "POST",
        "/v1/model-brand-source-artifacts",
        headers={**operator_auth, "Idempotency-Key": "workflow-artifact"},
        files={"file": ("workflow-source.pdf", source_pdf, "application/pdf")},
        data={
            "source_title": "Official workflow manual",
            "source_url": "https://manufacturer.example/workflow.pdf",
        },
    )
    assert artifact_response.status_code == 201
    artifact = artifact_response.json()
    proposal_body = {
        "catalog_id": "workflow-catalog-1",
        "approval_reference": "review/workflow-1",
        "entries": [
            {
                "entry_id": "workflow-entry-1",
                "model": "MODEL-EXACT-1",
                "brand": "Verified Brand",
                "valid_from": "2026-01-01T00:00:00Z",
                "valid_to": None,
                "evidence": {
                    "source_kind": "OFFICIAL_MANUFACTURER",
                    "source_artifact_id": artifact["artifact_id"],
                    "source_title": artifact["source_title"],
                    "source_url": artifact["source_url"],
                    "source_document_sha256": artifact["sha256"],
                    "locator": "model table, row 1",
                    "retrieved_at": artifact["retrieved_at"],
                },
            }
        ],
    }
    submitted = request(
        app,
        "POST",
        "/v1/model-brand-reviews",
        headers={**operator_auth, "Idempotency-Key": "workflow-submit"},
        json=proposal_body,
    )
    assert submitted.status_code == 201
    assert submitted.json()["status"] == "DRAFT"
    proposal_id = submitted.json()["proposal"]["proposal_id"]

    forbidden = request(
        app,
        "POST",
        f"/v1/model-brand-reviews/{proposal_id}/decision",
        headers={**operator_auth, "Idempotency-Key": "workflow-forbidden"},
        json={"decision": "APPROVED", "reason": "operator cannot approve"},
    )
    assert forbidden.status_code == 403

    decision_headers = {**AUTH_A, "Idempotency-Key": "workflow-decision"}
    decision_body = {"decision": "APPROVED", "reason": "Exact source verified"}
    approved = request(
        app,
        "POST",
        f"/v1/model-brand-reviews/{proposal_id}/decision",
        headers=decision_headers,
        json=decision_body,
    )
    replay = request(
        app,
        "POST",
        f"/v1/model-brand-reviews/{proposal_id}/decision",
        headers=decision_headers,
        json=decision_body,
    )
    assert approved.status_code == replay.status_code == 200
    assert approved.json() == replay.json()
    assert approved.json()["status"] == "APPROVED"
    assert approved.json()["decision"]["decided_by"] == "operator-a"
    assert approved.json()["decision"]["catalog_id"] == "workflow-catalog-1"

    changed = request(
        app,
        "POST",
        f"/v1/model-brand-reviews/{proposal_id}/decision",
        headers=decision_headers,
        json={"decision": "REJECTED", "reason": "changed"},
    )
    assert changed.status_code == 409
    listed = request(app, "GET", "/v1/model-brand-reviews", headers=operator_auth)
    assert listed.status_code == 200
    assert listed.json()[0]["status"] == "APPROVED"

    rejected_draft = request(
        app,
        "POST",
        "/v1/model-brand-reviews",
        headers={**operator_auth, "Idempotency-Key": "workflow-submit-rejected"},
        json=proposal_body | {"catalog_id": "workflow-catalog-rejected"},
    )
    rejected_id = rejected_draft.json()["proposal"]["proposal_id"]
    rejected = request(
        app,
        "POST",
        f"/v1/model-brand-reviews/{rejected_id}/decision",
        headers={**AUTH_A, "Idempotency-Key": "workflow-reject"},
        json={"decision": "REJECTED", "reason": "Locator is insufficient"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "REJECTED"
    assert rejected.json()["decision"]["catalog_id"] is None


def test_document_upload_requires_a_known_role(
    app: object,
    service: FakeCaseService,
) -> None:
    upload = {
        "file": (
            "requirements.docx",
            docx_bytes("Гарантия не менее 12 мес."),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }

    missing = request(
        app,
        "POST",
        "/v1/documents",
        headers={**AUTH_A, "Idempotency-Key": "document-role-missing"},
        files=upload,
    )
    invalid = request(
        app,
        "POST",
        "/v1/documents",
        headers={**AUTH_A, "Idempotency-Key": "document-role-invalid"},
        files=upload,
        data={"document_role": "UNTRUSTED_GUESS"},
    )

    assert missing.status_code == invalid.status_code == 422
    assert service.document_calls == []


def test_document_role_participates_in_idempotency_digest(
    app: object,
    service: FakeCaseService,
) -> None:
    content = docx_bytes("Гарантия не менее 12 мес.")
    upload = {
        "file": (
            "document.docx",
            content,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }

    for key, role in (
        ("document-role-tender", DocumentRole.TENDER_REQUIREMENTS),
        ("document-role-quote", DocumentRole.SUPPLIER_QUOTE),
    ):
        response = request(
            app,
            "POST",
            "/v1/documents",
            headers={**AUTH_A, "Idempotency-Key": key},
            files=upload,
            data={"document_role": role.value},
        )
        assert response.status_code == 201
        assert response.json()["document_role"] == role.value

    assert (
        service.document_calls[0]["request_digest"] != service.document_calls[1]["request_digest"]
    )


def test_blank_pdf_stays_unknown_and_bad_magic_is_rejected(app: object) -> None:
    scanned = request(
        app,
        "POST",
        "/v1/documents",
        headers={**AUTH_A, "Idempotency-Key": "document-scan"},
        files={"file": ("scan.pdf", blank_pdf_bytes(), "application/pdf")},
        data={"document_role": DocumentRole.UNKNOWN.value},
    )
    malformed = request(
        app,
        "POST",
        "/v1/documents",
        headers={**AUTH_A, "Idempotency-Key": "document-bad"},
        files={"file": ("fake.pdf", b"not a PDF", "application/pdf")},
        data={"document_role": DocumentRole.TENDER_REQUIREMENTS.value},
    )

    assert scanned.status_code == 201
    assert scanned.json()["extraction"]["status"] == "UNKNOWN"
    assert scanned.json()["extraction"]["reasons"] == ["OCR_REQUIRED"]
    assert malformed.status_code == 422
    assert malformed.json() == {"detail": {"code": "MAGIC_MISMATCH"}}


def test_document_cross_tenant_and_missing_are_identical(
    app: object,
    service: FakeCaseService,
) -> None:
    foreign = DocumentRecord(
        document_id="foreign-document",
        original_filename="foreign.pdf",
        media_type="application/pdf",
        document_role=DocumentRole.UNKNOWN,
        byte_size=1,
        sha256="0" * 64,
        extraction={
            "status": "UNKNOWN",
            "reasons": ["OCR_REQUIRED"],
            "source_units_total": 1,
            "source_units_extracted": 0,
            "characters_extracted": 0,
        },
        created_at=datetime.now(UTC),
    )
    service.documents[("other-company", foreign.document_id)] = foreign

    guessed = request(app, "GET", "/v1/documents/foreign-document", headers=AUTH_A)
    missing = request(app, "GET", "/v1/documents/not-there", headers=AUTH_A)

    assert guessed.status_code == missing.status_code == 404
    assert guessed.json() == missing.json() == {"detail": "not_found"}


def test_document_bundle_upload_persists_typed_members_without_source_bytes(
    app: object,
    service: FakeCaseService,
) -> None:
    content = zip_bytes(
        (
            ("requirements.docx", docx_bytes("Гарантия не менее 24 мес.")),
            ("unknown.ods", b"unsupported synthetic spreadsheet"),
        )
    )

    response = request(
        app,
        "POST",
        "/v1/document-bundles",
        headers={**AUTH_A, "Idempotency-Key": "bundle-001"},
        files={"file": ("tender.zip", content, "application/zip")},
        data={"document_role": DocumentRole.TENDER_REQUIREMENTS.value},
    )

    assert response.status_code == 201
    payload = response.json()
    assert "content" not in payload
    assert payload["document_role"] == "TENDER_REQUIREMENTS"
    assert payload["sha256"] == hashlib.sha256(content).hexdigest()
    assert payload["result"]["source_document_id"] == payload["bundle_id"]
    assert payload["result"]["source_sha256"] == payload["sha256"]
    assert payload["result"]["status"] == "UNKNOWN"
    assert payload["result"]["reasons"] == ["UNSUPPORTED_MEMBERS"]
    assert payload["result"]["members_total"] == 2
    supported = next(
        member for member in payload["result"]["members"] if member["media_type"] is not None
    )
    assert supported["extraction"]["blocks"][0]["provenance"]["locator"] == (
        'archive member "requirements.docx" :: paragraph 1'
    )
    assert service.document_bundle_calls[0]["company_id"] == "demo-company"
    assert service.document_bundle_calls[0]["actor_id"] == "operator-a"

    loaded = request(
        app,
        "GET",
        f"/v1/document-bundles/{payload['bundle_id']}",
        headers=AUTH_A,
    )
    assert loaded.status_code == 200
    assert loaded.json() == payload


def test_document_bundle_rejection_never_reaches_storage(
    app: object,
    service: FakeCaseService,
) -> None:
    unsafe = zip_bytes((("../escape.pdf", b"unsafe"),))

    response = request(
        app,
        "POST",
        "/v1/document-bundles",
        headers={**AUTH_A, "Idempotency-Key": "bundle-unsafe"},
        files={"file": ("unsafe.zip", unsafe, "application/zip")},
        data={"document_role": DocumentRole.TENDER_REQUIREMENTS.value},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "UNSAFE_MEMBER_PATH"}}
    assert service.document_bundle_calls == []
    assert service.document_bundles == {}


def test_document_bundle_idempotency_replays_and_role_change_conflicts(
    app: object,
    service: FakeCaseService,
) -> None:
    upload = {
        "file": (
            "tender.zip",
            zip_bytes((("requirements.docx", docx_bytes("Порты не менее 48 шт.")),)),
            "application/zip",
        )
    }
    headers = {**AUTH_A, "Idempotency-Key": "bundle-replay"}

    first = request(
        app,
        "POST",
        "/v1/document-bundles",
        headers=headers,
        files=upload,
        data={"document_role": DocumentRole.TENDER_REQUIREMENTS.value},
    )
    replay = request(
        app,
        "POST",
        "/v1/document-bundles",
        headers=headers,
        files=upload,
        data={"document_role": DocumentRole.TENDER_REQUIREMENTS.value},
    )
    conflict = request(
        app,
        "POST",
        "/v1/document-bundles",
        headers=headers,
        files=upload,
        data={"document_role": DocumentRole.SUPPLIER_QUOTE.value},
    )

    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "version_conflict"}
    assert len(service.document_bundle_calls) == 1


def test_document_bundle_cross_tenant_and_missing_are_identical(app: object) -> None:
    uploaded = request(
        app,
        "POST",
        "/v1/document-bundles",
        headers={
            "Authorization": "Bearer tenant-b-token",
            "Idempotency-Key": "foreign-bundle",
        },
        files={"file": ("foreign.zip", zip_bytes((("note.txt", b"text"),)), "application/zip")},
        data={"document_role": DocumentRole.UNKNOWN.value},
    )
    assert uploaded.status_code == 201

    guessed = request(
        app,
        "GET",
        f"/v1/document-bundles/{uploaded.json()['bundle_id']}",
        headers=AUTH_A,
    )
    missing = request(app, "GET", "/v1/document-bundles/not-there", headers=AUTH_A)

    assert guessed.status_code == missing.status_code == 404
    assert guessed.json() == missing.json() == {"detail": "not_found"}


def test_ai_transfer_api_exact_independent_approval_and_replay(app, service) -> None:
    source = _upload_completeness_source(app, "Мощность насоса не менее 5 кВт.", "transfer-source")
    path = f"/v1/documents/{source['document_id']}/ai-transfer-requests"
    headers = {"Authorization": "Bearer tenant-a-operator-token", "Idempotency-Key": "prepare"}
    created = request(app, "POST", path, headers=headers, json={"model": DEFAULT_OPENROUTER_MODEL})
    assert created.status_code == 201, created.text
    assert created.headers["cache-control"] == "no-store"
    prepared = created.json()
    assert prepared["source_binding"] == "VERIFIED_PERSISTED_SOURCE"
    assert prepared["retention"] == "RAW_RESPONSE_30_DAYS_V1"
    assert prepared["execution"] == "ORDERED_BATCH_ONE_ATTEMPT_PER_CHUNK_V1"
    assert (
        prepared["chunks"][0]["request_sha256"]
        == hashlib.sha256(prepared["chunks"][0]["request_body_json"].encode("utf-8")).hexdigest()
    )
    detail_path = f"/v1/ai-transfer-requests/{prepared['transfer_id']}"
    approval_path = detail_path + "/approval"
    payload = {"request_payload_sha256": prepared["payload_sha256"]}
    for token, expected in [
        ("transfer-self-approver", 409),
        ("tenant-a-operator-token", 403),
        ("tenant-a-ai-reviewer-token", 403),
        ("transfer-foreign-approver", 404),
    ]:
        rejected = request(
            app,
            "POST",
            approval_path,
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "approve"},
            json=payload,
        )
        assert rejected.status_code == expected
    approval_headers = {"Authorization": "Bearer transfer-approver", "Idempotency-Key": "approve"}
    stale = request(
        app,
        "POST",
        approval_path,
        headers=approval_headers,
        json={"request_payload_sha256": "0" * 64},
    )
    assert stale.status_code == 409
    approved = request(app, "POST", approval_path, headers=approval_headers, json=payload)
    assert approved.status_code == 201, approved.text
    assert approved.headers["cache-control"] == "no-store"
    approval = approved.json()
    assert (
        datetime.fromisoformat(approval["expires_at"])
        - datetime.fromisoformat(approval["approved_at"])
    ).total_seconds() == 900
    assert (
        request(app, "POST", approval_path, headers=approval_headers, json=payload).json()
        == approval
    )
    assert (
        request(
            app,
            "POST",
            approval_path,
            headers={**approval_headers, "Idempotency-Key": "second"},
            json=payload,
        ).status_code
        == 409
    )
    assert (
        request(app, "POST", path, headers=headers, json={"model": DEFAULT_OPENROUTER_MODEL}).json()
        == prepared
    )
    assert (
        request(
            app, "POST", path, headers=headers, json={"model": "inclusionai/ling-3.0-flash-vl:free"}
        ).status_code
        == 409
    )
    for token, expected in [
        ("transfer-approver", 200),
        ("tenant-a-operator-token", 200),
        ("transfer-other-operator", 404),
        ("transfer-foreign-approver", 404),
        ("tenant-a-ai-reviewer-token", 403),
    ]:
        detail = request(app, "GET", detail_path, headers={"Authorization": f"Bearer {token}"})
        assert detail.status_code == expected
        if expected == 200:
            assert detail.headers["cache-control"] == "no-store"
            assert detail.json() == {"request": prepared, "approval": approval}

    admission_path = detail_path + "/execution-admissions"
    admission_headers = {
        "Authorization": "Bearer tenant-a-operator-token",
        "Idempotency-Key": "admit",
    }
    assert (
        request(
            app,
            "POST",
            admission_path,
            headers={
                "Authorization": "Bearer transfer-approver",
                "Idempotency-Key": "admit",
            },
            json=payload,
        ).status_code
        == 403
    )
    assert (
        request(
            app,
            "POST",
            admission_path,
            headers={
                "Authorization": "Bearer transfer-other-operator",
                "Idempotency-Key": "admit",
            },
            json=payload,
        ).status_code
        == 409
    )
    assert (
        request(
            app,
            "POST",
            admission_path,
            headers=admission_headers,
            json={"request_payload_sha256": "0" * 64},
        ).status_code
        == 409
    )
    admitted = request(app, "POST", admission_path, headers=admission_headers, json=payload)
    assert admitted.status_code == 201, admitted.text
    assert admitted.headers["cache-control"] == "no-store"
    admission = admitted.json()
    assert admission["status"] == "ADMITTED"
    assert admission["execution_policy"] == "ORDERED_BATCH_ONE_ATTEMPT_PER_CHUNK_V1"
    assert admission["admitted_by"] == "proposal-author-a"
    assert (
        request(app, "POST", admission_path, headers=admission_headers, json=payload).json()
        == admission
    )
    assert (
        request(
            app,
            "POST",
            admission_path,
            headers={**admission_headers, "Idempotency-Key": "admit-again"},
            json=payload,
        ).status_code
        == 409
    )
    execution_path = f"/v1/ai-transfer-executions/{admission['execution_id']}"
    for token, expected in [
        ("tenant-a-operator-token", 200),
        ("transfer-approver", 200),
        ("transfer-other-operator", 404),
        ("transfer-foreign-approver", 404),
        ("tenant-a-ai-reviewer-token", 200),
        ("tenant-a-auditor-token", 200),
        ("tenant-b-auditor-token", 404),
    ]:
        execution = request(
            app, "GET", execution_path, headers={"Authorization": f"Bearer {token}"}
        )
        assert execution.status_code == expected
        if expected == 200:
            assert execution.headers["cache-control"] == "no-store"
            assert execution.json() == {
                "admission": admission,
                "claim": None,
                "receipt": None,
                "raw_response": None,
            }
    assert len(service.ai_transfers) == 1
    assert len(service.ai_transfer_executions) == 1
    assert request(app, "GET", "/v1/ai-transfer-requests", headers=headers).status_code == 404


def test_ai_transfer_materialization_api_is_owner_only_and_no_store(app, service) -> None:
    operator_headers = {"Authorization": "Bearer tenant-a-operator-token"}
    source = _upload_completeness_source(
        app,
        "Ð¢Ñ€ÐµÐ±Ð¾Ð²Ð°Ð½Ð¸Ðµ 5 ÐºÐ’Ñ‚.",
        "materialize-source",
    )
    prepared = request(
        app,
        "POST",
        f"/v1/documents/{source['document_id']}/ai-transfer-requests",
        headers={**operator_headers, "Idempotency-Key": "materialize-prepare"},
        json={"model": DEFAULT_OPENROUTER_MODEL},
    ).json()
    approval = request(
        app,
        "POST",
        f"/v1/ai-transfer-requests/{prepared['transfer_id']}/approval",
        headers={
            "Authorization": "Bearer transfer-approver",
            "Idempotency-Key": "materialize-approve",
        },
        json={"request_payload_sha256": prepared["payload_sha256"]},
    ).json()
    admission = request(
        app,
        "POST",
        f"/v1/ai-transfer-requests/{prepared['transfer_id']}/execution-admissions",
        headers={**operator_headers, "Idempotency-Key": "materialize-admit"},
        json={"request_payload_sha256": approval["request_payload_sha256"]},
    ).json()
    path = f"/v1/ai-transfer-executions/{admission['execution_id']}/requirement-materializations"
    for token, expected in [
        ("transfer-approver", 403),
        ("tenant-a-ai-reviewer-token", 403),
        ("tenant-a-auditor-token", 403),
        ("transfer-other-operator", 404),
        ("tenant-b-token", 404),
    ]:
        response = request(app, "POST", path, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == expected
    created = request(app, "POST", path, headers=operator_headers)
    assert created.status_code == 200, created.text
    assert created.headers["cache-control"] == "no-store"
    assert created.json()["status"] == "REJECTED"
    assert created.json()["reason"] == "INVALID_CANDIDATE_EVIDENCE"
    assert service.ai_transfer_materialize_calls == [
        ("demo-company", "proposal-author-a", admission["execution_id"])
    ]

    original = service.ai_transfer_materializations[("demo-company", admission["execution_id"])]
    replay_fields = original.model_dump(mode="python", exclude={"payload_sha256"})
    replay_fields["materialized_by"] = "background-worker"
    replay = AiTransferRequirementMaterialization.model_validate(
        {
            **replay_fields,
            "payload_sha256": canonical_json_sha256(
                {
                    "schema_version": "ai-transfer-requirement-materialization-v1",
                    **replay_fields,
                }
            ),
        },
        strict=True,
    )
    service.ai_transfer_materializations[("demo-company", admission["execution_id"])] = replay
    recovered = request(app, "POST", path, headers=operator_headers)
    assert recovered.status_code == 200
    assert recovered.json()["materialization_id"] == original.materialization_id
    assert recovered.json()["materialized_by"] == "background-worker"

    batch_path = (
        f"/v1/ai-transfer-executions/{admission['execution_id']}/requirement-batch-materializations"
    )
    for token, expected in [
        ("transfer-approver", 403),
        ("tenant-a-ai-reviewer-token", 403),
        ("tenant-a-auditor-token", 403),
        ("transfer-other-operator", 404),
        ("tenant-b-token", 404),
    ]:
        batch_response = request(
            app, "POST", batch_path, headers={"Authorization": f"Bearer {token}"}
        )
        assert batch_response.status_code == expected
    batch_response = request(app, "POST", batch_path, headers=operator_headers)
    assert batch_response.status_code == 200
    assert batch_response.headers["cache-control"] == "no-store"
    assert batch_response.json() == {
        "company_id": "demo-company",
        "execution_id": admission["execution_id"],
        "status": "PENDING",
        "materialized_ordinals": [],
        "run_id": None,
        "run_evidence_sha256": None,
        "rejection": None,
    }
    assert service.ai_transfer_batch_materialize_calls == [
        ("demo-company", "proposal-author-a", admission["execution_id"])
    ]


def test_server_managed_requirement_run_projection_is_raw_free(app, service) -> None:
    result = AiTransferRequirementResult.model_construct(
        schema_version="ai-transfer-requirement-result-v1",
        company_id="demo-company",
        result_id="result-v2",
        transfer_id="transfer-v2",
        execution_id="execution-v2",
        ordinal=1,
        claim_id="claim-v2",
        receipt_id="receipt-v2",
        raw_response_id="raw-v2",
        request_payload_sha256="a" * 64,
        claim_payload_sha256="b" * 64,
        receipt_payload_sha256="c" * 64,
        raw_metadata_sha256="d" * 64,
        request_sha256="e" * 64,
        response_body_sha256="f" * 64,
        assistant_content_sha256="0" * 64,
        provider_response_id="provider-v2",
        provider_model=DEFAULT_OPENROUTER_MODEL,
        source_document_id="doc-v2",
        source_sha256="1" * 64,
        extraction_sha256="2" * 64,
        source_block_ids=("block-v2",),
        candidates=(),
        item_candidates=(),
        unresolved_block_ids=("block-v2",),
        execution_status="COMPLETE",
        completeness_status="UNKNOWN",
        prepared_by="proposal-author-a",
        materialized_by="worker-v2",
        materialized_at=datetime(2026, 9, 17, 12, tzinfo=UTC),
        payload_sha256="3" * 64,
    )
    snapshot = AiRequirementTransferRunSnapshot.model_construct(
        schema_version="persisted-ai-requirement-run-v2",
        origin="SERVER_MANAGED_TRANSFER",
        company_id="demo-company",
        run_id="run-v2",
        source_document_id="doc-v2",
        source_sha256="1" * 64,
        extraction=ExtractionResult.model_construct(),
        result=result,
        completeness_status="UNKNOWN",
        prepared_by="proposal-author-a",
        materialized_by="worker-v2",
        materialized_at=result.materialized_at,
        evidence_sha256="4" * 64,
    )
    service.ai_requirement_runs[("demo-company", "run-v2")] = (
        AiRequirementReviewRecord.model_construct(snapshot=snapshot, decision=None)
    )
    summary = request(
        app,
        "GET",
        "/v1/ai-requirement-runs",
        headers={"Authorization": "Bearer tenant-a-operator-token"},
    )
    assert summary.status_code == 200
    item = next(row for row in summary.json() if row["run_id"] == "run-v2")
    assert item["submitted_by"] == "proposal-author-a"
    assert item["submitted_at"] == "2026-09-17T12:00:00Z"
    assert item["model"] == DEFAULT_OPENROUTER_MODEL
    assert "raw_response_id" not in item
    detail = request(
        app,
        "GET",
        "/v1/ai-requirement-runs/run-v2",
        headers={"Authorization": "Bearer tenant-a-ai-reviewer-token"},
    )
    assert detail.status_code == 200
    assert detail.headers["cache-control"] == "no-store"
    assert "raw_response_id" not in detail.json()
    assert "result" not in detail.json()
    assert "extraction" not in detail.json()


def test_ai_transfer_api_strict_body_limits_roles_and_openapi(app, service) -> None:
    path = "/v1/documents/missing/ai-transfer-requests"
    headers = {
        "Authorization": "Bearer tenant-a-operator-token",
        "Idempotency-Key": "prepare",
        "Content-Type": "application/json",
    }
    for content in [
        b"{}",
        b"[]",
        b'{"model":null}',
        b'{"model":"unknown"}',
        b'{"model":NaN}',
        b'{"model":true}',
        b'{"model":"google/gemma-4-31b-it:free","model":"google/gemma-4-31b-it:free"}',
        b'{"model":"google/gemma-4-31b-it:free","company_id":"other"}',
        b'{"request_payload_sha256":"0"}',
        b"{",
        b"\xff",
    ]:
        result = request(app, "POST", path, headers=headers, content=content)
        assert result.status_code == 422, result.text
        assert result.json() == {"detail": "invalid_ai_transfer"}
    assert (
        request(
            app, "POST", path, headers={**headers, "Content-Type": "text/plain"}, content=b"{}"
        ).status_code
        == 415
    )
    assert request(app, "POST", path, headers=headers, content=b" " * 16_385).status_code == 413
    assert (
        request(
            app, "POST", path, headers={**headers, "Content-Length": "1"}, content=b" " * 16_385
        ).status_code
        == 413
    )

    async def stream() -> AsyncIterator[bytes]:
        yield b" " * 8192
        yield b" " * 8193

    assert request(app, "POST", path, headers=headers, content=stream()).status_code == 413
    assert request(app, "POST", path, content=b" " * 16_385).status_code == 401
    assert (
        request(
            app,
            "POST",
            path,
            headers={**headers, "Authorization": "Bearer transfer-approver"},
            content=b" ",
        ).status_code
        == 403
    )
    assert (
        request(
            app, "POST", path, headers=headers, json={"model": DEFAULT_OPENROUTER_MODEL}
        ).status_code
        == 404
    )
    assert not service.ai_transfers
    schema = app.openapi()
    prepare_schema = schema["paths"]["/v1/documents/{document_id}/ai-transfer-requests"]["post"][
        "requestBody"
    ]["content"]["application/json"]["schema"]
    assert prepare_schema["additionalProperties"] is False
    assert len(prepare_schema["properties"]["model"]["enum"]) == 2
    approval_schema = schema["paths"]["/v1/ai-transfer-requests/{transfer_id}/approval"]["post"][
        "requestBody"
    ]["content"]["application/json"]["schema"]
    assert list(approval_schema["properties"]) == ["request_payload_sha256"]
    admission_schema = schema["paths"][
        "/v1/ai-transfer-requests/{transfer_id}/execution-admissions"
    ]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert list(admission_schema["properties"]) == ["request_payload_sha256"]
    assert "/v1/ai-transfer-raw-responses/{raw_response_id}" in schema["paths"]


def test_ai_transfer_raw_response_requires_reviewer_or_auditor_and_is_no_store(
    app, service
) -> None:
    raw_response_id = "raw-response-1"
    received_at = datetime(2026, 9, 17, 12, tzinfo=UTC)
    metadata = AiTransferRawMetadata.model_construct(
        schema_version="ai-transfer-raw-metadata-v1",
        company_id="demo-company",
        raw_response_id=raw_response_id,
        transfer_id="transfer-1",
        execution_id="execution-1",
        ordinal=1,
        claim_id="claim-1",
        chunk_id="chunk-0001",
        claim_payload_sha256="a" * 64,
        receipt_id="receipt-1",
        receipt_payload_sha256="b" * 64,
        request_sha256="c" * 64,
        response_body_sha256="d" * 64,
        response_byte_count=18,
        received_at=received_at,
        expires_at=received_at + timedelta(days=30),
        algorithm="AES-256-GCM+TENANT-KEK-V1",
        key_id="tenant/demo-company/test-kek/v1",
        body_aad_sha256="e" * 64,
        metadata_sha256="f" * 64,
    )
    body = b'{"provider":"raw"}'
    service.ai_transfer_raw_responses[("demo-company", raw_response_id)] = (body, metadata)
    path = f"/v1/ai-transfer-raw-responses/{raw_response_id}"

    for token in ("tenant-a-ai-reviewer-token", "tenant-a-auditor-token"):
        result = request(app, "GET", path, headers={"Authorization": f"Bearer {token}"})
        assert result.status_code == 200
        assert result.content == body
        assert result.headers["content-type"] == "application/octet-stream"
        assert result.headers["cache-control"] == "no-store"
        assert result.headers["x-content-type-options"] == "nosniff"
        assert result.headers["content-disposition"] == (
            'attachment; filename="ai-transfer-response.json"'
        )

    assert (
        request(
            app,
            "GET",
            path,
            headers={"Authorization": "Bearer tenant-a-operator-token"},
        ).status_code
        == 403
    )
    assert (
        request(
            app,
            "GET",
            path,
            headers={"Authorization": "Bearer tenant-b-auditor-token"},
        ).status_code
        == 404
    )


def test_auditor_role_is_read_only_on_general_write_routes(app, service) -> None:
    response = request(
        app,
        "POST",
        "/v1/cases",
        headers={
            "Authorization": "Bearer tenant-a-auditor-token",
            "Idempotency-Key": "auditor-must-not-write",
        },
        json=paper_case_payload(),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "auditor_read_only"}
    assert service.created_with == []


def _upload_completeness_source(app: object, text: str, key: str) -> dict[str, Any]:
    response = request(
        app,
        "POST",
        "/v1/documents",
        headers={
            "Authorization": "Bearer tenant-a-operator-token",
            "Idempotency-Key": key,
        },
        files={
            "file": (
                f"{key}.docx",
                docx_bytes(text),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"document_role": DocumentRole.TENDER_REQUIREMENTS.value},
    )
    assert response.status_code == 201
    return response.json()


def _create_completeness_review(app: object, document_id: str, key: str) -> httpx.Response:
    return request(
        app,
        "POST",
        f"/v1/documents/{document_id}/completeness-reviews",
        headers={
            "Authorization": "Bearer tenant-a-operator-token",
            "Idempotency-Key": key,
        },
    )


@pytest.mark.parametrize(
    "schema_version",
    ["ai-requirement-analysis-v1", "ai-requirement-analysis-v2"],
)
def test_ai_requirement_report_import_is_sanitized_and_idempotent(
    app: object,
    service: FakeCaseService,
    schema_version: str,
) -> None:
    document_id, report = _importable_ai_report(
        service,
        run_id=f"import-{schema_version}",
        schema_version=schema_version,
    )
    path = f"/v1/documents/{document_id}/ai-requirement-runs"
    headers = {
        "Authorization": "Bearer tenant-a-operator-token",
        "Idempotency-Key": f"import-{schema_version}",
    }
    payload = {"report": report.model_dump(mode="json")}

    created = request(app, "POST", path, headers=headers, json=payload)
    replay = request(app, "POST", path, headers=headers, json=payload)

    assert created.status_code == replay.status_code == 201
    assert created.json() == replay.json()
    assert created.headers["cache-control"] == "no-store"
    assert created.json()["report_schema_version"] == schema_version
    assert created.json()["completeness_status"] == "UNKNOWN"
    assert created.json()["submitted_by"] == "proposal-author-a"
    assert created.json()["reviewed"] is False
    for forbidden in (
        "response_content",
        "authorization_reference",
        "extraction",
        "chunks",
        "provider_response_id",
    ):
        assert forbidden not in created.text


def test_ai_requirement_report_import_auth_media_size_and_json_gates(
    app: object,
    service: FakeCaseService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id, report = _importable_ai_report(service, run_id="import-gates")
    path = f"/v1/documents/{document_id}/ai-requirement-runs"
    payload = {"report": report.model_dump(mode="json")}
    operator = {
        "Authorization": "Bearer tenant-a-operator-token",
        "Idempotency-Key": "import-gates",
    }
    reviewer = {
        "Authorization": "Bearer tenant-a-ai-reviewer-token",
        "Idempotency-Key": "import-gates-reviewer",
    }

    assert request(app, "POST", path, json=payload).status_code == 401
    assert request(app, "POST", path, headers=reviewer, content=b"not-json").status_code == 403
    unsupported = request(
        app,
        "POST",
        path,
        headers={**operator, "Content-Type": "text/plain"},
        content=b"{}",
    )
    assert unsupported.status_code == 415
    assert unsupported.json() == {"detail": "unsupported_media_type"}

    malformed = request(
        app,
        "POST",
        path,
        headers={**operator, "Content-Type": "application/json"},
        content=b'{"report":',
    )
    assert malformed.status_code == 422
    deeply_nested = request(
        app,
        "POST",
        path,
        headers={**operator, "Content-Type": "application/json"},
        content=("[" * 10_000 + "]" * 10_000).encode(),
    )
    assert deeply_nested.status_code == 422
    duplicate = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    duplicate = f'{{"report":{duplicate[10:-1]},"report":{duplicate[10:-1]}}}'
    assert (
        request(
            app,
            "POST",
            path,
            headers={**operator, "Content-Type": "application/json"},
            content=duplicate.encode(),
        ).status_code
        == 422
    )
    assert (
        request(
            app,
            "POST",
            path,
            headers=operator,
            json=payload | {"unexpected": True},
        ).status_code
        == 422
    )
    nested_extra = json.loads(json.dumps(payload))
    nested_extra["report"]["candidates"][0]["evidence"][0]["provenance"]["unexpected"] = (
        "must-not-be-ignored"
    )
    nested_extra["report"]["chunks"][0]["candidates"][0]["evidence"][0]["provenance"][
        "unexpected"
    ] = "must-not-be-ignored"
    assert (
        request(
            app,
            "POST",
            path,
            headers={**operator, "Idempotency-Key": "import-nested-extra"},
            json=nested_extra,
        ).status_code
        == 422
    )
    oversized_model = json.loads(json.dumps(payload))
    oversized_model["report"]["model"] = "m" * 501
    oversized_model["report"]["chunks"][0]["provider_model"] = "m" * 501
    assert (
        request(
            app,
            "POST",
            path,
            headers={**operator, "Idempotency-Key": "import-model-too-long"},
            json=oversized_model,
        ).status_code
        == 422
    )
    for index, (field, value) in enumerate(
        (("blocks_total", True), ("external_transfer", 1), ("blocks_total", 1.0))
    ):
        silently_coerced = json.loads(json.dumps(payload))
        silently_coerced["report"][field] = value
        assert (
            request(
                app,
                "POST",
                path,
                headers={**operator, "Idempotency-Key": f"import-coercion-{index}"},
                json=silently_coerced,
            ).status_code
            == 422
        )

    monkeypatch.setattr("procurement.api.app.MAX_AI_REQUIREMENT_IMPORT_BYTES", 64)
    declared = request(
        app,
        "POST",
        path,
        headers={**operator, "Content-Type": "application/json"},
        content=b"x" * 65,
    )
    assert declared.status_code == 413

    async def chunked_body() -> AsyncIterator[bytes]:
        yield b"x" * 40
        yield b"y" * 40

    chunked = request(
        app,
        "POST",
        path,
        headers={
            **operator,
            "Content-Type": "application/json",
            "Transfer-Encoding": "chunked",
        },
        content=chunked_body(),
    )
    assert chunked.status_code == 413
    assert not service.ai_requirement_import_receipts


def test_ai_requirement_report_import_exact_source_and_replay_conflicts(
    app: object,
    service: FakeCaseService,
) -> None:
    first_document, first_report = _importable_ai_report(service, run_id="import-first")
    second_document, second_report = _importable_ai_report(service, run_id="import-second")
    headers = {
        "Authorization": "Bearer tenant-a-operator-token",
        "Idempotency-Key": "import-exact-source",
    }
    first_path = f"/v1/documents/{first_document}/ai-requirement-runs"
    assert (
        request(
            app,
            "POST",
            first_path,
            headers=headers,
            json={"report": first_report.model_dump(mode="json")},
        ).status_code
        == 201
    )
    changed = request(
        app,
        "POST",
        f"/v1/documents/{second_document}/ai-requirement-runs",
        headers=headers,
        json={"report": second_report.model_dump(mode="json")},
    )
    assert changed.status_code == 409
    assert "response_content" not in changed.text
    assert (
        request(
            app,
            "POST",
            first_path,
            headers={**headers, "Idempotency-Key": "import-wrong-source"},
            json={"report": second_report.model_dump(mode="json")},
        ).status_code
        == 422
    )
    missing = request(
        app,
        "POST",
        "/v1/documents/missing/ai-requirement-runs",
        headers={**headers, "Idempotency-Key": "import-missing"},
        json={"report": first_report.model_dump(mode="json")},
    )
    assert missing.status_code == 404
    assert missing.json() == {"detail": "not_found"}
    foreign_seed = _seed_ai_requirement_run(
        service,
        company_id="other-company",
        run_id="foreign-import-source",
    )
    service.ai_requirement_runs.pop(("other-company", "foreign-import-source"))
    foreign = request(
        app,
        "POST",
        f"/v1/documents/{foreign_seed.snapshot.source_document_id}/ai-requirement-runs",
        headers={**headers, "Idempotency-Key": "import-foreign"},
        json={"report": foreign_seed.snapshot.report.model_dump(mode="json")},
    )
    assert foreign.status_code == missing.status_code
    assert foreign.json() == missing.json()


def test_ai_requirement_review_queue_is_sanitized_and_reviewer_gated(
    app: object, service: FakeCaseService
) -> None:
    record = _seed_ai_requirement_run(service)
    run_id = record.snapshot.run_id
    listed = request(
        app,
        "GET",
        "/v1/ai-requirement-runs",
        headers={"Authorization": "Bearer tenant-a-operator-token"},
    )
    assert listed.status_code == 200
    assert listed.headers["cache-control"] == "no-store"
    assert listed.json()[0]["run_id"] == run_id
    assert listed.json()[0]["completeness_status"] == "UNKNOWN"
    assert listed.json()[0]["reviewed"] is False
    for forbidden in (
        "response_content",
        "authorization_reference",
        "extraction",
        "provider_response_id",
    ):
        assert forbidden not in listed.text

    detail_path = f"/v1/ai-requirement-runs/{run_id}"
    assert (
        request(
            app, "GET", detail_path, headers={"Authorization": "Bearer tenant-a-operator-token"}
        ).status_code
        == 403
    )
    detail = request(
        app, "GET", detail_path, headers={"Authorization": "Bearer tenant-a-ai-reviewer-token"}
    )
    assert detail.status_code == 200
    assert detail.headers["cache-control"] == "no-store"
    assert detail.json()["requirement_candidates"][0]["evidence"][0]["text"] == (
        "Warranty not less than 24 months"
    )
    for forbidden in (
        "response_content",
        "authorization_reference",
        "extraction",
        "chunks",
        "provider_response_id",
    ):
        assert forbidden not in detail.text

    _seed_ai_requirement_run(service, company_id="other-company", run_id="foreign-ai-run")
    foreign = request(
        app,
        "GET",
        "/v1/ai-requirement-runs/foreign-ai-run",
        headers={"Authorization": "Bearer tenant-a-ai-reviewer-token"},
    )
    missing = request(
        app,
        "GET",
        "/v1/ai-requirement-runs/missing-ai-run",
        headers={"Authorization": "Bearer tenant-a-ai-reviewer-token"},
    )
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == {"detail": "not_found"}


def test_ai_requirement_review_decision_is_exact_full_and_independent(
    app: object, service: FakeCaseService
) -> None:
    record = _seed_ai_requirement_run(service)
    run_id = record.snapshot.run_id
    path = f"/v1/ai-requirement-runs/{run_id}/decision"
    candidate = record.snapshot.report.candidates[0]
    payload = {
        "evidence_sha256": record.snapshot.evidence_sha256,
        "candidate_decisions": [
            {
                "candidate_kind": "REQUIREMENT",
                "candidate_id": candidate.candidate_id,
                "disposition": "ACCEPTED",
                "reason": "Exact source evidence was reviewed.",
            }
        ],
    }
    assert (
        request(
            app,
            "POST",
            path,
            headers={
                "Authorization": "Bearer tenant-a-operator-token",
                "Idempotency-Key": "ai-wrong-role",
            },
            json=payload,
        ).status_code
        == 403
    )
    assert (
        request(
            app,
            "POST",
            path,
            headers={
                "Authorization": "Bearer tenant-a-ai-self-reviewer-token",
                "Idempotency-Key": "ai-self",
            },
            json=payload,
        ).status_code
        == 409
    )
    assert (
        request(
            app,
            "POST",
            path,
            headers={
                "Authorization": "Bearer tenant-a-ai-reviewer-token",
                "Idempotency-Key": "ai-stale",
            },
            json=payload | {"evidence_sha256": "0" * 64},
        ).status_code
        == 409
    )
    assert (
        request(
            app,
            "POST",
            path,
            headers={
                "Authorization": "Bearer tenant-a-ai-reviewer-token",
                "Idempotency-Key": "ai-incomplete",
            },
            json=payload | {"candidate_decisions": []},
        ).status_code
        == 409
    )
    headers = {
        "Authorization": "Bearer tenant-a-ai-reviewer-token",
        "Idempotency-Key": "ai-decision",
    }
    decided = request(app, "POST", path, headers=headers, json=payload)
    replay = request(app, "POST", path, headers=headers, json=payload)
    assert decided.status_code == replay.status_code == 200
    assert decided.json() == replay.json()
    assert decided.headers["cache-control"] == "no-store"
    assert decided.json()["reviewed_by"] == "ai-reviewer-a"
    assert decided.json()["candidate_decisions"][0]["disposition"] == "ACCEPTED"
    assert decided.json()["completeness_status"] == "UNKNOWN"
    assert (
        request(
            app,
            "POST",
            path,
            headers={
                "Authorization": "Bearer tenant-a-ai-reviewer-token",
                "Idempotency-Key": "ai-second",
            },
            json=payload,
        ).status_code
        == 409
    )


def test_completeness_review_pass_replay_role_and_tenant_gates(app: object) -> None:
    document = _upload_completeness_source(app, "Гарантия не менее 24 мес.", "complete-pass")
    create_forbidden = request(
        app,
        "POST",
        f"/v1/documents/{document['document_id']}/completeness-reviews",
        headers={**AUTH_A, "Idempotency-Key": "review-role-forbidden"},
    )
    assert create_forbidden.status_code == 403
    created = _create_completeness_review(app, document["document_id"], "review-pass")
    replay = _create_completeness_review(app, document["document_id"], "review-pass")
    assert created.status_code == replay.status_code == 201
    assert created.json() == replay.json()
    body = created.json()
    assert body["snapshot"]["mapping"]["completeness"]["status"] == "UNKNOWN"
    assert body["snapshot"]["extraction"] == document["extraction"]
    review_id = body["snapshot"]["review_id"]
    decision_payload = {
        "evidence_sha256": body["snapshot"]["evidence_sha256"],
        "status": "PASS",
        "scope": "all extracted requirements",
        "reason": "native extraction reviewed in full",
        "block_decisions": [],
    }
    self_review = request(
        app,
        "POST",
        f"/v1/completeness-reviews/{review_id}/decision",
        headers={
            "Authorization": "Bearer tenant-a-self-reviewer-token",
            "Idempotency-Key": "pass-self-review",
        },
        json=decision_payload,
    )
    assert self_review.status_code == 409
    forbidden = request(
        app,
        "POST",
        f"/v1/completeness-reviews/{review_id}/decision",
        headers={
            "Authorization": "Bearer tenant-a-operator-token",
            "Idempotency-Key": "pass-forbidden",
        },
        json=decision_payload,
    )
    assert forbidden.status_code == 403
    headers = {
        "Authorization": "Bearer tenant-a-completeness-reviewer-token",
        "Idempotency-Key": "pass-decision",
    }
    decided = request(
        app,
        "POST",
        f"/v1/completeness-reviews/{review_id}/decision",
        headers=headers,
        json=decision_payload,
    )
    exact_replay = request(
        app,
        "POST",
        f"/v1/completeness-reviews/{review_id}/decision",
        headers=headers,
        json=decision_payload,
    )
    assert decided.status_code == exact_replay.status_code == 200
    assert decided.json() == exact_replay.json()
    assert decided.json()["decision"]["reviewed_mapping"]["completeness"]["status"] == "PASS"
    changed_replay = request(
        app,
        "POST",
        f"/v1/completeness-reviews/{review_id}/decision",
        headers=headers,
        json=decision_payload | {"reason": "changed"},
    )
    assert changed_replay.status_code == 409
    listed = request(app, "GET", "/v1/completeness-reviews?limit=10", headers=AUTH_A)
    detail = request(app, "GET", f"/v1/completeness-reviews/{review_id}", headers=AUTH_A)
    assert listed.status_code == detail.status_code == 200
    assert listed.json() == [detail.json()]
    foreign = request(
        app,
        "GET",
        f"/v1/completeness-reviews/{review_id}",
        headers={"Authorization": "Bearer tenant-b-token"},
    )
    assert foreign.status_code == 404


@pytest.mark.parametrize(
    ("decision_status", "block_decisions"),
    [
        (
            "FAIL",
            [
                {
                    "unmapped_index": 0,
                    "disposition": "MATERIAL_REQUIREMENT",
                    "rationale": "material condition remains unstructured",
                }
            ],
        ),
        ("UNKNOWN", []),
    ],
)
def test_completeness_review_fail_unknown_and_stale_digest(
    app: object,
    decision_status: str,
    block_decisions: list[dict[str, object]],
) -> None:
    suffix = decision_status.casefold()
    document = _upload_completeness_source(
        app, "Неразобранное обязательное требование", f"complete-{suffix}"
    )
    created = _create_completeness_review(app, document["document_id"], f"review-{suffix}")
    assert created.status_code == 201
    review = created.json()["snapshot"]
    stale = request(
        app,
        "POST",
        f"/v1/completeness-reviews/{review['review_id']}/decision",
        headers={
            "Authorization": "Bearer tenant-a-completeness-reviewer-token",
            "Idempotency-Key": f"stale-{suffix}",
        },
        json={
            "evidence_sha256": "0" * 64,
            "status": decision_status,
            "scope": "all",
            "reason": "reviewed",
            "block_decisions": block_decisions,
        },
    )
    assert stale.status_code == 409
    decided = request(
        app,
        "POST",
        f"/v1/completeness-reviews/{review['review_id']}/decision",
        headers={
            "Authorization": "Bearer tenant-a-completeness-reviewer-token",
            "Idempotency-Key": f"decision-{suffix}",
        },
        json={
            "evidence_sha256": review["evidence_sha256"],
            "status": decision_status,
            "scope": "all",
            "reason": "reviewed",
            "block_decisions": block_decisions,
        },
    )
    assert decided.status_code == 200
    assert decided.json()["decision"]["status"] == decision_status


def test_completeness_review_rejects_incomplete_source_and_partial_pass(app: object) -> None:
    uploaded = request(
        app,
        "POST",
        "/v1/documents",
        headers={
            "Authorization": "Bearer tenant-a-operator-token",
            "Idempotency-Key": "incomplete-source",
        },
        files={"file": ("scan.pdf", blank_pdf_bytes(), "application/pdf")},
        data={"document_role": DocumentRole.TENDER_REQUIREMENTS.value},
    )
    assert uploaded.status_code == 201
    rejected = _create_completeness_review(app, uploaded.json()["document_id"], "incomplete-review")
    assert rejected.status_code == 422

    document = _upload_completeness_source(
        app, "Неразобранное обязательное требование", "partial-pass-source"
    )
    created = _create_completeness_review(app, document["document_id"], "partial-pass-review")
    snapshot = created.json()["snapshot"]
    partial = request(
        app,
        "POST",
        f"/v1/completeness-reviews/{snapshot['review_id']}/decision",
        headers={
            "Authorization": "Bearer tenant-a-completeness-reviewer-token",
            "Idempotency-Key": "partial-pass-decision",
        },
        json={
            "evidence_sha256": snapshot["evidence_sha256"],
            "status": "PASS",
            "scope": "all",
            "reason": "incorrectly claims complete",
            "block_decisions": [],
        },
    )
    assert partial.status_code == 422


def test_document_set_evidence_manifest_api_is_ordered_unknown_and_no_store(
    app: object,
    service: FakeCaseService,
) -> None:
    first_document = _upload_completeness_source(app, "Мощность не менее 5 кВт", "set-a")
    second_document = _upload_completeness_source(app, "Гарантия не менее 12 месяцев", "set-b")
    first_review = _create_completeness_review(
        app, first_document["document_id"], "set-review-a"
    ).json()["snapshot"]
    second_review = _create_completeness_review(
        app, second_document["document_id"], "set-review-b"
    ).json()["snapshot"]
    payload = {
        "scope": "  review this tender package  ",
        "review_refs": [
            {
                "review_id": second_review["review_id"],
                "evidence_sha256": second_review["evidence_sha256"],
            },
            {
                "review_id": first_review["review_id"],
                "evidence_sha256": first_review["evidence_sha256"],
            },
        ],
    }
    headers = {
        "Authorization": "Bearer tenant-a-operator-token",
        "Idempotency-Key": "document-set-evidence-1",
    }

    created = request(
        app,
        "POST",
        "/v1/document-set-evidence-manifests",
        headers=headers,
        json=payload,
    )
    replay = request(
        app,
        "POST",
        "/v1/document-set-evidence-manifests",
        headers=headers,
        json=payload,
    )

    assert created.status_code == 201
    assert created.headers["cache-control"] == "no-store"
    assert replay.status_code == 201
    assert replay.json()["manifest_id"] == created.json()["manifest_id"]
    assert created.json()["scope"] == "review this tender package"
    assert created.json()["completeness_status"] == "UNKNOWN"
    assert created.json()["reason"] == "MULTI_DOCUMENT_REVIEW_REQUIRED"
    assert [item["source_document_id"] for item in created.json()["members"]] == [
        second_document["document_id"],
        first_document["document_id"],
    ]
    assert len(service.document_set_evidence_manifests) == 1

    read = request(
        app,
        "GET",
        f"/v1/document-set-evidence-manifests/{created.json()['manifest_id']}",
        headers={"Authorization": "Bearer tenant-a-operator-token"},
    )
    foreign = request(
        app,
        "GET",
        f"/v1/document-set-evidence-manifests/{created.json()['manifest_id']}",
        headers={"Authorization": "Bearer tenant-b-token"},
    )
    assert read.status_code == 200
    assert read.headers["cache-control"] == "no-store"
    assert foreign.status_code == 404


def test_document_set_evidence_api_requires_operator_and_rejects_invalid_payload(
    app: object,
) -> None:
    valid_ref = {"review_id": "review-1", "evidence_sha256": "a" * 64}
    operator_payload = {
        "scope": "package",
        "review_refs": [valid_ref, valid_ref | {"review_id": "review-2"}],
    }
    refused = request(
        app,
        "POST",
        "/v1/document-set-evidence-manifests",
        headers={**AUTH_A, "Idempotency-Key": "document-set-role"},
        json=operator_payload,
    )
    assert refused.status_code == 403

    headers = {
        "Authorization": "Bearer tenant-a-operator-token",
        "Idempotency-Key": "document-set-invalid",
    }
    for payload in (
        {"scope": "", "review_refs": [valid_ref, valid_ref | {"review_id": "review-2"}]},
        {"scope": "package", "review_refs": [valid_ref]},
        {"scope": "package", "review_refs": [valid_ref] * 11},
        {"scope": "package", "review_refs": [valid_ref, valid_ref]},
        operator_payload | {"tenant_id": "forged"},
        operator_payload | {"actor_id": "forged"},
        operator_payload | {"manifest_id": "forged"},
        operator_payload | {"status": "PASS"},
        operator_payload | {"source_text": "must not be accepted"},
    ):
        response = request(
            app,
            "POST",
            "/v1/document-set-evidence-manifests",
            headers=headers,
            json=payload,
        )
        assert response.status_code == 422

    duplicate_key = request(
        app,
        "POST",
        "/v1/document-set-evidence-manifests",
        headers={**headers, "Content-Type": "application/json"},
        content=(
            '{"scope":"first","scope":"second","review_refs":['
            '{"review_id":"review-1","evidence_sha256":"'
            + "a" * 64
            + '"},{"review_id":"review-2","evidence_sha256":"'
            + "b" * 64
            + '"}]}'
        ).encode(),
    )
    assert duplicate_key.status_code == 422
    assert duplicate_key.json() == {"detail": "invalid_document_set_evidence"}

    oversized = request(
        app,
        "POST",
        "/v1/document-set-evidence-manifests",
        headers={**headers, "Content-Type": "application/json"},
        content=b" " * (16 * 1024 + 1),
    )
    assert oversized.status_code == 413
    assert oversized.json() == {"detail": "document_set_evidence_request_too_large"}

    unsupported = request(
        app,
        "POST",
        "/v1/document-set-evidence-manifests",
        headers={**headers, "Content-Type": "text/plain"},
        content=b"{}",
    )
    assert unsupported.status_code == 415


def test_document_set_evidence_api_maps_missing_mismatch_and_conflict_safely(
    app: object,
) -> None:
    headers = {
        "Authorization": "Bearer tenant-a-operator-token",
        "Idempotency-Key": "document-set-errors",
    }
    missing = request(
        app,
        "POST",
        "/v1/document-set-evidence-manifests",
        headers=headers,
        json={
            "scope": "package",
            "review_refs": [
                {"review_id": "missing-1", "evidence_sha256": "a" * 64},
                {"review_id": "missing-2", "evidence_sha256": "b" * 64},
            ],
        },
    )
    assert missing.status_code == 404

    document = _upload_completeness_source(app, "Мощность не менее 5 кВт", "set-error")
    review = _create_completeness_review(app, document["document_id"], "set-error-review").json()[
        "snapshot"
    ]
    mismatch = request(
        app,
        "POST",
        "/v1/document-set-evidence-manifests",
        headers={**headers, "Idempotency-Key": "document-set-mismatch"},
        json={
            "scope": "package",
            "review_refs": [
                {"review_id": review["review_id"], "evidence_sha256": "c" * 64},
                {"review_id": "missing-2", "evidence_sha256": "b" * 64},
            ],
        },
    )
    assert mismatch.status_code == 422

    second_document = _upload_completeness_source(
        app, "Гарантия не менее 12 месяцев", "set-conflict-second"
    )
    second_review = _create_completeness_review(
        app, second_document["document_id"], "set-conflict-review"
    ).json()["snapshot"]
    conflict_headers = {**headers, "Idempotency-Key": "document-set-conflict"}
    valid = {
        "scope": "package",
        "review_refs": [
            {"review_id": review["review_id"], "evidence_sha256": review["evidence_sha256"]},
            {
                "review_id": second_review["review_id"],
                "evidence_sha256": second_review["evidence_sha256"],
            },
        ],
    }
    assert (
        request(
            app,
            "POST",
            "/v1/document-set-evidence-manifests",
            headers=conflict_headers,
            json=valid,
        ).status_code
        == 201
    )
    conflict = request(
        app,
        "POST",
        "/v1/document-set-evidence-manifests",
        headers=conflict_headers,
        json=valid | {"scope": "different package"},
    )
    assert conflict.status_code == 409


def test_document_set_completeness_review_api_binds_exact_evidence_and_no_store(
    app: object,
    service: FakeCaseService,
) -> None:
    first = _upload_completeness_source(app, "Мощность не менее 5 кВт", "set-review-doc-a")
    second = _upload_completeness_source(app, "Гарантия не менее 12 месяцев", "set-review-doc-b")
    first_review = _create_completeness_review(
        app, first["document_id"], "set-review-source-a"
    ).json()["snapshot"]
    second_review = _create_completeness_review(
        app, second["document_id"], "set-review-source-b"
    ).json()["snapshot"]
    manifest = request(
        app,
        "POST",
        "/v1/document-set-evidence-manifests",
        headers={
            "Authorization": "Bearer tenant-a-operator-token",
            "Idempotency-Key": "set-review-manifest",
        },
        json={
            "scope": "package",
            "review_refs": [
                {
                    "review_id": first_review["review_id"],
                    "evidence_sha256": first_review["evidence_sha256"],
                },
                {
                    "review_id": second_review["review_id"],
                    "evidence_sha256": second_review["evidence_sha256"],
                },
            ],
        },
    )
    assert manifest.status_code == 201
    for review in (first_review, second_review):
        decided = request(
            app,
            "POST",
            f"/v1/completeness-reviews/{review['review_id']}/decision",
            headers={
                "Authorization": "Bearer tenant-a-completeness-reviewer-token",
                "Idempotency-Key": f"set-review-decision-{review['review_id']}",
            },
            json={
                "evidence_sha256": review["evidence_sha256"],
                "status": "PASS",
                "scope": "all",
                "reason": "reviewed",
                "block_decisions": [],
            },
        )
        assert decided.status_code == 200

    path = f"/v1/document-sets/{manifest.json()['manifest_id']}"
    reviewer_headers = {
        "Authorization": "Bearer tenant-a-completeness-reviewer-token",
        "Idempotency-Key": "set-review-terminal",
    }
    evidence = request(app, "GET", f"{path}/completeness-evidence", headers=reviewer_headers)
    assert evidence.status_code == 200
    assert evidence.headers["cache-control"] == "no-store"
    payload = {
        "manifest_evidence_sha256": manifest.json()["evidence_sha256"],
        "attestations": [
            {
                "reference": {
                    "member_ordinal": item["member"]["ordinal"],
                    "review_id": item["member"]["completeness_review_id"],
                    "review_evidence_sha256": item["member"]["completeness_review_evidence_sha256"],
                    "decision_sha256": item["decision_sha256"],
                },
                "assessment": "REVIEWED_IN_SCOPE",
                "rationale": "reviewed in declared scope",
            }
            for item in evidence.json()["constituents"]
        ],
        "inventory_assessment": "CONFIRMED_FOR_DECLARED_SCOPE",
        "inventory_rationale": "inventory checked",
        "cross_document_assessment": "CHECKED_NO_OPEN_ISSUES",
        "cross_document_rationale": "cross-document checks complete",
        "reviewer_findings": [],
        "status": "PASS",
        "reason": "complete package",
    }
    created = request(
        app,
        "POST",
        f"{path}/completeness-decisions",
        headers=reviewer_headers,
        json=payload,
    )
    replay = request(
        app,
        "POST",
        f"{path}/completeness-decisions",
        headers=reviewer_headers,
        json=payload,
    )
    read = request(app, "GET", f"{path}/completeness-decisions", headers=reviewer_headers)
    foreign = request(
        app,
        "GET",
        f"{path}/completeness-evidence",
        headers={"Authorization": "Bearer tenant-b-completeness-reviewer-token"},
    )
    assert created.status_code == replay.status_code == read.status_code == 200
    assert created.json() == replay.json() == read.json()
    assert created.headers["cache-control"] == "no-store"
    assert created.json()["status"] == "PASS"
    assert len(service.document_set_review_decisions) == 1
    assert foreign.status_code == 404


def test_document_set_completeness_review_api_rejects_untrusted_json_and_roles(
    app: object,
) -> None:
    path = "/v1/document-sets/unknown/completeness-decisions"
    headers = {
        "Authorization": "Bearer tenant-a-completeness-reviewer-token",
        "Idempotency-Key": "set-review-invalid",
        "Content-Type": "application/json",
    }
    refused = request(
        app, "POST", path, headers={**AUTH_A, "Idempotency-Key": "wrong-role"}, content=b"{"
    )
    malformed = request(app, "POST", path, headers=headers, content=b"{")
    duplicate = request(
        app,
        "POST",
        path,
        headers=headers,
        content=(
            b'{"manifest_evidence_sha256":"' + b"a" * 64 + b'",'
            b'"manifest_evidence_sha256":"' + b"a" * 64 + b'"}'
        ),
    )
    non_finite = request(
        app,
        "POST",
        path,
        headers=headers,
        content=b'{"manifest_evidence_sha256":NaN}',
    )
    unsupported = request(
        app,
        "POST",
        path,
        headers={**headers, "Content-Type": "text/plain"},
        content=b"{}",
    )
    oversized = request(
        app,
        "POST",
        path,
        headers=headers,
        content=b" " * (256 * 1024 + 1),
    )
    server_finding = request(
        app,
        "POST",
        path,
        headers=headers,
        json={
            "manifest_evidence_sha256": "a" * 64,
            "attestations": [],
            "inventory_assessment": "UNRESOLVED",
            "inventory_rationale": "unknown",
            "cross_document_assessment": "UNRESOLVED",
            "cross_document_rationale": "unknown",
            "reviewer_findings": [
                {
                    "finding_id": "server-forged",
                    "kind": "UNRESOLVED_CONFLICT",
                    "origin": "SERVER",
                    "rationale": "forged",
                    "evidence": [
                        {
                            "kind": "MAPPING_FIELD",
                            "member_ordinal": 1,
                            "field": "delivery_deadline",
                        },
                        {
                            "kind": "MAPPING_FIELD",
                            "member_ordinal": 2,
                            "field": "delivery_deadline",
                        },
                    ],
                }
            ],
            "status": "UNKNOWN",
            "reason": "unknown",
        },
    )
    assert refused.status_code == 403
    assert malformed.status_code == duplicate.status_code == non_finite.status_code == 422
    assert unsupported.status_code == 415
    assert oversized.status_code == 413
    assert server_finding.status_code == 422
