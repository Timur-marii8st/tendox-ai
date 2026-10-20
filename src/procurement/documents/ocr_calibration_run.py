"""Воспроизводимый локальный запуск OCR-калибровки по разрешённому manifest.

Manifest хранит ручную разметку и immutable SHA-256 каждого PDF. Исходные пути
не попадают в отчёт, а полный набор ожидаемых строк и сырых OCR-кандидатов
сохраняется рядом с решением, чтобы метрики можно было проверить повторно.
"""

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

MAX_CALIBRATION_MANIFEST_BYTES = 1024 * 1024
"""Manifest не должен становиться обходом лимитов входных данных."""


class CalibrationRunErrorCode(StrEnum):
    """Безопасные причины отказа до публикации калибровочного отчёта."""

    MANIFEST_TOO_LARGE = "MANIFEST_TOO_LARGE"
    MANIFEST_INVALID = "MANIFEST_INVALID"
    SOURCE_PATH_INVALID = "SOURCE_PATH_INVALID"
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    SOURCE_TOO_LARGE = "SOURCE_TOO_LARGE"
    SOURCE_DIGEST_MISMATCH = "SOURCE_DIGEST_MISMATCH"
    SOURCE_NOT_RASTER_ONLY = "SOURCE_NOT_RASTER_ONLY"
    SOURCE_REJECTED = "SOURCE_REJECTED"
    LABEL_PAGE_OUT_OF_RANGE = "LABEL_PAGE_OUT_OF_RANGE"
    ENGINE_MISMATCH = "ENGINE_MISMATCH"
    OCR_FAILED = "OCR_FAILED"


class CalibrationRunError(ValueError):
    """Ошибка набора без утечки имени файла или содержимого документа."""

    def __init__(self, code: CalibrationRunErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


class OcrCalibrationManifestSample(BaseModel):
    """Ссылка на локальный снимок и полная ручная построчная разметка."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sample_id: str = Field(min_length=1)
    source_file: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected: tuple[ExpectedOcrLine, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _fields_are_safe(self) -> Self:
        if not self.sample_id.strip():
            raise ValueError("sample_id must not be blank")
        source_file = self.source_file.strip()
        posix = PurePosixPath(source_file)
        windows = PureWindowsPath(source_file)
        if (
            not source_file
            or "\x00" in source_file
            or posix.is_absolute()
            or windows.is_absolute()
            or posix.drive
            or windows.drive
            or ".." in posix.parts
            or ".." in windows.parts
        ):
            raise ValueError("source_file must be a safe relative path")
        return self


class OcrCalibrationManifest(BaseModel):
    """Версионированный контракт разрешённого размеченного набора."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["ocr-calibration-v1"] = "ocr-calibration-v1"
    dataset_id: str = Field(min_length=1)
    authorization_reference: str = Field(min_length=1)
    labeled_by: str = Field(min_length=1)
    labeled_at: datetime
    labeling_draft_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    engine: Literal["paddleocr/3.7.0:PP-OCRv5-ru"] = "paddleocr/3.7.0:PP-OCRv5-ru"
    minimum_expected_lines: int = Field(default=20, ge=1)
    minimum_recall: float = Field(default=0.9, ge=0.0, le=1.0)
    baseline_threshold: float = Field(
        default=DEFAULT_OCR_CONFIDENCE_THRESHOLD,
        ge=0.0,
        le=1.0,
    )
    samples: tuple[OcrCalibrationManifestSample, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _evidence_is_unambiguous(self) -> Self:
        for value, name in (
            (self.dataset_id, "dataset_id"),
            (self.authorization_reference, "authorization_reference"),
            (self.labeled_by, "labeled_by"),
        ):
            if not value.strip():
                raise ValueError(f"{name} must not be blank")
        if self.labeled_at.utcoffset() is None:
            raise ValueError("labeled_at must include a timezone")
        sample_ids = tuple(sample.sample_id for sample in self.samples)
        digests = tuple(sample.source_sha256 for sample in self.samples)
        if len(set(sample_ids)) != len(sample_ids):
            raise ValueError("calibration sample_id values must be unique")
        if len(set(digests)) != len(digests):
            raise ValueError("calibration source digests must be unique")
        return self


class OcrCalibrationRunReport(BaseModel):
    """Самодостаточный локальный артефакт калибровки без исходных путей."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["ocr-calibration-report-v1"] = "ocr-calibration-report-v1"
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_id: str = Field(min_length=1)
    authorization_reference: str = Field(min_length=1)
    labeled_by: str = Field(min_length=1)
    labeled_at: datetime
    labeling_draft_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    samples: tuple[OcrCalibrationSample, ...]
    calibration: OcrCalibrationReport

    @model_validator(mode="after")
    def _report_matches_evidence(self) -> Self:
        sample_ids = tuple(sample.sample_id for sample in self.samples)
        digests = tuple(sample.source_sha256 for sample in self.samples)
        if self.calibration.sample_ids != sample_ids:
            raise ValueError("calibration sample IDs do not match report evidence")
        if self.calibration.source_sha256 != digests:
            raise ValueError("calibration digests do not match report evidence")
        return self


def run_ocr_calibration_manifest(
    manifest_path: Path,
    *,
    runner: OcrRunner | None = None,
) -> OcrCalibrationRunReport:
    """Проверить manifest, локально распознать immutable PDF и собрать отчёт."""
    raw_manifest = _read_manifest(manifest_path)
    manifest = OcrCalibrationManifest.model_validate(_parse_json(raw_manifest))
    active_runner = runner or PaddleOcrRunner()
    if active_runner.engine != manifest.engine:
        raise CalibrationRunError(CalibrationRunErrorCode.ENGINE_MISMATCH)

    root = manifest_path.resolve().parent
    samples = tuple(
        _run_sample(root, item, active_runner)
        for item in manifest.samples
    )
    calibration = calibrate_ocr_threshold(
        samples,
        engine=manifest.engine,
        minimum_expected_lines=manifest.minimum_expected_lines,
        minimum_recall=manifest.minimum_recall,
        baseline_threshold=manifest.baseline_threshold,
    )
    return OcrCalibrationRunReport(
        manifest_sha256=hashlib.sha256(raw_manifest).hexdigest(),
        dataset_id=manifest.dataset_id,
        authorization_reference=manifest.authorization_reference,
        labeled_by=manifest.labeled_by,
        labeled_at=manifest.labeled_at,
        labeling_draft_sha256=manifest.labeling_draft_sha256,
        samples=samples,
        calibration=calibration,
    )


def publish_ocr_calibration_report(
    report: OcrCalibrationRunReport,
    target: Path,
) -> Path:
    """Атомарно опубликовать новый отчёт, не перезаписывая существующий."""
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


def _read_manifest(path: Path) -> bytes:
    try:
        if path.stat().st_size > MAX_CALIBRATION_MANIFEST_BYTES:
            raise CalibrationRunError(CalibrationRunErrorCode.MANIFEST_TOO_LARGE)
        content = path.read_bytes()
    except CalibrationRunError:
        raise
    except OSError as error:
        raise CalibrationRunError(CalibrationRunErrorCode.MANIFEST_INVALID) from error
    if len(content) > MAX_CALIBRATION_MANIFEST_BYTES:
        raise CalibrationRunError(CalibrationRunErrorCode.MANIFEST_TOO_LARGE)
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
        raise CalibrationRunError(CalibrationRunErrorCode.MANIFEST_INVALID) from error


def _run_sample(
    root: Path,
    sample: OcrCalibrationManifestSample,
    runner: OcrRunner,
) -> OcrCalibrationSample:
    source_path = _resolve_source(root, sample.source_file)
    try:
        if source_path.stat().st_size > MAX_UPLOAD_BYTES:
            raise CalibrationRunError(CalibrationRunErrorCode.SOURCE_TOO_LARGE)
        content = source_path.read_bytes()
    except CalibrationRunError:
        raise
    except OSError as error:
        raise CalibrationRunError(CalibrationRunErrorCode.SOURCE_NOT_FOUND) from error
    if len(content) > MAX_UPLOAD_BYTES:
        raise CalibrationRunError(CalibrationRunErrorCode.SOURCE_TOO_LARGE)
    digest = hashlib.sha256(content).hexdigest()
    if not hmac.compare_digest(digest, sample.source_sha256):
        raise CalibrationRunError(CalibrationRunErrorCode.SOURCE_DIGEST_MISMATCH)

    try:
        native = extract_document(
            DocumentInput(
                document_id=sample.sample_id,
                filename=source_path.name,
                declared_media_type="application/pdf",
                content=content,
            )
        )
    except DocumentRejected as error:
        raise CalibrationRunError(CalibrationRunErrorCode.SOURCE_REJECTED) from error
    if (
        native.status is not ExtractionStatus.UNKNOWN
        or native.blocks
        or ExtractionReason.OCR_REQUIRED not in native.reasons
        or not 1 <= native.source_units_total <= MAX_OCR_PAGES
    ):
        raise CalibrationRunError(CalibrationRunErrorCode.SOURCE_NOT_RASTER_ONLY)
    if any(line.page_number > native.source_units_total for line in sample.expected):
        raise CalibrationRunError(CalibrationRunErrorCode.LABEL_PAGE_OUT_OF_RANGE)

    source = OcrEngineInput(
        source_document_id=sample.sample_id,
        source_sha256=digest,
        page_count=native.source_units_total,
    )
    try:
        candidates = runner.recognize(
            source,
            content=content,
            media_type="application/pdf",
        )
    except (OcrEngineError, OcrSourceRejected) as error:
        raise CalibrationRunError(CalibrationRunErrorCode.OCR_FAILED) from error
    if any(candidate.page_number > native.source_units_total for candidate in candidates):
        raise CalibrationRunError(CalibrationRunErrorCode.OCR_FAILED)
    return OcrCalibrationSample(
        sample_id=sample.sample_id,
        source_sha256=digest,
        expected=sample.expected,
        candidates=candidates,
    )


def _resolve_source(root: Path, source_file: str) -> Path:
    try:
        candidate = (root / source_file).resolve(strict=True)
        candidate.relative_to(root)
    except (OSError, ValueError) as error:
        raise CalibrationRunError(CalibrationRunErrorCode.SOURCE_PATH_INVALID) from error
    if not candidate.is_file():
        raise CalibrationRunError(CalibrationRunErrorCode.SOURCE_NOT_FOUND)
    return candidate
