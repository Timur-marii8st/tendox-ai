"""Real PostgreSQL checks for immutable tenant-scoped manufacturer searches."""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import insert, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from procurement.sources.eaeu_registry import RegistryCandidate, _request_body
from procurement.sources.manufacturer_search import ManufacturerSourceCapture
from procurement.storage import manufacturer_search as module
from procurement.storage.manufacturer_search import (
    ManufacturerSearchConflict,
    ManufacturerSearchNotFound,
    ManufacturerSearchRateLimited,
    list_saved_searches,
    read_candidate,
    read_search,
    start_search,
)
from procurement.storage.models import (
    audit_events,
    manufacturer_search_results,
    manufacturer_search_runs,
)
from procurement.storage.repository import PostgresStorage

DATABASE = "procurement_manufacturer_test"
NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)


@pytest.fixture
def storage() -> PostgresStorage:
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration")
    if make_url(url).database != DATABASE:
        pytest.fail(f"manufacturer tests require isolated database {DATABASE}")
    return PostgresStorage.from_url(url)


def _capture(query: str = "насос", *, expiry: date | None = date(2026, 10, 5)):
    body = _request_body(tuple(query.split()))
    raw = (
        b'{"result":[{"_id":{"$oid":"6582fb75a4a4b05007bb2d05"},'
        b'"registrynumber":"0001","goodsname":"Pump","name":"Factory",'
        + (
            f'"expertactenddate":"{expiry.isoformat()}"'.encode()
            if expiry is not None
            else b'"expertactenddate":null'
        )
        + b'}],"matchedDocuments":1}'
    )
    candidate = RegistryCandidate(
        source_record_index=1,
        record_id="6582fb75a4a4b05007bb2d05",
        registry_number="0001",
        product_name="Pump",
        manufacturer_name="Factory",
        record_url=(
            "https://goszakupki.eaeunion.org/erpt/ru/registers/products/list/card/"
            "6582fb75a4a4b05007bb2d05"
        ),
        document_expires_on=expiry,
    )
    return ManufacturerSourceCapture(
        query=query,
        observed_at=NOW,
        request_body=body,
        request_sha256=hashlib.sha256(body).hexdigest(),
        status="COMPLETED",
        reason_code="VERIFIED_RESPONSE",
        response_body=raw,
        response_sha256=hashlib.sha256(raw).hexdigest(),
        matched_count=1,
        candidates=(candidate,),
    )


def test_success_reconstructs_retained_bytes_and_offline_dossier(storage, monkeypatch):
    company = "manufacturer-success-" + uuid.uuid4().hex
    command = str(uuid.uuid4())
    calls = 0

    def capture(query: str):
        nonlocal calls
        calls += 1
        return _capture(query)

    monkeypatch.setattr(module, "capture_manufacturer_search", capture)
    saved = start_search(storage, company, "насос", "actor", command)
    replay = start_search(storage, company, " насос ", "actor", command)
    dossier = read_candidate(storage, company, saved.report.run_id, "6582fb75a4a4b05007bb2d05")

    assert calls == 1 and saved.created and saved.source_requests == 1
    assert not replay.created and replay.source_requests == 0 and replay.report == saved.report
    assert saved.report.candidates[0].document_validity == "FAIL"
    assert dossier.verified_from_retained_response is True
    assert dossier.provenance.response_sha256 == saved.report.response_sha256
    assert list_saved_searches(storage, company)[0].candidate_count == 1
    with pytest.raises(ManufacturerSearchNotFound):
        read_search(storage, "other-" + company, saved.report.run_id)

    with storage.transaction(company, consistent_read=True) as conn:
        events = conn.scalars(
            select(audit_events.c.event_type).where(
                audit_events.c.object_id == saved.report.run_id
            )
        ).all()
    assert events == ["manufacturer_search.started", "manufacturer_search.finished"]


def test_started_survives_process_failure_and_idempotency_conflict(storage, monkeypatch):
    company = "manufacturer-started-" + uuid.uuid4().hex
    command = str(uuid.uuid4())

    def crash(query: str):
        raise RuntimeError(query)

    monkeypatch.setattr(module, "capture_manufacturer_search", crash)
    with pytest.raises(RuntimeError):
        start_search(storage, company, "насос", "actor", command)
    summary = list_saved_searches(storage, company)[0]
    assert summary.status == "STARTED" and summary.matched_count is None
    replay = start_search(storage, company, "насос", "actor", command)
    assert replay.report.status == "STARTED" and replay.source_requests == 0
    with pytest.raises(ManufacturerSearchConflict):
        start_search(storage, company, "компрессор", "actor", command)


def test_cooldown_is_tenant_scoped_and_immutable(storage, monkeypatch):
    monkeypatch.setattr(module, "capture_manufacturer_search", _capture)
    company = "manufacturer-rate-" + uuid.uuid4().hex
    saved = start_search(storage, company, "насос", "actor", str(uuid.uuid4()))
    with pytest.raises(ManufacturerSearchRateLimited, match="COOLDOWN"):
        start_search(storage, company, "компрессор", "actor", str(uuid.uuid4()))
    other = start_search(
        storage, "other-" + company, "компрессор", "actor", str(uuid.uuid4())
    )
    assert other.report.status == "COMPLETED"
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(
            update(manufacturer_search_runs)
            .where(manufacturer_search_runs.c.run_id == saved.report.run_id)
            .values(query="changed")
        )


def test_twenty_daily_reservations_block_the_next_attempt(storage, monkeypatch):
    monkeypatch.setattr(module, "capture_manufacturer_search", _capture)
    company = "manufacturer-daily-" + uuid.uuid4().hex
    now = datetime.now(UTC)
    request = _request_body(("насос",))
    with storage.transaction(company) as conn:
        conn.execute(
            insert(manufacturer_search_runs),
            [
                {
                    "company_id": company,
                    "run_id": str(uuid.uuid4()),
                    "command_id": str(uuid.uuid4()),
                    "query": "насос",
                    "parser_revision": "eaeu-registry-parser-v1",
                    "request_body": request,
                    "request_sha256": hashlib.sha256(request).hexdigest(),
                    "created_at": now - timedelta(minutes=20, seconds=index),
                }
                for index in range(20)
            ],
        )
    with pytest.raises(ManufacturerSearchRateLimited, match="DAILY_LIMIT"):
        start_search(storage, company, "насос", "actor", str(uuid.uuid4()))


def test_inconsistent_parser_reconstruction_fails_closed(storage):
    company = "manufacturer-hash-" + uuid.uuid4().hex
    run_id, attempt_id = str(uuid.uuid4()), str(uuid.uuid4())
    # Exercise reconstruction defense through ordinary writes: the DB constrains shape/size,
    # while the reader verifies the cryptographic relationship to retained bytes.
    with storage.transaction(company) as conn:
        conn.execute(
            insert(manufacturer_search_runs).values(
                company_id=company,
                run_id=run_id,
                command_id=str(uuid.uuid4()),
                query="насос",
                parser_revision="eaeu-registry-parser-v1",
                request_body=_request_body(("насос",)),
                request_sha256=hashlib.sha256(_request_body(("насос",))).hexdigest(),
                created_at=NOW,
            )
        )
        conn.exec_driver_sql(
            "INSERT INTO manufacturer_search_attempts "
            "(company_id,attempt_id,run_id,status,started_at) VALUES (%s,%s,%s,'STARTED',%s)",
            (company, attempt_id, run_id, NOW),
        )
        raw = b'{"result":"changed-shape","matchedDocuments":0}'
        conn.execute(
            insert(manufacturer_search_results).values(
                company_id=company,
                run_id=run_id,
                attempt_id=attempt_id,
                status="COMPLETED",
                reason_code="VERIFIED_RESPONSE",
                observed_at=NOW,
                finished_at=NOW,
                response_body=raw,
                response_sha256=hashlib.sha256(raw).hexdigest(),
                response_byte_size=len(raw),
                matched_count=0,
                candidate_count=0,
            )
        )
    with pytest.raises(ManufacturerSearchNotFound, match="EVIDENCE_INVALID"):
        read_search(storage, company, run_id)
