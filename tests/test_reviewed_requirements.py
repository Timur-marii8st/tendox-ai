import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from procurement.documents.reviewed_requirements import (
    RequirementEntryDisposition,
    RequirementSetCoverageAssessment,
    RequirementSetNormalizationAssessment,
    ReviewedRequirementEntry,
    ReviewedRequirementSetProposal,
    build_case_requirement_set_binding,
    build_reviewed_requirement_set_decision,
    build_reviewed_requirement_set_proposal,
)
from procurement.domain.compliance import Verdict
from procurement.domain.provenance import Extractor, Provenance
from procurement.domain.requirements import Operator, Requirement

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _entry(ordinal: int, *, executable: bool) -> ReviewedRequirementEntry:
    provenance = Provenance(
        document_id="tz-1",
        locator=f"table 1 row {ordinal}",
        extractor=Extractor.MANUAL,
    )
    requirement = (
        Requirement(
            property=f"property_{ordinal}",
            operator=Operator.GE,
            value=Decimal(ordinal),
            mandatory=True,
            raw_text=f"Не менее {ordinal}",
            provenance=provenance,
        )
        if executable
        else None
    )
    return ReviewedRequirementEntry(
        ordinal=ordinal,
        raw_name=f"Параметр {ordinal}",
        raw_value=f"Значение {ordinal}",
        provenance=provenance,
        disposition=(
            RequirementEntryDisposition.EXECUTABLE
            if executable
            else RequirementEntryDisposition.MANUAL_REVIEW_REQUIRED
        ),
        requirement=requirement,
        review_note="Сверено с исходной строкой",
    )


def _proposal(*, prepared_by: str = "operator-1") -> ReviewedRequirementSetProposal:
    return build_reviewed_requirement_set_proposal(
        company_id="tenant-a",
        set_id="set-1",
        source_document_id="tz-1",
        source_document_sha256="a" * 64,
        declared_scope="Все строки таблицы технических требований",
        expected_entry_count=3,
        entries=(
            _entry(1, executable=True),
            _entry(2, executable=False),
            _entry(3, executable=True),
        ),
        prepared_by=prepared_by,
        prepared_at=NOW,
    )


def test_proposal_preserves_manual_rows_and_exposes_only_executable_requirements() -> None:
    proposal = _proposal()

    assert proposal.manual_entry_ordinals == (2,)
    assert tuple(item.property for item in proposal.executable_requirements) == (
        "property_1",
        "property_3",
    )
    assert (
        ReviewedRequirementSetProposal.model_validate_json(proposal.model_dump_json()) == proposal
    )


def test_proposal_rejects_missing_or_reordered_source_rows() -> None:
    with pytest.raises(ValidationError, match="contiguous and ordered"):
        build_reviewed_requirement_set_proposal(
            company_id="tenant-a",
            set_id="set-1",
            source_document_id="tz-1",
            source_document_sha256="a" * 64,
            declared_scope="scope",
            expected_entry_count=2,
            entries=(_entry(1, executable=True), _entry(3, executable=False)),
            prepared_by="operator-1",
            prepared_at=NOW,
        )


def test_entry_rejects_typed_requirement_with_different_provenance() -> None:
    entry = _entry(1, executable=True)
    assert entry.requirement is not None
    different = entry.requirement.model_copy(
        update={
            "provenance": Provenance(
                document_id="tz-1",
                locator="another row",
                extractor=Extractor.MANUAL,
            )
        }
    )
    with pytest.raises(ValidationError, match="provenance must match"):
        ReviewedRequirementEntry(
            **entry.model_dump(exclude={"requirement"}),
            requirement=different,
        )


def test_pass_requires_independent_reviewer_and_terminal_attestations() -> None:
    proposal = _proposal()
    with pytest.raises(ValueError, match="reviewer must differ"):
        build_reviewed_requirement_set_decision(
            proposal,
            coverage_assessment=RequirementSetCoverageAssessment.CONFIRMED,
            normalization_assessment=RequirementSetNormalizationAssessment.REVIEWED,
            status=Verdict.PASS,
            reason="ok",
            reviewed_by=proposal.prepared_by,
            reviewed_at=NOW,
        )

    with pytest.raises(ValidationError, match="PASS requires"):
        build_reviewed_requirement_set_decision(
            proposal,
            coverage_assessment=RequirementSetCoverageAssessment.UNRESOLVED,
            normalization_assessment=RequirementSetNormalizationAssessment.REVIEWED,
            status=Verdict.PASS,
            reason="ok",
            reviewed_by="reviewer-1",
            reviewed_at=NOW,
        )


def test_only_exact_pass_decision_can_be_bound_by_another_actor() -> None:
    proposal = _proposal()
    unknown = build_reviewed_requirement_set_decision(
        proposal,
        coverage_assessment=RequirementSetCoverageAssessment.UNRESOLVED,
        normalization_assessment=RequirementSetNormalizationAssessment.UNRESOLVED,
        status=Verdict.UNKNOWN,
        reason="coverage remains unresolved",
        reviewed_by="reviewer-1",
        reviewed_at=NOW,
    )
    with pytest.raises(ValueError, match="only a PASS"):
        build_case_requirement_set_binding(
            proposal,
            unknown,
            binding_id="binding-0",
            case_id="case-1",
            case_version=2,
            bound_by="operator-2",
            bound_at=NOW,
        )

    decision = build_reviewed_requirement_set_decision(
        proposal,
        coverage_assessment=RequirementSetCoverageAssessment.CONFIRMED,
        normalization_assessment=RequirementSetNormalizationAssessment.REVIEWED,
        status=Verdict.PASS,
        reason="Покрытие полное; ручные строки перечислены явно",
        reviewed_by="reviewer-1",
        reviewed_at=NOW,
    )
    binding = build_case_requirement_set_binding(
        proposal,
        decision,
        binding_id="binding-1",
        case_id="case-1",
        case_version=2,
        bound_by="operator-2",
        bound_at=NOW,
    )
    assert binding.proposal_sha256 == proposal.proposal_sha256
    assert binding.decision_sha256 == decision.decision_sha256

    with pytest.raises(ValidationError, match="binder must differ"):
        build_case_requirement_set_binding(
            proposal,
            decision,
            binding_id="binding-2",
            case_id="case-1",
            case_version=2,
            bound_by="reviewer-1",
            bound_at=NOW,
        )


def test_digest_tampering_is_rejected() -> None:
    payload = json.loads(_proposal().model_dump_json())
    payload["declared_scope"] = "changed"
    with pytest.raises(ValidationError, match="digest does not match"):
        ReviewedRequirementSetProposal.model_validate_json(json.dumps(payload))
