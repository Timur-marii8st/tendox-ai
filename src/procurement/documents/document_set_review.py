"""Terminal human completeness decision for one exact document-set manifest."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.documents.completeness_review import (
    CompletenessReviewRecord,
    canonical_json_sha256,
)
from procurement.documents.document_set_evidence import (
    DocumentSetEvidenceManifest,
    DocumentSetEvidenceMember,
    project_document_set_evidence_member,
)
from procurement.documents.facts import CompletenessStatus


class DocumentSetMemberAssessment(StrEnum):
    REVIEWED_IN_SCOPE = "REVIEWED_IN_SCOPE"
    UNRESOLVED = "UNRESOLVED"


class DocumentSetInventoryAssessment(StrEnum):
    CONFIRMED_FOR_DECLARED_SCOPE = "CONFIRMED_FOR_DECLARED_SCOPE"
    UNRESOLVED = "UNRESOLVED"


class DocumentSetCrossAssessment(StrEnum):
    CHECKED_NO_OPEN_ISSUES = "CHECKED_NO_OPEN_ISSUES"
    OPEN_ISSUES = "OPEN_ISSUES"
    UNRESOLVED = "UNRESOLVED"


class DocumentSetFindingKind(StrEnum):
    CONFIRMED_MATERIAL_OMISSION = "CONFIRMED_MATERIAL_OMISSION"
    CONFIRMED_MISSING_DOCUMENT = "CONFIRMED_MISSING_DOCUMENT"
    UNRESOLVED_CONFLICT = "UNRESOLVED_CONFLICT"
    UNRESOLVED_GAP = "UNRESOLVED_GAP"


class DocumentSetFindingOrigin(StrEnum):
    REVIEWER = "REVIEWER"
    SERVER = "SERVER"


class DocumentSetMappingField(StrEnum):
    DELIVERY_DEADLINE = "delivery_deadline"
    EQUIVALENT_ALLOWED = "equivalent_allowed"


class ConstituentDecisionRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    member_ordinal: int = Field(ge=1, le=10)
    review_id: str = Field(min_length=1, max_length=200)
    review_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DocumentSetMemberAttestation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    reference: ConstituentDecisionRef
    assessment: DocumentSetMemberAssessment
    rationale: str = Field(min_length=1, max_length=2_000)

    @field_validator("rationale")
    @classmethod
    def _trim_rationale(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("member attestation rationale must not be blank")
        return value.strip()


class DocumentSetSourceBlockRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    kind: Literal["SOURCE_BLOCK"] = "SOURCE_BLOCK"
    member_ordinal: int = Field(ge=1, le=10)
    extraction_block_index: int = Field(ge=0)


class DocumentSetMappingFieldRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    kind: Literal["MAPPING_FIELD"] = "MAPPING_FIELD"
    member_ordinal: int = Field(ge=1, le=10)
    field: DocumentSetMappingField


DocumentSetEvidenceRef = Annotated[
    DocumentSetSourceBlockRef | DocumentSetMappingFieldRef,
    Field(discriminator="kind"),
]


class DocumentSetFinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    finding_id: str = Field(min_length=1, max_length=200)
    kind: DocumentSetFindingKind
    evidence: tuple[DocumentSetEvidenceRef, ...] = Field(min_length=1, max_length=20)
    rationale: str = Field(min_length=1, max_length=2_000)
    origin: DocumentSetFindingOrigin

    @field_validator("finding_id", "rationale")
    @classmethod
    def _trim_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("finding text must not be blank")
        return value.strip()

    @model_validator(mode="after")
    def _finding_has_required_evidence(self) -> Self:
        unique = {canonical_json_sha256(item.model_dump(mode="json")) for item in self.evidence}
        if len(unique) != len(self.evidence):
            raise ValueError("finding evidence must not repeat")
        if self.kind is DocumentSetFindingKind.UNRESOLVED_CONFLICT:
            if len(self.evidence) < 2 or len({item.member_ordinal for item in self.evidence}) < 2:
                raise ValueError("cross-document conflict needs evidence from two members")
        elif not any(isinstance(item, DocumentSetSourceBlockRef) for item in self.evidence):
            raise ValueError("non-conflict finding needs source-block evidence")
        return self


class DocumentSetReviewDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["document-set-completeness-decision-v1"] = (
        "document-set-completeness-decision-v1"
    )
    company_id: str = Field(min_length=1, max_length=200)
    manifest_id: str = Field(min_length=1, max_length=200)
    manifest_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope: str = Field(min_length=1, max_length=4_000)
    members: tuple[DocumentSetMemberAttestation, ...] = Field(min_length=2, max_length=10)
    inventory_assessment: DocumentSetInventoryAssessment
    inventory_rationale: str = Field(min_length=1, max_length=2_000)
    cross_document_assessment: DocumentSetCrossAssessment
    cross_document_rationale: str = Field(min_length=1, max_length=4_000)
    findings: tuple[DocumentSetFinding, ...] = Field(default=(), max_length=100)
    status: CompletenessStatus
    reason: str = Field(min_length=1, max_length=4_000)
    decided_by: str = Field(min_length=1, max_length=200)
    decided_at: datetime
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator(
        "company_id",
        "manifest_id",
        "scope",
        "inventory_rationale",
        "cross_document_rationale",
        "reason",
        "decided_by",
    )
    @classmethod
    def _trim_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("document-set decision text must not be blank")
        return value.strip()

    @field_validator("decided_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("document-set decision time must include timezone")
        return value

    @model_validator(mode="after")
    def _decision_is_bound(self) -> Self:
        if tuple(item.reference.member_ordinal for item in self.members) != tuple(
            range(1, len(self.members) + 1)
        ):
            raise ValueError("member attestations must be complete and ordered")
        finding_ids = [item.finding_id for item in self.findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("finding IDs must be unique")
        payload = self.model_dump(mode="json", exclude={"decision_sha256"})
        if canonical_json_sha256(payload) != self.decision_sha256:
            raise ValueError("document-set decision digest does not match payload")
        return self


class DocumentSetConstituentEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    member: DocumentSetEvidenceMember
    review: CompletenessReviewRecord
    decision_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class DocumentSetReviewEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    manifest: DocumentSetEvidenceManifest
    constituents: tuple[DocumentSetConstituentEvidence, ...] = Field(min_length=2, max_length=10)
    server_findings: tuple[DocumentSetFinding, ...] = Field(default=(), max_length=100)


def _server_findings(
    records: tuple[CompletenessReviewRecord, ...],
) -> tuple[DocumentSetFinding, ...]:
    dated = tuple(
        (ordinal, record.snapshot.mapping.delivery_deadline)
        for ordinal, record in enumerate(records, start=1)
        if record.snapshot.mapping.delivery_deadline is not None
    )
    if len({value for _, value in dated}) <= 1:
        return ()
    evidence = tuple(
        DocumentSetMappingFieldRef(
            member_ordinal=ordinal,
            field=DocumentSetMappingField.DELIVERY_DEADLINE,
        )
        for ordinal, _ in dated
    )
    identity = canonical_json_sha256(tuple((ordinal, value) for ordinal, value in dated))[:20]
    return (
        DocumentSetFinding(
            finding_id=f"server-deadline-conflict-{identity}",
            kind=DocumentSetFindingKind.UNRESOLVED_CONFLICT,
            evidence=evidence,
            rationale="Selected documents contain different non-empty delivery deadlines.",
            origin=DocumentSetFindingOrigin.SERVER,
        ),
    )


def build_document_set_review_evidence(
    manifest: DocumentSetEvidenceManifest,
    records: tuple[CompletenessReviewRecord, ...],
) -> DocumentSetReviewEvidence:
    validated_manifest = DocumentSetEvidenceManifest.model_validate(
        manifest.model_dump(mode="python")
    )
    if type(records) is not tuple or len(records) != len(validated_manifest.members):
        raise ValueError("constituent reviews must match every manifest member")
    constituents: list[DocumentSetConstituentEvidence] = []
    for member, record in zip(validated_manifest.members, records, strict=True):
        validated_record = CompletenessReviewRecord.model_validate(record.model_dump(mode="python"))
        if validated_record.snapshot.company_id != validated_manifest.company_id:
            raise ValueError("constituent review tenant does not match manifest")
        expected = project_document_set_evidence_member(
            validated_record.snapshot,
            ordinal=member.ordinal,
        )
        if expected != member:
            raise ValueError("constituent review does not match manifest member")
        digest = (
            None
            if validated_record.decision is None
            else canonical_json_sha256(validated_record.decision.model_dump(mode="json"))
        )
        constituents.append(
            DocumentSetConstituentEvidence(
                member=member,
                review=validated_record,
                decision_sha256=digest,
            )
        )
    validated_records = tuple(item.review for item in constituents)
    return DocumentSetReviewEvidence(
        manifest=validated_manifest,
        constituents=tuple(constituents),
        server_findings=_server_findings(validated_records),
    )


def build_document_set_review_decision(
    evidence: DocumentSetReviewEvidence,
    *,
    attestations: tuple[DocumentSetMemberAttestation, ...],
    inventory_assessment: DocumentSetInventoryAssessment,
    inventory_rationale: str,
    cross_document_assessment: DocumentSetCrossAssessment,
    cross_document_rationale: str,
    reviewer_findings: tuple[DocumentSetFinding, ...],
    status: CompletenessStatus,
    reason: str,
    decided_by: str,
    decided_at: datetime,
) -> DocumentSetReviewDecision:
    """Validate exact constituent decisions and derive a fail-closed package result."""
    validated = DocumentSetReviewEvidence.model_validate(evidence.model_dump(mode="python"))
    rebuilt = build_document_set_review_evidence(
        validated.manifest,
        tuple(item.review for item in validated.constituents),
    )
    if validated != rebuilt:
        raise ValueError("document-set evidence projections do not match source reviews")
    validated = rebuilt
    attestations = tuple(
        DocumentSetMemberAttestation.model_validate(item.model_dump(mode="python"))
        for item in attestations
    )
    reviewer_findings = tuple(
        DocumentSetFinding.model_validate(item.model_dump(mode="python"))
        for item in reviewer_findings
    )
    if decided_by == validated.manifest.created_by or any(
        decided_by == item.review.snapshot.created_by for item in validated.constituents
    ):
        raise ValueError("document-set reviewer must be independent from snapshot creators")
    if len(attestations) != len(validated.constituents):
        raise ValueError("every manifest member needs one attestation")
    decisions = []
    for constituent, attestation in zip(validated.constituents, attestations, strict=True):
        decision = constituent.review.decision
        if decision is None or constituent.decision_sha256 is None:
            raise ValueError("every constituent review needs a terminal decision")
        expected_ref = ConstituentDecisionRef(
            member_ordinal=constituent.member.ordinal,
            review_id=constituent.member.completeness_review_id,
            review_evidence_sha256=constituent.member.completeness_review_evidence_sha256,
            decision_sha256=constituent.decision_sha256,
        )
        if attestation.reference != expected_ref:
            raise ValueError("member attestation does not match exact constituent decision")
        decisions.append(decision)
    if any(item.origin is not DocumentSetFindingOrigin.REVIEWER for item in reviewer_findings):
        raise ValueError("caller cannot create server findings")

    records = tuple(item.review for item in validated.constituents)
    for finding in reviewer_findings:
        for ref in finding.evidence:
            record = records[ref.member_ordinal - 1] if ref.member_ordinal <= len(records) else None
            if record is None:
                raise ValueError("finding references a member outside the manifest")
            if isinstance(ref, DocumentSetSourceBlockRef):
                if ref.extraction_block_index >= len(record.snapshot.extraction.blocks):
                    raise ValueError("finding references a block outside the snapshot")
            else:
                if getattr(record.snapshot.mapping, ref.field.value) is None:
                    raise ValueError("finding references an absent mapping field")

    findings = tuple(reviewer_findings) + validated.server_findings
    positive_fail = any(item.status is CompletenessStatus.FAIL for item in decisions) or any(
        item.kind
        in {
            DocumentSetFindingKind.CONFIRMED_MATERIAL_OMISSION,
            DocumentSetFindingKind.CONFIRMED_MISSING_DOCUMENT,
        }
        for item in findings
    )
    unresolved = (
        any(item.status is CompletenessStatus.UNKNOWN for item in decisions)
        or any(item.assessment is DocumentSetMemberAssessment.UNRESOLVED for item in attestations)
        or inventory_assessment is DocumentSetInventoryAssessment.UNRESOLVED
        or cross_document_assessment is not DocumentSetCrossAssessment.CHECKED_NO_OPEN_ISSUES
        or bool(findings)
    )
    derived_status = (
        CompletenessStatus.FAIL
        if positive_fail
        else CompletenessStatus.UNKNOWN
        if unresolved
        else CompletenessStatus.PASS
    )
    if status is not derived_status:
        raise ValueError("requested status does not match fail-closed package evidence")
    if cross_document_assessment is DocumentSetCrossAssessment.OPEN_ISSUES and not findings:
        raise ValueError("open cross-document issues require findings")
    if cross_document_assessment is DocumentSetCrossAssessment.CHECKED_NO_OPEN_ISSUES and findings:
        raise ValueError("no-open-issues assessment cannot contain findings")
    if inventory_assessment is DocumentSetInventoryAssessment.CONFIRMED_FOR_DECLARED_SCOPE and any(
        item.kind is DocumentSetFindingKind.CONFIRMED_MISSING_DOCUMENT for item in findings
    ):
        raise ValueError("confirmed inventory cannot contain a confirmed missing document")

    fields = dict(
        company_id=validated.manifest.company_id,
        manifest_id=validated.manifest.manifest_id,
        manifest_evidence_sha256=validated.manifest.evidence_sha256,
        scope=validated.manifest.scope,
        members=attestations,
        inventory_assessment=inventory_assessment,
        inventory_rationale=inventory_rationale,
        cross_document_assessment=cross_document_assessment,
        cross_document_rationale=cross_document_rationale,
        findings=findings,
        status=status,
        reason=reason,
        decided_by=decided_by,
        decided_at=decided_at,
    )
    digest = canonical_json_sha256(
        {"schema_version": "document-set-completeness-decision-v1", **fields}
    )
    return DocumentSetReviewDecision(
        company_id=validated.manifest.company_id,
        manifest_id=validated.manifest.manifest_id,
        manifest_evidence_sha256=validated.manifest.evidence_sha256,
        scope=validated.manifest.scope,
        members=attestations,
        inventory_assessment=inventory_assessment,
        inventory_rationale=inventory_rationale,
        cross_document_assessment=cross_document_assessment,
        cross_document_rationale=cross_document_rationale,
        findings=findings,
        status=status,
        reason=reason,
        decided_by=decided_by,
        decided_at=decided_at,
        decision_sha256=digest,
    )
