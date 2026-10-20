"""Fail-closed подготовка и финализация ручной OCR-разметки.

OCR-кандидаты в draft служат только подсказками. Эталон ``expected`` заполняет
и подтверждает человек; ни один кандидат автоматически туда не копируется.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.documents.extraction import (
    MAX_UPLOAD_BYTES,
    DocumentInput,
    DocumentRejected,
    ExtractionReason,
    ExtractionStatus,
    extract_document,
)
from procurement.documents.ocr import (
    DEFAULT_OCR_CONFIDENCE_THRESHOLD,
    MAX_OCR_PAGES,
    OcrCandidate,
    OcrEngineError,
    OcrEngineInput,
    OcrRunner,
    OcrSourceRejected,
)
from procurement.documents.ocr_calibration import ExpectedOcrLine
from procurement.documents.ocr_calibration_run import OcrCalibrationManifest
from procurement.documents.paddle_ocr import PaddleOcrRunner

MAX_LABELING_DRAFT_BYTES = 10 * 1024 * 1024
"""Draft содержит OCR-подсказки, но остаётся ограниченным локальным JSON."""


class LabelingReviewStatus(StrEnum):
    """Человеческое подтверждение не сводится к неявному bool."""

    UNREVIEWED = "UNREVIEWED"
    CONFIRMED = "CONFIRMED"


class LabelingErrorCode(StrEnum):
    """Безопасные причины отказа без текста или имени приватного документа."""

    DATASET_DIRECTORY_INVALID = "DATASET_DIRECTORY_INVALID"
    NO_PDF_SOURCES = "NO_PDF_SOURCES"
    OUTPUT_OUTSIDE_DATASET = "OUTPUT_OUTSIDE_DATASET"
    SOURCE_TOO_LARGE = "SOURCE_TOO_LARGE"
    SOURCE_REJECTED = "SOURCE_REJECTED"
    SOURCE_NOT_RASTER_ONLY = "SOURCE_NOT_RASTER_ONLY"
    SOURCE_DIGEST_MISMATCH = "SOURCE_DIGEST_MISMATCH"
    SOURCE_PAGE_COUNT_MISMATCH = "SOURCE_PAGE_COUNT_MISMATCH"
    ENGINE_MISMATCH = "ENGINE_MISMATCH"
    OCR_FAILED = "OCR_FAILED"
    DRAFT_TOO_LARGE = "DRAFT_TOO_LARGE"
    DRAFT_INVALID = "DRAFT_INVALID"
    REVIEW_INCOMPLETE = "REVIEW_INCOMPLETE"


class LabelingError(ValueError):
    """Ошибка workflow, безопасная для вывода CLI."""

    def __init__(self, code: LabelingErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


class OcrLabelingDraftSample(BaseModel):
    """Один immutable PDF, OCR-подсказки и отдельный ручной эталон."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sample_id: str = Field(min_length=1)
    source_file: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_count: int = Field(ge=1, le=MAX_OCR_PAGES)
    suggestions: tuple[OcrCandidate, ...]
    expected: tuple[ExpectedOcrLine, ...] = ()
    review_status: LabelingReviewStatus = LabelingReviewStatus.UNREVIEWED

    @model_validator(mode="after")
    def _sample_is_consistent(self) -> Self:
        _validate_relative_path(self.source_file)
        if not self.sample_id.strip():
            raise ValueError("sample_id must not be blank")
        if any(item.page_number > self.page_count for item in self.suggestions):
            raise ValueError("OCR suggestion page is outside the source")
        if any(item.page_number > self.page_count for item in self.expected):
            raise ValueError("expected line page is outside the source")
        if self.review_status is LabelingReviewStatus.CONFIRMED and not self.expected:
            raise ValueError("confirmed sample requires manually expected lines")
        return self


class OcrLabelingDraft(BaseModel):
    """Редактируемый пакет: OCR-текст недоверен до явного review."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["ocr-labeling-draft-v1"] = "ocr-labeling-draft-v1"
    dataset_id: str = Field(min_length=1)
    authorization_reference: str = Field(min_length=1)
    generated_at: datetime
    engine: Literal["paddleocr/3.7.0:PP-OCRv5-ru"] = "paddleocr/3.7.0:PP-OCRv5-ru"
    minimum_expected_lines: int = Field(default=20, ge=1)
    minimum_recall: float = Field(default=0.9, ge=0.0, le=1.0)
    baseline_threshold: float = Field(
        default=DEFAULT_OCR_CONFIDENCE_THRESHOLD,
        ge=0.0,
        le=1.0,
    )
    review_status: LabelingReviewStatus = LabelingReviewStatus.UNREVIEWED
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    samples: tuple[OcrLabelingDraftSample, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _draft_is_consistent(self) -> Self:
        for value, name in (
            (self.dataset_id, "dataset_id"),
            (self.authorization_reference, "authorization_reference"),
        ):
            if not value.strip():
                raise ValueError(f"{name} must not be blank")
        if self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must include a timezone")
        sample_ids = tuple(sample.sample_id for sample in self.samples)
        digests = tuple(sample.source_sha256 for sample in self.samples)
        source_files = tuple(sample.source_file for sample in self.samples)
        if len(set(sample_ids)) != len(sample_ids):
            raise ValueError("labeling sample_id values must be unique")
        if len(set(digests)) != len(digests):
            raise ValueError("labeling source digests must be unique")
        if len(set(source_files)) != len(source_files):
            raise ValueError("labeling source files must be unique")

        if self.review_status is LabelingReviewStatus.UNREVIEWED:
            if self.reviewed_by is not None or self.reviewed_at is not None:
                raise ValueError("unreviewed draft cannot contain reviewer evidence")
        else:
            if self.reviewed_by is None or not self.reviewed_by.strip():
                raise ValueError("confirmed draft requires reviewed_by")
            if self.reviewed_at is None or self.reviewed_at.utcoffset() is None:
                raise ValueError("confirmed draft requires timezone-aware reviewed_at")
            if self.reviewed_at < self.generated_at:
                raise ValueError("reviewed_at cannot precede generated_at")
            if any(
                sample.review_status is not LabelingReviewStatus.CONFIRMED
                for sample in self.samples
            ):
                raise ValueError("confirmed draft requires every sample to be confirmed")
        return self


def prepare_ocr_labeling_draft(
    dataset_directory: Path,
    *,
    dataset_id: str,
    authorization_reference: str,
    runner: OcrRunner | None = None,
    generated_at: datetime | None = None,
    minimum_expected_lines: int = 20,
    minimum_recall: float = 0.9,
    baseline_threshold: float = DEFAULT_OCR_CONFIDENCE_THRESHOLD,
) -> OcrLabelingDraft:
    """Распознать все PDF каталога и оставить ручной эталон пустым."""
    try:
        root = dataset_directory.resolve(strict=True)
    except OSError as error:
        raise LabelingError(LabelingErrorCode.DATASET_DIRECTORY_INVALID) from error
    if not root.is_dir():
        raise LabelingError(LabelingErrorCode.DATASET_DIRECTORY_INVALID)
    sources = tuple(
        sorted(
            (
                path
                for path in root.iterdir()
                if path.is_file() and path.suffix.casefold() == ".pdf"
            ),
            key=lambda path: path.name.casefold(),
        )
    )
    if not sources:
        raise LabelingError(LabelingErrorCode.NO_PDF_SOURCES)

    active_runner = runner or PaddleOcrRunner()
    if active_runner.engine != "paddleocr/3.7.0:PP-OCRv5-ru":
        raise LabelingError(LabelingErrorCode.ENGINE_MISMATCH)
    samples = tuple(
        _prepare_sample(root, source, active_runner)
        for source in sources
    )
    return OcrLabelingDraft(
        dataset_id=dataset_id,
        authorization_reference=authorization_reference,
        generated_at=generated_at or datetime.now(UTC),
        minimum_expected_lines=minimum_expected_lines,
        minimum_recall=minimum_recall,
        baseline_threshold=baseline_threshold,
        samples=samples,
    )


def load_ocr_labeling_draft(path: Path) -> tuple[bytes, OcrLabelingDraft]:
    """Прочитать draft строго: UTF-8, конечные числа и уникальные JSON-ключи."""
    raw = _read_limited(path)
    return raw, OcrLabelingDraft.model_validate(_parse_json(raw))


def finalize_ocr_labeling_draft(path: Path) -> OcrCalibrationManifest:
    """Собрать calibration manifest только из полностью подтверждённого эталона."""
    raw, draft = load_ocr_labeling_draft(path)
    if draft.review_status is not LabelingReviewStatus.CONFIRMED:
        raise LabelingError(LabelingErrorCode.REVIEW_INCOMPLETE)
    root = path.resolve().parent
    for sample in draft.samples:
        _verify_reviewed_source(root, sample)
    reviewed_by = draft.reviewed_by
    reviewed_at = draft.reviewed_at
    if reviewed_by is None or reviewed_at is None:
        raise LabelingError(LabelingErrorCode.REVIEW_INCOMPLETE)
    return OcrCalibrationManifest(
        dataset_id=draft.dataset_id,
        authorization_reference=draft.authorization_reference,
        labeled_by=reviewed_by,
        labeled_at=reviewed_at,
        engine=draft.engine,
        minimum_expected_lines=draft.minimum_expected_lines,
        minimum_recall=draft.minimum_recall,
        baseline_threshold=draft.baseline_threshold,
        labeling_draft_sha256=hashlib.sha256(raw).hexdigest(),
        samples=tuple(
            {
                "sample_id": sample.sample_id,
                "source_file": sample.source_file,
                "source_sha256": sample.source_sha256,
                "expected": sample.expected,
            }
            for sample in draft.samples
        ),
    )


def publish_labeling_artifact(model: BaseModel, target: Path, *, root: Path) -> Path:
    """Атомарно создать JSON внутри dataset-каталога без перезаписи."""
    resolved_root = root.resolve(strict=True)
    resolved_target = target.resolve()
    if resolved_target.parent != resolved_root:
        raise LabelingError(LabelingErrorCode.OUTPUT_OUTSIDE_DATASET)
    resolved_target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=resolved_target.parent,
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary = Path(output.name)
            output.write(model.model_dump_json(indent=2))
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, resolved_target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return resolved_target


def _prepare_sample(root: Path, source_path: Path, runner: OcrRunner) -> OcrLabelingDraftSample:
    content, digest, page_count = _validated_source(source_path)
    source = OcrEngineInput(
        source_document_id=f"scan-{digest[:16]}",
        source_sha256=digest,
        page_count=page_count,
    )
    try:
        suggestions = runner.recognize(
            source,
            content=content,
            media_type="application/pdf",
        )
    except (OcrEngineError, OcrSourceRejected) as error:
        raise LabelingError(LabelingErrorCode.OCR_FAILED) from error
    if any(item.page_number > page_count for item in suggestions):
        raise LabelingError(LabelingErrorCode.OCR_FAILED)
    return OcrLabelingDraftSample(
        sample_id=source.source_document_id,
        source_file=source_path.relative_to(root).as_posix(),
        source_sha256=digest,
        page_count=page_count,
        suggestions=suggestions,
    )


def _verify_reviewed_source(root: Path, sample: OcrLabelingDraftSample) -> None:
    source_path = _resolve_source(root, sample.source_file)
    _, digest, page_count = _validated_source(source_path)
    if not hmac.compare_digest(digest, sample.source_sha256):
        raise LabelingError(LabelingErrorCode.SOURCE_DIGEST_MISMATCH)
    if page_count != sample.page_count:
        raise LabelingError(LabelingErrorCode.SOURCE_PAGE_COUNT_MISMATCH)


def _validated_source(source_path: Path) -> tuple[bytes, str, int]:
    try:
        if source_path.stat().st_size > MAX_UPLOAD_BYTES:
            raise LabelingError(LabelingErrorCode.SOURCE_TOO_LARGE)
        content = source_path.read_bytes()
    except LabelingError:
        raise
    except OSError as error:
        raise LabelingError(LabelingErrorCode.SOURCE_REJECTED) from error
    if len(content) > MAX_UPLOAD_BYTES:
        raise LabelingError(LabelingErrorCode.SOURCE_TOO_LARGE)
    digest = hashlib.sha256(content).hexdigest()
    try:
        native = extract_document(
            DocumentInput(
                document_id=f"scan-{digest[:16]}",
                filename=source_path.name,
                declared_media_type="application/pdf",
                content=content,
            )
        )
    except DocumentRejected as error:
        raise LabelingError(LabelingErrorCode.SOURCE_REJECTED) from error
    if (
        native.status is not ExtractionStatus.UNKNOWN
        or native.blocks
        or ExtractionReason.OCR_REQUIRED not in native.reasons
        or not 1 <= native.source_units_total <= MAX_OCR_PAGES
    ):
        raise LabelingError(LabelingErrorCode.SOURCE_NOT_RASTER_ONLY)
    return content, digest, native.source_units_total


def _resolve_source(root: Path, source_file: str) -> Path:
    _validate_relative_path(source_file)
    try:
        candidate = (root / source_file).resolve(strict=True)
        candidate.relative_to(root)
    except (OSError, ValueError) as error:
        raise LabelingError(LabelingErrorCode.SOURCE_REJECTED) from error
    if not candidate.is_file():
        raise LabelingError(LabelingErrorCode.SOURCE_REJECTED)
    return candidate


def _validate_relative_path(source_file: str) -> None:
    value = source_file.strip()
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        not value
        or "\x00" in value
        or posix.is_absolute()
        or windows.is_absolute()
        or posix.drive
        or windows.drive
        or ".." in posix.parts
        or ".." in windows.parts
    ):
        raise ValueError("source_file must be a safe relative path")


def _read_limited(path: Path) -> bytes:
    try:
        if path.stat().st_size > MAX_LABELING_DRAFT_BYTES:
            raise LabelingError(LabelingErrorCode.DRAFT_TOO_LARGE)
        raw = path.read_bytes()
    except LabelingError:
        raise
    except OSError as error:
        raise LabelingError(LabelingErrorCode.DRAFT_INVALID) from error
    if len(raw) > MAX_LABELING_DRAFT_BYTES:
        raise LabelingError(LabelingErrorCode.DRAFT_TOO_LARGE)
    return raw


def _parse_json(raw: bytes) -> object:
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
            raw.decode("utf-8-sig"),
            parse_constant=reject_constant,
            object_pairs_hook=unique_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise LabelingError(LabelingErrorCode.DRAFT_INVALID) from error
