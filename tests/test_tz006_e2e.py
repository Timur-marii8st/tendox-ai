"""Сквозной сертификатный путь: DOCX → факты → compliance verdict."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from conftest import DATASHEET, candidate
from procurement.documents import DocumentInput, extract_document
from procurement.documents.facts import DocumentRole, map_blocks_to_requirements
from procurement.domain.compliance import CandidateVerdict, Verdict, evaluate
from procurement.domain.offers import Certificate
from procurement.domain.requirements import LineItem

GOLDENSET = Path(__file__).parent.parent / "data" / "goldenset" / "v1"
DOCUMENT_ID = "goldenset-tz-006"
DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _item_from_tz006() -> LineItem:
    content = (GOLDENSET / "tz_006.docx").read_bytes()
    extraction = extract_document(
        DocumentInput(
            document_id=DOCUMENT_ID,
            filename="tz_006.docx",
            declared_media_type=DOCX_MEDIA,
            content=content,
        )
    )
    mapped = map_blocks_to_requirements(
        extraction.blocks,
        document_role=DocumentRole.TENDER_REQUIREMENTS,
    )
    assert mapped.delivery_deadline is not None
    return LineItem(
        number=1,
        name="Сетевой коммутатор",
        quantity=Decimal(1),
        requirements=mapped.requirements,
        equivalent_allowed=False,
        delivery_deadline=mapped.delivery_deadline,
        provenance=mapped.requirements[0].provenance,
    )


def _declaration(valid_until: date | None) -> Certificate:
    return Certificate(
        kind="Декларация соответствия ТР ТС",
        number="ЕАЭС N RU Д-RU.XX.00.006",
        valid_from=date(2026, 1, 1) if valid_until is not None else None,
        valid_until=valid_until,
        provenance=DATASHEET,
    )


def test_tz006_valid_declaration_passes() -> None:
    result = evaluate(
        _item_from_tz006(),
        candidate(certificates=(_declaration(date(2027, 1, 1)),)),
    )

    assert result.verdict is CandidateVerdict.COMPLIANT
    assert len(result.checks) == 1
    assert result.checks[0].verdict is Verdict.PASS
    assert result.checks[0].requirement.provenance.document_id == DOCUMENT_ID
    assert "2026-12-01" in result.checks[0].actual


def test_tz006_unknown_declaration_validity_is_not_a_pass() -> None:
    result = evaluate(
        _item_from_tz006(),
        candidate(certificates=(_declaration(None),)),
    )

    assert result.verdict is CandidateVerdict.NEEDS_CLARIFICATION
    assert result.open_questions[0].verdict is Verdict.UNKNOWN
    assert result.soft_score is None
