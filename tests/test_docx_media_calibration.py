"""DOCX-media calibration preserves reviewer provenance and exact source evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from docx.shared import Inches
from PIL import Image
from pydantic import ValidationError

import procurement.cli as cli
from procurement.documents import DocumentInput, OcrCandidate, extract_docx_media
from procurement.documents.docx_media_calibration import (
    DocxMediaCalibrationError,
    DocxMediaCalibrationErrorCode,
    DocxMediaCalibrationReview,
    DocxMediaReviewerType,
    DocxMediaReviewStatus,
    DocxMediaReviewUncertainty,
    run_docx_media_calibration_review,
)
from procurement.documents.extraction import ExtractionStatus
from procurement.documents.ocr import OcrEngineInput

ENGINE = "paddleocr/3.7.0:PP-OCRv5-ru"
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class FakeRunner:
    engine = ENGINE

    def __init__(self) -> None:
        self.content: bytes | None = None

    def recognize(
        self,
        source: OcrEngineInput,
        *,
        content: bytes,
        media_type: str,
    ) -> tuple[OcrCandidate, ...]:
        assert source.page_count == 1
        assert media_type == "image/png"
        self.content = content
        return (
            OcrCandidate(
                page_number=1,
                block_index=0,
                text="Строка один",
                confidence=0.91,
                locator="image 1 bbox 1,2,30,10",
            ),
            OcrCandidate(
                page_number=1,
                block_index=1,
                text="Строка два",
                confidence=0.95,
                locator="image 1 bbox 1,20,30,30",
            ),
        )


def _source(tmp_path: Path) -> tuple[Path, bytes, object]:
    image_output = BytesIO()
    Image.new("RGB", (80, 40), color="white").save(image_output, format="PNG")
    image = image_output.getvalue()
    document_output = BytesIO()
    document = Document()
    document.add_picture(BytesIO(image), width=Inches(1))
    document.save(document_output)
    path = tmp_path / "source.docx"
    path.write_bytes(document_output.getvalue())
    media = extract_docx_media(
        DocumentInput(
            document_id="source",
            filename=path.name,
            declared_media_type=DOCX_MEDIA_TYPE,
            content=document_output.getvalue(),
        )
    ).media[0]
    return path, image, media


def _review(tmp_path: Path) -> DocxMediaCalibrationReview:
    path, _, media = _source(tmp_path)
    return DocxMediaCalibrationReview(
        review_status=DocxMediaReviewStatus.AI_REVIEWED_REQUIRES_HUMAN_CONFIRMATION,
        reviewer_type=DocxMediaReviewerType.AI_VISUAL_REVIEW,
        reviewed_by="codex-vision",
        reviewed_at=datetime.now(UTC),
        authorization_reference="synthetic-test",
        source_document=path.name,
        source_document_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        media_index=media.media_index,  # type: ignore[attr-defined]
        source_media=media.archive_path,  # type: ignore[attr-defined]
        source_media_sha256=media.sha256,  # type: ignore[attr-defined]
        image_width=media.width,  # type: ignore[attr-defined]
        image_height=media.height,  # type: ignore[attr-defined]
        method="independent synthetic visual review",
        minimum_expected_lines=2,
        minimum_recall=1.0,
        expected=(
            {"page_number": 1, "text": "Строка один"},
            {"page_number": 1, "text": "Строка два"},
        ),
        uncertainties=(
            DocxMediaReviewUncertainty(
                region="corner",
                visible_text="?",
                reason="synthetic unresolved mark",
            ),
        ),
    )


def _write_review(path: Path, review: DocxMediaCalibrationReview) -> None:
    path.write_text(review.model_dump_json(indent=2), encoding="utf-8")


def test_ai_review_gets_metrics_but_cannot_pass_production_gate(tmp_path: Path) -> None:
    review = _review(tmp_path)
    review_path = tmp_path / "ai-review.json"
    _write_review(review_path, review)
    runner = FakeRunner()

    report = run_docx_media_calibration_review(review_path, runner=runner)

    assert report.calibration.status is ExtractionStatus.PASS
    assert report.calibration.recommended_threshold == 0.75
    assert report.status is ExtractionStatus.UNKNOWN
    assert report.gate_reason == "HUMAN_REVIEW_REQUIRED"
    assert report.production_recommended_threshold is None
    assert runner.content is not None
    assert hashlib.sha256(runner.content).hexdigest() == review.source_media_sha256


def test_human_confirmation_can_expose_only_a_passing_threshold(tmp_path: Path) -> None:
    ai_review = _review(tmp_path)
    human_review = ai_review.model_copy(
        update={
            "review_status": DocxMediaReviewStatus.HUMAN_CONFIRMED,
            "reviewer_type": DocxMediaReviewerType.HUMAN,
            "reviewed_by": "reviewer-1",
            "uncertainties": (),
        }
    )
    review_path = tmp_path / "human-review.json"
    _write_review(review_path, human_review)

    report = run_docx_media_calibration_review(review_path, runner=FakeRunner())

    assert report.status is ExtractionStatus.PASS
    assert report.gate_reason is None
    assert report.production_recommended_threshold == 0.75


def test_review_rejects_false_human_provenance_and_source_tampering(tmp_path: Path) -> None:
    review = _review(tmp_path)
    with pytest.raises(ValidationError, match="human reviewer"):
        DocxMediaCalibrationReview.model_validate(
            review.model_dump(mode="python")
            | {"review_status": DocxMediaReviewStatus.HUMAN_CONFIRMED}
        )

    review_path = tmp_path / "tampered-review.json"
    _write_review(
        review_path,
        review.model_copy(update={"source_document_sha256": "0" * 64}),
    )
    with pytest.raises(DocxMediaCalibrationError) as raised:
        run_docx_media_calibration_review(review_path, runner=FakeRunner())
    assert raised.value.code is DocxMediaCalibrationErrorCode.SOURCE_DIGEST_MISMATCH


def test_cli_publishes_unknown_summary_without_visual_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    review = _review(tmp_path)
    review_path = tmp_path / "ai-review.json"
    _write_review(review_path, review)
    report = run_docx_media_calibration_review(review_path, runner=FakeRunner())
    output = tmp_path / "report.json"
    monkeypatch.setattr(cli, "run_docx_media_calibration_review", lambda _: report)

    result = cli.main(
        ["calibrate-docx-media-review", str(review_path), "--output", str(output)]
    )

    stdout = capsys.readouterr().out
    summary = json.loads(stdout)
    assert result == 3
    assert summary["status"] == "UNKNOWN"
    assert summary["gate_reason"] == "HUMAN_REVIEW_REQUIRED"
    assert "Строка" not in stdout
    assert output.exists()
