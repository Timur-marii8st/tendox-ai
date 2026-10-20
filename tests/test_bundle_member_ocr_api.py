"""OCR одного ZIP-участника сохраняет exact evidence и tenant isolation."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
from docx import Document
from pypdf import PdfWriter

from procurement.api import create_app
from procurement.api.contracts import (
    BundleMemberOcrRecord,
    DocumentBundleRecord,
    Principal,
    VersionConflict,
)
from procurement.documents import (
    DocumentBundleResult,
    DocumentRole,
    OcrCandidate,
    OcrDerivative,
)
from procurement.documents.ocr import OcrEngineInput

AUTH_A = {"Authorization": "Bearer tenant-a-token"}
AUTH_B = {"Authorization": "Bearer tenant-b-token"}


class FakeAuthenticator:
    async def authenticate(self, credential: str) -> Principal | None:
        return {
            "tenant-a-token": Principal(company_id="tenant-a", actor_id="operator-a"),
            "tenant-b-token": Principal(company_id="tenant-b", actor_id="operator-b"),
        }.get(credential)


class RecordingOcrRunner:
    engine = "test-ocr/1"

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


class FakeBundleService:
    def __init__(self) -> None:
        self.bundles: dict[tuple[str, str], DocumentBundleRecord] = {}
        self.contents: dict[tuple[str, str], bytes] = {}
        self.ocr: dict[tuple[str, str], BundleMemberOcrRecord] = {}
        self.latest: dict[tuple[str, str, int], BundleMemberOcrRecord] = {}
        self.ocr_receipts: dict[tuple[str, str], tuple[str, BundleMemberOcrRecord]] = {}
        self.ocr_calls: list[dict[str, object]] = []

    async def store_document_bundle(
        self,
        *,
        company_id: str,
        actor_id: str,
        bundle_id: str,
        original_filename: str,
        media_type: str,
        document_role: DocumentRole,
        content: bytes,
        result: DocumentBundleResult,
        idempotency_key: str,
        request_digest: str,
    ) -> DocumentBundleRecord:
        _ = (actor_id, idempotency_key, request_digest)
        record = DocumentBundleRecord(
            bundle_id=bundle_id,
            original_filename=original_filename,
            media_type=media_type,
            document_role=document_role,
            byte_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            result=result,
            created_at=datetime.now(UTC),
        )
        self.bundles[(company_id, bundle_id)] = record
        self.contents[(company_id, bundle_id)] = content
        return record

    async def get_document_bundle(
        self,
        *,
        company_id: str,
        bundle_id: str,
    ) -> DocumentBundleRecord | None:
        return self.bundles.get((company_id, bundle_id))

    async def get_document_bundle_content(
        self,
        *,
        company_id: str,
        bundle_id: str,
    ) -> bytes | None:
        return self.contents.get((company_id, bundle_id))

    async def store_bundle_member_ocr_derivative(
        self,
        *,
        company_id: str,
        actor_id: str,
        ocr_id: str,
        source_bundle_id: str,
        member_index: int,
        archive_path: str,
        source_member_sha256: str,
        engine: str,
        threshold: float,
        result: OcrDerivative,
        mean_confidence: float | None,
        idempotency_key: str,
        request_digest: str,
    ) -> BundleMemberOcrRecord:
        receipt_key = (company_id, idempotency_key)
        replay = self.ocr_receipts.get(receipt_key)
        if replay is not None:
            if replay[0] != request_digest:
                raise VersionConflict
            return replay[1]
        record = BundleMemberOcrRecord(
            ocr_id=ocr_id,
            source_bundle_id=source_bundle_id,
            member_index=member_index,
            archive_path=archive_path,
            source_member_sha256=source_member_sha256,
            engine=engine,
            threshold=threshold,
            result=result,
            mean_confidence=mean_confidence,
            created_at=datetime.now(UTC),
        )
        self.ocr[(company_id, ocr_id)] = record
        self.latest[(company_id, source_bundle_id, member_index)] = record
        self.ocr_receipts[receipt_key] = (request_digest, record)
        self.ocr_calls.append(
            {
                "company_id": company_id,
                "actor_id": actor_id,
                "source_bundle_id": source_bundle_id,
                "member_index": member_index,
                "archive_path": archive_path,
                "source_member_sha256": source_member_sha256,
            }
        )
        return record

    async def get_bundle_member_ocr_derivative(
        self,
        *,
        company_id: str,
        ocr_id: str,
    ) -> BundleMemberOcrRecord | None:
        return self.ocr.get((company_id, ocr_id))

    async def get_latest_ocr_for_bundle_member(
        self,
        *,
        company_id: str,
        source_bundle_id: str,
        member_index: int,
    ) -> BundleMemberOcrRecord | None:
        return self.latest.get((company_id, source_bundle_id, member_index))


def request(app: object, method: str, url: str, **kwargs: object) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, url, **kwargs)

    return asyncio.run(send())


def blank_pdf() -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.write(output)
    return output.getvalue()


def docx() -> bytes:
    output = BytesIO()
    document = Document()
    document.add_paragraph("Гарантия не менее 24 мес.")
    document.save(output)
    return output.getvalue()


def bundle(entries: tuple[tuple[str, bytes], ...]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return output.getvalue()


def upload_bundle(
    app: object,
    content: bytes,
    *,
    key: str,
    auth: dict[str, str] = AUTH_A,
) -> dict[str, object]:
    response = request(
        app,
        "POST",
        "/v1/document-bundles",
        headers={**auth, "Idempotency-Key": key},
        files={"file": ("tender.zip", content, "application/zip")},
        data={"document_role": DocumentRole.TENDER_REQUIREMENTS.value},
    )
    assert response.status_code == 201
    return response.json()


def test_bundle_member_ocr_uses_exact_pdf_and_preserves_archive_provenance() -> None:
    pdf = blank_pdf()
    service = FakeBundleService()
    runner = RecordingOcrRunner(
        (
            OcrCandidate(
                page_number=1,
                block_index=0,
                text="Гарантия 24 месяца",
                confidence=0.94,
                locator="page 1 bbox [1,2,3,4]",
            ),
        )
    )
    app = create_app(service, FakeAuthenticator(), ocr_runner=runner)
    uploaded = upload_bundle(app, bundle((("scans/spec.pdf", pdf),)), key="bundle-ocr")
    bundle_id = str(uploaded["bundle_id"])
    endpoint = f"/v1/document-bundles/{bundle_id}/members/0/ocr"

    response = request(
        app,
        "POST",
        endpoint,
        headers={**AUTH_A, "Idempotency-Key": "member-ocr"},
        json={"threshold": 0.75},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["source_bundle_id"] == bundle_id
    assert payload["member_index"] == 0
    assert payload["archive_path"] == "scans/spec.pdf"
    assert payload["source_member_sha256"] == hashlib.sha256(pdf).hexdigest()
    assert payload["result"]["source_document_id"] == f"{bundle_id}:member:0"
    assert payload["result"]["status"] == "PASS"
    provenance = payload["result"]["blocks"][0]["provenance"]
    assert provenance["document_id"] == f"{bundle_id}:member:0"
    assert provenance["locator"] == (
        'archive member "scans/spec.pdf" :: page 1 bbox [1,2,3,4]'
    )
    assert runner.calls[0][1:] == (pdf, "application/pdf")
    assert service.ocr_calls[0]["actor_id"] == "operator-a"

    latest = request(app, "GET", f"{endpoint}/latest", headers=AUTH_A)
    by_id = request(
        app,
        "GET",
        f"/v1/document-bundle-member-ocr/{payload['ocr_id']}",
        headers=AUTH_A,
    )
    assert latest.status_code == by_id.status_code == 200
    assert latest.json() == by_id.json() == payload


def test_bundle_member_ocr_empty_candidates_stay_unknown_and_replay_is_idempotent() -> None:
    service = FakeBundleService()
    runner = RecordingOcrRunner(())
    app = create_app(service, FakeAuthenticator(), ocr_runner=runner)
    uploaded = upload_bundle(app, bundle((("scan.pdf", blank_pdf()),)), key="empty-bundle")
    endpoint = f"/v1/document-bundles/{uploaded['bundle_id']}/members/0/ocr"
    headers = {**AUTH_A, "Idempotency-Key": "empty-member-ocr"}

    first = request(app, "POST", endpoint, headers=headers, json={"threshold": 0.75})
    replay = request(app, "POST", endpoint, headers=headers, json={"threshold": 0.75})
    conflict = request(app, "POST", endpoint, headers=headers, json={"threshold": 0.8})

    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert first.json()["result"]["status"] == "UNKNOWN"
    assert first.json()["result"]["reasons"] == ["OCR_REQUIRED"]
    assert conflict.status_code == 409
    assert len(service.ocr_calls) == 1


def test_bundle_member_ocr_rejects_non_pdf_and_hides_foreign_or_missing_members() -> None:
    service = FakeBundleService()
    runner = RecordingOcrRunner(())
    app = create_app(service, FakeAuthenticator(), ocr_runner=runner)
    non_pdf = upload_bundle(app, bundle((("requirements.docx", docx()),)), key="docx-bundle")
    foreign = upload_bundle(
        app,
        bundle((("scan.pdf", blank_pdf()),)),
        key="foreign-bundle",
        auth=AUTH_B,
    )
    precise = upload_bundle(
        app,
        bundle((("scan.pdf", blank_pdf()),)),
        key="precision-bundle",
    )

    unsupported = request(
        app,
        "POST",
        f"/v1/document-bundles/{non_pdf['bundle_id']}/members/0/ocr",
        headers={**AUTH_A, "Idempotency-Key": "docx-ocr"},
        json={},
    )
    foreign_response = request(
        app,
        "POST",
        f"/v1/document-bundles/{foreign['bundle_id']}/members/0/ocr",
        headers={**AUTH_A, "Idempotency-Key": "foreign-ocr"},
        json={},
    )
    missing = request(
        app,
        "POST",
        "/v1/document-bundles/not-there/members/0/ocr",
        headers={**AUTH_A, "Idempotency-Key": "missing-ocr"},
        json={},
    )
    out_of_range = request(
        app,
        "POST",
        f"/v1/document-bundles/{non_pdf['bundle_id']}/members/9/ocr",
        headers={**AUTH_A, "Idempotency-Key": "missing-member-ocr"},
        json={},
    )
    invalid_precision = request(
        app,
        "POST",
        f"/v1/document-bundles/{precise['bundle_id']}/members/0/ocr",
        headers={**AUTH_A, "Idempotency-Key": "precision-ocr"},
        json={"threshold": 0.755},
    )

    assert unsupported.status_code == 422
    assert unsupported.json() == {"detail": "ocr_source_unsupported"}
    assert foreign_response.status_code == missing.status_code == out_of_range.status_code == 404
    assert foreign_response.json() == missing.json() == out_of_range.json() == {
        "detail": "not_found"
    }
    assert invalid_precision.status_code == 422
    assert invalid_precision.json() == {"detail": "validation_error"}
    assert runner.calls == []


def test_bundle_member_ocr_fails_closed_when_stored_outer_bytes_change() -> None:
    service = FakeBundleService()
    runner = RecordingOcrRunner(())
    app = create_app(service, FakeAuthenticator(), ocr_runner=runner)
    uploaded = upload_bundle(app, bundle((("scan.pdf", blank_pdf()),)), key="tamper-bundle")
    bundle_id = str(uploaded["bundle_id"])
    service.contents[("tenant-a", bundle_id)] += b"tampered"

    response = request(
        app,
        "POST",
        f"/v1/document-bundles/{bundle_id}/members/0/ocr",
        headers={**AUTH_A, "Idempotency-Key": "tamper-ocr"},
        json={},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "internal_error"}
    assert "tamper" not in response.text
    assert runner.calls == []
    assert service.ocr_calls == []
