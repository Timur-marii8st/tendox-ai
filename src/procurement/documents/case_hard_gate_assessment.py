"""Create a new immutable case version with exact remaining hard-gate checks."""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.domain.cases import (
    CaseAssessment,
    GateCheck,
    GateKind,
    ProcurementCase,
    case_input_digest,
)
from procurement.domain.decisions import GateStatus
from procurement.domain.provenance import Extractor, Provenance


class CaseHardGateEvidenceRef(BaseModel):
    """Exact persisted document identity plus the reviewed locator."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str = Field(min_length=1, max_length=200)
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: str = Field(min_length=1, max_length=1_000)

    def provenance(self) -> Provenance:
        return Provenance(
            document_id=self.document_id,
            locator=self.locator,
            extractor=Extractor.MANUAL,
        )


class CaseHardGateDecisionInput(BaseModel):
    """One non-technical gate decision; technical evidence is server-owned."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: GateKind
    status: GateStatus
    reason: str = Field(min_length=1, max_length=4_000)
    evidence: tuple[CaseHardGateEvidenceRef, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def _known_decision_has_exact_evidence(self) -> Self:
        if self.kind in {GateKind.TECHNICAL, GateKind.DOCUMENT}:
            raise ValueError("technical and document gates are server-owned")
        if self.status is not GateStatus.UNKNOWN and not self.evidence:
            raise ValueError("known hard-gate decision requires exact document evidence")
        identities = [
            (item.document_id, item.document_sha256, item.locator) for item in self.evidence
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("hard-gate evidence references must be unique")
        return self


def materialize_case_hard_gate_assessment(
    source: ProcurementCase,
    checks: tuple[GateCheck, ...],
    *,
    reviewer_id: str,
    assessed_at: datetime,
) -> ProcurementCase:
    """Create version N+1 while preserving the exact inherited technical PASS."""
    source_assessment = source.assessment
    if source_assessment is None or source_assessment.input_digest != case_input_digest(source):
        raise ValueError("source case requires a current partial assessment")
    if len(source_assessment.checks) != 1:
        raise ValueError("source case must contain only the inherited technical gate")
    technical = source_assessment.checks[0]
    if technical.kind is not GateKind.TECHNICAL or technical.status is not GateStatus.PASS:
        raise ValueError("source case requires an exact technical PASS")
    if assessed_at.tzinfo is None or assessed_at.utcoffset() is None:
        raise ValueError("assessment time must include a timezone")
    if assessed_at < source_assessment.assessed_at:
        raise ValueError("assessment cannot predate the inherited technical review")
    expected = {kind for kind in GateKind if kind is not GateKind.TECHNICAL}
    actual = {check.kind for check in checks}
    if len(checks) != len(expected) or actual != expected:
        raise ValueError("all five non-technical hard gates are required exactly once")
    ordered_by_kind = {check.kind: check for check in checks} | {GateKind.TECHNICAL: technical}
    draft = source.model_copy(update={"version": source.version + 1, "assessment": None})
    assessment = CaseAssessment(
        reviewer_id=reviewer_id,
        assessed_at=assessed_at,
        input_digest=case_input_digest(draft),
        checks=tuple(ordered_by_kind[kind] for kind in GateKind),
    )
    return ProcurementCase.model_validate(draft.model_copy(update={"assessment": assessment}))
