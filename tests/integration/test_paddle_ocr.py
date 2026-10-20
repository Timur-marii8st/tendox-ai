"""Опциональная реальная проверка русского PP-OCRv5 на raster-only PDF."""

from __future__ import annotations

import hashlib
import json
import os
from io import BytesIO
from pathlib import Path

import pytest

from procurement.documents import (
    DocumentRole,
    extract_document,
    map_blocks_to_requirements,
    run_ocr_calibration_manifest,
)
from procurement.documents.extraction import DocumentInput, ExtractionStatus
from procurement.documents.ocr import OcrEngineInput, build_ocr_derivative
from procurement.documents.paddle_ocr import PADDLE_OCR_ENGINE

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_PADDLE_OCR_INTEGRATION") != "1",
    reason="set RUN_PADDLE_OCR_INTEGRATION=1 and install the ocr extra",
)


def _font_path() -> Path:
    candidates = (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    pytest.skip("a Cyrillic TrueType font is required")


def _raster_pdf() -> bytes:
    image_module = pytest.importorskip("PIL.Image")
    draw_module = pytest.importorskip("PIL.ImageDraw")
    filter_module = pytest.importorskip("PIL.ImageFilter")
    font_module = pytest.importorskip("PIL.ImageFont")
    font = font_module.truetype(str(_font_path()), 44)
    pages = []
    for angle, color, blur in (
        (0.0, "black", 0.0),
        (2.5, "black", 0.0),
        (0.0, (125, 125, 125), 0.6),
    ):
        image = image_module.new("RGB", (1654, 1170), "white")
        draw = draw_module.Draw(image)
        draw.text((100, 130), "Гарантия не менее 24 мес.", fill=color, font=font)
        draw.text((100, 230), "Количество портов не менее 48 шт.", fill=color, font=font)
        if angle:
            image = image.rotate(
                angle,
                resample=image_module.Resampling.BICUBIC,
                fillcolor="white",
            )
        if blur:
            image = image.filter(filter_module.GaussianBlur(blur))
        pages.append(image)
    output = BytesIO()
    pages[0].save(
        output,
        "PDF",
        resolution=150.0,
        save_all=True,
        append_images=pages[1:],
    )
    return output.getvalue()


def test_real_ppocrv5_russian_scan_reaches_typed_requirements(tmp_path: Path) -> None:
    content = _raster_pdf()
    document_id = "golden-russian-scan"
    native = extract_document(
        DocumentInput(
            document_id=document_id,
            filename="scan.pdf",
            declared_media_type="application/pdf",
            content=content,
        )
    )
    assert native.status is ExtractionStatus.UNKNOWN

    source = OcrEngineInput(
        source_document_id=document_id,
        source_sha256=hashlib.sha256(content).hexdigest(),
        page_count=native.source_units_total,
    )
    expected = [
        {"page_number": page, "text": text}
        for page in range(1, 4)
        for text in (
            "Гарантия не менее 24 мес.",
            "Количество портов не менее 48 шт.",
        )
    ]
    scan_path = tmp_path / "scan.pdf"
    scan_path.write_bytes(content)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "ocr-calibration-v1",
                "dataset_id": "synthetic-ppocrv5-regression",
                "authorization_reference": "synthetic-test-data",
                "labeled_by": "test-suite",
                "labeled_at": "2026-09-13T12:00:00+03:00",
                "engine": PADDLE_OCR_ENGINE,
                "minimum_expected_lines": 6,
                "minimum_recall": 1.0,
                "baseline_threshold": 0.75,
                "samples": [
                    {
                        "sample_id": document_id,
                        "source_file": scan_path.name,
                        "source_sha256": source.source_sha256,
                        "expected": expected,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calibration_run = run_ocr_calibration_manifest(manifest_path)
    candidates = calibration_run.samples[0].candidates
    derivative = build_ocr_derivative(
        source,
        native,
        candidates,
        engine=PADDLE_OCR_ENGINE,
    )
    facts = map_blocks_to_requirements(
        derivative.blocks,
        document_role=DocumentRole.TENDER_REQUIREMENTS,
    )

    assert derivative.status is ExtractionStatus.PASS
    assert native.source_units_total == 3
    assert len(derivative.blocks) == 6
    assert all(block.provenance.confidence >= 0.75 for block in derivative.blocks)
    assert {(item.property, str(item.value)) for item in facts.requirements} == {
        ("warranty", "24"),
        ("ethernet_ports", "48"),
    }
    assert len(facts.requirements) == 6
    assert all(item.provenance.extractor.value == "ocr" for item in facts.requirements)

    calibration = calibration_run.calibration
    assert calibration.status is ExtractionStatus.PASS
    assert calibration.recommended_threshold == 0.75
