from datetime import timedelta

import pytest

from procurement.documents import (
    CaseHardGateDecisionInput,
    CaseHardGateEvidenceRef,
    materialize_case_hard_gate_assessment,
)
from procurement.domain.cases import GateCheck, GateKind, case_input_digest, evaluate_case
from procurement.domain.decisions import GateStatus, RecommendationDecision
from procurement.domain.provenance import Extractor, Provenance
from test_server_offer_case import record


def _source():
    from procurement.documents import materialize_case_from_server_offer_economics

    return materialize_case_from_server_offer_economics(record())


def _decisions(status: GateStatus = GateStatus.PASS) -> tuple[CaseHardGateDecisionInput, ...]:
    evidence = CaseHardGateEvidenceRef(
        document_id="evidence-1",
        document_sha256="a" * 64,
        locator="paragraph 1",
    )
    return tuple(
        CaseHardGateDecisionInput(
            kind=kind,
            status=status,
            reason=f"reviewed {kind.value}",
            evidence=() if status is GateStatus.UNKNOWN else (evidence,),
        )
        for kind in GateKind
        if kind not in {GateKind.TECHNICAL, GateKind.DOCUMENT}
    )


def _checks(decisions: tuple[CaseHardGateDecisionInput, ...]) -> tuple[GateCheck, ...]:
    caller_checks = tuple(
        GateCheck(
            kind=item.kind,
            status=item.status,
            reason=item.reason,
            evidence=tuple(reference.provenance() for reference in item.evidence),
        )
        for item in decisions
    )
    document = GateCheck(
        kind=GateKind.DOCUMENT,
        status=GateStatus.PASS,
        reason="terminal document-set review",
        evidence=(
            Provenance(
                document_id="manifest-1",
                locator="terminal decision",
                extractor=Extractor.MANUAL,
            ),
        ),
    )
    return (*caller_checks, document)


def test_materializes_complete_six_gate_assessment_on_next_version() -> None:
    source = _source()
    assert source.assessment is not None
    at = source.assessment.assessed_at + timedelta(minutes=1)
    result = materialize_case_hard_gate_assessment(
        source, _checks(_decisions()), reviewer_id="operator-2", assessed_at=at
    )
    assert result.version == source.version + 1
    assert result.selected_quote == source.selected_quote
    assert result.scenarios == source.scenarios
    assert result.assessment is not None
    assert tuple(item.kind for item in result.assessment.checks) == tuple(GateKind)
    assert result.assessment.input_digest == case_input_digest(result)
    assert result.assessment.checks[2] == source.assessment.checks[0]


def test_explicit_unknown_remains_needs_analysis() -> None:
    source = _source()
    assert source.assessment is not None
    at = source.assessment.assessed_at + timedelta(minutes=1)
    result = materialize_case_hard_gate_assessment(
        source, _checks(_decisions(GateStatus.UNKNOWN)), reviewer_id="operator-2", assessed_at=at
    )
    assert evaluate_case(result, at=at).decision is RecommendationDecision.NEEDS_ANALYSIS


def test_rejects_missing_gate_or_caller_owned_technical_gate() -> None:
    source = _source()
    assert source.assessment is not None
    at = source.assessment.assessed_at + timedelta(minutes=1)
    checks = _checks(_decisions())
    with pytest.raises(ValueError, match="five"):
        materialize_case_hard_gate_assessment(
            source, checks[:-1], reviewer_id="operator-2", assessed_at=at
        )
    with pytest.raises(ValueError, match="technical"):
        CaseHardGateDecisionInput(
            kind=GateKind.TECHNICAL,
            status=GateStatus.PASS,
            reason="caller replacement",
            evidence=(
                CaseHardGateEvidenceRef(
                    document_id="evidence-1",
                    document_sha256="a" * 64,
                    locator="paragraph 1",
                ),
            ),
        )
    with pytest.raises(ValueError, match="document"):
        CaseHardGateDecisionInput(
            kind=GateKind.DOCUMENT,
            status=GateStatus.PASS,
            reason="caller replacement",
            evidence=(
                CaseHardGateEvidenceRef(
                    document_id="evidence-1",
                    document_sha256="a" * 64,
                    locator="paragraph 1",
                ),
            ),
        )
