"""Явная привязка terminal document-set решения к заготовке кейса.

Граница preparation-only: только чистый домен, без SQL, API, сети и фоновых
задач. Вызывающий код передаёт точные immutable evidence и decision; выбор
«последнего PASS» автоматически запрещён — несовпадение digest отклоняется.
Привязка не объединяет mapping, не выбирает latest, не создаёт ``Requirement``
и не разрешает ``PARTICIPATE``: экономика, КП и hard gates проверяются позже
существующим case evaluator.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.documents.completeness_review import canonical_json_sha256
from procurement.documents.document_set_review import (
    DocumentSetReviewDecision,
    DocumentSetReviewEvidence,
    build_document_set_review_evidence,
)
from procurement.documents.facts import CompletenessStatus
from procurement.domain.cases import GateCheck, GateKind
from procurement.domain.decisions import GateStatus
from procurement.domain.provenance import Extractor, Provenance

CASE_DOCUMENT_EVIDENCE_SCHEMA_VERSION: Literal["case-document-evidence-binding-v1"] = (
    "case-document-evidence-binding-v1"
)


class CaseDocumentEvidenceBinding(BaseModel):
    """Точная ссылка заготовки кейса на одно terminal document-set решение."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["case-document-evidence-binding-v1"] = (
        CASE_DOCUMENT_EVIDENCE_SCHEMA_VERSION
    )
    company_id: str = Field(min_length=1, max_length=200)
    binding_id: str = Field(min_length=1, max_length=200)
    manifest_id: str = Field(min_length=1, max_length=200)
    manifest_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: CompletenessStatus
    scope: str = Field(min_length=1, max_length=4_000)
    member_count: int = Field(ge=2, le=10)
    member_review_ids: tuple[str, ...] = Field(min_length=2, max_length=10)
    decided_by: str = Field(min_length=1, max_length=200)
    bound_by: str = Field(min_length=1, max_length=200)
    bound_at: datetime
    binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator(
        "company_id",
        "binding_id",
        "manifest_id",
        "scope",
        "decided_by",
        "bound_by",
    )
    @classmethod
    def _trim_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("case evidence binding text must not be blank")
        return normalized

    @field_validator("bound_at")
    @classmethod
    def _bound_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("case evidence binding time must include timezone")
        return value

    @model_validator(mode="after")
    def _binding_is_bound(self) -> Self:
        if len(self.member_review_ids) != self.member_count:
            raise ValueError("member review IDs must match member count")
        if len(set(self.member_review_ids)) != len(self.member_review_ids):
            raise ValueError("member review IDs must be unique")
        if any(not item.strip() for item in self.member_review_ids):
            raise ValueError("member review IDs must not be blank")
        if self.bound_by == self.decided_by:
            raise ValueError("case binder must differ from terminal decision maker")
        payload = self.model_dump(mode="json", exclude={"binding_sha256"})
        if canonical_json_sha256(payload) != self.binding_sha256:
            raise ValueError("case evidence binding digest does not match payload")
        return self


def build_case_document_evidence_binding(
    evidence: DocumentSetReviewEvidence,
    decision: DocumentSetReviewDecision,
    *,
    company_id: str,
    binding_id: str,
    bound_by: str,
    bound_at: datetime,
) -> CaseDocumentEvidenceBinding:
    """Связать точные evidence/decision с заготовкой кейса без автовыбора."""
    validated_evidence = DocumentSetReviewEvidence.model_validate(
        evidence.model_dump(mode="python")
    )
    rebuilt = build_document_set_review_evidence(
        validated_evidence.manifest,
        tuple(item.review for item in validated_evidence.constituents),
    )
    if validated_evidence != rebuilt:
        raise ValueError("document-set evidence projections do not match source reviews")
    validated_decision = DocumentSetReviewDecision.model_validate(
        decision.model_dump(mode="python")
    )
    manifest = validated_evidence.manifest
    normalized_company = company_id.strip()
    normalized_binding = binding_id.strip()
    normalized_binder = bound_by.strip()
    if not normalized_company:
        raise ValueError("case evidence binding company must not be blank")
    if not normalized_binding:
        raise ValueError("case evidence binding ID must not be blank")
    if not normalized_binder:
        raise ValueError("case evidence binder must not be blank")
    if bound_at.tzinfo is None or bound_at.utcoffset() is None:
        raise ValueError("case evidence binding time must include timezone")
    if normalized_company != manifest.company_id:
        raise ValueError("case evidence company does not match manifest tenant")
    if validated_decision.company_id != manifest.company_id:
        raise ValueError("terminal decision tenant does not match manifest")
    if validated_decision.manifest_id != manifest.manifest_id:
        raise ValueError("terminal decision manifest does not match evidence")
    if validated_decision.manifest_evidence_sha256 != manifest.evidence_sha256:
        raise ValueError("terminal decision evidence digest is stale")
    expected_refs = tuple(
        (
            item.member.ordinal,
            item.member.completeness_review_id,
            item.member.completeness_review_evidence_sha256,
            item.decision_sha256,
        )
        for item in validated_evidence.constituents
    )
    actual_refs = tuple(
        (
            item.reference.member_ordinal,
            item.reference.review_id,
            item.reference.review_evidence_sha256,
            item.reference.decision_sha256,
        )
        for item in validated_decision.members
    )
    if actual_refs != expected_refs:
        raise ValueError("terminal decision members do not match exact evidence")
    if normalized_binder == validated_decision.decided_by:
        raise ValueError("case binder must differ from terminal decision maker")
    member_review_ids = tuple(item.completeness_review_id for item in manifest.members)
    fields: dict[str, object] = {
        "company_id": normalized_company,
        "binding_id": normalized_binding,
        "manifest_id": manifest.manifest_id,
        "manifest_evidence_sha256": manifest.evidence_sha256,
        "decision_sha256": validated_decision.decision_sha256,
        "status": validated_decision.status,
        "scope": validated_decision.scope,
        "member_count": len(manifest.members),
        "member_review_ids": member_review_ids,
        "decided_by": validated_decision.decided_by,
        "bound_by": normalized_binder,
        "bound_at": bound_at,
    }
    digest = canonical_json_sha256(
        {"schema_version": CASE_DOCUMENT_EVIDENCE_SCHEMA_VERSION, **fields}
    )
    return CaseDocumentEvidenceBinding(
        company_id=normalized_company,
        binding_id=normalized_binding,
        manifest_id=manifest.manifest_id,
        manifest_evidence_sha256=manifest.evidence_sha256,
        decision_sha256=validated_decision.decision_sha256,
        status=validated_decision.status,
        scope=validated_decision.scope,
        member_count=len(manifest.members),
        member_review_ids=member_review_ids,
        decided_by=validated_decision.decided_by,
        bound_by=normalized_binder,
        bound_at=bound_at,
        binding_sha256=digest,
    )


_STATUS_TO_GATE = {
    CompletenessStatus.PASS: GateStatus.PASS,
    CompletenessStatus.FAIL: GateStatus.FAIL,
    CompletenessStatus.UNKNOWN: GateStatus.UNKNOWN,
}

_STATUS_REASON = {
    CompletenessStatus.PASS: "комплектность доказана терминальным решением",
    CompletenessStatus.FAIL: "терминальное решение зафиксировало некомплектность",
    CompletenessStatus.UNKNOWN: "полнота не доказана терминальным решением",
}


def document_gate_check_from_binding(binding: CaseDocumentEvidenceBinding) -> GateCheck:
    """Вывести DOCUMENT-проверку кейса из точной привязки без новой оценки.

    Статус наследуется один к одному: ``FAIL`` привязки блокирует кандидата
    через существующий hard gate, ``UNKNOWN`` не превращается в допуск.
    Проверка ссылается на точные manifest/decision digest и не разрешает
    ``PARTICIPATE`` сама по себе: оператор включает её в полную оценку кейса,
    а экономика и КП проверяются case evaluator как раньше.
    """
    validated = CaseDocumentEvidenceBinding.model_validate(binding.model_dump(mode="python"))
    return GateCheck(
        kind=GateKind.DOCUMENT,
        status=_STATUS_TO_GATE[validated.status],
        reason=(
            f"{_STATUS_REASON[validated.status]} {validated.decision_sha256} "
            f"для комплекта {validated.manifest_id}"
        ),
        evidence=(
            Provenance(
                document_id=validated.manifest_id,
                locator=f"terminal decision {validated.decision_sha256}",
                extractor=Extractor.MANUAL,
                confidence=1.0,
            ),
        ),
    )
