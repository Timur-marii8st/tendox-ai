"""Золотой набор v0: байты DOCX → нативные блоки → строгие факты.

Первый файловый golden-тест S4. Эталон `tz_001.expected.json` проверен вручную:
два требования с точным provenance и один честно нераспознанный блок
(NO_PATTERN_MATCH — в факты не повышен, ложного PASS нет).
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from procurement.documents import DocumentInput, extract_document
from procurement.documents.extraction import ExtractedBlock, ExtractionResult
from procurement.documents.facts import (
    DEFAULT_FACT_MIN_CONFIDENCE,
    DocumentRole,
    FactMappingResult,
    UnmappedReason,
)
from procurement.documents.facts import (
    map_blocks_to_requirements as _map_blocks_to_requirements,
)
from procurement.domain.requirements import Operator

GOLDENSET = Path(__file__).parent.parent / "data" / "goldenset" / "v1"
DOCUMENT_ID = "goldenset-tz-001"
DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MEDIA = "application/pdf"
XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCUMENT_ID_TZ_002 = "goldenset-tz-002"
DOCUMENT_ID_TZ_003 = "goldenset-tz-003"
DOCUMENT_ID_TZ_004 = "goldenset-tz-004"
DOCUMENT_ID_TZ_005 = "goldenset-tz-005"
DOCUMENT_ID_TZ_006 = "goldenset-tz-006"
DOCUMENT_ID_QUOTE_001 = "goldenset-quote-001"


def map_blocks_to_requirements(blocks: tuple[ExtractedBlock, ...]) -> FactMappingResult:
    """Golden-файлы tz_* являются документами требований закупки."""
    return _map_blocks_to_requirements(
        blocks,
        document_role=DocumentRole.TENDER_REQUIREMENTS,
    )


def _mapped() -> FactMappingResult:
    content = (GOLDENSET / "tz_001.docx").read_bytes()
    extraction = extract_document(
        DocumentInput(
            document_id=DOCUMENT_ID,
            filename="tz_001.docx",
            declared_media_type=DOCX_MEDIA,
            content=content,
        )
    )
    assert extraction.status.value == "PASS"
    return map_blocks_to_requirements(extraction.blocks)


def _expected() -> FactMappingResult:
    payload = json.loads((GOLDENSET / "tz_001.expected.json").read_text(encoding="utf-8"))
    return FactMappingResult.model_validate(payload)


def test_golden_tz_001_matches_expected_facts() -> None:
    assert _mapped() == _expected()


def test_golden_tz_001_has_no_false_pass() -> None:
    mapped = _mapped()
    assert len(mapped.requirements) == 2
    assert len(mapped.unmapped) == 1
    for requirement in mapped.requirements:
        assert requirement.mandatory is True
        assert requirement.provenance.document_id == DOCUMENT_ID
        assert requirement.provenance.locator
        assert requirement.provenance.confidence >= DEFAULT_FACT_MIN_CONFIDENCE
        assert requirement.raw_text
    assert all(block.reason.value == "NO_PATTERN_MATCH" for block in mapped.unmapped)


def _expected_pair(name: str) -> tuple[ExtractionResult, FactMappingResult, dict]:
    payload = json.loads((GOLDENSET / f"{name}.expected.json").read_text(encoding="utf-8"))
    return (
        ExtractionResult.model_validate(payload["extraction"]),
        FactMappingResult.model_validate(payload["mapping"]),
        payload,
    )


def test_golden_tz_002_scan_stays_unknown() -> None:
    content = (GOLDENSET / "tz_002.pdf").read_bytes()
    extraction = extract_document(
        DocumentInput(
            document_id=DOCUMENT_ID_TZ_002,
            filename="tz_002.pdf",
            declared_media_type=PDF_MEDIA,
            content=content,
        )
    )
    expected_extraction, expected_mapping, _ = _expected_pair("tz_002")

    assert extraction == expected_extraction
    assert extraction.status.value == "UNKNOWN"
    assert [reason.value for reason in extraction.reasons] == ["OCR_REQUIRED"]
    assert extraction.blocks == ()
    assert extraction.source_units_total == 1

    mapped = map_blocks_to_requirements(extraction.blocks)
    assert mapped == expected_mapping
    assert mapped.requirements == ()
    assert mapped.unmapped == ()
    assert mapped.blocks_total == 0
    assert mapped.blocks_mapped == 0


def test_golden_tz_003_formulas_ignored_literals_mapped() -> None:
    content = (GOLDENSET / "tz_003.xlsx").read_bytes()
    extraction = extract_document(
        DocumentInput(
            document_id=DOCUMENT_ID_TZ_003,
            filename="tz_003.xlsx",
            declared_media_type=XLSX_MEDIA,
            content=content,
        )
    )
    expected_extraction, expected_mapping, payload = _expected_pair("tz_003")

    assert extraction == expected_extraction
    assert extraction.status.value == "UNKNOWN"
    assert "FORMULAS_IGNORED" in [reason.value for reason in extraction.reasons]
    assert len(extraction.blocks) == 1
    assert extraction.blocks[0].provenance.locator == "Spec!A1"
    assert extraction.blocks[0].text == "Гарантия не менее 12 мес."

    # Decimal в эталоне — число, иначе Requirement остаётся str и валидация падает.
    assert payload["mapping"]["requirements"][0]["value"] == 12
    assert isinstance(payload["mapping"]["requirements"][0]["value"], int)

    mapped = map_blocks_to_requirements(extraction.blocks)
    assert mapped == expected_mapping
    assert len(mapped.requirements) == 1
    requirement = mapped.requirements[0]
    assert requirement.property == "warranty"
    assert requirement.operator.value == ">="
    assert requirement.value == Decimal(12)
    assert isinstance(requirement.value, Decimal)
    assert requirement.unit == "мес"
    assert requirement.mandatory is True
    assert requirement.provenance.locator == "Spec!A1"
    assert requirement.provenance.extractor.value == "native_xlsx"
    assert requirement.provenance.confidence == 1.0
    assert mapped.unmapped == ()


def _mapped_docx(name: str, document_id: str) -> FactMappingResult:
    content = (GOLDENSET / f"{name}.docx").read_bytes()
    extraction = extract_document(
        DocumentInput(
            document_id=document_id,
            filename=f"{name}.docx",
            declared_media_type=DOCX_MEDIA,
            content=content,
        )
    )
    assert extraction.status.value == "PASS"
    return map_blocks_to_requirements(extraction.blocks)


def _expected_mapping(name: str) -> FactMappingResult:
    payload = json.loads((GOLDENSET / f"{name}.expected.json").read_text(encoding="utf-8"))
    return FactMappingResult.model_validate(payload)


def test_golden_tz_004_ban_and_deadline() -> None:
    mapped = _mapped_docx("tz_004", DOCUMENT_ID_TZ_004)
    assert mapped == _expected_mapping("tz_004")
    assert mapped.requirements == ()
    assert mapped.unmapped == ()
    assert (mapped.blocks_total, mapped.blocks_mapped) == (2, 2)
    assert mapped.equivalent_allowed is False
    assert mapped.delivery_deadline == date(2026, 12, 1)


def test_golden_tz_005_numeric_and_country() -> None:
    mapped = _mapped_docx("tz_005", DOCUMENT_ID_TZ_005)
    assert mapped == _expected_mapping("tz_005")
    assert len(mapped.requirements) == 3
    assert mapped.unmapped == ()
    assert (mapped.blocks_total, mapped.blocks_mapped) == (3, 3)
    assert mapped.equivalent_allowed is None
    assert mapped.delivery_deadline is None

    # Decimal в эталоне — числа, иначе Requirement остаётся str и валидация падает.
    payload = json.loads((GOLDENSET / "tz_005.expected.json").read_text(encoding="utf-8"))
    assert payload["requirements"][0]["value"] == 400
    assert isinstance(payload["requirements"][0]["value"], int)
    assert payload["requirements"][1]["value"] == 1.5
    assert isinstance(payload["requirements"][1]["value"], float)

    depth, power, country = mapped.requirements
    assert (depth.property, depth.operator.value) == ("depth", "<=")
    assert depth.value == Decimal(400)
    assert isinstance(depth.value, Decimal)
    assert depth.unit == "мм"
    assert (power.property, power.operator.value) == ("power", ">=")
    assert power.value == Decimal("1.5")
    assert isinstance(power.value, Decimal)
    assert power.unit == "кВт"
    assert (country.property, country.operator.value) == ("country_of_origin", "==")
    assert country.value == "Россия"
    assert country.unit is None
    for requirement, locator, raw_text in zip(
        mapped.requirements,
        ("paragraph 1", "paragraph 2", "paragraph 3"),
        (
            "Глубина не более 400 мм.",
            "Мощность не менее 1,5 кВт.",
            "Страна происхождения: Россия.",
        ),
        strict=True,
    ):
        assert requirement.mandatory is True
        assert requirement.raw_text == raw_text
        assert requirement.provenance.document_id == DOCUMENT_ID_TZ_005
        assert requirement.provenance.locator == locator
        assert requirement.provenance.extractor.value == "native_docx"
        assert requirement.provenance.confidence == 1.0


def test_golden_tz_006_certificate_requirement_and_mention_trap() -> None:
    """Явное требование маппится, простое упоминание сертификата остаётся unmapped."""
    mapped = _mapped_docx("tz_006", DOCUMENT_ID_TZ_006)

    assert mapped == _expected_mapping("tz_006")
    assert len(mapped.requirements) == 1
    requirement = mapped.requirements[0]
    assert requirement.property == "certificate:Декларация соответствия ТР ТС"
    assert requirement.operator is Operator.EXISTS
    assert requirement.value is None
    assert requirement.provenance.document_id == DOCUMENT_ID_TZ_006
    assert requirement.provenance.locator == "paragraph 1"
    assert mapped.delivery_deadline == date(2026, 12, 1)
    assert (mapped.blocks_total, mapped.blocks_mapped) == (3, 2)
    assert len(mapped.unmapped) == 1
    assert "упомянут сертификат" in mapped.unmapped[0].text


def test_golden_quote_001_cannot_become_tender_requirements() -> None:
    """Фразы КП, совпадающие с шаблонами ТЗ, не создают hard gates."""
    content = (GOLDENSET / "quote_001.docx").read_bytes()
    extraction = extract_document(
        DocumentInput(
            document_id=DOCUMENT_ID_QUOTE_001,
            filename="quote_001.docx",
            declared_media_type=DOCX_MEDIA,
            content=content,
        )
    )
    assert extraction.status.value == "PASS"

    mapped = _map_blocks_to_requirements(
        extraction.blocks,
        document_role=DocumentRole.SUPPLIER_QUOTE,
    )
    expected = FactMappingResult.model_validate_json(
        (GOLDENSET / "quote_001.expected.json").read_text(encoding="utf-8")
    )

    assert mapped == expected
    assert mapped.document_role is DocumentRole.SUPPLIER_QUOTE
    assert mapped.requirements == ()
    assert mapped.blocks_mapped == 0
    assert mapped.equivalent_allowed is None
    assert mapped.delivery_deadline is None
    assert len(mapped.unmapped) == len(extraction.blocks) == 5
    assert all(block.reason is UnmappedReason.NON_REQUIREMENT_DOCUMENT for block in mapped.unmapped)
