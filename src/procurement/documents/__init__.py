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
from procurement.documents.facts import (
    DEFAULT_FACT_MIN_CONFIDENCE,
    FactMappingResult,
    UnmappedBlock,
    UnmappedReason,
    map_blocks_to_requirements,
)
from procurement.documents.ocr import (
    DEFAULT_OCR_CONFIDENCE_THRESHOLD,
    OcrCandidate,
    OcrDerivative,
    OcrEngineInput,
    build_ocr_derivative,
    ocr_candidates_from_native,
)

__all__ = [
    "DEFAULT_FACT_MIN_CONFIDENCE",
    "DEFAULT_OCR_CONFIDENCE_THRESHOLD",
    "MAX_UPLOAD_BYTES",
    "DocumentInput",
    "DocumentRejected",
    "DocumentRejectionCode",
    "ExtractedBlock",
    "ExtractionLimits",
    "ExtractionReason",
    "ExtractionResult",
    "ExtractionStatus",
    "FactMappingResult",
    "OcrCandidate",
    "OcrDerivative",
    "OcrEngineInput",
    "UnmappedBlock",
    "UnmappedReason",
    "build_ocr_derivative",
    "extract_document",
    "map_blocks_to_requirements",
    "ocr_candidates_from_native",
]
