"""Производная OCR-версия документа как отдельный срез.

Модуль строит текстовые блоки из кандидатов OCR-движка и не меняет нативный
результат извлечения. Кандидат ниже порога уверенности остаётся неоднозначным
и в факт не превращается: пустой итог честно возвращается как ``UNKNOWN``.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from procurement.documents.extraction import (
    ExtractedBlock,
    ExtractionReason,
    ExtractionResult,
    ExtractionStatus,
)
from procurement.domain.provenance import Extractor, Provenance

DEFAULT_OCR_CONFIDENCE_THRESHOLD = 0.75
"""Порог уверенности OCR: слабые распознавания фактами не становятся."""

MAX_OCR_PAGES = 200
"""Отдельный CPU-лимит OCR; нативный парсер допускает более крупные PDF."""


class OcrEngineError(RuntimeError):
    """Локальный OCR-движок не смог выдать проверяемый типизированный результат."""


class OcrSourceRejected(ValueError):
    """Исходник нельзя безопасно передать настроенному OCR-движку."""


class OcrRunner(Protocol):
    """Локальная синхронная граница OCR; API запускает её вне event loop."""

    engine: str

    def recognize(
        self,
        source: OcrEngineInput,
        *,
        content: bytes,
        media_type: str,
    ) -> tuple[OcrCandidate, ...]: ...


class OcrEngineInput(BaseModel):
    """Вход движка OCR: identity исходника без его байтов."""

    model_config = ConfigDict(frozen=True)

    source_document_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_count: int = Field(ge=0)


class OcrCandidate(BaseModel):
    """Один распознанный фрагмент претендует стать блоком."""

    model_config = ConfigDict(frozen=True)

    page_number: int = Field(ge=1)
    block_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    locator: str = Field(min_length=1)


class NoopOcrRunner:
    """Детерминированный runner для тестов API без тяжёлого optional runtime."""

    engine = "local-stub/0.1"

    def recognize(
        self,
        source: OcrEngineInput,
        *,
        content: bytes,
        media_type: str,
    ) -> tuple[OcrCandidate, ...]:
        _ = (source, content, media_type)
        return ()


class OcrDerivative(BaseModel):
    """Итог OCR-прохода: только прошедшие порог кандидаты."""

    model_config = ConfigDict(frozen=True)

    source_document_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extractor_literal: Literal["ocr"] = "ocr"
    engine: str = Field(min_length=1)
    threshold: float = Field(ge=0.0, le=1.0)
    status: ExtractionStatus
    reasons: tuple[ExtractionReason, ...] = ()
    blocks: tuple[ExtractedBlock, ...] = ()
    pages_total: int = Field(ge=0)
    pages_with_text: int = Field(ge=0)
    mean_confidence: float = Field(ge=0.0, le=1.0)


def build_ocr_derivative(
    source: OcrEngineInput,
    native: ExtractionResult,
    candidates: tuple[OcrCandidate, ...],
    *,
    engine: str,
    threshold: float = DEFAULT_OCR_CONFIDENCE_THRESHOLD,
) -> OcrDerivative:
    """Собрать производную версию из кандидатов движка.

    Порог вне отрезка ``[0, 1]`` отклоняется. Пустые и пробельные строки, а
    также кандидаты слабее порога отбрасываются без повышения до факта.
    Нативный результат не меняется и выводам не помогает: итог строится
    только из прошедших порог кандидатов.
    """
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be within [0, 1]")
    # Нативный результат осознанно не читаем и не меняем: он лишь фиксирует,
    # что OCR-срез является отдельной производной версией.
    _ = native
    # Отбор честный: пробелы фактом не становятся, слабые не дотягиваются.
    прошедшие = tuple(
        кандидат
        for кандидат in candidates
        if кандидат.text.strip() and кандидат.confidence >= threshold
    )
    if not прошедшие:
        return OcrDerivative(
            source_document_id=source.source_document_id,
            source_sha256=source.source_sha256,
            extractor_literal="ocr",
            engine=engine,
            threshold=threshold,
            status=ExtractionStatus.UNKNOWN,
            reasons=(ExtractionReason.OCR_REQUIRED,),
            blocks=(),
            pages_total=source.page_count,
            pages_with_text=0,
            mean_confidence=0.0,
        )
    # Локатор и уверенность переходят из кандидата без домыслов.
    блоки = tuple(
        ExtractedBlock(
            text=кандидат.text.strip(),
            provenance=Provenance(
                document_id=source.source_document_id,
                locator=кандидат.locator,
                extractor=Extractor.OCR,
                confidence=кандидат.confidence,
            ),
        )
        for кандидат in прошедшие
    )
    страниц = len({кандидат.page_number for кандидат in прошедшие})
    средняя = sum(кандидат.confidence for кандидат in прошедшие) / len(прошедшие)
    return OcrDerivative(
        source_document_id=source.source_document_id,
        source_sha256=source.source_sha256,
        extractor_literal="ocr",
        engine=engine,
        threshold=threshold,
        status=ExtractionStatus.PASS,
        reasons=(),
        blocks=блоки,
        pages_total=source.page_count,
        pages_with_text=страниц,
        mean_confidence=средняя,
    )


def ocr_candidates_from_native(
    source: OcrEngineInput, native: ExtractionResult
) -> tuple[OcrCandidate, ...]:
    """Заглушка: нативный путь OCR-текста не даёт.

    Реальный движок подключится отдельно, поэтому вызов API уже сейчас может
    опереться на эту точку расширения и получить честный пустой итог.
    """
    # Входы осознанно не используются: нативных OCR-блоков не существует.
    _ = (source, native)
    return ()
