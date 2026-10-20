"""Manifest-runner связывает локальный OCR-отчёт с разрешёнными байтами."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from pydantic import ValidationError
from pypdf import PdfWriter

from procurement.cli import main
from procurement.documents.extraction import ExtractionStatus
from procurement.documents.ocr import OcrCandidate, OcrEngineInput
from procurement.documents.ocr_calibration import ExpectedOcrLine
from procurement.documents.ocr_calibration_run import (
    CalibrationRunError,
    CalibrationRunErrorCode,
    OcrCalibrationManifest,
    OcrCalibrationManifestSample,
    publish_ocr_calibration_report,
    run_ocr_calibration_manifest,
)
from procurement.documents.paddle_ocr import PADDLE_OCR_ENGINE


class FakeRunner:
    engine = PADDLE_OCR_ENGINE

    def __init__(self, candidates: tuple[OcrCandidate, ...]) -> None:
        self.candidates = candidates
        self.calls = 0

    def recognize(
        self,
        source: OcrEngineInput,
        *,
        content: bytes,
        media_type: str,
    ) -> tuple[OcrCandidate, ...]:
        assert hashlib.sha256(content).hexdigest() == source.source_sha256
        assert media_type == "application/pdf"
        self.calls += 1
        return self.candidates


def _blank_pdf() -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.write(output)
    return output.getvalue()


def _manifest_payload(source_file: str, digest: str) -> dict[str, object]:
    return {
        "schema_version": "ocr-calibration-v1",
        "dataset_id": "approved-real-scans-v1",
        "authorization_reference": "DPA-2026-09-13-01",
        "labeled_by": "reviewer-1",
        "labeled_at": "2026-09-13T12:00:00+03:00",
        "engine": PADDLE_OCR_ENGINE,
        "minimum_expected_lines": 1,
        "minimum_recall": 1.0,
        "baseline_threshold": 0.75,
        "samples": [
            {
                "sample_id": "scan-001",
                "source_file": source_file,
                "source_sha256": digest,
                "expected": [
                    {"page_number": 1, "text": "Гарантия не менее 24 мес."}
                ],
            }
        ],
    }


def _write_manifest(directory: Path, payload: dict[str, object]) -> Path:
    manifest = directory / "manifest.json"
    manifest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return manifest


def _candidate() -> OcrCandidate:
    return OcrCandidate(
        page_number=1,
        block_index=0,
        text="Гарантия не менее 24 мес.",
        confidence=0.95,
        locator="page 1 bbox 10,20,250,40",
    )


def test_manifest_run_verifies_pdf_and_preserves_reproducible_evidence(tmp_path: Path) -> None:
    content = _blank_pdf()
    source = tmp_path / "scan.pdf"
    source.write_bytes(content)
    manifest = _write_manifest(
        tmp_path,
        _manifest_payload(source.name, hashlib.sha256(content).hexdigest()),
    )
    raw_manifest = manifest.read_bytes()

    report = run_ocr_calibration_manifest(
        manifest,
        runner=FakeRunner((_candidate(),)),
    )

    assert report.manifest_sha256 == hashlib.sha256(raw_manifest).hexdigest()
    assert report.dataset_id == "approved-real-scans-v1"
    assert report.authorization_reference == "DPA-2026-09-13-01"
    assert report.labeled_at == datetime.fromisoformat("2026-09-13T12:00:00+03:00")
    assert report.calibration.status is ExtractionStatus.PASS
    assert report.calibration.recommended_threshold == 0.75
    assert report.samples[0].candidates == (_candidate(),)
    assert "scan.pdf" not in report.model_dump_json()


def test_changed_source_is_rejected_before_ocr(tmp_path: Path) -> None:
    source = tmp_path / "scan.pdf"
    source.write_bytes(_blank_pdf())
    manifest = _write_manifest(tmp_path, _manifest_payload(source.name, "0" * 64))
    runner = FakeRunner((_candidate(),))

    with pytest.raises(CalibrationRunError) as exc_info:
        run_ocr_calibration_manifest(manifest, runner=runner)

    assert exc_info.value.code is CalibrationRunErrorCode.SOURCE_DIGEST_MISMATCH
    assert runner.calls == 0


def test_label_page_outside_immutable_pdf_is_rejected(tmp_path: Path) -> None:
    content = _blank_pdf()
    source = tmp_path / "scan.pdf"
    source.write_bytes(content)
    payload = _manifest_payload(source.name, hashlib.sha256(content).hexdigest())
    payload["samples"][0]["expected"][0]["page_number"] = 2
    manifest = _write_manifest(tmp_path, payload)
    runner = FakeRunner((_candidate(),))

    with pytest.raises(CalibrationRunError) as exc_info:
        run_ocr_calibration_manifest(manifest, runner=runner)

    assert exc_info.value.code is CalibrationRunErrorCode.LABEL_PAGE_OUT_OF_RANGE
    assert runner.calls == 0


def test_manifest_rejects_path_escape_and_naive_label_time() -> None:
    sample = {
        "sample_id": "scan-001",
        "source_file": "../private/scan.pdf",
        "source_sha256": "a" * 64,
        "expected": [{"page_number": 1, "text": "text"}],
    }
    with pytest.raises(ValidationError):
        OcrCalibrationManifest.model_validate(
            {
                "dataset_id": "dataset",
                "authorization_reference": "approval",
                "labeled_by": "reviewer",
                "labeled_at": "2026-09-13T12:00:00",
                "samples": [sample],
            }
        )


def test_manifest_rejects_duplicate_source_evidence() -> None:
    sample = OcrCalibrationManifestSample(
        sample_id="scan-001",
        source_file="scan.pdf",
        source_sha256="a" * 64,
        expected=(ExpectedOcrLine(page_number=1, text="text"),),
    )
    with pytest.raises(ValidationError, match="source digests must be unique"):
        OcrCalibrationManifest(
            dataset_id="dataset",
            authorization_reference="approval",
            labeled_by="reviewer",
            labeled_at=datetime.now(UTC),
            samples=(
                sample,
                sample.model_copy(update={"sample_id": "scan-002", "source_file": "copy.pdf"}),
            ),
        )


def test_report_publication_is_atomic_and_never_overwrites(tmp_path: Path) -> None:
    content = _blank_pdf()
    source = tmp_path / "scan.pdf"
    source.write_bytes(content)
    manifest = _write_manifest(
        tmp_path,
        _manifest_payload(source.name, hashlib.sha256(content).hexdigest()),
    )
    report = run_ocr_calibration_manifest(manifest, runner=FakeRunner((_candidate(),)))
    target = tmp_path / "reports" / "report.json"

    published = publish_ocr_calibration_report(report, target)

    assert published == target.resolve()
    assert json.loads(target.read_text(encoding="utf-8"))["calibration"]["status"] == "PASS"
    with pytest.raises(FileExistsError):
        publish_ocr_calibration_report(report, target)
    assert not tuple(target.parent.glob("*.tmp"))


@pytest.mark.parametrize(
    ("status", "reason", "exit_code"),
    [
        ("PASS", None, 0),
        ("UNKNOWN", "INSUFFICIENT_LABELS", 3),
        ("FAIL", "NO_SAFE_THRESHOLD", 4),
    ],
)
def test_cli_publishes_all_reports_but_only_pass_exits_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: str,
    reason: str | None,
    exit_code: int,
) -> None:
    content = _blank_pdf()
    source = tmp_path / "scan.pdf"
    source.write_bytes(content)
    manifest = _write_manifest(
        tmp_path,
        _manifest_payload(source.name, hashlib.sha256(content).hexdigest()),
    )
    report = run_ocr_calibration_manifest(manifest, runner=FakeRunner((_candidate(),)))
    payload = report.model_dump(mode="json")
    payload["calibration"]["status"] = status
    payload["calibration"]["reason"] = reason
    payload["calibration"]["recommended_threshold"] = 0.75 if status == "PASS" else None
    typed_report = report.model_validate(payload)
    monkeypatch.setattr(
        "procurement.cli.run_ocr_calibration_manifest",
        lambda _: typed_report,
    )
    output = tmp_path / f"{status.lower()}.json"

    result = main(["calibrate-ocr", str(manifest), "--output", str(output)])

    summary = json.loads(capsys.readouterr().out)
    assert result == exit_code
    assert summary["status"] == status
    assert "Гарантия" not in json.dumps(summary, ensure_ascii=False)
    assert output.is_file()
