"""Тесты источников и модели кандидата.

Инвариант домена №1: нет provenance — нет факта. Здесь проверяется, что модель
физически не даёт создать характеристику без ссылки на документ, и что «срок
действия неизвестен» не превращается в «документ действует».
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from conftest import DATASHEET, attr, candidate
from procurement.domain.offers import Attribute, Certificate
from procurement.domain.provenance import Extractor, Provenance


class TestProvenance:
    def test_str_is_document_and_locator(self) -> None:
        p = Provenance(document_id="ТЗ.pdf", locator="стр. 16", extractor=Extractor.NATIVE_PDF)
        assert str(p) == "ТЗ.pdf, стр. 16"

    @pytest.mark.parametrize("extractor", [Extractor.OCR, Extractor.LLM])
    def test_lossy_extractors(self, extractor: Extractor) -> None:
        """OCR и LLM могут ошибаться — это влияет на доверие к факту."""
        assert extractor.is_lossy is True

    @pytest.mark.parametrize(
        "extractor",
        [
            Extractor.NATIVE_PDF,
            Extractor.NATIVE_DOCX,
            Extractor.NATIVE_XLSX,
            Extractor.API,
            Extractor.MANUAL,
        ],
    )
    def test_exact_extractors(self, extractor: Extractor) -> None:
        assert extractor.is_lossy is False

    def test_confidence_bounds(self) -> None:
        with pytest.raises(ValidationError):
            Provenance(
                document_id="ТЗ.pdf",
                locator="стр. 1",
                extractor=Extractor.LLM,
                confidence=1.5,
            )


class TestAttributeDisplay:
    def test_number_with_unit(self) -> None:
        assert attr("warranty", Decimal("36.0"), unit="мес").display() == "36 мес"

    def test_number_without_unit(self) -> None:
        assert attr("ethernet_ports", Decimal(24)).display() == "24"

    def test_list_is_joined(self) -> None:
        assert attr("protocols", ["SSH", "SNMPv3"]).display() == "SSH, SNMPv3"

    def test_bool_is_russian(self) -> None:
        assert attr("poe", True).display() == "да"
        assert attr("poe", False).display() == "нет"

    def test_attribute_without_provenance_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Attribute(property="warranty", value=Decimal(24), unit="мес")  # type: ignore[call-arg]


class TestCertificateValidity:
    def _cert(self, valid_from: date | None, valid_until: date | None) -> Certificate:
        return Certificate(
            kind="Декларация соответствия",
            number="Д-RU.XX.00.000",
            valid_from=valid_from,
            valid_until=valid_until,
            provenance=DATASHEET,
        )

    def test_inside_window(self) -> None:
        cert = self._cert(date(2025, 1, 1), date(2027, 1, 1))
        assert cert.is_valid_on(date(2026, 12, 1)) is True

    def test_expired(self) -> None:
        assert self._cert(None, date(2026, 6, 30)).is_valid_on(date(2026, 12, 1)) is False

    def test_not_yet_in_force(self) -> None:
        assert self._cert(date(2027, 1, 1), None).is_valid_on(date(2026, 12, 1)) is False

    def test_boundary_dates_are_inclusive(self) -> None:
        cert = self._cert(date(2026, 12, 1), date(2026, 12, 1))
        assert cert.is_valid_on(date(2026, 12, 1)) is True

    def test_unknown_window_is_none_not_true(self) -> None:
        """None — это UNKNOWN. Превратить его в PASS запрещено инвариантом №2."""
        assert self._cert(None, None).is_valid_on(date(2026, 12, 1)) is None


class TestCandidateLookup:
    def test_attribute_by_canonical_key(self) -> None:
        c = candidate(attr("warranty", Decimal(36), unit="мес"), attr("poe", "да"))
        found = c.attribute("warranty")
        assert found is not None
        assert found.value == Decimal(36)

    def test_missing_attribute_is_none(self) -> None:
        assert candidate().attribute("warranty") is None

    def test_lookup_is_exact_not_fuzzy(self) -> None:
        """Ключи канонические. Похожее имя не должно «почти совпасть»."""
        c = candidate(attr("warranty", Decimal(36), unit="мес"))
        assert c.attribute("Warranty") is None
        assert c.attribute("warranty_months") is None
