"""EIS review HTTP boundaries parse bounded strict JSON before storage dispatch."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from importlib import import_module
from typing import cast

import httpx
import pytest

from procurement.access import AccessRole
from procurement.api import create_app
from procurement.api.contracts import Authenticator, CaseService, Principal
from procurement.api.eis_document_review_runner import ReviewRunnerFailure
from procurement.storage.eis_document_review import (
    ReviewDocumentRequest,
    SavedReviewDocumentPage,
)
from procurement.storage.eis_document_store import NoticeDocumentRef
from procurement.storage.repository import PostgresStorage

PREPARE = "/v1/tender-discovery/eis-document-review/prepare"
PAGE = "/v1/tender-discovery/eis-document-review/page"
REF = NoticeDocumentRef(
    purchase_number="0848300054826000154",
    version_number=1,
    notice_xml_sha256="a" * 64,
)
REQUEST = ReviewDocumentRequest(
    notice=REF,
    content_uid="A" * 32,
    expected_document_sha256="b" * 64,
)


class Auth:
    def __init__(self, role: AccessRole) -> None:
        self.role = role

    async def authenticate(self, credential: str) -> Principal | None:
        if credential != "test":
            return None
        return Principal(company_id="tenant-a", actor_id="actor-a", access_role=self.role)


def send(
    path: str,
    *,
    raw: bytes | None = None,
    body: object | None = None,
    role: AccessRole = AccessRole.OPERATOR,
    storage: object | None = object(),
    authorization: str | None = "Bearer test",
) -> httpx.Response:
    app = create_app(
        cast(CaseService, object()),
        cast(Authenticator, Auth(role)),
        eis_index_storage=cast(PostgresStorage, storage) if storage is not None else None,
    )

    async def run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            kwargs = {"content": raw} if raw is not None else {"json": body}
            headers = {"Content-Type": "application/json"}
            if authorization is not None:
                headers["Authorization"] = authorization
            return await client.post(path, headers=headers, **kwargs)

    return asyncio.run(run())


def result() -> SavedReviewDocumentPage:
    from procurement.documents.extraction import ExtractedBlock
    from procurement.domain.provenance import Extractor, Provenance
    from procurement.sources.eis_document_review import ReviewDocumentAnalysis, review_document_page

    analysis = ReviewDocumentAnalysis(
        sha256="b" * 64,
        filename="spec.docx",
        byte_count=100,
        extraction_status="PASS",
        extraction_reasons=(),
        source_units_total=1,
        source_units_extracted=1,
        characters_extracted=4,
        blocks_extracted_total=1,
        blocks=(
            ExtractedBlock(
                text="text",
                provenance=Provenance(
                    document_id="b" * 64,
                    locator="word/document.xml :: paragraph[1]",
                    extractor=Extractor.NATIVE_DOCX,
                ),
            ),
        ),
        retained_blocks=1,
        retained_characters=4,
        retention_truncated=False,
        retention_reasons=(),
        retained_extracted_text_complete=True,
    )
    return SavedReviewDocumentPage(
        request=REQUEST,
        filename="spec.docx",
        source_url="https://zakupki.gov.ru/file",
        source_locator="attachment[1]",
        observation_id="obs-1",
        observed_at=datetime(2026, 10, 6, tzinfo=UTC),
        analyzed_at=datetime(2026, 10, 6, tzinfo=UTC),
        analysis_created=True,
        page=review_document_page(analysis, 0, 25),
    )


def test_prepare_requires_operator_before_body_and_forwards_tenant_actor(monkeypatch):
    calls = []

    def prepare(storage, company, request, *, actor_id):
        calls.append((company, actor_id, request))
        return result()

    module = import_module("procurement.api.app")
    monkeypatch.setattr(module, "run_prepare_review_subprocess", prepare)
    denied = send(PREPARE, raw=b"{", role=AccessRole.AUDITOR)
    assert denied.status_code == 403 and denied.headers["Cache-Control"] == "no-store"
    assert not calls
    response = send(PREPARE, body=REQUEST.model_dump(mode="json"))
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    assert calls == [("tenant-a", "actor-a", REQUEST)]


@pytest.mark.parametrize(
    "path,authorization",
    [
        (PREPARE, None),
        (PREPARE, "Basic malformed"),
        (PREPARE, "Bearer invalid"),
        (PAGE, None),
        (PAGE, "Basic malformed"),
        (PAGE, "Bearer invalid"),
    ],
)
def test_unauthorized_review_is_no_store_before_body_or_dispatch(monkeypatch, path, authorization):
    module = import_module("procurement.api.app")
    monkeypatch.setattr(
        module,
        "run_prepare_review_subprocess",
        lambda *_args, **_kwargs: pytest.fail("unauthorized prepare dispatched"),
    )
    monkeypatch.setattr(
        module,
        "read_review_document_page",
        lambda *_args, **_kwargs: pytest.fail("unauthorized page dispatched"),
    )
    response = send(path, raw=b"{ malformed", authorization=authorization)
    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_page_allows_auditor_and_forwards_strict_cursor(monkeypatch):
    calls = []

    def read(storage, company, request, *, offset, character_offset, limit):
        calls.append((company, request, offset, character_offset, limit))
        return result()

    monkeypatch.setattr(import_module("procurement.api.app"), "read_review_document_page", read)
    body = {
        "request": REQUEST.model_dump(mode="json"),
        "offset": 2,
        "character_offset": 7,
        "limit": 3,
    }
    response = send(PAGE, body=body, role=AccessRole.AUDITOR)
    assert response.status_code == 200
    assert calls == [("tenant-a", REQUEST, 2, 7, 3)]


@pytest.mark.parametrize(
    "raw",
    [
        b'{"request":{},"request":{}}',
        b'{"request":{},"offset":NaN}',
        b"{",
        b"x" * 4_097,
    ],
)
def test_invalid_or_oversized_json_never_dispatches(monkeypatch, raw):
    monkeypatch.setattr(
        import_module("procurement.api.app"),
        "read_review_document_page",
        lambda *_args, **_kwargs: pytest.fail("invalid request dispatched"),
    )
    response = send(PAGE, raw=raw)
    assert response.status_code in {413, 422}
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "change",
    [
        {"offset": True},
        {"character_offset": True},
        {"limit": 1.0},
        {"tenant": "foreign"},
        {"request": {**REQUEST.model_dump(mode="json"), "extra": 1}},
        {
            "request": {
                **REQUEST.model_dump(mode="json"),
                "notice": {**REF.model_dump(), "version_number": True},
            }
        },
    ],
)
def test_page_rejects_coercion_and_unknown_fields(monkeypatch, change):
    monkeypatch.setattr(
        import_module("procurement.api.app"),
        "read_review_document_page",
        lambda *_args, **_kwargs: pytest.fail("invalid request dispatched"),
    )
    body = {"request": REQUEST.model_dump(mode="json")} | change
    assert send(PAGE, body=body).status_code == 422


def test_errors_are_no_store_whitelisted_and_redacted(monkeypatch):
    module = import_module("procurement.api.app")
    monkeypatch.setattr(
        module,
        "run_prepare_review_subprocess",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ReviewRunnerFailure("value", "NOTICE_VERSION_STALE")
        ),
    )
    conflict = send(PREPARE, body=REQUEST.model_dump(mode="json"))
    assert conflict.status_code == 409 and conflict.json() == {"detail": "NOTICE_VERSION_STALE"}
    assert conflict.headers["Cache-Control"] == "no-store"

    monkeypatch.setattr(
        module,
        "read_review_document_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("private secret")),
    )
    failed = send(PAGE, body={"request": REQUEST.model_dump(mode="json")})
    assert failed.status_code == 503
    assert failed.json() == {"detail": "document_review_unavailable"}
    assert "private" not in failed.text and failed.headers["Cache-Control"] == "no-store"


def test_unavailable_storage_never_dispatches(monkeypatch):
    monkeypatch.setattr(
        import_module("procurement.api.app"),
        "run_prepare_review_subprocess",
        lambda *_args, **_kwargs: pytest.fail("unavailable storage dispatched"),
    )
    response = send(PREPARE, body=REQUEST.model_dump(mode="json"), storage=None)
    assert response.status_code == 503 and response.headers["Cache-Control"] == "no-store"


def test_openapi_exposes_strict_review_request_schemas():
    app = create_app(
        cast(CaseService, object()),
        cast(Authenticator, Auth(AccessRole.OPERATOR)),
        eis_index_storage=cast(PostgresStorage, object()),
    )
    schema = app.openapi()
    request_schemas = [
        schema["paths"][path]["post"]["requestBody"]["content"]["application/json"]["schema"]
        for path in (PREPARE, PAGE)
    ]

    def assert_fully_inlined(value):
        if isinstance(value, dict):
            assert "$ref" not in value and "$defs" not in value
            for child in value.values():
                assert_fully_inlined(child)
        elif isinstance(value, list):
            for child in value:
                assert_fully_inlined(child)

    for request_schema in request_schemas:
        assert request_schema["additionalProperties"] is False
        assert_fully_inlined(request_schema)
