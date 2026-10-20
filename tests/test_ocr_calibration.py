"""Калибровка OCR не допускает ложные строки ради recall."""

from __future__ import annotations

import pytest

from procurement.documents.extraction import ExtractionStatus
from procurement.documents.ocr import OcrCandidate
from procurement.documents.ocr_calibration import (
    CalibrationReason,
    ExpectedOcrLine,
    OcrCalibrationSample,
    calibrate_ocr_threshold,
)


def _candidate(page: int, text: str, confidence: float) -> OcrCandidate:
    return OcrCandidate(
        page_number=page,
        block_index=0,
        text=text,
        confidence=confidence,
        locator=f"page {page} bbox 1,2,3,4",
    )


def _sample(
    expected: tuple[ExpectedOcrLine, ...],
    candidates: tuple[OcrCandidate, ...],
) -> OcrCalibrationSample:
    return OcrCalibrationSample(
        sample_id="calibration-scan-1",
        source_sha256="a" * 64,
        expected=expected,
        candidates=candidates,
    )


def test_calibration_selects_lowest_zero_false_positive_threshold() -> None:
    expected = tuple(
        ExpectedOcrLine(page_number=page, text=f"Количество портов не менее {page} шт.")
        for page in range(1, 21)
    )
    candidates = (
        *(
            _candidate(page, f"КОЛИЧЕСТВО   ПОРТОВ не менее {page} шт.", 0.9)
            for page in range(1, 21)
        ),
        _candidate(1, "Количество портов не менее 999 шт.", 0.8),
    )

    report = calibrate_ocr_threshold(
        (_sample(expected, candidates),),
        engine="test-ocr/1",
    )

    assert report.status is ExtractionStatus.PASS
    assert report.recommended_threshold == 0.9
    selected = next(
        item for item in report.observations if item.threshold == report.recommended_threshold
    )
    assert selected.false_positive == 0
    assert selected.false_negative == 0
    assert selected.precision == selected.recall == 1.0
    assert report.sample_ids == ("calibration-scan-1",)
    assert report.source_sha256 == ("a" * 64,)


def test_high_confidence_wrong_number_makes_calibration_fail() -> None:
    expected = tuple(
        ExpectedOcrLine(page_number=page, text="Гарантия не менее 24 мес.")
        for page in range(1, 21)
    )
    candidates = (
        *(
            _candidate(page, "Гарантия не менее 24 мес.", 0.9)
            for page in range(1, 21)
        ),
        _candidate(1, "Гарантия не менее 36 мес.", 0.99),
    )

    report = calibrate_ocr_threshold(
        (_sample(expected, candidates),),
        engine="test-ocr/1",
    )

    assert report.status is ExtractionStatus.FAIL
    assert report.reason is CalibrationReason.NO_SAFE_THRESHOLD
    assert report.recommended_threshold is None


def test_small_perfect_sample_remains_unknown() -> None:
    expected = (ExpectedOcrLine(page_number=1, text="Гарантия не менее 24 мес."),)
    candidates = (_candidate(1, "Гарантия не менее 24 мес.", 0.99),)

    report = calibrate_ocr_threshold(
        (_sample(expected, candidates),),
        engine="test-ocr/1",
    )

    assert report.status is ExtractionStatus.UNKNOWN
    assert report.reason is CalibrationReason.INSUFFICIENT_LABELS
    assert report.recommended_threshold is None


def test_duplicate_expected_lines_are_counted_independently() -> None:
    expected = (
        ExpectedOcrLine(page_number=1, text="Поставка до 01.12.2026"),
        ExpectedOcrLine(page_number=1, text="Поставка до 01.12.2026"),
    )
    candidates = (_candidate(1, "Поставка до 01.12.2026", 0.95),)

    report = calibrate_ocr_threshold(
        (_sample(expected, candidates),),
        engine="test-ocr/1",
        minimum_expected_lines=2,
        minimum_recall=0.5,
    )

    assert report.status is ExtractionStatus.PASS
    selected = next(
        item for item in report.observations if item.threshold == report.recommended_threshold
    )
    assert selected.true_positive == 1
    assert selected.false_negative == 1
    assert selected.recall == 0.5


def test_same_source_cannot_inflate_calibration_evidence() -> None:
    expected = (ExpectedOcrLine(page_number=1, text="Гарантия не менее 24 мес."),)
    candidates = (_candidate(1, "Гарантия не менее 24 мес.", 0.95),)
    sample = _sample(expected, candidates)
    duplicate = sample.model_copy(update={"sample_id": "calibration-scan-copy"})

    with pytest.raises(ValueError, match="source digests must be unique"):
        calibrate_ocr_threshold(
            (sample, duplicate),
            engine="test-ocr/1",
            minimum_expected_lines=2,
        )
