"""Детерминированная калибровка OCR confidence по размеченным строкам.

Сопоставление намеренно строгое: нормализуются Unicode, регистр и пробелы, но не
цифры и пунктуация. Ошибочная характеристика не может считаться правильной.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.documents.extraction import ExtractionStatus
from procurement.documents.ocr import DEFAULT_OCR_CONFIDENCE_THRESHOLD, OcrCandidate


class CalibrationReason(StrEnum):
    """Почему безопасный рабочий порог не подтверждён."""

    INSUFFICIENT_LABELS = "INSUFFICIENT_LABELS"
    NO_SAFE_THRESHOLD = "NO_SAFE_THRESHOLD"


class ExpectedOcrLine(BaseModel):
    """Ручная разметка одной строки с точной страницей исходного снимка."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    page_number: int = Field(ge=1)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _text_is_not_blank(self) -> Self:
        if not self.text.strip():
            raise ValueError("expected OCR text must not be blank")
        return self


class OcrCalibrationSample(BaseModel):
    """Размеченный immutable-снимок и сырые кандидаты одного engine run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sample_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected: tuple[ExpectedOcrLine, ...]
    candidates: tuple[OcrCandidate, ...]

    @model_validator(mode="after")
    def _sample_id_is_not_blank(self) -> Self:
        if not self.sample_id.strip():
            raise ValueError("sample_id must not be blank")
        return self


class OcrThresholdMetrics(BaseModel):
    """Матрица ошибок одного порога на точном наборе source digests."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    threshold: float = Field(ge=0.0, le=1.0)
    true_positive: int = Field(ge=0)
    false_positive: int = Field(ge=0)
    false_negative: int = Field(ge=0)
    precision: float | None = Field(default=None, ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)


class OcrCalibrationReport(BaseModel):
    """Типизированное решение о пороге с evidence набора и всеми наблюдениями."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    engine: str = Field(min_length=1)
    status: ExtractionStatus
    reason: CalibrationReason | None = None
    recommended_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    minimum_recall: float = Field(ge=0.0, le=1.0)
    minimum_expected_lines: int = Field(ge=1)
    samples_total: int = Field(ge=0)
    expected_lines_total: int = Field(ge=0)
    sample_ids: tuple[str, ...]
    source_sha256: tuple[str, ...]
    observations: tuple[OcrThresholdMetrics, ...]

    @model_validator(mode="after")
    def _decision_is_consistent(self) -> Self:
        if self.status is ExtractionStatus.PASS:
            if self.reason is not None or self.recommended_threshold is None:
                raise ValueError("PASS calibration requires a recommended threshold")
        elif self.recommended_threshold is not None or self.reason is None:
            raise ValueError("non-PASS calibration requires a reason and no threshold")
        return self


def calibrate_ocr_threshold(
    samples: tuple[OcrCalibrationSample, ...],
    *,
    engine: str,
    minimum_expected_lines: int = 20,
    minimum_recall: float = 0.9,
    baseline_threshold: float = DEFAULT_OCR_CONFIDENCE_THRESHOLD,
) -> OcrCalibrationReport:
    """Выбрать самый низкий порог с нулём false positives и нужным recall.

    Недостаточная разметка даёт ``UNKNOWN``. Достаточная выборка, для которой ни
    один наблюдаемый порог не обеспечивает одновременно ноль ложных строк и
    требуемую полноту, даёт ``FAIL``.
    """
    if not engine.strip():
        raise ValueError("engine must not be blank")
    if minimum_expected_lines < 1:
        raise ValueError("minimum_expected_lines must be positive")
    if not 0.0 <= minimum_recall <= 1.0:
        raise ValueError("minimum_recall must be within [0, 1]")
    if not 0.0 <= baseline_threshold <= 1.0:
        raise ValueError("baseline_threshold must be within [0, 1]")

    expected_total = sum(len(sample.expected) for sample in samples)
    sample_ids = tuple(sample.sample_id for sample in samples)
    source_digests = tuple(sample.source_sha256 for sample in samples)
    if len(set(sample_ids)) != len(sample_ids):
        raise ValueError("calibration sample_id values must be unique")
    if len(set(source_digests)) != len(source_digests):
        raise ValueError("calibration source digests must be unique")
    thresholds = sorted(
        {baseline_threshold}
        | {
            candidate.confidence
            for sample in samples
            for candidate in sample.candidates
        }
    )
    observations = tuple(_metrics(samples, threshold) for threshold in thresholds)
    basis = {
        "engine": engine,
        "minimum_recall": minimum_recall,
        "minimum_expected_lines": minimum_expected_lines,
        "samples_total": len(samples),
        "expected_lines_total": expected_total,
        "sample_ids": sample_ids,
        "source_sha256": source_digests,
        "observations": observations,
    }
    if expected_total < minimum_expected_lines:
        return OcrCalibrationReport(
            **basis,
            status=ExtractionStatus.UNKNOWN,
            reason=CalibrationReason.INSUFFICIENT_LABELS,
        )

    safe = [
        item
        for item in observations
        if item.false_positive == 0
        and item.true_positive > 0
        and item.recall >= minimum_recall
    ]
    if not safe:
        return OcrCalibrationReport(
            **basis,
            status=ExtractionStatus.FAIL,
            reason=CalibrationReason.NO_SAFE_THRESHOLD,
        )
    best = max(safe, key=lambda item: (item.recall, -item.threshold))
    return OcrCalibrationReport(
        **basis,
        status=ExtractionStatus.PASS,
        recommended_threshold=best.threshold,
    )


def _metrics(
    samples: tuple[OcrCalibrationSample, ...],
    threshold: float,
) -> OcrThresholdMetrics:
    true_positive = 0
    false_positive = 0
    expected_total = 0
    for sample in samples:
        expected = Counter(
            (line.page_number, _normalize(line.text)) for line in sample.expected
        )
        accepted = Counter(
            (candidate.page_number, _normalize(candidate.text))
            for candidate in sample.candidates
            if candidate.confidence >= threshold
        )
        matched = sum((expected & accepted).values())
        true_positive += matched
        false_positive += sum(accepted.values()) - matched
        expected_total += sum(expected.values())
    false_negative = expected_total - true_positive
    accepted_total = true_positive + false_positive
    precision = None if accepted_total == 0 else true_positive / accepted_total
    recall = 0.0 if expected_total == 0 else true_positive / expected_total
    return OcrThresholdMetrics(
        threshold=threshold,
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
        precision=precision,
        recall=recall,
    )


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())
