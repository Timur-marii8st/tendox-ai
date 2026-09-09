"""Безопасное извлечение текста из неизменяемых документов закупки."""

from procurement.documents.extraction import (
    MAX_UPLOAD_BYTES,
    DocumentInput,
    DocumentRejected,
    DocumentRejectionCode,
    ExtractedBlock,
    ExtractionLimits,
    ExtractionReason,
    ExtractionResult,
    ExtractionStatus,
    extract_document,
)

__all__ = [
    "MAX_UPLOAD_BYTES",
    "DocumentInput",
    "DocumentRejected",
    "DocumentRejectionCode",
    "ExtractedBlock",
    "ExtractionLimits",
    "ExtractionReason",
    "ExtractionResult",
    "ExtractionStatus",
    "extract_document",
]
