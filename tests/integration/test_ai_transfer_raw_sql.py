"""Direct SQL regressions for complete-response atomicity and terminal semantics."""

from __future__ import annotations

import itertools
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from queue import Queue

import pytest
import test_document_storage as helpers
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.exc import DBAPIError

from procurement.documents.ai_transfer_raw import (
    AiTransferRawBinding,
    encrypt_ai_transfer_raw_response,
)
from procurement.storage import PostgresStorage
from procurement.storage.models import (
    ai_transfer_approvals,
    ai_transfer_chunks,
    ai_transfer_dispatch_claims,
    ai_transfer_dispatch_receipts,
    ai_transfer_execution_admissions,
    ai_transfer_raw_response_blobs,
    ai_transfer_raw_response_deletion_receipts,
    ai_transfer_raw_responses,
    ai_transfer_requests,
    audit_events,
)


@pytest.fixture(scope="module")
def sql_storage():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is not set")
    engine = create_engine(url)
    yield PostgresStorage(engine, raw_key_provider=helpers._EphemeralTenantKekProvider())
    engine.dispose()


@pytest.fixture(scope="module")
def raw_template(sql_storage):
    tenant = f"raw-sql-{uuid.uuid4()}"
    admission, claim = helpers._claimed_ai_transfer(sql_storage, tenant)
    receipt, metadata = sql_storage.persist_captured_ai_transfer_result(
        tenant,
        claim.claimed_by,
        admission.execution_id,
        helpers._successful_transport_attempt(claim),
        helpers.SYNTHETIC_RAW_RESPONSE,
    )
    with sql_storage.transaction(tenant) as connection:
        raw = dict(
            connection.execute(
                select(ai_transfer_raw_responses).where(
                    ai_transfer_raw_responses.c.raw_response_id == metadata.raw_response_id
                )
            )
            .mappings()
            .one()
        )
        blob = dict(
            connection.execute(
                select(ai_transfer_raw_response_blobs).where(
                    ai_transfer_raw_response_blobs.c.raw_response_id == metadata.raw_response_id
                )
            )
            .mappings()
            .one()
        )
    return tenant, receipt, raw, blob


def _new_rows(storage, template, **receipt_changes):
    tenant, original_receipt, original_raw, original_blob = template
    _, claim = helpers._claimed_ai_transfer(storage, tenant)
    receipt, receipt_json = helpers._forged_receipt_values(original_receipt, claim)
    receipt.update(receipt_changes)
    receipt_json.update(receipt_changes)
    receipt["receipt"] = receipt_json
    raw = dict(original_raw)
    raw.update(
        raw_response_id=str(uuid.uuid4()),
        transfer_id=claim.transfer_id,
        execution_id=claim.execution_id,
        claim_id=claim.claim_id,
        chunk_id=claim.chunk_id,
        claim_payload_sha256=claim.payload_sha256,
        receipt_id=receipt["receipt_id"],
        receipt_payload_sha256=receipt["payload_sha256"],
        request_sha256=claim.request_sha256,
        received_at=receipt["finished_at"],
        expires_at=receipt["finished_at"] + timedelta(hours=720),
    )
    raw["metadata"] = {
        key: (raw[key].isoformat() if isinstance(raw[key], datetime) else raw[key])
        for key in original_raw["metadata"]
    }
    blob = dict(original_blob)
    for key in blob.keys() & raw.keys() - {"schema_version"}:
        blob[key] = raw[key]
    return tenant, receipt, raw, blob


def _age_synthetic_claim(receipt, claimed_at):
    """Simulate elapsed retention for one test claim, never for runtime data."""
    admin = create_engine(os.environ["DATABASE_ADMIN_URL"])
    try:
        with admin.begin() as connection:
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            connection.execute(
                text(
                    "UPDATE ai_transfer_dispatch_claims SET claimed_at = :at, "
                    "claim = jsonb_set(claim, '{claimed_at}', to_jsonb(CAST(:stamp AS text))) "
                    "WHERE company_id = :tenant AND claim_id = :claim"
                ),
                {
                    "at": claimed_at,
                    "stamp": claimed_at.isoformat(),
                    "tenant": receipt["company_id"],
                    "claim": receipt["claim_id"],
                },
            )
    finally:
        admin.dispose()


@pytest.mark.parametrize("attempted", [False, True])
def test_receipt_cannot_claim_activity_before_durable_claim(sql_storage, raw_template, attempted):
    tenant, receipt, _, _ = _new_rows(sql_storage, raw_template)
    before_claim = datetime.now(UTC) - timedelta(days=1)
    if attempted:
        receipt.update(started_at=before_claim)
        receipt["receipt"].update(started_at=before_claim.isoformat())
    else:
        receipt.update(
            outcome="FAILED",
            reason="APPROVAL_EXPIRED_BEFORE_DISPATCH",
            attempted=False,
            http_status=None,
            capture_complete=False,
            captured_byte_count=0,
            response_body_sha256=None,
            provider_response_id=None,
            provider_model=None,
            assistant_content_sha256=None,
            assistant_content_byte_count=None,
            started_at=None,
            finished_at=None,
            recorded_at=before_claim,
        )
        receipt["receipt"].update(
            {
                key: value.isoformat() if isinstance(value, datetime) else value
                for key, value in receipt.items()
                if key != "receipt"
            }
        )
    with pytest.raises(DBAPIError) as error, sql_storage.transaction(tenant) as connection:
        connection.execute(insert(ai_transfer_dispatch_receipts).values(**receipt))
    assert error.value.orig.sqlstate == "23514"
    assert "cannot precede its durable claim" in str(error.value.orig)


def _as_pre_dispatch_expiry(receipt, *, recorded_at):
    receipt.update(
        outcome="FAILED",
        reason="APPROVAL_EXPIRED_BEFORE_DISPATCH",
        attempted=False,
        http_status=None,
        capture_complete=False,
        captured_byte_count=0,
        response_body_sha256=None,
        provider_response_id=None,
        provider_model=None,
        assistant_content_sha256=None,
        assistant_content_byte_count=None,
        started_at=None,
        finished_at=None,
        recorded_at=recorded_at,
    )
    receipt["receipt"].update(
        {
            key: value.isoformat() if isinstance(value, datetime) else value
            for key, value in receipt.items()
            if key != "receipt"
        }
    )


def test_runtime_sql_cannot_record_receipt_as_another_worker(sql_storage, raw_template):
    tenant, receipt, _, _ = _new_rows(
        sql_storage,
        raw_template,
        outcome="DELIVERY_UNKNOWN",
        reason="TIMEOUT",
        http_status=None,
        capture_complete=False,
        response_body_sha256=None,
        provider_response_id=None,
        provider_model=None,
        assistant_content_sha256=None,
        assistant_content_byte_count=None,
        recorded_by="different-worker",
    )
    with pytest.raises(DBAPIError) as error, sql_storage.transaction(tenant) as connection:
        connection.execute(insert(ai_transfer_dispatch_receipts).values(**receipt))
    assert error.value.orig.sqlstate == "23514"
    assert "claiming worker" in str(error.value.orig)


@pytest.mark.parametrize("future_recorded_at", [False, True])
def test_runtime_sql_cannot_record_expiry_before_server_deadline(
    sql_storage, raw_template, future_recorded_at
):
    tenant, receipt, _, _ = _new_rows(sql_storage, raw_template)
    recorded_at = datetime.now(UTC)
    if future_recorded_at:
        recorded_at += timedelta(minutes=16)
    _as_pre_dispatch_expiry(receipt, recorded_at=recorded_at)
    with pytest.raises(DBAPIError) as error, sql_storage.transaction(tenant) as connection:
        connection.execute(insert(ai_transfer_dispatch_receipts).values(**receipt))
    assert error.value.orig.sqlstate == "23514"
    assert "approval has not expired" in str(error.value.orig)


def _expired_claimed_transfer(storage):
    """Seed a coherent historical chain; runtime operations never bypass its guards."""
    tenant = f"expired-transfer-{uuid.uuid4()}"
    source = helpers._store_transfer_source(storage, tenant)
    request = helpers.build_persisted_ai_transfer_request(
        helpers.prepare_ai_requirements_transfer(
            source.extraction,
            company_id=tenant,
            source_document_id=source.document_id,
            source_sha256=source.sha256,
        ),
        transfer_id=str(uuid.uuid4()),
        prepared_by="preparer",
        prepared_at=datetime.now(UTC) - timedelta(minutes=20),
    )
    approval = helpers.build_persisted_ai_transfer_approval(
        request,
        approved_by="approver",
        approved_at=request.prepared_at + timedelta(minutes=1),
    )
    admission = helpers.build_ai_transfer_execution_admission(
        request,
        approval,
        company_id=tenant,
        transfer_id=request.transfer_id,
        execution_id=str(uuid.uuid4()),
        admitted_by="preparer",
        admitted_at=approval.approved_at + timedelta(minutes=1),
        existing_admission=None,
    )
    claim = helpers.build_ai_transfer_dispatch_claim(
        request,
        approval,
        admission,
        claim_id=str(uuid.uuid4()),
        claimed_by="expiry-worker",
        claimed_at=admission.admitted_at + timedelta(minutes=1),
        existing_claims=(),
        existing_receipts=(),
    )
    admin = create_engine(os.environ["DATABASE_ADMIN_URL"])
    try:
        with admin.begin() as connection:
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            for table, document, json_column, extra in (
                (
                    ai_transfer_requests,
                    request,
                    "request",
                    {"created_at": request.prepared_at, "chunk_count": len(request.chunks)},
                ),
                (ai_transfer_approvals, approval, "approval", {}),
                (ai_transfer_execution_admissions, admission, "admission", {}),
                (ai_transfer_dispatch_claims, claim, "claim", {}),
            ):
                payload = document.model_dump()
                values = {
                    column.name: payload[column.name]
                    for column in table.columns
                    if column.name in payload
                }
                values.update(extra)
                values[json_column] = document.model_dump(mode="json")
                connection.execute(insert(table).values(**values))
            connection.execute(
                insert(ai_transfer_chunks),
                [
                    {
                        "company_id": tenant,
                        "transfer_id": request.transfer_id,
                        "payload_sha256": request.payload_sha256,
                        "ordinal": ordinal,
                        "chunk_id": chunk.chunk_id,
                        "request_body_json": chunk.request_body_json,
                        "request_sha256": chunk.request_sha256,
                        "chunk": chunk.model_dump(mode="json"),
                    }
                    for ordinal, chunk in enumerate(request.chunks, 1)
                ],
            )
    finally:
        admin.dispose()
    return admission, claim


def test_repository_can_record_actual_pre_dispatch_expiry(sql_storage):
    admission, claim = _expired_claimed_transfer(sql_storage)
    receipt = sql_storage.record_ai_transfer_pre_dispatch_expiry(
        claim.company_id,
        claim.claimed_by,
        claim.execution_id,
        claim,
        observed_at=datetime.now(UTC),
    )
    assert receipt.reason == "APPROVAL_EXPIRED_BEFORE_DISPATCH"
    assert receipt.recorded_by == claim.claimed_by
    assert receipt.recorded_at >= admission.approval_expires_at
    assert receipt.attempted is False
    assert sql_storage.get_ai_transfer_execution(claim.company_id, claim.execution_id) == (
        admission,
        claim,
        receipt,
    )


@pytest.mark.parametrize("recorded_at_offset", [timedelta(seconds=-1), timedelta(days=1)])
def test_runtime_sql_expiry_requires_current_timestamp_after_approval(
    sql_storage, raw_template, recorded_at_offset
):
    admission, claim = _expired_claimed_transfer(sql_storage)
    receipt, _ = helpers._forged_receipt_values(raw_template[1], claim)
    _as_pre_dispatch_expiry(receipt, recorded_at=admission.approval_expires_at + recorded_at_offset)
    with (
        pytest.raises(DBAPIError) as error,
        sql_storage.transaction(claim.company_id) as connection,
    ):
        connection.execute(insert(ai_transfer_dispatch_receipts).values(**receipt))
    assert error.value.orig.sqlstate == "23514"
    assert "approval has not expired or expiry receipt is not current" in str(error.value.orig)


@pytest.mark.parametrize(
    "changes",
    [
        {"http_status": None},
        {
            "outcome": "FAILED",
            "reason": "REDIRECT_REJECTED",
            "http_status": None,
            "capture_complete": False,
            "captured_byte_count": 0,
            "response_body_sha256": None,
            "provider_response_id": None,
            "provider_model": None,
            "assistant_content_sha256": None,
            "assistant_content_byte_count": None,
        },
        {
            "outcome": "FAILED",
            "reason": "MALFORMED_RESPONSE_JSON",
            "http_status": 201,
            "provider_response_id": None,
            "provider_model": None,
            "assistant_content_sha256": None,
            "assistant_content_byte_count": None,
        },
        {
            "outcome": "FAILED",
            "reason": "MODEL_MISMATCH",
            "http_status": 204,
            "assistant_content_sha256": None,
            "assistant_content_byte_count": None,
        },
    ],
)
def test_terminal_semantics_reject_null_and_non_200_envelopes(sql_storage, raw_template, changes):
    tenant, receipt, _, _ = _new_rows(sql_storage, raw_template, **changes)
    with pytest.raises(DBAPIError) as error, sql_storage.transaction(tenant) as connection:
        connection.execute(insert(ai_transfer_dispatch_receipts).values(**receipt))
    assert error.value.orig.diag.constraint_name == "ck_ai_transfer_receipt_terminal_semantics"


@pytest.mark.parametrize("with_metadata", [False, True])
def test_complete_receipt_cannot_commit_without_encrypted_blob(
    sql_storage, raw_template, with_metadata
):
    tenant, receipt, raw, _ = _new_rows(sql_storage, raw_template)
    with pytest.raises(DBAPIError) as error, sql_storage.transaction(tenant) as connection:
        connection.execute(insert(ai_transfer_dispatch_receipts).values(**receipt))
        if with_metadata:
            connection.execute(insert(ai_transfer_raw_responses).values(**raw))
    assert error.value.orig.sqlstate == "23514"


@pytest.mark.parametrize("order", list(itertools.permutations(range(3))))
def test_complete_response_inserts_are_order_independent(sql_storage, raw_template, order):
    tenant, receipt, raw, blob = _new_rows(sql_storage, raw_template)
    rows = (
        (ai_transfer_dispatch_receipts, receipt),
        (ai_transfer_raw_responses, raw),
        (ai_transfer_raw_response_blobs, blob),
    )
    with sql_storage.transaction(tenant) as connection:
        for index in order:
            table, values = rows[index]
            connection.execute(insert(table).values(**values))


@pytest.mark.parametrize("status", [101, 201, 204, 299, 400, 599])
def test_all_non_redirect_non_200_statuses_are_persistable(sql_storage, raw_template, status):
    tenant, receipt, raw, blob = _new_rows(
        sql_storage,
        raw_template,
        outcome="FAILED",
        reason="HTTP_STATUS_REJECTED",
        http_status=status,
        provider_response_id=None,
        provider_model=None,
        assistant_content_sha256=None,
        assistant_content_byte_count=None,
    )
    with sql_storage.transaction(tenant) as connection:
        connection.execute(insert(ai_transfer_dispatch_receipts).values(**receipt))
        connection.execute(insert(ai_transfer_raw_responses).values(**raw))
        connection.execute(insert(ai_transfer_raw_response_blobs).values(**blob))


def test_unknown_receipt_does_not_require_raw(sql_storage, raw_template):
    tenant, receipt, _, _ = _new_rows(
        sql_storage,
        raw_template,
        outcome="DELIVERY_UNKNOWN",
        reason="TIMEOUT",
        http_status=None,
        capture_complete=False,
        response_body_sha256=None,
        provider_response_id=None,
        provider_model=None,
        assistant_content_sha256=None,
        assistant_content_byte_count=None,
    )
    with sql_storage.transaction(tenant) as connection:
        connection.execute(insert(ai_transfer_dispatch_receipts).values(**receipt))


def test_retention_constraint_is_elapsed_hours_across_dst(sql_storage, raw_template):
    tenant = raw_template[0]
    with sql_storage.transaction(tenant) as connection:
        connection.execute(text("SET LOCAL TIME ZONE 'America/New_York'"))
        check = connection.execute(
            text(
                "SELECT pg_get_expr(conbin, conrelid) FROM pg_constraint "
                "WHERE conname = 'ck_ai_transfer_raw_expiry'"
            )
        ).scalar_one()
        # Use the actual installed CHECK with fixed instants spanning DST.
        valid = connection.execute(
            text(
                f"SELECT {check} FROM (SELECT "
                "'2027-03-01T12:00:00-05:00'::timestamptz AS received_at, "
                "'2027-03-31T13:00:00-04:00'::timestamptz AS expires_at) AS sample"
            )
        ).scalar_one()
    assert valid is True


def test_blob_insert_rechecks_expiry_at_commit(sql_storage, raw_template):
    tenant, receipt, raw, blob = _new_rows(sql_storage, raw_template)
    expires_at = datetime.now(UTC) + timedelta(seconds=1)
    received_at = expires_at - timedelta(hours=720)
    _age_synthetic_claim(receipt, received_at)
    receipt.update(started_at=received_at, finished_at=received_at)
    receipt["receipt"].update(
        started_at=received_at.isoformat(), finished_at=received_at.isoformat()
    )
    raw.update(received_at=received_at, expires_at=expires_at)
    raw["metadata"].update(received_at=received_at.isoformat(), expires_at=expires_at.isoformat())
    blob.update(received_at=received_at, expires_at=expires_at)
    with pytest.raises(DBAPIError) as error, sql_storage.transaction(tenant) as connection:
        connection.execute(insert(ai_transfer_dispatch_receipts).values(**receipt))
        connection.execute(insert(ai_transfer_raw_responses).values(**raw))
        connection.execute(insert(ai_transfer_raw_response_blobs).values(**blob))
        connection.execute(text("SELECT pg_sleep(1.1)"))
    assert error.value.orig.sqlstate == "23514"
    assert "expired or deleted AI transfer raw blob" in str(error.value.orig)


def test_runtime_retention_purge_preserves_evidence_and_is_idempotent(sql_storage, raw_template):
    tenant, receipt, raw, blob = _new_rows(sql_storage, raw_template)
    received_at = datetime.now(UTC) - timedelta(hours=721)
    receipt.update(started_at=received_at, finished_at=received_at)
    receipt["receipt"].update(
        started_at=received_at.isoformat(), finished_at=received_at.isoformat()
    )
    raw["received_at"] = received_at
    envelope = encrypt_ai_transfer_raw_response(
        binding=AiTransferRawBinding(
            **{
                key: raw[key]
                for key in AiTransferRawBinding.model_fields
                if key != "schema_version"
            }
        ),
        raw_response_body=helpers.SYNTHETIC_RAW_RESPONSE,
        key_provider=helpers._EphemeralTenantKekProvider(),
    )
    raw.update(envelope.metadata.model_dump())
    raw.update(
        metadata=envelope.metadata.model_dump(mode="json"),
        wrap_aad_sha256=envelope.wrap_aad_sha256,
        envelope_sha256=envelope.envelope_sha256,
    )
    for key in blob.keys() & raw.keys() - {"schema_version"}:
        blob[key] = raw[key]
    for key in ("body_nonce", "ciphertext", "wrapping_nonce", "wrapped_dek"):
        blob[key] = getattr(envelope, key)
    # The privileged fixture models a record whose retention already elapsed.
    # All tested purge operations below run with ordinary procurement_app grants.
    admin = create_engine(os.environ["DATABASE_ADMIN_URL"])
    try:
        with admin.begin() as connection:
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            connection.execute(insert(ai_transfer_dispatch_receipts).values(**receipt))
            connection.execute(insert(ai_transfer_raw_responses).values(**raw))
            connection.execute(insert(ai_transfer_raw_response_blobs).values(**blob))
    finally:
        admin.dispose()
    deleted = sql_storage.purge_expired_ai_transfer_raw_responses(tenant, "retention-worker")
    assert len(deleted) == 1
    result = deleted[0]
    assert result.raw_response_id == raw["raw_response_id"]
    assert result.metadata_schema_version == envelope.metadata.schema_version
    assert result.body_aad_sha256 == envelope.metadata.body_aad_sha256
    assert result.wrap_aad_sha256 == envelope.wrap_aad_sha256
    with sql_storage.transaction(tenant) as connection:
        assert (
            connection.execute(
                select(ai_transfer_raw_response_blobs).where(
                    ai_transfer_raw_response_blobs.c.raw_response_id == result.raw_response_id
                )
            ).first()
            is None
        )
        assert connection.execute(
            select(ai_transfer_raw_responses.c.metadata).where(
                ai_transfer_raw_responses.c.raw_response_id == result.raw_response_id
            )
        ).scalar_one() == envelope.metadata.model_dump(mode="json")
        stored_receipt = connection.execute(
            select(ai_transfer_raw_response_deletion_receipts.c.deletion_receipt).where(
                ai_transfer_raw_response_deletion_receipts.c.raw_response_id
                == result.raw_response_id
            )
        ).scalar_one()
        assert stored_receipt == result.model_dump(mode="json")
        event = (
            connection.execute(
                select(audit_events).where(
                    audit_events.c.object_id == result.raw_response_id,
                    audit_events.c.event_type == "document.ai_transfer_raw_response_deleted",
                )
            )
            .mappings()
            .one()
        )
        assert event["actor_id"] == "retention-worker"
        assert event["basis"]["deletion_receipt_id"] == result.deletion_receipt_id
    assert sql_storage.purge_expired_ai_transfer_raw_responses(tenant, "retention-worker") == ()


def _wait_for_lock(connection, worker_pid, expected_event):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        event = connection.execute(
            text("SELECT wait_event FROM pg_stat_activity WHERE pid = :pid"),
            {"pid": worker_pid},
        ).scalar_one()
        if event == expected_event:
            return
        time.sleep(0.02)
    pytest.fail(f"worker did not reach expected {expected_event} lock")


def test_insert_started_before_purge_cannot_resurrect_deleted_blob(sql_storage, raw_template):
    tenant, receipt, raw, blob = _new_rows(sql_storage, raw_template)
    expires_at = datetime.now(UTC) + timedelta(seconds=3)
    received_at = expires_at - timedelta(hours=720)
    _age_synthetic_claim(receipt, received_at)
    receipt.update(started_at=received_at, finished_at=received_at)
    receipt["receipt"].update(
        started_at=received_at.isoformat(), finished_at=received_at.isoformat()
    )
    raw.update(received_at=received_at, expires_at=expires_at)
    raw["metadata"].update(received_at=received_at.isoformat(), expires_at=expires_at.isoformat())
    blob.update(received_at=received_at, expires_at=expires_at)
    with sql_storage.transaction(tenant) as connection:
        connection.execute(insert(ai_transfer_dispatch_receipts).values(**receipt))
        connection.execute(insert(ai_transfer_raw_responses).values(**raw))
        connection.execute(insert(ai_transfer_raw_response_blobs).values(**blob))

    admin = create_engine(os.environ["DATABASE_ADMIN_URL"])
    lock_id = uuid.uuid4().int % (2**63)
    worker_pids = Queue()

    def insert_again():
        try:
            with sql_storage.transaction(tenant) as connection:
                worker_pids.put(connection.execute(text("SELECT pg_backend_pid()")).scalar_one())
                connection.execute(insert(ai_transfer_raw_response_blobs).values(**blob))
        except DBAPIError as error:
            return error.orig.sqlstate
        return "COMMITTED"

    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as control:
        # This test-only trigger pauses after the production BEFORE guard but
        # before the index insertion, making the otherwise tiny race deterministic.
        control.execute(
            text(f"""
            CREATE FUNCTION test_pause_raw_insert() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.raw_response_id = '{raw["raw_response_id"]}' THEN
                    PERFORM pg_advisory_xact_lock({lock_id});
                END IF;
                RETURN NEW;
            END; $$
        """)
        )
        control.execute(
            text(
                "CREATE TRIGGER z_test_pause_raw_insert BEFORE INSERT "
                "ON ai_transfer_raw_response_blobs FOR EACH ROW "
                "EXECUTE FUNCTION test_pause_raw_insert()"
            )
        )
        control.execute(text("SELECT pg_advisory_lock(:key)"), {"key": lock_id})
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(insert_again)
            worker_pid = worker_pids.get(timeout=5)
            _wait_for_lock(control, worker_pid, "advisory")
            delay = max(0, (expires_at - datetime.now(UTC)).total_seconds()) + 0.02
            control.execute(text("SELECT pg_sleep(:delay)"), {"delay": delay})
            with sql_storage.transaction(tenant) as connection:
                deleted_at = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
                deletion = {
                    column.name: raw[column.name]
                    for column in ai_transfer_raw_response_deletion_receipts.columns
                    if column.name in raw
                }
                deletion.update(
                    deletion_receipt_id=str(uuid.uuid4()),
                    metadata_schema_version=raw["schema_version"],
                    reason="RETENTION_EXPIRED",
                    deleted_by="sql-race-test",
                    deleted_at=deleted_at,
                    payload_sha256="d" * 64,
                )
                deletion["deletion_receipt"] = {
                    "schema_version": "ai-transfer-raw-deletion-receipt-v1",
                    **{
                        key: value.isoformat() if isinstance(value, datetime) else value
                        for key, value in deletion.items()
                    },
                }
                connection.execute(
                    insert(ai_transfer_raw_response_deletion_receipts).values(**deletion)
                )
                connection.execute(
                    ai_transfer_raw_response_blobs.delete().where(
                        ai_transfer_raw_response_blobs.c.raw_response_id == raw["raw_response_id"]
                    )
                )
                control.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_id})
                _wait_for_lock(control, worker_pid, "transactionid")
            assert future.result(timeout=5) == "23514"
            with sql_storage.transaction(tenant) as connection:
                assert (
                    connection.execute(
                        select(ai_transfer_raw_response_blobs).where(
                            ai_transfer_raw_response_blobs.c.raw_response_id
                            == raw["raw_response_id"]
                        )
                    ).first()
                    is None
                )
        finally:
            control.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_id})
            pool.shutdown(wait=True)
            control.execute(
                text("DROP TRIGGER z_test_pause_raw_insert ON ai_transfer_raw_response_blobs")
            )
            control.execute(text("DROP FUNCTION test_pause_raw_insert()"))
    admin.dispose()
