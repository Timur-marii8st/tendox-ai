"""Контракт адаптера PaddleOCR без загрузки тяжёлой модели в обычном test gate."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Any

import pytest

from procurement.documents.ocr import OcrEngineError, OcrEngineInput, OcrSourceRejected
from procurement.documents.paddle_ocr import PADDLE_OCR_ENGINE, PaddleOcrRunner

_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class FakePipeline:
    def __init__(
        self,
        results: tuple[object, ...],
        *,
        expected_content: bytes = b"%PDF-synthetic",
    ) -> None:
        self.results = results
        self.expected_content = expected_content
        self.path: Path | None = None
        self.path_suffix: str | None = None
        self.threshold: float | None = None

    def predict(self, path: str, *, text_rec_score_thresh: float) -> tuple[object, ...]:
        self.path = Path(path)
        self.path_suffix = self.path.suffix
        self.threshold = text_rec_score_thresh
        assert self.path.read_bytes() == self.expected_content
        return self.results


def _source(content: bytes = b"%PDF-synthetic", pages: int = 1) -> OcrEngineInput:
    return OcrEngineInput(
        source_document_id="scan-1",
        source_sha256=hashlib.sha256(content).hexdigest(),
        page_count=pages,
    )


def test_paddle_adapter_preserves_text_score_bbox_and_removes_temporary_file() -> None:
    pipeline = FakePipeline(
        (
            {
                "res": {
                    "page_index": 0,
                    "rec_texts": ["Гарантия не менее 24 мес.", "  "],
                    "rec_scores": [0.98, 0.99],
                    "rec_boxes": [[10, 20, 300, 60], [1, 2, 3, 4]],
                }
            },
        )
    )
    runner = PaddleOcrRunner(lambda: pipeline)

    candidates = runner.recognize(
        _source(),
        content=b"%PDF-synthetic",
        media_type="application/pdf",
    )

    assert runner.engine == PADDLE_OCR_ENGINE
    assert len(candidates) == 1
    assert candidates[0].text == "Гарантия не менее 24 мес."
    assert candidates[0].confidence == pytest.approx(0.98)
    assert candidates[0].locator == "page 1 bbox 10,20,300,60"
    assert pipeline.threshold == 0.0
    assert pipeline.path is not None and not pipeline.path.exists()


def test_paddle_adapter_accepts_verified_png_and_normalizes_missing_page_index() -> None:
    pipeline = FakePipeline(
        (
            {
                "res": {
                    "page_index": None,
                    "rec_texts": ["Текст изображения"],
                    "rec_scores": [0.96],
                    "rec_boxes": [[1, 2, 30, 40]],
                }
            },
        ),
        expected_content=_TINY_PNG,
    )
    runner = PaddleOcrRunner(lambda: pipeline)

    candidates = runner.recognize(
        _source(_TINY_PNG),
        content=_TINY_PNG,
        media_type="image/png",
    )

    assert candidates[0].page_number == 1
    assert candidates[0].locator == "image 1 bbox 1,2,30,40"
    assert pipeline.path_suffix == ".png"
    assert pipeline.path is not None and not pipeline.path.exists()


def test_paddle_adapter_rejects_invalid_or_multi_page_image_source() -> None:
    runner = PaddleOcrRunner(lambda: pytest.fail("pipeline must not initialize"))

    with pytest.raises(OcrSourceRejected):
        runner.recognize(
            _source(b"not-an-image"),
            content=b"not-an-image",
            media_type="image/png",
        )
    with pytest.raises(OcrSourceRejected):
        runner.recognize(
            _source(_TINY_PNG, pages=2),
            content=_TINY_PNG,
            media_type="image/png",
        )


@pytest.mark.parametrize(
    ("source", "content", "media_type"),
    [
        (_source(), b"%PDF-other", "application/pdf"),
        (_source(), b"%PDF-synthetic", "application/octet-stream"),
        (_source(pages=201), b"%PDF-synthetic", "application/pdf"),
    ],
)
def test_paddle_adapter_rejects_untrusted_or_excessive_source(
    source: OcrEngineInput,
    content: bytes,
    media_type: str,
) -> None:
    runner = PaddleOcrRunner(lambda: pytest.fail("pipeline must not initialize"))

    error = OcrEngineError if content == b"%PDF-other" else OcrSourceRejected
    with pytest.raises(error):
        runner.recognize(source, content=content, media_type=media_type)


@pytest.mark.parametrize(
    "payload",
    [
        {"res": {"page_index": 0, "rec_texts": ["text"], "rec_scores": [], "rec_boxes": []}},
        {"res": {"page_index": 2, "rec_texts": [], "rec_scores": [], "rec_boxes": []}},
        {
            "res": {
                "page_index": 0,
                "rec_texts": ["text"],
                "rec_scores": [1.2],
                "rec_boxes": [[0, 0, 1, 1]],
            }
        },
    ],
)
def test_paddle_adapter_rejects_malformed_engine_output(payload: dict[str, Any]) -> None:
    runner = PaddleOcrRunner(lambda: FakePipeline((payload,)))

    with pytest.raises(OcrEngineError, match="invalid result envelope"):
        runner.recognize(
            _source(),
            content=b"%PDF-synthetic",
            media_type="application/pdf",
        )
