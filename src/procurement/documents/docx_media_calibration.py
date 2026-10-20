"""Fail-closed calibration of OCR for one immutable image linked by a DOCX."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.documents.docx_media import (
    DocxMediaRejected,
    extract_docx_media,
)
from procurement.documents.extraction import (
    MAX_UPLOAD_BYTES,
    DocumentInput,
    ExtractionStatus,
)
from procurement.documents.ocr import (
    DEFAULT_OCR_CONFIDENCE_THRESHOLD,
    OcrEngineError,
    OcrEngineInput,
    OcrRunner,
    OcrSourceRejected,
)
from procurement.documents.ocr_calibration import (
    ExpectedOcrLine,
    OcrCalibrationReport,
    OcrCalibrationSample,
    calibrate_ocr_threshold,
)
from procurement.documents.paddle_ocr import PaddleOcrRunner

MAX_DOCX_MEDIA_REVIEW_BYTES = 2 * 1024 * 1024


class DocxMediaReviewStatus(StrEnum):
    """Provenance of a visual review is explicit and cannot be silently promoted."""

    AI_REVIEWED_REQUIRES_HUMAN_CONFIRMATION = (
        "AI_REVIEWED_REQUIRES_HUMAN_CONFIRMATION"
    )
    HUMAN_CONFIRMED = "HUMAN_CONFIRMED"


class DocxMediaReviewerType(StrEnum):
    AI_VISUAL_REVIEW = "AI_VISUAL_REVIEW"
    HUMAN = "HUMAN"


class DocxMediaCalibrationGateReason(StrEnum):
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    CALIBRATION_NOT_PASSING = "CALIBRATION_NOT_PASSING"


class DocxMediaCalibrationErrorCode(StrEnum):
    REVIEW_TOO_LARGE = "REVIEW_TOO_LARGE"
    REVIEW_INVALID = "REVIEW_INVALID"
    SOURCE_PATH_INVALID = "SOURCE_PATH_INVALID"
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    SOURCE_TOO_LARGE = "SOURCE_TOO_LARGE"
    SOURCE_DIGEST_MISMATCH = "SOURCE_DIGEST_MISMATCH"
    SOURCE_REJECTED = "SOURCE_REJECTED"
    MEDIA_NOT_FOUND = "MEDIA_NOT_FOUND"
    MEDIA_EVIDENCE_MISMATCH = "MEDIA_EVIDENCE_MISMATCH"
    ENGINE_MISMATCH = "ENGINE_MISMATCH"
    OCR_FAILED = "OCR_FAILED"


class DocxMediaCalibrationError(ValueError):
    def __init__(self, code: DocxMediaCalibrationErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


class DocxMediaReviewUncertainty(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    region: str = Field(min_length=1)
    visible_text: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class DocxMediaCalibrationReview(BaseModel):
    """Versioned visual labels and immutable evidence for one linked image."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["docx-media-calibration-review-v1"] = (
        "docx-media-calibration-review-v1"
    )
    review_status: DocxMediaReviewStatus
    reviewer_type: DocxMediaReviewerType
    reviewed_by: str = Field(min_length=1)
    reviewed_at: datetime
    authorization_reference: str = Field(min_length=1)
    source_document: str = Field(min_length=1)
    source_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_index: int = Field(ge=0)
    source_media: str = Field(min_length=1, max_length=512)
    source_media_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    image_width: int = Field(ge=1)
    image_height: int = Field(ge=1)
    ocr_report_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    method: str = Field(min_length=1)
    engine: Literal["paddleocr/3.7.0:PP-OCRv5-ru"] = (
        "paddleocr/3.7.0:PP-OCRv5-ru"
    )
    minimum_expected_lines: int = Field(default=20, ge=1)
    minimum_recall: float = Field(default=0.9, ge=0.0, le=1.0)
    baseline_threshold: float = Field(
        default=DEFAULT_OCR_CONFIDENCE_THRESHOLD,
        ge=0.0,
        le=1.0,
    )
    expected: tuple[ExpectedOcrLine, ...] = Field(min_length=1)
    uncertainties: tuple[DocxMediaReviewUncertainty, ...] = ()

    @model_validator(mode="after")
    def _review_is_consistent(self) -> Self:
        for value, name in (
            (self.reviewed_by, "reviewed_by"),
            (self.authorization_reference, "authorization_reference"),
            (self.method, "method"),
        ):
            if not value.strip():
                raise ValueError(f"{name} must not be blank")
        if self.reviewed_at.utcoffset() is None:
            raise ValueError("reviewed_at must include a timezone")
        _validate_relative_path(self.source_document)
        if not self.source_media.startswith("word/media/"):
            raise ValueError("source_media must be a DOCX word/media path")
        if any(line.page_number != 1 for line in self.expected):
            raise ValueError("DOCX image labels must use page_number=1")
        if self.review_status is DocxMediaReviewStatus.HUMAN_CONFIRMED:
            if self.reviewer_type is not DocxMediaReviewerType.HUMAN:
                raise ValueError("human-confirmed review requires a human reviewer")
            if self.uncertainties:
                raise ValueError("human-confirmed review cannot contain uncertainties")
        elif self.reviewer_type is not DocxMediaReviewerType.AI_VISUAL_REVIEW:
            raise ValueError("AI-reviewed status requires AI_VISUAL_REVIEW provenance")
        return self


class DocxMediaCalibrationRunReport(BaseModel):
    """Full private metrics plus a separate fail-closed production gate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["docx-media-calibration-report-v1"] = (
        "docx-media-calibration-report-v1"
    )
    review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_status: DocxMediaReviewStatus
    reviewer_type: DocxMediaReviewerType
    reviewed_by: str = Field(min_length=1)
    source_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_media_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sample: OcrCalibrationSample
    calibration: OcrCalibrationReport
    status: ExtractionStatus
    gate_reason: DocxMediaCalibrationGateReason | None = None
    production_recommended_threshold: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def _gate_matches_review(self) -> Self:
        if self.sample.source_sha256 != self.source_media_sha256:
            raise ValueError("calibration sample does not match DOCX media")
        if self.review_status is not DocxMediaReviewStatus.HUMAN_CONFIRMED:
            if (
                self.status is not ExtractionStatus.UNKNOWN
                or self.gate_reason is not DocxMediaCalibrationGateReason.HUMAN_REVIEW_REQUIRED
                or self.production_recommended_threshold is not None
            ):
                raise ValueError("AI review must remain behind the human-review gate")
        elif self.calibration.status is ExtractionStatus.PASS:
            if (
                self.status is not ExtractionStatus.PASS
                or self.gate_reason is not None
                or self.production_recommended_threshold
                != self.calibration.recommended_threshold
            ):
                raise ValueError("passing human review must expose exact calibrated threshold")
        elif (
            self.status is not self.calibration.status
            or self.gate_reason
            is not DocxMediaCalibrationGateReason.CALIBRATION_NOT_PASSING
            or self.production_recommended_threshold is not None
        ):
            raise ValueError("non-passing human review must remain fail-closed")
        return self


def run_docx_media_calibration_review(
    review_path: Path,
    *,
    runner: OcrRunner | None = None,
) -> DocxMediaCalibrationRunReport:
    """Verify exact DOCX/media evidence, run OCR, and preserve reviewer provenance."""
    raw_review = _read_review(review_path)
    review = DocxMediaCalibrationReview.model_validate(_parse_json(raw_review))
    active_runner = runner or PaddleOcrRunner()
    if active_runner.engine != review.engine:
        raise DocxMediaCalibrationError(DocxMediaCalibrationErrorCode.ENGINE_MISMATCH)
    source_path = _resolve_source(review_path.resolve().parent, review.source_document)
    content = _read_source(source_path)
    document_digest = hashlib.sha256(content).hexdigest()
    if not hmac.compare_digest(document_digest, review.source_document_sha256):
        raise DocxMediaCalibrationError(
            DocxMediaCalibrationErrorCode.SOURCE_DIGEST_MISMATCH
        )
    try:
        extraction = extract_docx_media(
            DocumentInput(
                document_id=f"docx-{document_digest[:16]}",
                filename=source_path.name,
                declared_media_type=(
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ),
                content=content,
            )
        )
    except DocxMediaRejected as error:
        raise DocxMediaCalibrationError(
            DocxMediaCalibrationErrorCode.SOURCE_REJECTED
        ) from error
    media = next(
        (item for item in extraction.media if item.media_index == review.media_index),
        None,
    )
    if media is None:
        raise DocxMediaCalibrationError(DocxMediaCalibrationErrorCode.MEDIA_NOT_FOUND)
    if (
        media.archive_path != review.source_media
        or not hmac.compare_digest(media.sha256, review.source_media_sha256)
        or media.width != review.image_width
        or media.height != review.image_height
    ):
        raise DocxMediaCalibrationError(
            DocxMediaCalibrationErrorCode.MEDIA_EVIDENCE_MISMATCH
        )
    source = OcrEngineInput(
        source_document_id=media.source_media_id,
        source_sha256=media.sha256,
        page_count=1,
    )
    try:
        candidates = active_runner.recognize(
            source,
            content=media.content,
            media_type=media.media_type,
        )
    except (OcrEngineError, OcrSourceRejected) as error:
        raise DocxMediaCalibrationError(DocxMediaCalibrationErrorCode.OCR_FAILED) from error
    if any(candidate.page_number != 1 for candidate in candidates):
        raise DocxMediaCalibrationError(DocxMediaCalibrationErrorCode.OCR_FAILED)
    sample = OcrCalibrationSample(
        sample_id=media.source_media_id,
        source_sha256=media.sha256,
        expected=review.expected,
        candidates=candidates,
    )
    calibration = calibrate_ocr_threshold(
        (sample,),
        engine=review.engine,
        minimum_expected_lines=review.minimum_expected_lines,
        minimum_recall=review.minimum_recall,
        baseline_threshold=review.baseline_threshold,
    )
    human_confirmed = review.review_status is DocxMediaReviewStatus.HUMAN_CONFIRMED
    status = calibration.status if human_confirmed else ExtractionStatus.UNKNOWN
    gate_reason = (
        None
        if human_confirmed and calibration.status is ExtractionStatus.PASS
        else (
            DocxMediaCalibrationGateReason.CALIBRATION_NOT_PASSING
            if human_confirmed
            else DocxMediaCalibrationGateReason.HUMAN_REVIEW_REQUIRED
        )
    )
    return DocxMediaCalibrationRunReport(
        review_sha256=hashlib.sha256(raw_review).hexdigest(),
        review_status=review.review_status,
        reviewer_type=review.reviewer_type,
        reviewed_by=review.reviewed_by,
        source_document_sha256=document_digest,
        source_media_sha256=media.sha256,
        sample=sample,
        calibration=calibration,
        status=status,
        gate_reason=gate_reason,
        production_recommended_threshold=(
            calibration.recommended_threshold
            if human_confirmed and calibration.status is ExtractionStatus.PASS
            else None
        ),
    )


def publish_docx_media_calibration_report(
    report: DocxMediaCalibrationRunReport,
    target: Path,
) -> Path:
    """Atomically publish a private report without replacing existing evidence."""
    resolved = target.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=resolved.parent,
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary = Path(output.name)
            output.write(report.model_dump_json(indent=2))
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, resolved)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return resolved


def _read_review(path: Path) -> bytes:
    try:
        if path.stat().st_size > MAX_DOCX_MEDIA_REVIEW_BYTES:
            raise DocxMediaCalibrationError(
                DocxMediaCalibrationErrorCode.REVIEW_TOO_LARGE
            )
        content = path.read_bytes()
    except DocxMediaCalibrationError:
        raise
    except OSError as error:
        raise DocxMediaCalibrationError(
            DocxMediaCalibrationErrorCode.REVIEW_INVALID
        ) from error
    if len(content) > MAX_DOCX_MEDIA_REVIEW_BYTES:
        raise DocxMediaCalibrationError(DocxMediaCalibrationErrorCode.REVIEW_TOO_LARGE)
    return content


def _parse_json(content: bytes) -> object:
    def reject_constant(value: str) -> None:
        raise ValueError(f"invalid JSON constant: {value}")

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("JSON contains a duplicate key")
            result[key] = value
        return result

    try:
        return json.loads(
            content.decode("utf-8-sig"),
            parse_constant=reject_constant,
            object_pairs_hook=unique_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise DocxMediaCalibrationError(
            DocxMediaCalibrationErrorCode.REVIEW_INVALID
        ) from error


def _validate_relative_path(value: str) -> None:
    normalized = value.strip()
    posix = PurePosixPath(normalized)
    windows = PureWindowsPath(normalized)
    if (
        not normalized
        or "\x00" in normalized
        or posix.is_absolute()
        or windows.is_absolute()
        or posix.drive
        or windows.drive
        or ".." in posix.parts
        or ".." in windows.parts
    ):
        raise ValueError("source_document must be a safe relative path")


def _resolve_source(root: Path, source_file: str) -> Path:
    try:
        candidate = (root / source_file).resolve(strict=True)
        candidate.relative_to(root)
    except (OSError, ValueError) as error:
        raise DocxMediaCalibrationError(
            DocxMediaCalibrationErrorCode.SOURCE_PATH_INVALID
        ) from error
    if not candidate.is_file():
        raise DocxMediaCalibrationError(DocxMediaCalibrationErrorCode.SOURCE_NOT_FOUND)
    return candidate


def _read_source(path: Path) -> bytes:
    try:
        if path.stat().st_size > MAX_UPLOAD_BYTES:
            raise DocxMediaCalibrationError(DocxMediaCalibrationErrorCode.SOURCE_TOO_LARGE)
        content = path.read_bytes()
    except DocxMediaCalibrationError:
        raise
    except OSError as error:
        raise DocxMediaCalibrationError(
            DocxMediaCalibrationErrorCode.SOURCE_NOT_FOUND
        ) from error
    if len(content) > MAX_UPLOAD_BYTES:
        raise DocxMediaCalibrationError(DocxMediaCalibrationErrorCode.SOURCE_TOO_LARGE)
    return content
