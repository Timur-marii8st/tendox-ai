"""Completeness gate между document mapping и compliance verdict."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from conftest import attr, candidate, line_item
from procurement.documents.assessment import evaluate_document_mapping
from procurement.documents.extraction import ExtractedBlock
from procurement.documents.facts import (
    CompletenessAssessment,
    CompletenessStatus,
    DocumentRole,
    UnmappedBlockReview,
    UnmappedDisposition,
    map_blocks_to_requirements,
)
from procurement.domain.compliance import CandidateVerdict
from procurement.domain.provenance import Extractor, Provenance


def _block(text: str, locator: str) -> ExtractedBlock:
    return ExtractedBlock(
        text=text,
        provenance=Provenance(
            document_id="requirements.docx",
            locator=locator,
            extractor=Extractor.NATIVE_DOCX,
        ),
    )


def _automatic_mapping():
    return map_blocks_to_requirements(
        (
            _block("Гарантия не менее 24 мес.", "paragraph 1"),
            _block("Технические требования", "paragraph 2"),
        ),
        document_role=DocumentRole.TENDER_REQUIREMENTS,
    )


def _reviewed_mapping(status: CompletenessStatus):
    mapping = _automatic_mapping()
    disposition = (
        UnmappedDisposition.MATERIAL_REQUIREMENT
        if status is CompletenessStatus.FAIL
        else UnmappedDisposition.NON_REQUIREMENT
    )
    completeness = CompletenessAssessment(
        status=status,
        scope="Весь документ, все существенные технические требования",
        source_document_ids=("requirements.docx",),
        reviewer_id="reviewer-1",
        reviewed_at=datetime(2026, 9, 16, 12, tzinfo=UTC),
        review_reference="review/requirements/1",
        unmapped_reviews=(
            UnmappedBlockReview(
                block=mapping.unmapped[0],
                disposition=disposition,
                rationale="Заголовок без проверяемого условия"
                if status is CompletenessStatus.PASS
                else "Существенное условие требует отдельного правила",
            ),
        ),
    )
    return mapping.model_copy(update={"completeness": completeness})


def _item(mapping):
    return line_item(*mapping.requirements, equivalent_allowed=True)


def test_automatic_mapping_cannot_produce_compliant_result() -> None:
    mapping = _automatic_mapping()
    result = evaluate_document_mapping(
        mapping,
        _item(mapping),
        candidate(attr("warranty", Decimal(36), unit="мес")),
    )

    assert result.compliance.verdict is CandidateVerdict.COMPLIANT
    assert result.verdict is CandidateVerdict.NEEDS_CLARIFICATION
    assert "полнота" in result.reasons[0]


def test_reviewed_complete_mapping_can_produce_compliant_result() -> None:
    mapping = _reviewed_mapping(CompletenessStatus.PASS)
    result = evaluate_document_mapping(
        mapping,
        _item(mapping),
        candidate(attr("warranty", Decimal(2), unit="года")),
    )

    assert result.verdict is CandidateVerdict.COMPLIANT


def test_known_mandatory_failure_is_not_hidden_by_unknown_completeness() -> None:
    mapping = _automatic_mapping()
    result = evaluate_document_mapping(
        mapping,
        _item(mapping),
        candidate(attr("warranty", Decimal(12), unit="мес")),
    )

    assert result.verdict is CandidateVerdict.FAIL


def test_failed_completeness_needs_clarification_for_otherwise_matching_candidate() -> None:
    mapping = _reviewed_mapping(CompletenessStatus.FAIL)
    result = evaluate_document_mapping(
        mapping,
        _item(mapping),
        candidate(attr("warranty", Decimal(36), unit="мес")),
    )

    assert result.completeness.status is CompletenessStatus.FAIL
    assert result.verdict is CandidateVerdict.NEEDS_CLARIFICATION


def test_line_item_cannot_replace_mapping_requirements() -> None:
    mapping = _automatic_mapping()
    with pytest.raises(ValueError, match="точные requirements"):
        evaluate_document_mapping(
            mapping,
            line_item(),
            candidate(attr("warranty", Decimal(36), unit="мес")),
        )
