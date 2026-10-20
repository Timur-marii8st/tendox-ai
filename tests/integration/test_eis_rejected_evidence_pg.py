"""Quarantine audit must never create a successful source checkpoint."""

import hashlib
import uuid
from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZipFile

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from test_eis_notice_index_pg import _archive
from test_eis_notice_index_pg import storage as eis_storage_fixture

from procurement.sources.eis_feed_archive import EisFeedArchiveError
from procurement.sources.eis_rejected_evidence import retain_rejected_window
from procurement.storage.eis_notice_index import EisReadyWindow, preflight_ready_window
from procurement.storage.eis_rejected_evidence import record_rejected_evidence
from procurement.storage.models import audit_events, eis_feed_windows, eis_notice_versions


@pytest.fixture(scope="module")
def storage():
    yield from eis_storage_fixture.__wrapped__()


def rejected(company, tmp_path):
    raw = BytesIO()
    with ZipFile(raw, "w") as output:
        for name, title in (("first.xml", "first"), ("second.xml", "different")):
            with ZipFile(BytesIO(_archive("9000000000000000001", title=title))) as source:
                output.writestr(name, source.read(source.namelist()[0]))
    window = EisReadyWindow(
        "getDocsIP/PRIZ/77/2026-09-29+03:00",
        "a" * 64,
        1,
        (raw.getvalue(),),
        "b" * 64,
        (
            "https://int44.zakupki.gov.ru/dstore/common/download/compound?docRequestUid=11111111-1111-4111-8111-111111111111&compoundUid="
            + "A" * 32,
        ),
    )
    with pytest.raises(EisFeedArchiveError, match="DUPLICATE_NOTICE_VERSION"):
        preflight_ready_window(window)
    evidence = retain_rejected_window(
        window,
        company,
        "DUPLICATE_NOTICE_VERSION",
        "synthetic-token-123456",
        datetime.now(UTC),
        tmp_path,
    )
    assert evidence.status == "RETAINED" and evidence.complete_set
    assert (
        evidence.manifest_sha256
        == hashlib.sha256((tmp_path / evidence.relative_manifest_path).read_bytes()).hexdigest()
    )
    return window, evidence


def test_rejected_audit_replay_immutable_and_no_checkpoint(storage, tmp_path):
    company = f"rejected-{uuid.uuid4()}"
    window, evidence = rejected(company, tmp_path)
    event = record_rejected_evidence(storage, company, evidence, actor_id="test")
    assert record_rejected_evidence(storage, company, evidence, actor_id="retry") == event
    with storage.transaction(company, consistent_read=True) as conn:
        assert (
            conn.scalar(
                select(func.count())
                .select_from(audit_events)
                .where(audit_events.c.event_id == event)
            )
            == 1
        )
        assert (
            conn.scalar(
                select(func.count())
                .select_from(eis_feed_windows)
                .where(eis_feed_windows.c.window_key == window.window_key)
            )
            == 0
        )
        assert conn.scalar(select(func.count()).select_from(eis_notice_versions)) == 0
        row = (
            conn.execute(select(audit_events).where(audit_events.c.event_id == event))
            .mappings()
            .one()
        )
        assert row["basis"]["coverage"] == "UNKNOWN"
        assert row["basis"]["evidence"]["manifest_sha256"] == evidence.manifest_sha256
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(update(audit_events).where(audit_events.c.event_id == event).values(basis={}))


def test_rejected_audit_is_tenant_scoped_and_replay_binding_cannot_change(storage, tmp_path):
    company = f"rejected-{uuid.uuid4()}"
    _, evidence = rejected(company, tmp_path)
    event = record_rejected_evidence(storage, company, evidence, actor_id="test")
    other = f"rejected-{uuid.uuid4()}"
    with storage.transaction(other, consistent_read=True) as conn:
        assert (
            conn.scalar(
                select(func.count())
                .select_from(audit_events)
                .where(audit_events.c.event_id == event)
            )
            == 0
        )
    with pytest.raises(ValueError, match="AUDIT_INVALID"):
        record_rejected_evidence(storage, other, evidence, actor_id="test")
    with pytest.raises(ValueError, match="REPLAY_CONFLICT"):
        record_rejected_evidence(
            storage, company, evidence.model_copy(update={"window_key": "changed"}), actor_id="test"
        )
