"""Multi-document evidence remains ordered, source-bound, and UNKNOWN."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from procurement.documents.completeness_review import build_completeness_review_snapshot
from procurement.documents.document_set_evidence import (
    DocumentSetEvidenceManifest,
    build_document_set_evidence_manifest,
)
from procurement.documents.extraction import ExtractedBlock, ExtractionResult, ExtractionStatus
from procurement.documents.facts import CompletenessStatus, DocumentRole
from procurement.domain.provenance import Extractor, Provenance


def _snapshot(
    *,
    review_id: str,
    document_id: str,
    source_sha256: str,
    company_id: str = "company-a",
) -> object:
    text = "Мощность не менее 5 кВт"
    extraction = ExtractionResult(
        status=ExtractionStatus.PASS,
        blocks=(
            ExtractedBlock(
                text=text,
                provenance=Provenance(
                    document_id=document_id,
                    locator="paragraph 1",
                    extractor=Extractor.NATIVE_DOCX,
                    confidence=1,
                ),
            ),
        ),
        reasons=(),
        source_units_total=1,
        source_units_extracted=1,
        characters_extracted=len(text),
    )
    return build_completeness_review_snapshot(
        company_id=company_id,
        review_id=review_id,
        source_document_id=document_id,
        source_document_sha256=source_sha256,
        document_role=DocumentRole.TENDER_REQUIREMENTS,
        extraction=extraction,
        created_by="operator-1",
        created_at=datetime(2026, 9, 17, tzinfo=UTC),
    )


def _manifest(*snapshots: object, **changes: object) -> DocumentSetEvidenceManifest:
    return build_document_set_evidence_manifest(
        tuple(snapshots),  # type: ignore[arg-type]
        company_id=str(changes.get("company_id", "company-a")),
        manifest_id=str(changes.get("manifest_id", "manifest-1")),
        scope=str(changes.get("scope", "Tender package review")),
        created_by=str(changes.get("created_by", "operator-1")),
        created_at=changes.get("created_at", datetime(2026, 9, 17, tzinfo=UTC)),  # type: ignore[arg-type]
    )


def test_manifest_is_deterministic_preserves_order_and_stays_unknown() -> None:
    first = _snapshot(review_id="review-1", document_id="doc-1", source_sha256="a" * 64)
    second = _snapshot(review_id="review-2", document_id="doc-2", source_sha256="b" * 64)

    manifest = _manifest(first, second)
    repeated = _manifest(first, second)
    reversed_manifest = _manifest(second, first)

    assert manifest == repeated
    assert manifest.evidence_sha256 != reversed_manifest.evidence_sha256
    assert [member.source_document_id for member in manifest.members] == ["doc-1", "doc-2"]
    assert [member.ordinal for member in manifest.members] == [1, 2]
    assert manifest.completeness_status is CompletenessStatus.UNKNOWN
    assert manifest.reason == "MULTI_DOCUMENT_REVIEW_REQUIRED"


def test_scope_source_and_review_evidence_change_manifest_digest() -> None:
    first = _snapshot(review_id="review-1", document_id="doc-1", source_sha256="a" * 64)
    second = _snapshot(review_id="review-2", document_id="doc-2", source_sha256="b" * 64)
    different_source = _snapshot(review_id="review-2", document_id="doc-2", source_sha256="c" * 64)
    different_review = _snapshot(review_id="review-3", document_id="doc-2", source_sha256="b" * 64)

    original = _manifest(first, second)
    assert (
        original.evidence_sha256
        != _manifest(first, second, scope="Different scope").evidence_sha256
    )
    assert original.evidence_sha256 != _manifest(first, different_source).evidence_sha256
    assert original.evidence_sha256 != _manifest(first, different_review).evidence_sha256


def test_builder_rejects_duplicate_document_review_and_mixed_tenant() -> None:
    first = _snapshot(review_id="review-1", document_id="doc-1", source_sha256="a" * 64)
    same_document = _snapshot(review_id="review-2", document_id="doc-1", source_sha256="b" * 64)
    same_review = _snapshot(review_id="review-1", document_id="doc-2", source_sha256="b" * 64)
    other_tenant = _snapshot(
        review_id="review-3",
        document_id="doc-3",
        source_sha256="c" * 64,
        company_id="company-b",
    )

    with pytest.raises(ValidationError, match="source document IDs"):
        _manifest(first, same_document)
    with pytest.raises(ValidationError, match="review IDs"):
        _manifest(first, same_review)
    with pytest.raises(ValueError, match="one company"):
        _manifest(first, other_tenant)


@pytest.mark.parametrize("count", [1, 11])
def test_builder_requires_two_to_ten_snapshots(count: int) -> None:
    snapshot = _snapshot(review_id="review-1", document_id="doc-1", source_sha256="a" * 64)
    with pytest.raises(ValueError, match=r"2..10"):
        _manifest(*(snapshot for _ in range(count)))


def test_manifest_rejects_blank_scope_naive_time_tampering_extra_and_coercion() -> None:
    first = _snapshot(review_id="review-1", document_id="doc-1", source_sha256="a" * 64)
    second = _snapshot(review_id="review-2", document_id="doc-2", source_sha256="b" * 64)
    with pytest.raises(ValidationError, match="must not be blank"):
        _manifest(first, second, scope="   ")
    with pytest.raises(ValidationError, match="timezone"):
        _manifest(first, second, created_at=datetime(2026, 9, 17))

    manifest = _manifest(first, second)
    tampered = manifest.model_dump(mode="python")
    tampered["members"][0]["source_document_sha256"] = "c" * 64
    with pytest.raises(ValidationError, match="digest"):
        DocumentSetEvidenceManifest.model_validate(tampered)
    with pytest.raises(ValidationError):
        DocumentSetEvidenceManifest.model_validate(
            manifest.model_dump(mode="python") | {"unexpected": "field"}
        )
    coerced = manifest.model_dump(mode="python")
    coerced["members"][0]["ordinal"] = "1"
    with pytest.raises(ValidationError):
        DocumentSetEvidenceManifest.model_validate(coerced)
