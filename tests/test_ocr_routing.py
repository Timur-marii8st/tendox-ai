"""Unsafe local OCR is rejected without rejecting the procurement document."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

import procurement.cli as cli
from procurement.documents.docx_media_calibration import (
    DocxMediaCalibrationGateReason,
    DocxMediaCalibrationRunReport,
    DocxMediaReviewerType,
    DocxMediaReviewStatus,
)
from procurement.documents.extraction import ExtractionStatus
from procurement.documents.ocr_calibration import (
    CalibrationReason,
    OcrCalibrationReport,
    OcrCalibrationSample,
)
from procurement.documents.ocr_routing import (
    LocalOcrDisposition,
    OcrNextAction,
    OcrRoutingReason,
    VisionDraftStatus,
    VisionEscalationConfig,
    route_docx_media_ocr,
)

SOURCE_DOCUMENT_SHA = "1" * 64
SOURCE_MEDIA_SHA = "2" * 64
SOURCE_REPORT_SHA = "3" * 64
ENGINE = "paddleocr/3.7.0:PP-OCRv5-ru"


def _report(*, passing: bool = False) -> DocxMediaCalibrationRunReport:
    sample = OcrCalibrationSample(
        sample_id="source:media:0",
        source_sha256=SOURCE_MEDIA_SHA,
        expected=(),
        candidates=(),
    )
    calibration = OcrCalibrationReport(
        engine=ENGINE,
        status=ExtractionStatus.PASS if passing else ExtractionStatus.FAIL,
        reason=None if passing else CalibrationReason.NO_SAFE_THRESHOLD,
        recommended_threshold=0.75 if passing else None,
        minimum_recall=0.9,
        minimum_expected_lines=20,
        samples_total=1,
        expected_lines_total=20,
        sample_ids=(sample.sample_id,),
        source_sha256=(SOURCE_MEDIA_SHA,),
        observations=(),
    )
    return DocxMediaCalibrationRunReport(
        review_sha256="4" * 64,
        review_status=(
            DocxMediaReviewStatus.HUMAN_CONFIRMED
            if passing
            else DocxMediaReviewStatus.AI_REVIEWED_REQUIRES_HUMAN_CONFIRMATION
        ),
        reviewer_type=(
            DocxMediaReviewerType.HUMAN
            if passing
            else DocxMediaReviewerType.AI_VISUAL_REVIEW
        ),
        reviewed_by="reviewer",
        source_document_sha256=SOURCE_DOCUMENT_SHA,
        source_media_sha256=SOURCE_MEDIA_SHA,
        sample=sample,
        calibration=calibration,
        status=ExtractionStatus.PASS if passing else ExtractionStatus.UNKNOWN,
        gate_reason=(
            None
            if passing
            else DocxMediaCalibrationGateReason.HUMAN_REVIEW_REQUIRED
        ),
        production_recommended_threshold=0.75 if passing else None,
    )


def test_failed_calibration_rejects_method_but_keeps_document_unknown() -> None:
    decision = route_docx_media_ocr(
        _report(),
        source_report_sha256=SOURCE_REPORT_SHA,
        created_at=datetime.now(UTC),
    )

    assert decision.document_status is ExtractionStatus.UNKNOWN
    assert decision.disposition is LocalOcrDisposition.REJECT_LOCAL_OCR
    assert decision.reason is OcrRoutingReason.LOCAL_OCR_NO_SAFE_THRESHOLD
    assert decision.next_actions == (
        OcrNextAction.REQUEST_NATIVE_SOURCE,
        OcrNextAction.PREPARE_VISION_API_APPROVAL,
    )
    assert decision.vision_escalation is None


def test_vision_escalation_is_an_exact_non_executable_draft() -> None:
    config = VisionEscalationConfig(
        provider="approved-provider",
        model="vision-model-v1",
        endpoint="https://vision.example.test/v1/analyze",
        retention_policy_reference="security-review-42",
    )
    decision = route_docx_media_ocr(
        _report(),
        source_report_sha256=SOURCE_REPORT_SHA,
        created_at=datetime.now(UTC),
        vision=config,
    )

    draft = decision.vision_escalation
    assert draft is not None
    assert draft.status is VisionDraftStatus.APPROVAL_REQUIRED
    assert draft.send_allowed is False
    assert draft.payload["source_media_sha256"] == SOURCE_MEDIA_SHA
    assert "prompt" in draft.payload
    assert len(draft.payload_sha256) == 64

    changed = route_docx_media_ocr(
        _report(),
        source_report_sha256=SOURCE_REPORT_SHA,
        created_at=datetime.now(UTC),
        vision=config.model_copy(update={"model": "vision-model-v2"}),
    )
    assert changed.vision_escalation is not None
    assert changed.vision_escalation.payload_sha256 != draft.payload_sha256


def test_confirmed_safe_calibration_uses_local_ocr_without_external_draft() -> None:
    decision = route_docx_media_ocr(
        _report(passing=True),
        source_report_sha256=SOURCE_REPORT_SHA,
        created_at=datetime.now(UTC),
    )

    assert decision.document_status is ExtractionStatus.PASS
    assert decision.disposition is LocalOcrDisposition.USE_LOCAL_OCR
    assert decision.next_actions == (OcrNextAction.USE_LOCAL_OCR,)
    assert decision.vision_escalation is None


def test_vision_configuration_requires_https() -> None:
    with pytest.raises(ValidationError, match="https"):
        VisionEscalationConfig(
            provider="provider",
            model="model",
            endpoint="http://vision.example.test/v1/analyze",
            retention_policy_reference="security-review",
        )


def test_cli_publishes_private_routing_without_document_text(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report_path = tmp_path / "calibration.json"
    raw = _report().model_dump_json(indent=2)
    report_path.write_text(raw, encoding="utf-8")
    output = tmp_path / "routing.json"

    result = cli.main(
        [
            "route-docx-media-ocr",
            str(report_path),
            "--output",
            str(output),
            "--at",
            "2026-09-15T12:00:00+03:00",
        ]
    )

    summary = json.loads(capsys.readouterr().out)
    assert result == 3
    assert summary["document_status"] == "UNKNOWN"
    assert summary["disposition"] == "REJECT_LOCAL_OCR"
    assert summary["vision_draft_status"] is None
    assert summary["source_calibration_report_sha256"] == hashlib.sha256(
        report_path.read_bytes()
    ).hexdigest()
    assert output.exists()
