"""Isolated PostgreSQL recovery: exact latest evidence and standard full-archive intake."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, insert, select
from test_eis_corpus_fairness_pg import storage as storage_fixture

from procurement.sources import eis_attachment_recovery as subject
from procurement.storage.eis_sync_journal import EisSyncJournal
from procurement.storage.models import (
    audit_events,
    eis_feed_windows,
    eis_notice_versions,
    eis_sync_attempts,
    eis_sync_targets,
)
from test_eis_feed_archive import _archive, _notice_with_attachments
from test_eis_feed_sync import TOKEN, FakeTransport

NOW = datetime(2026, 10, 5, tzinfo=UTC)
KEY = "getDocsIP/PRIZ/50/2026-09-25+03:00"


@pytest.fixture(scope="module")
def storage():
    yield from storage_fixture.__wrapped__()


def seed(
    conn, company, key, *, at=None, code="ATTACHMENT_COUNT_LIMIT", outcome="FAILED", attempt_id=None
):
    conn.execute(
        insert(eis_sync_targets).values(
            company_id=company,
            window_key=key,
            planned_by="test",
            planned_at=NOW - timedelta(days=10),
            coverage="UNKNOWN",
        )
    )
    attempt_id = attempt_id or str(uuid4())
    conn.execute(
        insert(eis_sync_attempts).values(
            company_id=company,
            window_key=key,
            attempt_id=attempt_id,
            actor_id="test",
            outcome=outcome,
            reason_code=code if outcome == "FAILED" else None,
            source_response_sha256="a" * 64,
            attempted_at=at or NOW - timedelta(hours=25),
        )
    )
    return attempt_id


def counts(storage, company):
    with storage.transaction(company, consistent_read=True) as conn:
        return tuple(
            conn.scalar(
                select(func.count()).select_from(table).where(table.c.company_id == company)
            )
            for table in (eis_sync_attempts, eis_sync_targets, audit_events, eis_feed_windows)
        )


def test_plan_exact_latest_completed_windows_tenant_and_readonly(storage):
    company, other = f"recovery-{uuid4().hex}", f"recovery-{uuid4().hex}"
    hour = "getDocsIP/PRIZ/77/2026-10-02/12+03:00/epNotificationEOK2020"
    transport = "getDocsIP/PRIZ/78/2026-10-02+03:00"
    excluded = {
        "cool": ("getDocsIP/PRIZ/21/2026-10-02+03:00", {"at": NOW - timedelta(hours=23)}),
        "invalid_day": ("getDocsIP/PRIZ/22/2026-99-99+03:00", {}),
        "invalid_hour": ("getDocsIP/PRIZ/23/2026-10-02/24+03:00", {}),
        "future": ("getDocsIP/PRIZ/24/2026-10-05+03:00", {}),
        "future_hour": ("getDocsIP/PRIZ/24/2026-10-05/03+03:00", {}),
        "parser": ("getDocsIP/PRIZ/25/2026-10-02+03:00", {"code": "ATTACHMENT_METADATA_LIMIT"}),
        "no_data": ("getDocsIP/PRIZ/26/2026-10-02+03:00", {"outcome": "NO_DATA"}),
        "canonical": ("getDocsIP/PRIZ/27/2026-10-02+03:00", {}),
        "shadowed": ("getDocsIP/PRIZ/28/2026-10-02+03:00", {}),
    }
    with storage.transaction(company) as conn:
        ids = {key: seed(conn, company, key) for key in (KEY, hour, transport)}
        for key, options in excluded.values():
            seed(conn, company, key, **options)
        conn.execute(
            insert(eis_sync_attempts).values(
                company_id=company,
                window_key=excluded["shadowed"][0],
                attempt_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
                actor_id="test",
                outcome="NO_DATA",
                reason_code=None,
                source_response_sha256="b" * 64,
                attempted_at=NOW - timedelta(hours=25),
            )
        )
        for key, kind in (
            (excluded["canonical"][0], "LEGACY_CANONICAL"),
            (transport, "VARIANT_TRANSPORT"),
        ):
            conn.execute(
                insert(eis_feed_windows).values(
                    company_id=company,
                    window_key=key,
                    response_sha256="b" * 64,
                    manifest_sha256="c" * 64,
                    archive_count=1,
                    notice_count=0,
                    coverage="UNKNOWN",
                    intake_kind=kind,
                    ingested_at=NOW,
                )
            )
    with storage.transaction(other) as conn:
        seed(conn, other, KEY, outcome="NO_DATA")
    journal = EisSyncJournal(storage, company, "test")
    before = counts(storage, company)
    plan = subject.read_attachment_recovery_plan(journal, now=NOW, limit=2)
    assert plan.eligible_count == 3 and len(plan.candidates) == 2
    all_plan = subject.read_attachment_recovery_plan(journal, now=NOW)
    assert {item.window_key for item in all_plan.candidates} == {KEY, hour, transport}
    assert all(item.original_attempt_id == ids[item.window_key] for item in all_plan.candidates)
    assert all(item.original_source_response_sha256 == "a" * 64 for item in all_plan.candidates)
    assert counts(storage, company) == before
    candidate = next(item for item in all_plan.candidates if item.window_key == KEY)
    assert subject._recheck(journal, candidate, NOW) is None
    assert (
        subject._recheck(journal, candidate, NOW - timedelta(hours=2)) == "SOURCE_CANDIDATE_CHANGED"
    )


class MetadataTransport(FakeTransport):
    def __init__(self):
        super().__init__(expect_date=True)
        self.content = _archive(
            ("notice.xml", _notice_with_attachments("0848300054826000154", 101))
        )

    async def download(self, url, token):
        assert url == self.prepared_url and token == TOKEN
        self.downloads += 1
        return 200, self.content


def test_standard_sync_recovers_more_than_100_metadata_entries_without_changing_original_attempt(
    storage, monkeypatch
):
    company = f"recovery-import-{uuid4().hex}"
    with storage.transaction(company) as conn:
        original_id = seed(conn, company, KEY)
        original = dict(
            conn.execute(select(eis_sync_attempts).where(eis_sync_attempts.c.company_id == company))
            .mappings()
            .one()
        )
    journal = EisSyncJournal(storage, company, "test")
    monkeypatch.setattr(subject, "resource_gate", lambda *args, **kwargs: None)
    transport = MetadataTransport()
    report = asyncio.run(
        subject.run_attachment_recovery(journal, TOKEN, now=NOW, transport=transport)
    )
    assert report.status == "FINISHED" and report.attempted == report.selected == 1
    outcome = report.outcomes[0]
    assert outcome.outcome == "SYNCED" and outcome.canonical_checkpoint
    assert outcome.new_versions == 1 and outcome.new_attempt_id != original_id
    assert transport.posts == 2 and transport.downloads == 1
    with storage.transaction(company, consistent_read=True) as conn:
        saved = dict(
            conn.execute(
                select(eis_sync_attempts).where(
                    eis_sync_attempts.c.company_id == company,
                    eis_sync_attempts.c.attempt_id == original_id,
                )
            )
            .mappings()
            .one()
        )
        attachments = conn.execute(
            select(eis_notice_versions.c.attachments).where(
                eis_notice_versions.c.company_id == company
            )
        ).scalar_one()
    assert saved == original and len(attachments) == 101
    assert subject.read_attachment_recovery_plan(journal, now=NOW).eligible_count == 0
