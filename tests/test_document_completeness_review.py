"""Persisted-review domain contract stays evidence-bound and fail-closed."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from procurement.documents import (
    CompletenessBlockDecision,
    CompletenessReviewRecord,
    CompletenessReviewSourceInvalid,
    CompletenessStatus,
    DocumentRole,
    ExtractedBlock,
    ExtractionReason,
    ExtractionResult,
    ExtractionStatus,
    UnmappedDisposition,
    build_completeness_review_decision,
    build_completeness_review_snapshot,
)
from procurement.domain.provenance import Extractor, Provenance

NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)


def _block(text: str, locator: str) -> ExtractedBlock:
    return ExtractedBlock(
        text=text,
        provenance=Provenance(
            document_id="doc-1",
            locator=locator,
            extractor=Extractor.NATIVE_DOCX,
            confidence=1,
        ),
    )


def _extraction() -> ExtractionResult:
    blocks = (
        _block("Гарантия не менее 24 мес.", "paragraph 1"),
        _block("Раздел общих сведений", "paragraph 2"),
    )
    return ExtractionResult(
        status=ExtractionStatus.PASS,
        blocks=blocks,
        reasons=(),
        source_units_total=2,
        source_units_extracted=2,
        characters_extracted=sum(len(block.text) for block in blocks),
    )


def _snapshot():
    return build_completeness_review_snapshot(
        company_id="company-a",
        review_id="review-1",
        source_document_id="doc-1",
        source_document_sha256="a" * 64,
        document_role=DocumentRole.TENDER_REQUIREMENTS,
        extraction=_extraction(),
        created_by="operator-1",
        created_at=NOW,
    )


def test_snapshot_is_server_derived_unknown_and_digest_bound() -> None:
    snapshot = _snapshot()
    assert snapshot.mapping.completeness.status is CompletenessStatus.UNKNOWN
    assert snapshot.mapping.blocks_total == 2
    assert len(snapshot.mapping.requirements) == 1
    assert len(snapshot.mapping.unmapped) == 1
    restored = type(snapshot).model_validate_json(snapshot.model_dump_json())
    assert restored == snapshot
    with pytest.raises(ValidationError, match="evidence digest"):
        snapshot.model_copy(update={"evidence_sha256": "0" * 64}).model_validate(
            snapshot.model_dump(mode="python") | {"evidence_sha256": "0" * 64}
        )


def test_pass_requires_every_unmapped_block_and_no_material() -> None:
    snapshot = _snapshot()
    with pytest.raises(ValidationError, match="PASS требует решения"):
        build_completeness_review_decision(
            snapshot,
            status=CompletenessStatus.PASS,
            scope="all requirements",
            reason="reviewed",
            block_decisions=(),
            decided_by="reviewer-1",
            decided_at=NOW,
            review_reference="review:1",
        )
    decision = build_completeness_review_decision(
        snapshot,
        status=CompletenessStatus.PASS,
        scope="all requirements",
        reason="all residual text is informational",
        block_decisions=(
            CompletenessBlockDecision(
                unmapped_index=0,
                disposition=UnmappedDisposition.NON_REQUIREMENT,
                rationale="heading only",
            ),
        ),
        decided_by="reviewer-1",
        decided_at=NOW,
        review_reference="review:1",
    )
    assert decision.reviewed_mapping.completeness.status is CompletenessStatus.PASS


def test_fail_requires_material_and_unknown_preserves_review_metadata() -> None:
    snapshot = _snapshot()
    with pytest.raises(ValidationError, match="существен"):
        build_completeness_review_decision(
            snapshot,
            status=CompletenessStatus.FAIL,
            scope="all requirements",
            reason="incomplete mapping",
            block_decisions=(),
            decided_by="reviewer-1",
            decided_at=NOW,
            review_reference="review:1",
        )
    material = CompletenessBlockDecision(
        unmapped_index=0,
        disposition=UnmappedDisposition.MATERIAL_REQUIREMENT,
        rationale="requires manual structuring",
    )
    failed = build_completeness_review_decision(
        snapshot,
        status=CompletenessStatus.FAIL,
        scope="all requirements",
        reason="material requirement remains",
        block_decisions=(material,),
        decided_by="reviewer-1",
        decided_at=NOW,
        review_reference="review:1",
    )
    assert failed.status is CompletenessStatus.FAIL
    unknown = build_completeness_review_decision(
        snapshot,
        status=CompletenessStatus.UNKNOWN,
        scope="first section",
        reason="review could not cover the remainder",
        block_decisions=(),
        decided_by="reviewer-1",
        decided_at=NOW,
        review_reference="review:1",
    )
    assert unknown.reviewed_mapping.completeness.reviewer_id is None
    assert unknown.decided_by == "reviewer-1"
    assert unknown.scope == "first section"


def test_invalid_index_and_incomplete_or_non_native_source_are_rejected() -> None:
    with pytest.raises(ValueError, match="outside"):
        build_completeness_review_decision(
            _snapshot(),
            status=CompletenessStatus.UNKNOWN,
            scope="all",
            reason="uncertain",
            block_decisions=(
                CompletenessBlockDecision(
                    unmapped_index=10,
                    disposition=UnmappedDisposition.NON_REQUIREMENT,
                    rationale="invalid",
                ),
            ),
            decided_by="reviewer-1",
            decided_at=NOW,
            review_reference="review:1",
        )
    incomplete = _extraction().model_copy(
        update={
            "status": ExtractionStatus.UNKNOWN,
            "reasons": (ExtractionReason.OCR_REQUIRED,),
        }
    )
    with pytest.raises(CompletenessReviewSourceInvalid):
        build_completeness_review_snapshot(
            company_id="company-a",
            review_id="review-1",
            source_document_id="doc-1",
            source_document_sha256="a" * 64,
            document_role=DocumentRole.TENDER_REQUIREMENTS,
            extraction=incomplete,
            created_by="operator-1",
            created_at=NOW,
        )
    unexplained_gap = _extraction().model_copy(
        update={
            "source_units_total": 3,
            "source_units_extracted": 2,
        }
    )
    with pytest.raises(CompletenessReviewSourceInvalid):
        build_completeness_review_snapshot(
            company_id="company-a",
            review_id="review-gap",
            source_document_id="doc-1",
            source_document_sha256="a" * 64,
            document_role=DocumentRole.TENDER_REQUIREMENTS,
            extraction=unexplained_gap,
            created_by="operator-1",
            created_at=NOW,
        )
    ocr_block = _block("Гарантия не менее 24 мес.", "OCR page 1").model_copy(
        update={
            "provenance": _block("x", "x").provenance.model_copy(
                update={"extractor": Extractor.OCR}
            )
        }
    )
    ocr_extraction = ExtractionResult(
        status=ExtractionStatus.PASS,
        blocks=(ocr_block,),
        reasons=(),
        source_units_total=1,
        source_units_extracted=1,
        characters_extracted=len(ocr_block.text),
    )
    with pytest.raises(CompletenessReviewSourceInvalid):
        build_completeness_review_snapshot(
            company_id="company-a",
            review_id="review-ocr",
            source_document_id="doc-1",
            source_document_sha256="a" * 64,
            document_role=DocumentRole.TENDER_REQUIREMENTS,
            extraction=ocr_extraction,
            created_by="operator-1",
            created_at=NOW,
        )


def test_record_rejects_decision_bound_to_another_snapshot() -> None:
    snapshot = _snapshot()
    decision = build_completeness_review_decision(
        snapshot,
        status=CompletenessStatus.UNKNOWN,
        scope="all",
        reason="not enough evidence",
        block_decisions=(),
        decided_by="reviewer-1",
        decided_at=NOW,
        review_reference="review:1",
    )

    with pytest.raises(ValidationError, match="identity does not match snapshot"):
        CompletenessReviewRecord(
            snapshot=snapshot,
            decision=decision.model_copy(update={"evidence_sha256": "0" * 64}),
        )
