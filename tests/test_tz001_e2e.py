"""Сквозной путь golden DOCX tz_001 до verdict движка compliance.evaluate.

Требования не дублируются в тесте вручную: они извлекаются из настоящих байтов
``tz_001.docx`` и проходят production mapper перед проверкой кандидата.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from conftest import DATASHEET, attr, candidate, line_item
from procurement.documents import DocumentInput, ExtractionStatus, extract_document
from procurement.documents.facts import DocumentRole, map_blocks_to_requirements
from procurement.domain.compliance import CandidateVerdict, Verdict, check_requirement, evaluate
from procurement.domain.offers import Certificate
from procurement.domain.requirements import LineItem

GOLDENSET = Path(__file__).parent.parent / "data" / "goldenset" / "v1"
DOCUMENT_ID = "goldenset-tz-001"
DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _tz001_item(*, equivalent_allowed: bool, delivery_deadline: date | None = None) -> LineItem:
    """Извлечь позицию ТЗ из golden DOCX ``tz_001``.

    Аргумент equivalent_allowed обязателен и задаётся явно на каждом вызове:
    дефолт хелпера line_item() (True) отличается от доменного дефолта (False).
    """
    content = (GOLDENSET / "tz_001.docx").read_bytes()
    extraction = extract_document(
        DocumentInput(
            document_id=DOCUMENT_ID,
            filename="tz_001.docx",
            declared_media_type=DOCX_MEDIA,
            content=content,
        )
    )
    assert extraction.status is ExtractionStatus.PASS
    mapped = map_blocks_to_requirements(
        extraction.blocks,
        document_role=DocumentRole.TENDER_REQUIREMENTS,
    )
    assert [requirement.property for requirement in mapped.requirements] == [
        "warranty",
        "ethernet_ports",
    ]
    assert [requirement.label() for requirement in mapped.requirements] == [
        "warranty >= 24 мес",
        "ethernet_ports >= 24 шт",
    ]
    assert all(
        requirement.provenance.document_id == DOCUMENT_ID
        for requirement in mapped.requirements
    )
    return line_item(
        *mapped.requirements,
        equivalent_allowed=equivalent_allowed,
        delivery_deadline=delivery_deadline,
    )


def test_tz001_compliant() -> None:
    """Полный кандидат (гарантия 36 мес, 24 порта) проходит оба факта эталона."""
    item = _tz001_item(equivalent_allowed=False)
    cand = candidate(
        attr("warranty", Decimal(36), unit="мес"),
        attr("ethernet_ports", Decimal(24), unit="шт"),
    )
    result = evaluate(item, cand)
    assert result.verdict is CandidateVerdict.COMPLIANT


def test_tz001_warranty_fail() -> None:
    """Гарантия 12 мес при требовании >= 24 мес — FAIL без процентов в сводке."""
    item = _tz001_item(equivalent_allowed=False)
    cand = candidate(
        attr("warranty", Decimal(12), unit="мес"),
        attr("ethernet_ports", Decimal(24), unit="шт"),
    )
    result = evaluate(item, cand)
    assert result.verdict is CandidateVerdict.FAIL
    assert "warranty" in [c.requirement.property for c in result.blocking]
    assert result.soft_score is None
    assert "%" not in result.summary()


def test_tz001_missing_ports_needs_clarification() -> None:
    """Нет данных о портах — NEEDS_CLARIFICATION с открытым вопросом, а не FAIL."""
    item = _tz001_item(equivalent_allowed=False)
    cand = candidate(attr("warranty", Decimal(36), unit="мес"))
    result = evaluate(item, cand)
    assert result.verdict is CandidateVerdict.NEEDS_CLARIFICATION
    assert "ethernet_ports" in [c.requirement.property for c in result.open_questions]


def test_tz001_low_confidence_unknown() -> None:
    """Уверенность извлечения ниже порога 0.75 даёт UNKNOWN, а не COMPLIANT."""
    item = _tz001_item(equivalent_allowed=False)
    cand = candidate(
        attr("warranty", Decimal(36), unit="мес", confidence=0.5),
        attr("ethernet_ports", Decimal(24), unit="шт"),
    )
    warranty_req = item.requirements[0]
    assert check_requirement(warranty_req, cand).verdict is Verdict.UNKNOWN
    result = evaluate(item, cand)
    assert result.verdict is CandidateVerdict.NEEDS_CLARIFICATION
    assert result.verdict is not CandidateVerdict.COMPLIANT


def test_tz001_unrequired_certificate_does_not_create_requirement() -> None:
    """Документ кандидата сам по себе не создаёт отсутствующее в tz_001 требование."""
    item = _tz001_item(equivalent_allowed=False, delivery_deadline=date(2026, 12, 1))
    cert = Certificate(
        kind="Декларация соответствия ТР ТС",
        number="ЕАЭС N RU Д-RU.XX.00.001",
        valid_until=date(2026, 6, 30),
        provenance=DATASHEET,
    )
    cand = candidate(
        attr("warranty", Decimal(36), unit="мес"),
        attr("ethernet_ports", Decimal(24), unit="шт"),
        certificates=(cert,),
    )
    result = evaluate(item, cand)
    assert result.verdict is CandidateVerdict.COMPLIANT
    assert not any(c.requirement.property.startswith("certificate:") for c in result.checks)


def test_tz001_equivalent_trap() -> None:
    """Запрет эквивалента ловит аналог: FAIL по признаку equivalent."""
    item = _tz001_item(equivalent_allowed=False)
    cand = candidate(
        attr("warranty", Decimal(36), unit="мес"),
        attr("ethernet_ports", Decimal(24), unit="шт"),
        is_equivalent=True,
    )
    result = evaluate(item, cand)
    assert result.verdict is CandidateVerdict.FAIL
    assert "equivalent" in [c.requirement.property for c in result.blocking]
