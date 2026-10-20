"""Источник факта.

Инвариант домена №1: нет provenance — нет факта. Любое требование ТЗ и любой
атрибут товара обязаны нести ссылку на источник. Без неё невозможно ни защитить
заявку перед заказчиком, ни отладить ошибку извлечения.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Extractor(str, Enum):
    """Чем получен факт. Влияет на доверие к значению."""

    NATIVE_PDF = "native_pdf"
    NATIVE_DOCX = "native_docx"
    NATIVE_XLSX = "native_xlsx"
    NATIVE_XLS = "native_xls"
    LEGACY_DOC_TEXT = "legacy_doc_text"
    OCR = "ocr"
    LLM = "llm"
    API = "api"
    MANUAL = "manual"

    @property
    def is_lossy(self) -> bool:
        """OCR и LLM могут искажать значение — их результат требует осторожности."""
        return self in (Extractor.OCR, Extractor.LLM, Extractor.LEGACY_DOC_TEXT)


class Provenance(BaseModel):
    """Откуда взят факт.

    >>> p = Provenance(
    ...     document_id="ТЗ.pdf",
    ...     locator="стр. 16",
    ...     extractor=Extractor.NATIVE_PDF,
    ...     confidence=0.98,
    ... )
    >>> str(p)
    'ТЗ.pdf, стр. 16'
    """

    model_config = ConfigDict(frozen=True)

    document_id: str = Field(min_length=1, description="Файл, письмо или карточка каталога")
    locator: str = Field(
        min_length=1,
        description='Точное место: "стр. 14", "Лист1!C7", "абзац 3.2"',
    )
    extractor: Extractor
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)

    def __str__(self) -> str:
        return f"{self.document_id}, {self.locator}"
