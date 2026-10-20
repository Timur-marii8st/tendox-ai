"""Ручной OCR-эталон отделён от машинных подсказок и финализируется fail-closed."""

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
from procurement.documents.ocr_calibration_run import run_ocr_calibration_manifest
from procurement.documents.ocr_labeling import (
    LabelingError,
    LabelingErrorCode,
    LabelingReviewStatus,
    OcrLabelingDraft,
    finalize_ocr_labeling_draft,
    prepare_ocr_labeling_draft,
    publish_labeling_artifact,
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
        assert source.source_sha256 == hashlib.sha256(content).hexdigest()
        assert media_type == "application/pdf"
        self.calls += 1
        return self.candidates


def _blank_pdf(*, width: int = 300) -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=300)
    writer.write(output)
    return output.getvalue()


def _candidate(text: str = "OCR-подсказка") -> OcrCandidate:
    return OcrCandidate(
        page_number=1,
        block_index=0,
        text=text,
        confidence=0.95,
        locator="page 1 bbox 1,2,100,20",
    )


def _prepare(
    directory: Path,
    *,
    candidates: tuple[OcrCandidate, ...] | None = None,
) -> OcrLabelingDraft:
    (directory / "scan.pdf").write_bytes(_blank_pdf())
    return prepare_ocr_labeling_draft(
        directory,
        dataset_id="real-procurement-scans-v1",
        authorization_reference="approval-ticket-42",
        runner=FakeRunner(candidates or (_candidate(),)),
        generated_at=datetime(2026, 9, 14, 8, tzinfo=UTC),
        minimum_expected_lines=2,
        minimum_recall=0.5,
    )


def _confirm(draft: OcrLabelingDraft) -> OcrLabelingDraft:
    payload = draft.model_dump(mode="json")
    payload["review_status"] = "CONFIRMED"
    payload["reviewed_by"] = "reviewer-1"
    payload["reviewed_at"] = "2026-09-14T12:00:00+03:00"
    payload["samples"][0]["review_status"] = "CONFIRMED"
    payload["samples"][0]["expected"] = [
        {"page_number": 1, "text": "OCR-подсказка"},
        {"page_number": 1, "text": "Строка, полностью пропущенная OCR"},
    ]
    return OcrLabelingDraft.model_validate(payload)


def test_prepare_keeps_machine_suggestions_out_of_manual_truth(tmp_path: Path) -> None:
    draft = _prepare(tmp_path)

    assert draft.review_status is LabelingReviewStatus.UNREVIEWED
    assert draft.reviewed_by is draft.reviewed_at is None
    assert len(draft.samples) == 1
    sample = draft.samples[0]
    assert sample.sample_id == f"scan-{sample.source_sha256[:16]}"
    assert sample.source_file == "scan.pdf"
    assert sample.page_count == 1
    assert sample.suggestions == (_candidate(),)
    assert sample.expected == ()
    assert sample.review_status is LabelingReviewStatus.UNREVIEWED


def test_unreviewed_draft_cannot_be_finalized(tmp_path: Path) -> None:
    draft = _prepare(tmp_path)
    draft_path = publish_labeling_artifact(draft, tmp_path / "draft.json", root=tmp_path)

    with pytest.raises(LabelingError) as exc_info:
        finalize_ocr_labeling_draft(draft_path)

    assert exc_info.value.code is LabelingErrorCode.REVIEW_INCOMPLETE
    assert not (tmp_path / "manifest.json").exists()


def test_confirmed_draft_preserves_manual_miss_and_reaches_calibration(tmp_path: Path) -> None:
    draft = _confirm(_prepare(tmp_path))
    draft_path = publish_labeling_artifact(draft, tmp_path / "draft.json", root=tmp_path)
    raw_draft = draft_path.read_bytes()

    manifest = finalize_ocr_labeling_draft(draft_path)

    assert manifest.labeled_by == "reviewer-1"
    assert manifest.labeling_draft_sha256 == hashlib.sha256(raw_draft).hexdigest()
    assert len(manifest.samples[0].expected) == 2
    assert "suggestions" not in manifest.model_dump_json()
    manifest_path = publish_labeling_artifact(
        manifest,
        tmp_path / "manifest.json",
        root=tmp_path,
    )
    report = run_ocr_calibration_manifest(
        manifest_path,
        runner=FakeRunner((_candidate(),)),
    )
    assert report.labeling_draft_sha256 == manifest.labeling_draft_sha256
    assert report.calibration.status is ExtractionStatus.PASS
    selected = next(
        item
        for item in report.calibration.observations
        if item.threshold == report.calibration.recommended_threshold
    )
    assert selected.true_positive == 1
    assert selected.false_negative == 1
    assert selected.recall == 0.5


def test_confirmed_sample_requires_manual_expected_lines(tmp_path: Path) -> None:
    draft = _prepare(tmp_path)
    payload = draft.model_dump(mode="json")
    payload["samples"][0]["review_status"] = "CONFIRMED"

    with pytest.raises(ValidationError, match="manually expected lines"):
        OcrLabelingDraft.model_validate(payload)


def test_global_confirmation_requires_every_sample_and_reviewer_evidence(tmp_path: Path) -> None:
    draft = _prepare(tmp_path)
    payload = draft.model_dump(mode="json")
    payload["review_status"] = "CONFIRMED"
    payload["reviewed_by"] = "reviewer-1"
    payload["reviewed_at"] = "2026-09-14T12:00:00+03:00"

    with pytest.raises(ValidationError, match="every sample"):
        OcrLabelingDraft.model_validate(payload)


def test_changed_source_is_rejected_during_finalization(tmp_path: Path) -> None:
    draft = _confirm(_prepare(tmp_path))
    draft_path = publish_labeling_artifact(draft, tmp_path / "draft.json", root=tmp_path)
    (tmp_path / "scan.pdf").write_bytes(_blank_pdf(width=301))

    with pytest.raises(LabelingError) as exc_info:
        finalize_ocr_labeling_draft(draft_path)

    assert exc_info.value.code is LabelingErrorCode.SOURCE_DIGEST_MISMATCH


def test_labeling_artifact_cannot_escape_dataset(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    draft = _prepare(dataset)

    with pytest.raises(LabelingError) as exc_info:
        publish_labeling_artifact(draft, tmp_path / "outside.json", root=dataset)

    assert exc_info.value.code is LabelingErrorCode.OUTPUT_OUTSIDE_DATASET


def test_prepare_cli_summary_does_not_print_ocr_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    draft = _prepare(tmp_path)
    monkeypatch.setattr("procurement.cli.prepare_ocr_labeling_draft", lambda *args, **kwargs: draft)
    output = tmp_path / "draft.json"

    result = main(
        [
            "prepare-ocr-labeling",
            str(tmp_path),
            "--dataset-id",
            "dataset-v1",
            "--authorization-reference",
            "ticket-1",
            "--output",
            str(output),
        ]
    )

    summary = json.loads(capsys.readouterr().out)
    assert result == 0
    assert summary["status"] == "UNKNOWN"
    assert summary["reason"] == "HUMAN_REVIEW_REQUIRED"
    assert summary["suggestions_total"] == 1
    assert "OCR-подсказка" not in json.dumps(summary, ensure_ascii=False)
    assert output.is_file()


def test_finalize_cli_refuses_unreviewed_draft_without_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    draft = _prepare(tmp_path)
    draft_path = publish_labeling_artifact(draft, tmp_path / "draft.json", root=tmp_path)
    output = tmp_path / "manifest.json"

    result = main(["finalize-ocr-labeling", str(draft_path), "--output", str(output)])

    error = json.loads(capsys.readouterr().err)
    assert result == 2
    assert error == {
        "error": "labeling_finalization_failed",
        "code": "REVIEW_INCOMPLETE",
    }
    assert not output.exists()


def test_finalize_cli_creates_manifest_but_never_claims_calibration_pass(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    draft = _confirm(_prepare(tmp_path))
    draft_path = publish_labeling_artifact(draft, tmp_path / "draft.json", root=tmp_path)
    output = tmp_path / "manifest.json"

    result = main(["finalize-ocr-labeling", str(draft_path), "--output", str(output)])

    summary = json.loads(capsys.readouterr().out)
    assert result == 0
    assert summary["status"] == "UNKNOWN"
    assert summary["reason"] == "CALIBRATION_NOT_RUN"
    assert summary["review_status"] == "CONFIRMED"
    assert output.is_file()
