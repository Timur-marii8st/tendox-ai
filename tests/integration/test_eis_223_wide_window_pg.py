"""Four-archive admission and downgrade safety on an explicitly isolated DB."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from migration_support import assert_direct_downgrade_guard, historical_database
from sqlalchemy import create_engine, func, insert, select, text
from sqlalchemy.exc import DBAPIError
from test_eis_223_index_pg import counts
from test_eis_223_index_pg import storage as storage_fixture

from procurement.storage.eis_223_index import (
    Eis223IndexConflict,
    Eis223ReadyWindow,
    ingest_notice223_window,
)
from procurement.storage.models import eis_223_archive_sources, eis_223_windows
from test_eis_223_archive import xml, zip_bytes


@pytest.fixture(scope="module")
def storage():
    yield from storage_fixture.__wrapped__()


def wide_window(*, response="a" * 64, conflict=False, count=4):
    archives = tuple(
        zip_bytes([(f"notice-{i}.xml", xml().replace(b"32600000001", f"3260000000{i}".encode()))])
        for i in range(1, count + 1)
    )
    if conflict:
        archives = (
            *archives[:3],
            zip_bytes(
                [
                    (
                        "notice-4.xml",
                        xml()
                        .replace(b"32600000001", b"32600000004")
                        .replace("Бумага А4 80".encode(), "Другие данные".encode()),
                    )
                ]
            ),
        )
    return Eis223ReadyWindow(
        window_key="getDocsIP/RI223/77/2026-10-02+03:00/purchaseNoticeAESMBO",
        response_sha256=response,
        prepared_sha256="b" * 64,
        archives=archives,
        archive_urls=tuple(
            "https://int44.zakupki.gov.ru/dstore/common/download/compound"
            "?docRequestUid=11111111-1111-4111-8111-111111111111&compoundUid=" + f"{i:032X}"
            for i in range(1, count + 1)
        ),
    )


def test_migration_downgrade_roundtrip_before_wide_history(storage):
    with historical_database(
        expected_database="procurement_eis_test_20261004_s176",
        revision="20261004_01",
    ) as database:
        command.downgrade(database.config, "20261003_05")
        engine = create_engine(database.admin_url)
        try:
            with engine.connect() as conn:
                assert conn.scalar(text("SELECT version_num FROM alembic_version")) == (
                    "20261003_05"
                )
                definition = conn.scalar(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conname='ck_eis_223_counts'"
                    )
                )
                assert "<= 2" in definition
            command.upgrade(database.config, "20261004_01")
            with engine.connect() as conn:
                assert conn.scalar(text("SELECT version_num FROM alembic_version")) == (
                    "20261004_01"
                )
                definition = conn.scalar(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conname='ck_eis_223_counts'"
                    )
                )
                assert "<= 4" in definition
        finally:
            engine.dispose()


def test_four_archives_atomic_replay_rls_and_database_cap(storage):
    company = "wide-" + uuid4().hex
    ready = wide_window()
    first = ingest_notice223_window(storage, company, ready, actor_id="test")
    assert first.archive_count == first.record_count == first.new_versions == 4
    before = counts(storage, company)
    replay = ingest_notice223_window(storage, company, ready, actor_id="retry")
    assert replay.replayed and replay.new_versions == 0 and counts(storage, company) == before
    with storage.transaction(company, consistent_read=True) as conn:
        assert conn.scalar(select(func.count()).select_from(eis_223_archive_sources)) == 4
    with storage.transaction("other-" + company, consistent_read=True) as conn:
        assert conn.scalar(select(func.count()).select_from(eis_223_windows)) == 0
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(
            insert(eis_223_windows).values(
                company_id=company,
                window_key=ready.window_key,
                response_sha256="e" * 64,
                prepared_sha256="f" * 64,
                manifest_sha256="d" * 64,
                archive_count=9,
                record_count=9,
                ingested_at=datetime.now(UTC),
            )
        )
    assert counts(storage, company) == before


def test_last_archive_version_conflict_rolls_back_every_new_source(storage):
    company = "wide-conflict-" + uuid4().hex
    ingest_notice223_window(storage, company, wide_window(), actor_id="test")
    before = counts(storage, company)
    with pytest.raises(Eis223IndexConflict, match="NOTICE_VERSION_CONFLICT"):
        ingest_notice223_window(
            storage, company, wide_window(response="c" * 64, conflict=True), actor_id="test"
        )
    assert counts(storage, company) == before


def test_downgrade_does_not_hide_wide_history_of_another_tenant(storage):
    company = "wide-downgrade-" + uuid4().hex
    ingest_notice223_window(storage, company, wide_window(), actor_id="test")
    before = counts(storage, company)
    assert_direct_downgrade_guard(
        "20261004_01_eis_223_wide_archive_set",
        expected_database="procurement_eis_test_20261004_s176",
        match="wide archive history must be preserved",
        tenant_context="unrelated-" + uuid4().hex,
    )
    engine = create_engine(os.environ["DATABASE_ADMIN_URL"])
    try:
        with engine.connect() as conn:
            assert "<= 8" in conn.scalar(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname='ck_eis_223_counts'"
                )
            )
    finally:
        engine.dispose()
    assert counts(storage, company) == before


def test_eight_archives_replay_tenant_and_new_migration_guard(storage):
    company = "eight-" + uuid4().hex
    ready = wide_window(count=8)
    result = ingest_notice223_window(storage, company, ready, actor_id="test")
    assert result.archive_count == result.record_count == result.new_versions == 8
    before = counts(storage, company)
    assert ingest_notice223_window(storage, company, ready, actor_id="retry").replayed
    assert counts(storage, company) == before
    with storage.transaction("other-" + company, consistent_read=True) as conn:
        assert conn.scalar(select(func.count()).select_from(eis_223_windows)) == 0
    assert_direct_downgrade_guard(
        "20261008_01_eis_223_eight_archive_window",
        expected_database="procurement_eis_test_20261004_s176",
        match="223 wide archive history must be preserved",
        tenant_context="other-" + company,
    )
    assert counts(storage, company) == before


def test_large_notice_xml_checkpoint_replay_and_tenant_isolation(storage):
    from io import BytesIO
    from zipfile import ZIP_DEFLATED, ZipFile

    from procurement.storage.models import eis_223_notice_versions

    company = "notice-large-" + uuid4().hex
    raw = xml() + b"<!--" + b"x" * 9_471_478 + b"-->"
    stream = BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("large.xml", raw)
    ready = wide_window().model_copy(
        update={"archives": (stream.getvalue(),), "archive_urls": wide_window().archive_urls[:1]}
    )
    result = ingest_notice223_window(storage, company, ready, actor_id="test")
    assert result.new_versions == 1
    before = counts(storage, company)
    assert ingest_notice223_window(storage, company, ready, actor_id="test").new_versions == 0
    assert counts(storage, company) == before
    with storage.transaction(company) as conn:
        assert conn.scalar(select(func.count()).select_from(eis_223_notice_versions)) == 1
    with storage.transaction(company + "-foreign") as conn:
        assert conn.scalar(select(func.count()).select_from(eis_223_notice_versions)) == 0
