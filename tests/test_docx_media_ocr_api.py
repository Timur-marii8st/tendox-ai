"""Tenant API for OCR of one exact image linked by a stored DOCX."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from io import BytesIO

import httpx
from docx import Document
from docx.shared import Inches
from PIL import Image

from procurement.api import create_app
from procurement.api.contracts import (
    DocumentRecord,
    DocxMediaOcrRecord,
    Principal,
    VersionConflict,
)
from procurement.documents import (
    DocumentInput,
    DocumentRole,
    OcrCandidate,
    OcrDerivative,
    extract_document,
)
from procurement.documents.ocr import OcrEngineInput

AUTH_A = {"Authorization": "Bearer tenant-a-token"}
AUTH_B = {"Authorization": "Bearer tenant-b-token"}
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class FakeAuthenticator:
    async def authenticate(self, credential: str) -> Principal | None:
        return {
            "tenant-a-token": Principal(company_id="tenant-a", actor_id="operator-a"),
            "tenant-b-token": Principal(company_id="tenant-b", actor_id="operator-b"),
        }.get(credential)


class RecordingOcrRunner:
    engine = "test-image-ocr/1"

    def __init__(self, candidates: tuple[OcrCandidate, ...]) -> None:
        self.candidates = candidates
        self.calls: list[tuple[OcrEngineInput, bytes, str]] = []

    def recognize(
        self,
        source: OcrEngineInput,
        *,
        content: bytes,
        media_type: str,
    ) -> tuple[OcrCandidate, ...]:
        self.calls.append((source, content, media_type))
        return self.candidates


class FakeDocxService:
    def __init__(self, document: DocumentRecord, content: bytes) -> None:
        self.documents = {("tenant-a", document.document_id): document}
        self.contents = {("tenant-a", document.document_id): content}
        self.ocr: dict[tuple[str, str], DocxMediaOcrRecord] = {}
        self.latest: dict[tuple[str, str, int], DocxMediaOcrRecord] = {}
        self.receipts: dict[tuple[str, str], tuple[str, DocxMediaOcrRecord]] = {}
        self.store_calls: list[dict[str, object]] = []

    async def get_document(
        self,
        *,
        company_id: str,
        document_id: str,
    ) -> DocumentRecord | None:
        return self.documents.get((company_id, document_id))

    async def get_document_content(
        self,
        *,
        company_id: str,
        document_id: str,
    ) -> bytes | None:
        return self.contents.get((company_id, document_id))

    async def store_docx_media_ocr_derivative(
        self,
        *,
        company_id: str,
        actor_id: str,
        ocr_id: str,
        source_document_id: str,
        media_index: int,
        archive_path: str,
        source_document_sha256: str,
        source_media_sha256: str,
        media_type: str,
        engine: str,
        threshold: float,
        result: OcrDerivative,
        mean_confidence: float | None,
        idempotency_key: str,
        request_digest: str,
    ) -> DocxMediaOcrRecord:
        receipt_key = (company_id, idempotency_key)
        replay = self.receipts.get(receipt_key)
        if replay is not None:
            if replay[0] != request_digest:
                raise VersionConflict
            return replay[1]
        record = DocxMediaOcrRecord(
            ocr_id=ocr_id,
            source_document_id=source_document_id,
            media_index=media_index,
            archive_path=archive_path,
            source_document_sha256=source_document_sha256,
            source_media_sha256=source_media_sha256,
            media_type=media_type,
            engine=engine,
            threshold=threshold,
            result=result,
            mean_confidence=mean_confidence,
            created_at=datetime.now(UTC),
        )
        self.ocr[(company_id, ocr_id)] = record
        self.latest[(company_id, source_document_id, media_index)] = record
        self.receipts[receipt_key] = (request_digest, record)
        self.store_calls.append({"actor_id": actor_id, "archive_path": archive_path})
        return record

    async def get_docx_media_ocr_derivative(
        self,
        *,
        company_id: str,
        ocr_id: str,
    ) -> DocxMediaOcrRecord | None:
        return self.ocr.get((company_id, ocr_id))

    async def get_latest_ocr_for_docx_media(
        self,
        *,
        company_id: str,
        source_document_id: str,
        media_index: int,
    ) -> DocxMediaOcrRecord | None:
        return self.latest.get((company_id, source_document_id, media_index))


def request(app: object, method: str, url: str, **kwargs: object) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, url, **kwargs)

    return asyncio.run(send())


def pictured_docx() -> tuple[bytes, bytes]:
    image_output = BytesIO()
    Image.new("RGB", (80, 40), color="white").save(image_output, format="PNG")
    image = image_output.getvalue()
    output = BytesIO()
    document = Document()
    document.add_picture(BytesIO(image), width=Inches(1))
    document.save(output)
    return output.getvalue(), image


def document_record(content: bytes) -> DocumentRecord:
    source = DocumentInput(
        document_id="doc-1",
        filename="requirements.docx",
        declared_media_type=DOCX_MEDIA_TYPE,
        content=content,
    )
    return DocumentRecord(
        document_id=source.document_id,
        original_filename=source.filename,
        media_type=source.declared_media_type,
        document_role=DocumentRole.TENDER_REQUIREMENTS,
        byte_size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        extraction=extract_document(source),
        created_at=datetime.now(UTC),
    )


def test_docx_media_ocr_preserves_exact_evidence_and_tenant_scope() -> None:
    content, image = pictured_docx()
    stored_document = document_record(content)
    service = FakeDocxService(stored_document, content)
    runner = RecordingOcrRunner(
        (
            OcrCandidate(
                page_number=1,
                block_index=0,
                text="Гарантия 24 месяца",
                confidence=0.94,
                locator="image 1 bbox [1,2,30,10]",
            ),
        )
    )
    app = create_app(service, FakeAuthenticator(), ocr_runner=runner)  # type: ignore[arg-type]
    endpoint = "/v1/documents/doc-1/media/0/ocr"
    headers = {**AUTH_A, "Idempotency-Key": "docx-media-ocr"}

    first = request(app, "POST", endpoint, headers=headers, json={"threshold": 0.75})
    replay = request(app, "POST", endpoint, headers=headers, json={"threshold": 0.75})
    conflict = request(app, "POST", endpoint, headers=headers, json={"threshold": 0.8})

    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    payload = first.json()
    assert payload["source_document_sha256"] == stored_document.sha256
    assert payload["source_media_sha256"] == hashlib.sha256(image).hexdigest()
    assert payload["media_type"] == "image/png"
    assert payload["result"]["source_document_id"] == "doc-1:media:0"
    assert payload["result"]["status"] == "PASS"
    assert payload["result"]["blocks"][0]["provenance"]["locator"] == (
        'DOCX media "word/media/image1.png" :: image 1 bbox [1,2,30,10]'
    )
    assert "content" not in first.text
    assert runner.calls[0][1:] == (image, "image/png")
    assert service.store_calls == [
        {"actor_id": "operator-a", "archive_path": "word/media/image1.png"}
    ]
    assert conflict.status_code == 409

    latest = request(app, "GET", f"{endpoint}/latest", headers=AUTH_A)
    by_id = request(
        app,
        "GET",
        f"/v1/document-docx-media-ocr/{payload['ocr_id']}",
        headers=AUTH_A,
    )
    foreign = request(app, "GET", f"{endpoint}/latest", headers=AUTH_B)
    assert latest.status_code == by_id.status_code == 200
    assert latest.json() == by_id.json() == payload
    assert foreign.status_code == 404


def test_docx_media_ocr_fails_closed_for_missing_or_tampered_source() -> None:
    content, _ = pictured_docx()
    stored_document = document_record(content)
    service = FakeDocxService(stored_document, content)
    runner = RecordingOcrRunner(())
    app = create_app(service, FakeAuthenticator(), ocr_runner=runner)  # type: ignore[arg-type]

    missing = request(
        app,
        "POST",
        "/v1/documents/doc-1/media/9/ocr",
        headers={**AUTH_A, "Idempotency-Key": "missing-media"},
        json={},
    )
    service.contents[("tenant-a", "doc-1")] += b"tampered"
    tampered = request(
        app,
        "POST",
        "/v1/documents/doc-1/media/0/ocr",
        headers={**AUTH_A, "Idempotency-Key": "tampered-media"},
        json={},
    )

    assert missing.status_code == 404
    assert tampered.status_code == 500
    assert tampered.json() == {"detail": "internal_error"}
    assert runner.calls == []
    assert service.store_calls == []
