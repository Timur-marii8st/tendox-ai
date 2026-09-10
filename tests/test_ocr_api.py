"""API-регрессии OCR-производных версий: tenant-scope, replay и честный UNKNOWN."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

import httpx
import pytest
from pypdf import PdfWriter

from procurement.api import create_app
from procurement.api.contracts import (
    DocumentRecord,
    OcrDerivativeRecord,
    Principal,
    VersionConflict,
)
from procurement.documents import ExtractionResult
from procurement.documents.ocr import OcrDerivative
from procurement.domain.cases import ProcurementCase


class FakeAuthenticator:
    async def authenticate(self, credential: str) -> Principal | None:
        return {
            "tenant-a-token": Principal(company_id="demo-company", actor_id="operator-a"),
            "tenant-b-token": Principal(company_id="other-company", actor_id="operator-b"),
        }.get(credential)


class FakeOcrService:
    """Минимальный in-memory сервис с идемпотентностью OCR-записей."""

    def __init__(self) -> None:
        self.cases: dict[tuple[str, str, int], ProcurementCase] = {}
        self.documents: dict[tuple[str, str], DocumentRecord] = {}
        self.ocr: dict[tuple[str, str], OcrDerivativeRecord] = {}
        self.ocr_receipts: dict[tuple[str, str], tuple[str, OcrDerivativeRecord]] = {}

    async def create_case(self, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def get_case(self, **kwargs: Any) -> Any:
        return None

    async def list_cases(self, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def get_latest_evaluation(self, **kwargs: Any) -> Any:
        return None

    async def record_evaluation(self, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def store_document(
        self,
        *,
        company_id: str,
        actor_id: str,
        document_id: str,
        original_filename: str,
        media_type: str,
        content: bytes,
        extraction: ExtractionResult,
        idempotency_key: str,
        request_digest: str,
    ) -> DocumentRecord:
        record = DocumentRecord(
            document_id=document_id,
            original_filename=original_filename,
            media_type=media_type,
            byte_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            extraction=extraction,
            created_at=datetime.now(UTC),
        )
        self.documents[(company_id, document_id)] = record
        return record

    async def get_document(
        self, *, company_id: str, document_id: str
    ) -> DocumentRecord | None:
        return self.documents.get((company_id, document_id))

    async def store_ocr_derivative(
        self,
        *,
        company_id: str,
        actor_id: str,
        ocr_id: str,
        source_document_id: str,
        engine: str,
        threshold: float,
        result: OcrDerivative,
        mean_confidence: float | None,
        idempotency_key: str,
        request_digest: str,
    ) -> OcrDerivativeRecord:
        key = (company_id, idempotency_key)
        if key in self.ocr_receipts:
            old_digest, old_record = self.ocr_receipts[key]
            if old_digest != request_digest:
                raise VersionConflict
            return old_record
        record = OcrDerivativeRecord(
            ocr_id=ocr_id,
            source_document_id=source_document_id,
            engine=engine,
            threshold=threshold,
            result=result,
            mean_confidence=mean_confidence,
            created_at=datetime.now(UTC),
        )
        self.ocr[(company_id, ocr_id)] = record
        self.ocr_receipts[key] = (request_digest, record)
        return record

    async def get_ocr_derivative(
        self, *, company_id: str, ocr_id: str
    ) -> OcrDerivativeRecord | None:
        return self.ocr.get((company_id, ocr_id))

    async def get_latest_ocr_for_document(
        self, *, company_id: str, source_document_id: str
    ) -> OcrDerivativeRecord | None:
        items = [
            record
            for (tenant, _), record in self.ocr.items()
            if tenant == company_id and record.source_document_id == source_document_id
        ]
        if not items:
            return None
        return sorted(items, key=lambda record: record.created_at)[-1]


@pytest.fixture
def service() -> FakeOcrService:
    return FakeOcrService()


@pytest.fixture
def app(service: FakeOcrService):
    return create_app(service, FakeAuthenticator())  # type: ignore[arg-type]


def call(app: object, method: str, url: str, **kwargs: object) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, url, **kwargs)

    return asyncio.run(send())


def blank_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


AUTH_A = {"Authorization": "Bearer tenant-a-token"}
AUTH_B = {"Authorization": "Bearer tenant-b-token"}


def upload_blank_pdf(app: object, key: str = "doc-001") -> str:
    response = call(
        app,
        "POST",
        "/v1/documents",
        headers={**AUTH_A, "Idempotency-Key": key},
        files={"file": ("scan.pdf", blank_pdf_bytes(), "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()["document_id"]


def test_ocr_derivative_is_unknown_without_facts_and_bytes_never_leak() -> None:
    transport_app = create_app(FakeOcrService(), FakeAuthenticator())  # type: ignore[arg-type]
    document_id = upload_blank_pdf(transport_app)
    response = call(
        transport_app,
        "POST",
        f"/v1/documents/{document_id}/ocr",
        headers={**AUTH_A, "Idempotency-Key": "ocr-001"},
        json={},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["source_document_id"] == document_id
    assert payload["result"]["status"] == "UNKNOWN"
    assert payload["result"]["reasons"] == ["OCR_REQUIRED"]
    assert payload["result"]["blocks"] == []
    assert payload["result"]["extractor_literal"] == "ocr"
    assert "content" not in payload


def test_ocr_latest_and_direct_get_return_same_record() -> None:
    transport_app = create_app(FakeOcrService(), FakeAuthenticator())  # type: ignore[arg-type]
    document_id = upload_blank_pdf(transport_app)
    created = call(
        transport_app,
        "POST",
        f"/v1/documents/{document_id}/ocr",
        headers={**AUTH_A, "Idempotency-Key": "ocr-010"},
        json={"engine": "local-stub/0.1", "threshold": 0.75},
    )
    assert created.status_code == 201, created.text
    ocr_id = created.json()["ocr_id"]
    latest = call(
        transport_app, "GET", f"/v1/documents/{document_id}/ocr/latest", headers=AUTH_A
    )
    assert latest.status_code == 200, latest.text
    assert latest.json()["ocr_id"] == ocr_id
    direct = call(transport_app, "GET", f"/v1/document-ocr/{ocr_id}", headers=AUTH_A)
    assert direct.status_code == 200, direct.text
    assert direct.json()["ocr_id"] == ocr_id


def test_ocr_replay_returns_same_record_and_digest_conflict_is_409() -> None:
    transport_app = create_app(FakeOcrService(), FakeAuthenticator())  # type: ignore[arg-type]
    document_id = upload_blank_pdf(transport_app)
    first = call(
        transport_app,
        "POST",
        f"/v1/documents/{document_id}/ocr",
        headers={**AUTH_A, "Idempotency-Key": "ocr-replay"},
        json={"threshold": 0.75},
    )
    assert first.status_code == 201, first.text
    second = call(
        transport_app,
        "POST",
        f"/v1/documents/{document_id}/ocr",
        headers={**AUTH_A, "Idempotency-Key": "ocr-replay"},
        json={"threshold": 0.75},
    )
    assert second.status_code == 201, second.text
    assert second.json()["ocr_id"] == first.json()["ocr_id"]
    conflict = call(
        transport_app,
        "POST",
        f"/v1/documents/{document_id}/ocr",
        headers={**AUTH_A, "Idempotency-Key": "ocr-replay"},
        json={"threshold": 0.5},
    )
    assert conflict.status_code == 409, conflict.text


def test_ocr_missing_and_cross_tenant_are_identical_404() -> None:
    transport_app = create_app(FakeOcrService(), FakeAuthenticator())  # type: ignore[arg-type]
    document_id = upload_blank_pdf(transport_app)
    missing_post = call(
        transport_app,
        "POST",
        "/v1/documents/no-such-doc/ocr",
        headers={**AUTH_A, "Idempotency-Key": "ocr-missing"},
        json={},
    )
    assert missing_post.status_code == 404
    foreign_post = call(
        transport_app,
        "POST",
        f"/v1/documents/{document_id}/ocr",
        headers={**AUTH_B, "Idempotency-Key": "ocr-foreign"},
        json={},
    )
    assert foreign_post.status_code == 404
    foreign_latest = call(
        transport_app, "GET", f"/v1/documents/{document_id}/ocr/latest", headers=AUTH_B
    )
    assert foreign_latest.status_code == 404
    assert missing_post.json() == foreign_latest.json() == {"detail": "not_found"}


def test_ocr_invalid_threshold_is_422() -> None:
    transport_app = create_app(FakeOcrService(), FakeAuthenticator())  # type: ignore[arg-type]
    document_id = upload_blank_pdf(transport_app)
    response = call(
        transport_app,
        "POST",
        f"/v1/documents/{document_id}/ocr",
        headers={**AUTH_A, "Idempotency-Key": "ocr-bad"},
        json={"threshold": 2.0},
    )
    assert response.status_code == 422, response.text
