"""Регрессии отдельного производного OCR-среза."""

from __future__ import annotations

import pytest

from procurement.documents.extraction import ExtractionResult, ExtractionStatus
from procurement.documents.ocr import (
    DEFAULT_OCR_CONFIDENCE_THRESHOLD,
    OcrCandidate,
    OcrEngineInput,
    build_ocr_derivative,
    ocr_candidates_from_native,
)
from procurement.domain.provenance import Extractor


def _источник(page_count: int = 3) -> OcrEngineInput:
    return OcrEngineInput(
        source_document_id="document-version-42",
        source_sha256="a" * 64,
        page_count=page_count,
    )


def _нативный_пустой() -> ExtractionResult:
    return ExtractionResult(
        status=ExtractionStatus.UNKNOWN,
        blocks=(),
        reasons=(),
        source_units_total=0,
        source_units_extracted=0,
        characters_extracted=0,
    )


def _кандидат(
    text: str = "Счёт на оплату",
    confidence: float = 0.9,
    page_number: int = 1,
    block_index: int = 0,
) -> OcrCandidate:
    return OcrCandidate(
        page_number=page_number,
        block_index=block_index,
        text=text,
        confidence=confidence,
        locator=f"page {page_number} block {block_index}",
    )


class TestПорогОтбора:
    def test_порог_по_умолчанию_равен_контрактному(self) -> None:
        assert DEFAULT_OCR_CONFIDENCE_THRESHOLD == 0.75

    def test_кандидат_074_отбрасывается_а_075_проходит(self) -> None:
        результат = build_ocr_derivative(
            _источник(),
            _нативный_пустой(),
            (_кандидат(text="слабый", confidence=0.74), _кандидат(text="грань", confidence=0.75)),
            engine="local-stub/0.1",
        )

        assert результат.status is ExtractionStatus.PASS
        assert [блок.text for блок in результат.blocks] == ["грань"]

    def test_пробельный_текст_отбрасывается(self) -> None:
        результат = build_ocr_derivative(
            _источник(),
            _нативный_пустой(),
            (_кандидат(text="   "), _кандидат(text="\n\t ")),
            engine="local-stub/0.1",
        )

        assert результат.status is ExtractionStatus.UNKNOWN
        assert результат.blocks == ()


class TestПустойИПрошедшийИтог:
    def test_пустой_итог_остаётся_неоднозначным(self) -> None:
        результат = build_ocr_derivative(
            _источник(), _нативный_пустой(), (), engine="local-stub/0.1"
        )

        assert результат.status is ExtractionStatus.UNKNOWN
        assert результат.blocks == ()
        assert результат.mean_confidence == 0.0
        assert результат.pages_with_text == 0

    def test_пустой_итог_требует_ocr(self) -> None:
        from procurement.documents.extraction import ExtractionReason

        результат = build_ocr_derivative(
            _источник(),
            _нативный_пустой(),
            (_кандидат(confidence=0.1),),
            engine="local-stub/0.1",
        )

        assert результат.status is ExtractionStatus.UNKNOWN
        assert результат.reasons == (ExtractionReason.OCR_REQUIRED,)
        assert результат.blocks == ()

    def test_прошедший_блок_несёт_ocr_происхождение(self) -> None:
        источник = _источник()
        результат = build_ocr_derivative(
            источник,
            _нативный_пустой(),
            (_кандидат(text="Итого к оплате", confidence=0.82),),
            engine="local-stub/0.1",
        )

        assert результат.status is ExtractionStatus.PASS
        assert результат.reasons == ()
        происхождение = результат.blocks[0].provenance
        assert происхождение.extractor is Extractor.OCR
        assert происхождение.document_id == источник.source_document_id
        assert происхождение.confidence == pytest.approx(0.82)

    def test_средняя_уверенность_и_страницы_корректны(self) -> None:
        результат = build_ocr_derivative(
            _источник(page_count=5),
            _нативный_пустой(),
            (
                _кандидат(text="первый", confidence=0.8, page_number=1, block_index=0),
                _кандидат(text="второй", confidence=1.0, page_number=1, block_index=1),
                _кандидат(text="третий", confidence=0.9, page_number=2, block_index=0),
            ),
            engine="local-stub/0.1",
        )

        assert результат.pages_total == 5
        assert результат.pages_with_text == 2
        assert результат.mean_confidence == pytest.approx((0.8 + 1.0 + 0.9) / 3)


class TestГраницыИЗаглушка:
    @pytest.mark.parametrize("threshold", [-0.1, -1.0, 1.1, 2.0])
    def test_порог_вне_отрезка_отклоняется(self, threshold: float) -> None:
        with pytest.raises(ValueError):
            build_ocr_derivative(
                _источник(),
                _нативный_пустой(),
                (_кандидат(),),
                engine="local-stub/0.1",
                threshold=threshold,
            )

    def test_нативный_путь_кандидатов_не_даёт(self) -> None:
        assert ocr_candidates_from_native(_источник(), _нативный_пустой()) == ()
