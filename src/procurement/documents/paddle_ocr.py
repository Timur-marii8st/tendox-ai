"""Локальный русский OCR на PaddleOCR 3.7 и PP-OCRv5.

Модели работают только с локальным временным PDF. Распознанный текст, bbox и
confidence преобразуются в нейтральные ``OcrCandidate``; семантические решения
остаются за детерминированным mapper/compliance.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib
import os
import threading
import warnings
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from PIL import Image, UnidentifiedImageError

from procurement.documents.ocr import (
    MAX_OCR_PAGES,
    OcrCandidate,
    OcrEngineError,
    OcrEngineInput,
    OcrSourceRejected,
)

PADDLE_OCR_ENGINE = "paddleocr/3.7.0:PP-OCRv5-ru"
MAX_OCR_IMAGE_BYTES = 10 * 1024 * 1024
MAX_OCR_IMAGE_DIMENSION = 12_000
MAX_OCR_IMAGE_PIXELS = 80_000_000
_MODEL_DIRECTORIES = {
    "doc_orientation_classify_model_dir": "PP-LCNet_x1_0_doc_ori",
    "doc_unwarping_model_dir": "UVDoc",
    "textline_orientation_model_dir": "PP-LCNet_x1_0_textline_ori",
    "text_detection_model_dir": "PP-OCRv5_server_det",
    "text_recognition_model_dir": "eslav_PP-OCRv5_mobile_rec",
}


@dataclass(frozen=True)
class _ValidatedSource:
    temporary_suffix: str
    image_input: bool


def _default_pipeline() -> Any:
    try:
        paddleocr = importlib.import_module("paddleocr")
        paddle_ocr = paddleocr.PaddleOCR
    except (AttributeError, ImportError) as error:
        raise OcrEngineError(
            "PaddleOCR runtime is unavailable; install with `uv sync --extra ocr`"
        ) from error

    options: dict[str, Any] = {
        "lang": "ru",
        "ocr_version": "PP-OCRv5",
        "device": os.environ.get("PADDLE_OCR_DEVICE", "cpu"),
        "use_doc_orientation_classify": True,
        "use_doc_unwarping": True,
        "use_textline_orientation": True,
    }
    model_root = os.environ.get("PADDLE_OCR_MODEL_ROOT")
    if model_root:
        options.pop("lang")
        options.pop("ocr_version")
        root = Path(model_root).resolve()
        missing = [name for name in _MODEL_DIRECTORIES.values() if not (root / name).is_dir()]
        if missing:
            raise OcrEngineError(
                "PADDLE_OCR_MODEL_ROOT does not contain required local models: "
                + ", ".join(sorted(missing))
            )
        for directory_option, name in _MODEL_DIRECTORIES.items():
            options[directory_option] = str(root / name)
            options[directory_option.replace("_dir", "_name")] = name
    try:
        return paddle_ocr(**options)
    except Exception as error:
        raise OcrEngineError("PaddleOCR pipeline initialization failed") from error


class PaddleOcrRunner:
    """Потокобезопасный lazy runner PP-OCRv5 для PDF и PNG/JPEG."""

    engine = PADDLE_OCR_ENGINE

    def __init__(self, pipeline_factory: Callable[[], Any] | None = None) -> None:
        self._pipeline_factory = pipeline_factory or _default_pipeline
        self._pipeline: Any | None = None
        self._lock = threading.Lock()

    def recognize(
        self,
        source: OcrEngineInput,
        *,
        content: bytes,
        media_type: str,
    ) -> tuple[OcrCandidate, ...]:
        """Распознать проверенный PDF/PNG/JPEG и вернуть строки с bbox/confidence."""
        raw_content = bytes(content)
        validated = self._validate_source(source, raw_content, media_type)
        digest = hashlib.sha256(raw_content).hexdigest()
        if not hmac.compare_digest(digest, source.source_sha256):
            raise OcrEngineError("source bytes do not match the immutable document digest")

        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(suffix=validated.temporary_suffix, delete=False) as temporary:
                temporary.write(raw_content)
                temporary_path = Path(temporary.name)
            with self._lock:
                pipeline = self._get_pipeline()
                results = tuple(
                    pipeline.predict(
                        str(temporary_path),
                        text_rec_score_thresh=0.0,
                    )
                )
        except OcrEngineError:
            raise
        except Exception as error:
            raise OcrEngineError("PaddleOCR inference failed") from error
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return self._candidates(
            results,
            source.page_count,
            image_input=validated.image_input,
        )

    @staticmethod
    def _validate_source(
        source: OcrEngineInput,
        content: bytes,
        media_type: str,
    ) -> _ValidatedSource:
        if media_type == "application/pdf":
            if not content.startswith(b"%PDF-"):
                raise OcrSourceRejected("PP-OCRv5 PDF signature is invalid")
            if source.page_count < 1 or source.page_count > MAX_OCR_PAGES:
                raise OcrSourceRejected(
                    f"OCR page count must be within [1, {MAX_OCR_PAGES}]"
                )
            return _ValidatedSource(temporary_suffix=".pdf", image_input=False)

        expected_format: str
        temporary_suffix: str
        if media_type == "image/png":
            expected_format = "PNG"
            temporary_suffix = ".png"
        elif media_type == "image/jpeg":
            expected_format = "JPEG"
            temporary_suffix = ".jpeg"
        else:
            raise OcrSourceRejected("PP-OCRv5 source media type is unsupported")
        if source.page_count != 1 or len(content) > MAX_OCR_IMAGE_BYTES:
            raise OcrSourceRejected("OCR image source exceeds resource limits")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(content), formats=[expected_format]) as image:
                    if image.format != expected_format:
                        raise OcrSourceRejected("OCR image format does not match media type")
                    width, height = image.size
                    if (
                        width > MAX_OCR_IMAGE_DIMENSION
                        or height > MAX_OCR_IMAGE_DIMENSION
                        or width * height > MAX_OCR_IMAGE_PIXELS
                    ):
                        raise OcrSourceRejected("OCR image dimensions exceed resource limits")
                    image.verify()
        except OcrSourceRejected:
            raise
        except (
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
            OSError,
            SyntaxError,
            UnidentifiedImageError,
            ValueError,
        ) as error:
            raise OcrSourceRejected("OCR image source is invalid") from error
        return _ValidatedSource(temporary_suffix=temporary_suffix, image_input=True)

    def _get_pipeline(self) -> Any:
        if self._pipeline is None:
            self._pipeline = self._pipeline_factory()
        return self._pipeline

    @classmethod
    def _candidates(
        cls,
        results: Iterable[object],
        expected_pages: int,
        *,
        image_input: bool = False,
    ) -> tuple[OcrCandidate, ...]:
        candidates: list[OcrCandidate] = []
        seen_pages: set[int] = set()
        try:
            for result in results:
                payload = cls._payload(result)
                page_index = payload.get("page_index")
                if page_index is None and image_input:
                    page_index = 0
                if not isinstance(page_index, int):
                    raise ValueError("page_index must be an integer")
                page_number = page_index + 1
                if not 1 <= page_number <= expected_pages or page_number in seen_pages:
                    raise ValueError("OCR page index is outside the immutable source")
                seen_pages.add(page_number)

                texts = cls._list(payload.get("rec_texts"), "rec_texts")
                scores = cls._list(payload.get("rec_scores"), "rec_scores")
                boxes = cls._list(payload.get("rec_boxes"), "rec_boxes")
                if not len(texts) == len(scores) == len(boxes):
                    raise ValueError("OCR text, score and bbox counts differ")
                for block_index, (text, score, box) in enumerate(
                    zip(texts, scores, boxes, strict=True)
                ):
                    if not isinstance(text, str) or not text.strip():
                        continue
                    coordinates = cls._list(box, "rec_box")
                    if len(coordinates) != 4:
                        raise ValueError("OCR bbox must contain four coordinates")
                    x_min, y_min, x_max, y_max = (int(value) for value in coordinates)
                    if x_min < 0 or y_min < 0 or x_max < x_min or y_max < y_min:
                        raise ValueError("OCR bbox coordinates are invalid")
                    candidates.append(
                        OcrCandidate(
                            page_number=page_number,
                            block_index=block_index,
                            text=text.strip(),
                            confidence=float(score),
                            locator=(
                                f"{'image' if image_input else 'page'} {page_number} bbox "
                                f"{x_min},{y_min},{x_max},{y_max}"
                            ),
                        )
                    )
        except (TypeError, ValueError) as error:
            raise OcrEngineError("PaddleOCR returned an invalid result envelope") from error
        return tuple(candidates)

    @staticmethod
    def _payload(result: object) -> Mapping[str, object]:
        raw: object
        if isinstance(result, Mapping):
            raw = result
        else:
            raw = getattr(result, "json", None)
            if callable(raw):
                raw = raw()
        if not isinstance(raw, Mapping):
            raise ValueError("OCR result must be a mapping")
        nested = raw.get("res", raw)
        if not isinstance(nested, Mapping):
            raise ValueError("OCR result payload must be a mapping")
        return nested

    @staticmethod
    def _list(value: object, field: str) -> list[Any]:
        if hasattr(value, "tolist"):
            value = value.tolist()
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"{field} must be a list")
        return list(value)
