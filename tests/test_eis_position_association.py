"""Operator fragment links preserve exact stored Unicode spans and UNKNOWN semantics."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from procurement.documents.extraction import ExtractedBlock
from procurement.domain.provenance import Extractor, Provenance
from procurement.sources.eis_223_archive import DecimalFact, TextFact
from procurement.sources.eis_characteristic_compare import PositionSelection, SavedPosition
from procurement.sources.eis_document_review import ReviewDocumentAnalysis
from procurement.sources.eis_position_association import (
    AssociationCursor,
    AssociationDetailRequest,
    AssociationListRequest,
    AssociationListResult,
    AssociationMetadata,
    AssociationReadScope,
    AssociationRequest,
    FragmentSelection,
    build_position_fragment_association,
)
from procurement.sources.eis_position_evidence import PositionEvidence
from procurement.storage.eis_document_review import ReviewDocumentRequest
from procurement.storage.eis_document_store import NoticeDocumentRef
from procurement.storage.eis_supplier_search import SupplierSearchRequest

NOTICE_SHA = "a" * 64
DOCUMENT_SHA = "b" * 64
NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)
REF = NoticeDocumentRef(
    purchase_number="0848300054826000154",
    version_number=1,
    notice_xml_sha256=NOTICE_SHA,
)


def provenance(document_id=NOTICE_SHA, locator="position[1]"):
    return Provenance(document_id=document_id, locator=locator, extractor=Extractor.API)


def text_fact(value, locator):
    return TextFact(value=value, raw=value, provenance=provenance(locator=locator))


def position() -> SavedPosition:
    selection = PositionSelection(notice=REF, source_index=1)
    empty_number = DecimalFact(value=None, raw=None, provenance=provenance(locator="quantity"))
    evidence = PositionEvidence(
        source_index=1,
        name=text_fact("Сервер HPE", "name"),
        quantity=DecimalFact(
            value=Decimal("1"), raw="1", provenance=provenance(locator="quantity")
        ),
        unit=text_fact("шт", "unit"),
        classification_code=text_fact(None, "classification"),
        ktru_code=text_fact(None, "ktru"),
        unit_price=empty_number,
        line_sum=empty_number,
        currency=text_fact(None, "currency"),
        characteristics=(),
        characteristics_total=0,
        characteristics_truncated=False,
        characteristics_status="UNKNOWN",
        provenance=provenance(),
    )
    return SavedPosition(
        selection=selection,
        position=evidence,
        storage_kind="SAVED_PROJECTION",
    )


def analysis(texts=("Альфа сервер", "Поставка 10 дней")) -> ReviewDocumentAnalysis:
    blocks = tuple(
        ExtractedBlock(
            text=text,
            provenance=Provenance(
                document_id=DOCUMENT_SHA,
                locator=f"word/document.xml :: paragraph[{index}]",
                extractor=Extractor.NATIVE_DOCX,
            ),
        )
        for index, text in enumerate(texts, 1)
    )
    characters = sum(len(block.text) for block in blocks)
    return ReviewDocumentAnalysis(
        sha256=DOCUMENT_SHA,
        filename="spec.docx",
        byte_count=100,
        extraction_status="PASS",
        extraction_reasons=(),
        source_units_total=len(blocks),
        source_units_extracted=len(blocks),
        characters_extracted=characters,
        blocks_extracted_total=len(blocks),
        blocks=blocks,
        retained_blocks=len(blocks),
        retained_characters=characters,
        retention_truncated=False,
        retention_reasons=(),
        retained_extracted_text_complete=True,
    )


def request(*fragments):
    return AssociationRequest(
        position=SupplierSearchRequest(selection=position().selection),
        document=ReviewDocumentRequest(
            notice=REF,
            content_uid="A" * 32,
            expected_document_sha256=DOCUMENT_SHA,
        ),
        fragments=fragments
        or (
            FragmentSelection(block_index=0, character_start=0, character_end=5),
            FragmentSelection(block_index=1, character_start=0, character_end=8),
        ),
    )


def build(value=None, review=None):
    return build_position_fragment_association(
        value or request(),
        position(),
        review or analysis(),
        position_sha256="c" * 64,
        observation_id="observation-1",
        observed_at=NOW,
        analyzed_at=NOW,
        linked_by="operator-1",
        now=NOW,
        association_id="11111111-1111-4111-8111-111111111111",
    )


def test_exact_unicode_spans_and_original_provenance_are_preserved():
    report = build()
    assert [fragment.text for fragment in report.fragments] == ["Альфа", "Поставка"]
    assert report.selected_characters == 13
    assert report.fragments[0].source_character_count == len("Альфа сервер")
    assert report.fragments[0].provenance.locator.endswith("characters[0:5]")
    assert report.fragments[0].provenance.document_id == DOCUMENT_SHA
    assert report.document_sha256 == DOCUMENT_SHA
    assert report.analysis_sha256 != report.document_sha256
    assert report.association_status == "OPERATOR_LINKED"
    assert {
        report.requirement_status,
        report.full_tspec_completeness,
        report.technical,
        report.quote,
        report.participation,
    } == {"UNKNOWN"}
    assert report.source_requests == report.jobs_created == 0


@pytest.mark.parametrize(
    "fragments,error",
    [
        (
            (
                FragmentSelection(block_index=0, character_start=4, character_end=6),
                FragmentSelection(block_index=0, character_start=5, character_end=7),
            ),
            "FRAGMENT_ORDER_INVALID",
        ),
        (
            (
                FragmentSelection(block_index=1, character_start=0, character_end=1),
                FragmentSelection(block_index=0, character_start=0, character_end=1),
            ),
            "FRAGMENT_ORDER_INVALID",
        ),
    ],
)
def test_fragments_must_be_ordered_and_nonoverlapping(fragments, error):
    with pytest.raises(ValidationError, match=error):
        request(*fragments)


def test_outside_range_and_total_character_limit_fail_closed():
    with pytest.raises(ValueError, match="RANGE_INVALID"):
        build(request(FragmentSelection(block_index=0, character_start=0, character_end=20)))
    long_analysis = analysis(("x" * 10_000, "y" * 10_000))
    selections = request(
        FragmentSelection(block_index=0, character_start=0, character_end=9_000),
        FragmentSelection(block_index=1, character_start=0, character_end=8_000),
    )
    with pytest.raises(ValueError, match="CHARACTER_LIMIT"):
        build(selections, long_analysis)


def test_request_rejects_other_notice_text_locator_and_coercible_ranges():
    payload = request().model_dump(mode="python")
    payload["document"]["notice"]["notice_xml_sha256"] = "d" * 64
    with pytest.raises(ValidationError, match="NOTICE_MISMATCH"):
        AssociationRequest.model_validate(payload)
    payload = request().model_dump(mode="python")
    payload["fragments"][0]["text"] = "client injection"
    with pytest.raises(ValidationError):
        AssociationRequest.model_validate(payload)
    payload = request().model_dump(mode="python")
    payload["fragments"][0]["character_start"] = "0"
    with pytest.raises(ValidationError):
        AssociationRequest.model_validate(payload)


def test_report_rejects_tampered_text_provenance_and_completeness():
    payload = build().model_dump(mode="python")
    payload["fragments"][0]["text"] = "иной"
    with pytest.raises(ValidationError, match="CHARACTER_COUNT_INVALID"):
        type(build()).model_validate(payload)


def test_read_contract_is_strict_bounded_and_cursor_bound_to_last_item():
    scope = AssociationReadScope(
        position=request().position,
        document=request().document,
    )
    listing = AssociationListRequest(scope=scope, limit=1)
    item = AssociationMetadata(
        association_id="11111111-1111-4111-8111-111111111111",
        created_at=NOW,
        linked_by="operator",
        fragment_count=2,
        selected_characters=13,
    )
    cursor = AssociationCursor(
        created_at=item.created_at, association_id=item.association_id
    )
    result = AssociationListResult(
        request=listing,
        items=(item,),
        next_cursor=cursor,
    )
    assert result.source_requests == result.jobs_created == result.writes == 0
    detail = AssociationDetailRequest(scope=scope, association_id=item.association_id)
    assert detail.scope == scope
    for mutation in (
        {"limit": True},
        {"limit": 21},
        {
            "cursor": {
                "created_at": NOW,
                "association_id": "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
            }
        },
    ):
        with pytest.raises(ValidationError):
            AssociationListRequest.model_validate(listing.model_dump() | mutation)
    with pytest.raises(ValidationError, match="CURSOR_INVALID"):
        AssociationListResult(
            request=listing,
            items=(item,),
            next_cursor=AssociationCursor(
                created_at=NOW,
                association_id="22222222-2222-4222-8222-222222222222",
            ),
        )
    with pytest.raises(ValidationError, match="CURSOR_INVALID"):
        AssociationListResult(
            request=AssociationListRequest(scope=scope, limit=2),
            items=(item,),
            next_cursor=cursor,
        )
    with pytest.raises(ValidationError, match="METADATA_COUNT_INVALID"):
        AssociationMetadata(
            association_id=item.association_id,
            created_at=NOW,
            linked_by="operator",
            fragment_count=2,
            selected_characters=1,
        )
    payload = build().model_dump(mode="python")
    payload["fragments"][0]["provenance"]["document_id"] = "e" * 64
    with pytest.raises(ValidationError, match="FRAGMENT_EVIDENCE_INVALID"):
        type(build()).model_validate(payload)
    payload = build().model_dump(mode="python")
    payload["technical"] = "PASS"
    with pytest.raises(ValidationError):
        type(build()).model_validate(payload)
    payload = build().model_dump(mode="python")
    payload["retained_characters"] = 1
    with pytest.raises(ValidationError, match="CHARACTER_COUNT_INVALID"):
        type(build()).model_validate(payload)
