"""Use isolated PostgreSQL to test capture audit, recovery and tenant isolation."""

import hashlib
import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import func, insert, select
from test_eis_223_index_pg import storage as pg_storage  # noqa: F401

from procurement.storage.eis_223_sync import record_attempt
from procurement.storage.models import audit_events
from test_eis_223_failed_capture import TOKEN, Transport, fetch, worker


@pytest.mark.usefixtures("pg_storage")
def test_capture_reconcile_after_audit_outage_preserves_tenant_boundary(
    request, monkeypatch, tmp_path
):
    storage = request.getfixturevalue("pg_storage")
    company = "capture-" + uuid4().hex
    other = "capture-" + uuid4().hex
    window = fetch(Transport()).window
    checked = datetime.now(UTC)
    monkeypatch.setattr(worker, "COMPANY", company)
    monkeypatch.setattr(worker, "CAPTURE_KEY", window.window_key)
    record_attempt(
        storage,
        company,
        window.window_key,
        "FAILED",
        actor_id="test",
        checked_at=checked,
        response_sha256=window.response_sha256,
        reason="SYNC_FAILED",
    )

    class Outage:
        @contextmanager
        def transaction(self, tenant, **kwargs):
            if not kwargs.get("consistent_read"):
                raise OSError("audit outage")
            with storage.transaction(tenant, **kwargs) as conn:
                yield conn

    root = tmp_path / "capture"
    with pytest.raises(OSError, match="audit outage"):
        worker.retain_failed_223(Outage(), window, TOKEN, checked, root=root)
    digest = worker.reconcile_failed_223(storage, root, TOKEN)
    assert worker.reconcile_failed_223(storage, root, TOKEN) == digest
    for tenant, expected in [(company, 1), (other, 0)]:
        with storage.transaction(tenant, consistent_read=True) as conn:
            count = conn.scalar(
                select(func.count())
                .select_from(audit_events)
                .where(audit_events.c.event_type == "EIS_223_FAILED_WINDOW_RETAINED")
            )
            assert count == expected


@pytest.mark.usefixtures("pg_storage")
def test_failed_capture_diagnostic_is_tenant_bound_and_idempotent(request, monkeypatch):
    storage = request.getfixturevalue("pg_storage")
    company, other = "capture-" + uuid4().hex, "capture-" + uuid4().hex
    window = fetch(Transport()).window
    checked = datetime.now(UTC)
    monkeypatch.setattr(worker, "COMPANY", company)
    monkeypatch.setattr(worker, "CAPTURE_KEY", window.window_key)
    record_attempt(storage, company, window.window_key, "FAILED", actor_id="test",
                   checked_at=checked, response_sha256=window.response_sha256, reason="SYNC_FAILED")
    for _ in range(2):
        worker._audit_capture_failure(storage, window.window_key, window.response_sha256,
                                      checked, "QUOTA_REACHED")
    with storage.transaction(company, consistent_read=True) as conn:
        rows = conn.execute(select(audit_events.c.basis).where(
            audit_events.c.event_type == "EIS_223_FAILED_CAPTURE_DIAGNOSTIC"
        )).scalars().all()
    assert len(rows) == 1
    assert rows[0]["reason"] == "QUOTA_REACHED" and rows[0]["coverage"] == "UNKNOWN"
    with storage.transaction(other, consistent_read=True) as conn:
        assert conn.scalar(select(func.count()).select_from(audit_events).where(
            audit_events.c.event_type == "EIS_223_FAILED_CAPTURE_DIAGNOSTIC"
        )) == 0
    with pytest.raises(ValueError, match="CAPTURE_DIAGNOSTIC_CONFLICT"):
        worker._audit_capture_failure(storage, window.window_key, window.response_sha256,
                                      checked, "OTHER")


@pytest.mark.parametrize("field", ["actor_id", "event_type", "object_type", "occurred_at"])
def test_capture_reconcile_rejects_conflicting_audit_identity(
    request, monkeypatch, tmp_path, field
):
    storage = request.getfixturevalue("pg_storage")
    company = "capture-" + uuid4().hex
    window = fetch(Transport()).window
    checked = datetime.now(UTC)
    monkeypatch.setattr(worker, "COMPANY", company)
    monkeypatch.setattr(worker, "CAPTURE_KEY", window.window_key)
    record_attempt(storage, company, window.window_key, "FAILED", actor_id="test",
                   checked_at=checked, response_sha256=window.response_sha256, reason="SYNC_FAILED")

    class Outage:
        @contextmanager
        def transaction(self, tenant, **kwargs):
            if not kwargs.get("consistent_read"):
                raise OSError("audit outage")
            with storage.transaction(tenant, **kwargs) as conn:
                yield conn

    root = tmp_path / "capture"
    with pytest.raises(OSError, match="audit outage"):
        worker.retain_failed_223(Outage(), window, TOKEN, checked, root=root)
    manifest = next((root / company).glob("*/manifest.json"))
    encoded = manifest.read_bytes()
    attempt_id = json.loads(encoded)["attempt_id"]
    event = dict(
        company_id=company,
        event_id=str(uuid5(NAMESPACE_URL, "tendox:eis-223-capture:" + attempt_id)),
        actor_id=worker.ACTOR, event_type="EIS_223_FAILED_WINDOW_RETAINED",
        object_type="EIS_223_SOURCE_WINDOW", object_id=window.window_key, occurred_at=checked,
        basis={"attempt_id": attempt_id, "manifest_sha256": hashlib.sha256(encoded).hexdigest(),
               "response_sha256": window.response_sha256, "coverage": "UNKNOWN"},
    )
    event[field] = checked + timedelta(seconds=1) if field == "occurred_at" else "conflicting"
    with storage.transaction(company) as conn:
        conn.execute(insert(audit_events).values(**event))
    with pytest.raises(ValueError, match="CAPTURE_AUDIT_CONFLICT"):
        worker.reconcile_failed_223(storage, root, TOKEN)


@pytest.mark.parametrize(
    "family,reason,detail",
    [
        ("purchaseNotice", "WINDOW_BYTES_LIMIT",
         {"kind": "WINDOW_BYTES", "downloaded_count": 3, "compressed_mib_floor": 48}),
        ("purchaseRejection", "ARCHIVE_SET_MISMATCH",
         {"kind": "ARCHIVE_SET", "cause": "UID_MISMATCH"}),
    ],
)
@pytest.mark.usefixtures("pg_storage")
def test_fetch_diagnostic_is_atomic_tenant_audit(request, family, reason, detail):
    from procurement.storage.models import eis_223_event_sync_attempts, eis_223_sync_attempts

    storage = request.getfixturevalue("pg_storage")
    company, other = "diag-" + uuid4().hex, "diag-" + uuid4().hex
    key = f"getDocsIP/RI223/77/2026-10-30+03:00/{family}"
    checked = datetime.now(UTC)
    record_attempt(storage, company, key, "FAILED", actor_id="test", checked_at=checked,
                   response_sha256=None, reason=reason, fetch_detail=detail)
    table = eis_223_event_sync_attempts if family == "purchaseRejection" else eis_223_sync_attempts
    with storage.transaction(company, consistent_read=True) as conn:
        attempt = conn.execute(
            select(table.c.attempt_id).where(table.c.company_id == company)
        ).one()
        basis = conn.execute(select(audit_events.c.basis).where(
            audit_events.c.company_id == company,
            audit_events.c.event_type == "EIS_223_SYNC_ATTEMPT",
        )).scalar_one()
        assert basis["attempt_id"] == attempt.attempt_id
        assert basis["fetch_detail"] == detail and basis["coverage"] == "UNKNOWN"
        assert basis["response_sha256"] is None
    with storage.transaction(other, consistent_read=True) as conn:
        assert conn.scalar(select(func.count()).select_from(audit_events).where(
            audit_events.c.company_id == other,
            audit_events.c.event_type == "EIS_223_SYNC_ATTEMPT",
        )) == 0
        assert conn.scalar(select(func.count()).select_from(audit_events).where(
            audit_events.c.company_id == company,
            audit_events.c.event_type == "EIS_223_SYNC_ATTEMPT",
        )) == 0
        assert conn.scalar(select(func.count()).select_from(table).where(
            table.c.company_id == company
        )) == 0


@pytest.mark.usefixtures("pg_storage")
def test_fetch_diagnostic_audit_failure_rolls_back_attempt(request):
    from procurement.storage.models import eis_223_sync_attempts

    storage = request.getfixturevalue("pg_storage")
    company = "diag-" + uuid4().hex
    key = "getDocsIP/RI223/77/2026-10-30+03:00/purchaseNotice"

    class FailingAudit:
        @contextmanager
        def transaction(self, tenant, **kwargs):
            with storage.transaction(tenant, **kwargs) as conn:
                class Proxy:
                    def execute(self, stmt, *args, **kw):
                        if getattr(stmt, "table", None) is audit_events:
                            raise RuntimeError("audit unavailable")
                        return conn.execute(stmt, *args, **kw)
                yield Proxy()

    with pytest.raises(RuntimeError, match="audit unavailable"):
        record_attempt(FailingAudit(), company, key, "FAILED", actor_id="test",
                       checked_at=datetime.now(UTC), response_sha256=None,
                       reason="WINDOW_BYTES_LIMIT", fetch_detail={
                           "kind": "WINDOW_BYTES", "downloaded_count": 3,
                           "compressed_mib_floor": 48,
                       })
    with storage.transaction(company, consistent_read=True) as conn:
        assert conn.scalar(select(func.count()).select_from(eis_223_sync_attempts).where(
            eis_223_sync_attempts.c.company_id == company
        )) == 0
