"""A complete conflict inventory is tenant evidence, never corpus admission."""

from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from test_eis_notice_index_pg import storage as eis_storage_fixture

from procurement.sources.eis_notice_conflicts import diagnose_notice_conflicts
from procurement.sources.eis_rejected_evidence import retain_rejected_window
from procurement.storage.eis_notice_index import EisReadyWindow
from procurement.storage.eis_rejected_evidence import (
    record_notice_conflict_diagnosis,
    record_rejected_evidence,
)
from procurement.storage.models import audit_events, eis_feed_windows, eis_notice_versions


@pytest.fixture(scope="module")
def storage():
    yield from eis_storage_fixture.__wrapped__()


def retained_pair(company, tmp_path):
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        for index, seconds in enumerate(("01", "02")):
            xml = f"""<e:export xmlns:e="http://zakupki.gov.ru/oos/export/1"
                xmlns:ep="http://zakupki.gov.ru/oos/EPtypes/1">
                <e:epNotificationEF2020><ep:id>123</ep:id><ep:versionNumber>1</ep:versionNumber>
                <ep:commonInfo><ep:purchaseNumber>9000000000000000001</ep:purchaseNumber>
                <ep:publishDTInEIS>2026-09-29T09:49:{seconds}+03:00</ep:publishDTInEIS>
                </ep:commonInfo><ep:notificationInfo><ep:procedureInfo><ep:collectingInfo>
                <ep:startDT>2026-09-29T09:49:{seconds}+03:00</ep:startDT>
                </ep:collectingInfo></ep:procedureInfo></ep:notificationInfo>
                </e:epNotificationEF2020></e:export>""".encode()
            archive.writestr(f"variant-{index}.xml", xml)
    archives = (output.getvalue(),)
    window = EisReadyWindow(
        "getDocsIP/PRIZ/77/2026-09-29+03:00",
        "a" * 64,
        1,
        archives,
        "b" * 64,
        (
            "https://int44.zakupki.gov.ru/dstore/common/download/compound?docRequestUid="
            "11111111-1111-4111-8111-111111111111&compoundUid=" + "A" * 32,
        ),
    )
    evidence = retain_rejected_window(
        window,
        company,
        "DUPLICATE_NOTICE_VERSION",
        "synthetic-token-123456",
        datetime.now(UTC),
        tmp_path,
    )
    assert evidence.status == "RETAINED"
    return window, evidence, diagnose_notice_conflicts(archives, "synthetic-token-123456")


def test_diagnosis_immutable_replay_retains_variants_but_never_checkpoints(storage, tmp_path):
    company = f"conflict-{uuid4()}"
    window, evidence, diagnosis = retained_pair(company, tmp_path)
    with pytest.raises(ValueError, match="RETENTION_UNAUDITED"):
        record_notice_conflict_diagnosis(storage, company, evidence, diagnosis, actor_id="test")
    record_rejected_evidence(storage, company, evidence, actor_id="test")
    event = record_notice_conflict_diagnosis(storage, company, evidence, diagnosis, actor_id="test")
    assert (
        record_notice_conflict_diagnosis(storage, company, evidence, diagnosis, actor_id="retry")
        == event
    )
    with storage.transaction(company, consistent_read=True) as conn:
        assert conn.scalar(select(func.count()).select_from(audit_events)) == 2
        basis = conn.scalar(select(audit_events.c.basis).where(audit_events.c.event_id == event))
        assert basis["canonical_admission"] == "REJECTED" and basis["coverage"] == "UNKNOWN"
        assert basis["diagnosis"]["sha256"] == diagnosis.sha256
        assert basis["diagnosis"] == diagnosis.model_dump(mode="json")
        assert conn.scalar(select(func.count()).select_from(eis_notice_versions)) == 0
        assert (
            conn.scalar(
                select(func.count())
                .select_from(eis_feed_windows)
                .where(
                    eis_feed_windows.c.window_key == window.window_key,
                )
            )
            == 0
        )
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(update(audit_events).where(audit_events.c.event_id == event).values(basis={}))


def test_diagnosis_requires_exact_tenant_and_ordered_archive_set(storage, tmp_path):
    company = f"conflict-{uuid4()}"
    _, evidence, diagnosis = retained_pair(company, tmp_path)
    record_rejected_evidence(storage, company, evidence, actor_id="test")
    event = record_notice_conflict_diagnosis(storage, company, evidence, diagnosis, actor_id="test")
    other = f"conflict-{uuid4()}"
    with storage.transaction(other, consistent_read=True) as conn:
        assert (
            conn.scalar(
                select(func.count())
                .select_from(audit_events)
                .where(
                    audit_events.c.event_id == event,
                )
            )
            == 0
        )
    with pytest.raises(ValueError, match="AUDIT_INVALID"):
        record_notice_conflict_diagnosis(storage, other, evidence, diagnosis, actor_id="test")
    changed = evidence.model_copy(update={"archive_sha256s": ("f" * 64,)})
    with pytest.raises(ValueError, match="AUDIT_INVALID"):
        record_notice_conflict_diagnosis(storage, company, changed, diagnosis, actor_id="test")
    changed = evidence.model_copy(update={"window_key": "changed"})
    with pytest.raises(ValueError, match="RETENTION_UNAUDITED"):
        record_notice_conflict_diagnosis(storage, company, changed, diagnosis, actor_id="test")
    with storage.transaction(company, consistent_read=True) as conn:
        assert conn.scalar(select(func.count()).select_from(audit_events)) == 2
