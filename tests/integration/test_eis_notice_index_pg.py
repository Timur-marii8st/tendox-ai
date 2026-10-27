"""PostgreSQL gate for EIS version, replay, RLS and transaction rollback."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from zipfile import ZipFile

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.exc import DBAPIError

from procurement.sources.eis_feed_sync import EisDateSelection
from procurement.storage.eis_index_query import search_eis_index
from procurement.storage.eis_notice_index import (
    EisIndexConflict,
    EisReadyWindow,
    ingest_ready_window,
)
from procurement.storage.eis_sync_journal import EisSyncJournal
from procurement.storage.models import (
    audit_events,
    eis_feed_archive_sources,
    eis_feed_windows,
    eis_notice_search_keys,
    eis_notice_versions,
    eis_procedure_events,
    eis_sync_attempts,
    eis_sync_targets,
)
from procurement.storage.repository import PostgresStorage


def test_mandatory_turn_keeps_recent_debt_ahead_of_history(storage):
    from procurement.sources.eis_feed_sync import EisHourSelection
    from procurement.sources.eis_freshness import EisFreshnessScope, eligible_freshness

    company = "mandatory-" + uuid.uuid4().hex
    journal = EisSyncJournal(storage, company, "worker")
    now = datetime.now(UTC)
    local = now + timedelta(hours=3)
    old = EisHourSelection("50", local.date() - timedelta(days=10), 0, 3)
    journal.plan((old,))
    scope = EisFreshnessScope(("50",), checkpointed=True, mandatory_only=True)
    due = eligible_freshness(journal, scope, now=now, limit=60)
    assert old.window_key not in {t.selection.window_key for t in due}
    assert all(t.selection.day >= local.date() - timedelta(days=3) for t in due)
    with storage.transaction(company) as conn:
        assert (
            conn.scalar(
                select(func.count())
                .select_from(eis_sync_targets)
                .where(
                    eis_sync_targets.c.company_id == company,
                    eis_sync_targets.c.window_key == old.window_key,
                )
            )
            == 1
        )  # Excluding history from a turn must never delete its checkpoint.


def test_checkpoint_hours_survive_restart_midnight_and_reconstruct_holes(storage):
    from procurement.sources.eis_feed_sync import EisHourSelection
    from procurement.sources.eis_freshness import (
        EisFreshnessScope,
        eligible_freshness,
        read_due_freshness,
    )

    company = "checkpoint-" + uuid.uuid4().hex
    journal = EisSyncJournal(storage, company, "worker")
    now = datetime.now(UTC)
    scope = EisFreshnessScope(("50",), ("epNotificationEF2020",), checkpointed=True)
    first = eligible_freshness(journal, scope, now=now, limit=60)
    hour = first[0].selection
    assert isinstance(hour, EisHourSelection)
    old = EisHourSelection("50", hour.day - timedelta(days=1), hour.hour, 3)
    journal.plan((old,))
    journal.record(hour.window_key, "NO_DATA", source_response_sha256="a" * 64)
    assert hour.window_key not in {
        t.selection.window_key for t in read_due_freshness(journal, scope, now=now, limit=60)
    }
    # A process restart has no in-memory cursor. New hours outrank old retained
    # gaps, and a week of missed planning is reconstructed, never marked covered.
    restarted = EisSyncJournal(storage, company, "restart-worker")
    due = eligible_freshness(restarted, scope, now=now + timedelta(days=8), limit=60)
    assert due[0].selection.day == hour.day + timedelta(days=8)
    assert old.window_key in {t.selection.window_key for t in due}
    assert hour.window_key not in {t.selection.window_key for t in due}
    assert len(due) <= 60
    with storage.transaction(company) as conn:
        count = conn.scalar(
            select(func.count())
            .select_from(eis_sync_targets)
            .where(eis_sync_targets.c.company_id == company)
        )
    # The read probe cannot write checkpoints or audits.
    assert read_due_freshness(restarted, scope, now=now + timedelta(days=8), limit=60)
    with storage.transaction(company) as conn:
        assert count == conn.scalar(
            select(func.count())
            .select_from(eis_sync_targets)
            .where(eis_sync_targets.c.company_id == company)
        )
    foreign = read_due_freshness(
        EisSyncJournal(storage, "foreign-" + uuid.uuid4().hex, "test"),
        scope,
        now=now + timedelta(days=8),
        limit=60,
    )
    assert old.window_key not in {t.selection.window_key for t in foreign}


def test_checkpoint_final_day_debt_survives_eight_day_outage(storage):
    from procurement.sources.eis_freshness import EisFreshnessScope, eligible_freshness

    company = "checkpoint-debt-" + uuid.uuid4().hex
    journal = EisSyncJournal(storage, company, "worker")
    now = datetime.now(UTC)
    scope = EisFreshnessScope(
        ("50",), ("epNotificationEF2020",), checkpointed=True, mandatory_only=True
    )
    source_day = (now + timedelta(hours=3)).date()
    day = EisDateSelection("50", source_day, 3)
    journal.plan((day,))
    journal.record(day.window_key, "NO_DATA", source_response_sha256="a" * 64)
    restarted = eligible_freshness(journal, scope, now=now + timedelta(days=8), limit=60)
    assert day.window_key in {t.selection.window_key for t in restarted}
    journal.record(day.window_key, "FAILED", reason_code="SOURCE_TRANSPORT_FAILED")
    retried = eligible_freshness(journal, scope, now=now + timedelta(days=8), limit=60)
    assert day.window_key in {t.selection.window_key for t in retried}
    # A thousand newer historical rows must not hide mandatory debt behind SQL LIMIT.
    historical = tuple(
        EisDateSelection("50", source_day + timedelta(days=n), 3) for n in range(1, 1002)
    )
    for offset in range(0, len(historical), 31):
        journal.plan(historical[offset : offset + 31])
    distant = eligible_freshness(journal, scope, now=now + timedelta(days=1008), limit=60)
    assert day.window_key in {t.selection.window_key for t in distant}


def test_checkpoint_new_hours_precede_bounded_daily_rechecks(storage):
    from procurement.sources.eis_freshness import EisFreshnessScope, eligible_freshness

    company = "checkpoint-fair-" + uuid.uuid4().hex
    journal = EisSyncJournal(storage, company, "worker")
    scope = EisFreshnessScope(("50", "77", "78"), checkpointed=True)
    now = datetime.now(UTC)
    first = eligible_freshness(journal, scope, now=now, limit=60)
    for t in first:
        if t.lane == "RECENT_HOUR":
            journal.record(t.selection.window_key, "NO_DATA", source_response_sha256="a" * 64)
    next_hour = eligible_freshness(journal, scope, now=now + timedelta(hours=1), limit=60)
    assert all(t.lane == "RECENT_HOUR" for t in next_hour[:15])
    assert sum(t.lane == "RECONCILE_DAY" for t in next_hour) <= 7
    assert len({t.selection.window_key for t in next_hour}) == len(next_hour)


def test_freshness_dispatch_is_read_only_missing_targets_and_foreground(storage, monkeypatch):
    from procurement import eis_freshness_dispatch_cli as dispatch
    from procurement.sources.eis_freshness import (
        EisFreshnessScope,
        eligible_freshness,
        read_due_freshness,
    )
    from procurement.storage.eis_freshness_requests import (
        EisRefreshRequestPayload,
        pending_refresh_targets,
        plan_refresh_request,
    )

    company = f"dispatch-{uuid.uuid4()}"
    journal = EisSyncJournal(storage, company, "worker")
    now = datetime.now(UTC)
    # Keep the generated scope stable across the test's writes.
    scope = EisFreshnessScope(("50",))
    monkeypatch.setattr(dispatch, "resource_gate", lambda *a, **k: None)

    def counts():
        with storage.transaction(company) as connection:
            return tuple(
                connection.execute(
                    select(func.count()).select_from(table).where(table.c.company_id == company)
                ).scalar_one()
                for table in (eis_sync_targets, eis_sync_attempts, audit_events)
            )

    before = counts()
    first = read_due_freshness(journal, scope, now=now, limit=24)
    expected_lane = (
        "RECENT_HOUR"
        if any(item.lane == "RECENT_HOUR" for item in scope.targets(now))
        else "RECONCILE_DAY"
    )
    assert first and first[0].lane == expected_lane
    assert dispatch.probe_dispatch(storage, company, scope, now=now).status == "READY"
    assert counts() == before == (0, 0, 0)
    assert eligible_freshness(journal, scope, now=now, limit=24) == first
    for target in scope.targets(now):
        journal.record(target.selection.window_key, "NO_DATA", source_response_sha256="a" * 64)
    checked = datetime.now(UTC) + timedelta(seconds=1)
    # No moving wall-clock scope: use a scope whose targets are pinned to now.
    original_targets = EisFreshnessScope.targets
    monkeypatch.setattr(EisFreshnessScope, "targets", lambda self, at: original_targets(self, now))
    before = counts()
    idle = dispatch.probe_dispatch(storage, company, scope, now=checked)
    assert idle.status == "IDLE" and idle.baseline_due == idle.foreground_due == 0
    assert counts() == before
    # A second tenant cannot inherit this tenant's successful observations.
    assert (
        dispatch.probe_dispatch(storage, f"other-{uuid.uuid4()}", scope, now=checked).status
        == "READY"
    )
    request = plan_refresh_request(
        storage,
        company,
        EisRefreshRequestPayload(query="бумага", regions=("77",)),
        actor_id="operator",
        now=checked,
    )
    before = counts()
    foreground = dispatch.probe_dispatch(storage, company, scope, now=checked)
    assert (
        foreground.status == "READY"
        and foreground.baseline_due == 0
        and foreground.foreground_due > 0
    )
    assert counts() == before  # No additional targets/audit events even for unplanned requests.
    assert pending_refresh_targets(journal, now=request.request.expires_at, plan=False) == ()
    assert counts() == before


def test_foreground_request_is_durable_coalesced_isolated_and_fail_closed(storage):
    from datetime import UTC, datetime, timedelta

    from procurement.storage.eis_freshness_requests import (
        EisRefreshRequestPayload,
        get_refresh_status,
        pending_refresh_targets,
        plan_refresh_request,
    )
    from procurement.storage.eis_sync_journal import EisSyncJournal

    company = f"refresh-{uuid.uuid4()}"
    now = datetime.now(UTC) - timedelta(minutes=2)
    payload = EisRefreshRequestPayload(query="бумага", regions=("50",))
    result = plan_refresh_request(storage, company, payload, actor_id="operator", now=now)
    assert result.status == "QUEUED"
    again = plan_refresh_request(storage, company, payload, actor_id="operator", now=now)
    assert result.request == again.request
    with pytest.raises(ValueError, match="REFRESH_REQUEST_RATE_LIMIT"):
        plan_refresh_request(
            storage,
            company,
            EisRefreshRequestPayload(query="сервер", regions=("50",)),
            actor_id="operator",
            now=now + timedelta(seconds=10),
        )
    with pytest.raises(LookupError, match="REFRESH_REQUEST_NOT_FOUND"):
        get_refresh_status(storage, "other", result.request.request_id, now=now)
    journal = EisSyncJournal(storage, company, "worker")
    targets = pending_refresh_targets(journal, now=now)
    assert tuple(item.selection.window_key for item in targets) == result.request.window_keys
    for index, target in enumerate(targets):
        # A legacy SYNCED without source response evidence cannot finish the request.
        journal.record(
            target.selection.window_key,
            "SYNCED" if index == 0 else "NO_DATA",
            source_response_sha256=None if index == 0 else "a" * 64,
        )
    checked = datetime.now(UTC) + timedelta(seconds=1)
    status = get_refresh_status(storage, company, result.request.request_id, now=checked)
    assert status.status == "PARTIAL" and status.pending_windows == 1
    assert status.freshness == status.coverage == "UNKNOWN"
    pending = pending_refresh_targets(journal, now=checked)
    assert len(pending) == 1 and pending[0] == targets[0]
    journal.record(
        targets[0].selection.window_key, "FAILED", reason_code="DUPLICATE_NOTICE_VERSION"
    )
    checked = datetime.now(UTC) + timedelta(seconds=1)
    assert pending_refresh_targets(journal, now=checked) == ()
    status = get_refresh_status(storage, company, result.request.request_id, now=checked)
    assert status.pending_windows == status.failed_windows == 1
    expired = get_refresh_status(
        storage, company, result.request.request_id, now=now + timedelta(hours=1)
    )
    assert expired.status == "EXPIRED" and expired.pending_windows == 1


@pytest.fixture(scope="module")
def storage() -> PostgresStorage:
    database_url = os.environ.get("DATABASE_URL")
    admin_url = os.environ.get("DATABASE_ADMIN_URL")
    if not database_url or not admin_url:
        pytest.skip("PostgreSQL integration gate requires DATABASE_URL and DATABASE_ADMIN_URL")
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", admin_url.replace("%", "%%"))
    command.upgrade(config, "head")
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        yield PostgresStorage(engine)
    finally:
        engine.dispose()


def _archive(
    number: str,
    *,
    title: str = "Поставка бумаги",
    version: int = 1,
    document_type: str = "epNotificationEF2020",
) -> bytes:
    xml = f"""<export xmlns="http://zakupki.gov.ru/oos/export/1">
<{document_type}><versionNumber>{version}</versionNumber>
<commonInfo><purchaseNumber>{number}</purchaseNumber>
<purchaseObjectInfo>{title}</purchaseObjectInfo></commonInfo>
<notificationInfo/></{document_type}></export>""".encode()
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(f"{number}.xml", xml)
    return output.getvalue()


def _assert_protocol_archive_search_replay_and_downgrade_guard(storage, kind, migration):
    from hashlib import sha256

    from migration_support import assert_direct_downgrade_guard

    from procurement.storage.models import eis_feed_archives
    from test_eis_mixed_number_archive import NUMBER, companion, mixed, window

    company = "ezk-final-" + uuid.uuid4().hex
    raw = mixed(companion(kind))
    bound = window(raw)
    report = ingest_ready_window(storage, company, bound, actor_id="ezk-test")
    assert report.new_versions == report.new_events == 1
    replay = ingest_ready_window(storage, company, bound, actor_id="ezk-test")
    assert replay.replayed and replay.new_versions == replay.new_events == 0
    now = datetime(2026, 10, 26, tzinfo=UTC)
    result = search_eis_index(storage, company, NUMBER, now=now, search_scope="ALL_CACHED")
    assert result.matched_count == 1
    assert result.matched[0].purchase_number == NUMBER
    assert result.matched[0].application_status == "FAIL"
    assert result.matched[0].economic_status == "UNKNOWN"
    assert any(kind in reason for reason in result.matched[0].reasons)
    with storage.transaction(company, consistent_read=True) as conn:
        archive = conn.execute(select(eis_feed_archives)).mappings().one()
        event = conn.execute(select(eis_procedure_events)).mappings().one()
        assert bytes(archive["content"]) == raw
        assert event["archive_sha256"] == sha256(raw).hexdigest()
        assert event["document_id"] == "sha256:" + event["xml_sha256"]
        assert conn.scalar(select(func.count()).select_from(audit_events)) == 1
    with storage.transaction(company + "-foreign", consistent_read=True) as conn:
        assert conn.scalar(select(func.count()).select_from(eis_procedure_events)) == 0
    assert_direct_downgrade_guard(
        migration,
        expected_database="procurement_eis_test_20261005_s209",
        match="ck_eis_event_type_stage",
        tenant_context=company,
    )
    assert search_eis_index(storage, company, NUMBER, now=now).matched_count == 1


def test_ezk_final_complete_archive_search_replay_and_downgrade_guard(storage):
    _assert_protocol_archive_search_replay_and_downgrade_guard(
        storage, "epProtocolEZK2020Final", "20261026_01_ezk_final_companion"
    )


@pytest.mark.parametrize("kind", ["epProtocolEF2020SubmitOffers", "epProtocolEF2020Final"])
def test_ea_protocol_complete_archive_search_replay_and_downgrade_guard(storage, kind):
    _assert_protocol_archive_search_replay_and_downgrade_guard(
        storage, kind, "20261026_02_ef_companions"
    )


def test_short_modifiers_are_compared_in_indexed_item_characteristics(storage):
    company = f"modifiers-{uuid.uuid4()}"
    number = "9000000000000000001"
    with ZipFile(BytesIO(_archive(number, title="Канцтовары"))) as archive:
        xml = archive.read(archive.namelist()[0])
    item_xml = """<notificationInfo><purchaseObjectsInfo><notDrugPurchaseObjectsInfo>
<purchaseObject><name>Бумага для печати</name><KTRU><characteristics>
<characteristicsUsingReferenceInfo><name>Формат</name><values><value>
<qualityDescription>A4</qualityDescription></value></values></characteristicsUsingReferenceInfo>
<characteristicsUsingReferenceInfo><name>Плотность</name><values><value>
<rangeSet><valueRange><min>80</min><max>100</max></valueRange></rangeSet>
</value></values></characteristicsUsingReferenceInfo>
</characteristics></KTRU></purchaseObject></notDrugPurchaseObjectsInfo>
</purchaseObjectsInfo></notificationInfo>""".encode()
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("notice.xml", xml.replace(b"<notificationInfo/>", item_xml))
    window = EisReadyWindow("getDocsIP/PRIZ/50/2026-09-25+03:00", "a" * 64, 1, (output.getvalue(),))
    ingest_ready_window(storage, company, window, actor_id="test")
    assert ingest_ready_window(storage, company, window, actor_id="test").replayed
    now = datetime.now(UTC)
    result = search_eis_index(storage, company, "бумага А4 80", now=now)
    assert result.evaluated_candidate_notices == result.matched_count == 1
    assert result.strong_matched_count == 1 and result.partial_matched_count == 0
    lead = result.matched[0]
    assert lead.match_quality == "STRONG" and lead.economic_status == "UNKNOWN"
    assert [part.value_kind for part in lead.term_evidence] == ["ITEM_NAME", "TEXT", "MINIMUM"]
    assert all(part.locator.startswith("epNotificationEF2020/") for part in lead.term_evidence)
    other = search_eis_index(storage, f"other-{company}", "бумага А4 80", now=now)
    assert other.matched_count == other.inspected_current_notices == 0
    partial = search_eis_index(storage, company, "бумага А3 80", now=now)
    assert partial.matched[0].match_quality == "PARTIAL"
    assert partial.strong_matched_count == 0 and partial.partial_matched_count == 1


def test_by_number_retains_exact_xml_and_is_tenant_scoped(storage: PostgresStorage) -> None:
    company = f"eis-number-{uuid.uuid4()}"
    other = f"eis-number-{uuid.uuid4()}"
    number = "0848300054826000154"
    window = EisReadyWindow(f"getDocsIP/PRIZ/by-number/{number}", "d" * 64, 1, (_archive(number),))
    first = ingest_ready_window(storage, company, window, actor_id="eis-test")
    assert first.new_versions == 1
    assert ingest_ready_window(storage, company, window, actor_id="eis-test").replayed
    with storage.transaction(company, consistent_read=True) as connection:
        assert connection.execute(
            select(eis_notice_versions.c.xml_sha256).where(
                eis_notice_versions.c.purchase_number == number
            )
        ).scalar_one()
    with storage.transaction(other, consistent_read=True) as connection:
        assert (
            connection.execute(
                select(eis_notice_versions.c.xml_sha256).where(
                    eis_notice_versions.c.purchase_number == number
                )
            ).first()
            is None
        )
    with pytest.raises(EisIndexConflict, match="BY_NUMBER_PURCHASE_MISMATCH"):
        ingest_ready_window(
            storage,
            company,
            EisReadyWindow(window.window_key, "e" * 64, 1, (_archive("0848300064126000341"),)),
            actor_id="eis-test",
        )


@pytest.mark.parametrize(
    "document_type,page", [("epNotificationEZK2020", "zk20"), ("epNotificationEOK2020", "ok20")]
)
def test_other_method_checkpoint_versions_and_search_are_separate(
    storage: PostgresStorage, document_type: str, page: str
) -> None:
    company = f"eis-{uuid.uuid4()}"
    journal = EisSyncJournal(storage, company, "eis-test")
    auction = EisDateSelection("50", date(2026, 9, 25), 3)
    quotation = EisDateSelection("50", date(2026, 9, 25), 3, document_type)
    assert journal.plan((auction, quotation)) == 2
    content = _archive("0303300031426000056", document_type=document_type)
    window = EisReadyWindow(quotation.window_key, "a" * 64, 1, (content,))
    assert ingest_ready_window(storage, company, window, actor_id="eis-test").new_versions == 1
    assert ingest_ready_window(storage, company, window, actor_id="eis-test").replayed
    # Two exact responses for one requested window must not double queue counts.
    assert (
        ingest_ready_window(
            storage,
            company,
            EisReadyWindow(quotation.window_key, "c" * 64, 1, (content,)),
            actor_id="eis-test",
        ).new_versions
        == 0
    )
    next_day = EisDateSelection("50", date(2026, 9, 26), 3, document_type)
    assert journal.plan((next_day,)) == 1
    updated = _archive("0303300031426000056", version=2, document_type=document_type)
    ingest_ready_window(
        storage,
        company,
        EisReadyWindow(next_day.window_key, "b" * 64, 1, (updated,)),
        actor_id="eis-test",
    )
    assert [gap.window_key for gap in journal.gaps(region="50")] == [auction.window_key]
    result = search_eis_index(storage, company, "бумага", now=datetime.now(UTC))
    lead = result.matched[0]
    assert result.planned_windows == 3 and result.pending_windows == 1
    assert result.requested_region_codes == 1
    assert lead.document_type == document_type
    assert lead.version_number == 2
    assert f"/{page}/" in lead.notice_url
    assert lead.match_locator.startswith(document_type + "/")
    assert (
        search_eis_index(storage, f"other-{uuid.uuid4()}", "бумага", now=datetime.now(UTC)).matched
        == ()
    )


def _window(hour: str, *archives: bytes) -> EisReadyWindow:
    return EisReadyWindow(
        window_key=f"getDocsIP/PRIZ/50/2026-09-25/{hour}+03:00",
        response_sha256="a" * 64,
        expected_archive_count=len(archives),
        archives=tuple(archives),
    )


def test_paper_sense_uses_existing_keys_without_hiding_explicit_securities(storage):
    company = f"paper-sense-{uuid.uuid4()}"
    financial, paper, price = ("9000000000000000001", "9000000000000000002", "9000000000000000003")
    ingest_ready_window(
        storage,
        company,
        _window(
            "17",
            _archive(financial, title="Оценка ценных бумаг"),
            _archive(paper, title="Поставка бумаги офисной"),
            _archive(price, title="Мониторинг цен бумаги офисной"),
        ),
        actor_id="test",
    )
    with storage.transaction(company) as connection:
        before = connection.scalar(select(func.count()).select_from(audit_events))
    now = datetime.now(UTC)  # Continuation cannot include imports after its snapshot clock.
    result = search_eis_index(storage, company, "бумага", now=now, paginate=True)
    assert result.evaluated_candidate_notices == 3  # Coarse keys still enter SQL.
    assert [lead.purchase_number for lead in result.matched] == [paper, price]
    assert result.matched[0].match_quality == "STRONG"
    explicit = search_eis_index(storage, company, "ценные бумаги", now=now)
    assert (
        next(lead for lead in explicit.matched if lead.purchase_number == financial).match_quality
        == "STRONG"
    )
    assert search_eis_index(storage, company + "-other", "бумага", now=now).matched_count == 0
    with storage.transaction(company) as connection:
        assert connection.scalar(select(func.count()).select_from(audit_events)) == before


def event_zip(
    kind: str = "epNotificationCancel",
    *,
    identifier: str = "1",
    published: str = "2026-09-25T10:00:00+03:00",
) -> bytes:
    detail = (
        "<cancelReasonInfo/>"
        if kind == "epNotificationCancel"
        else ("<cancelFailureInfo><recoveryToStage>AP</recoveryToStage></cancelFailureInfo>")
    )
    xml = f"""<export xmlns="http://zakupki.gov.ru/oos/export/1"><{kind}>
<id>{identifier}</id><commonInfo><purchaseNumber>0848300054826000154</purchaseNumber>
<docPublishDTInEIS>{published}</docPublishDTInEIS></commonInfo>{detail}</{kind}></export>"""
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("event.xml", xml.encode())
    return output.getvalue()


def test_cancel_intake_replay_conflict_rls_and_search_block(storage: PostgresStorage) -> None:

    company = f"eis-{uuid.uuid4()}"
    number = "0848300054826000154"
    now = datetime(2026, 9, 28, tzinfo=UTC)
    ingest_ready_window(storage, company, _window("10", _archive(number)), actor_id="test")
    key = EisDateSelection("50", date(2026, 9, 25), 3, "epNotificationCancel").window_key
    journal = EisSyncJournal(storage, company, "test")
    assert (
        journal.plan((EisDateSelection("50", date(2026, 9, 25), 3, "epNotificationCancel"),)) == 1
    )
    window = EisReadyWindow(key, "c" * 64, 1, (event_zip(),))
    report = ingest_ready_window(storage, company, window, actor_id="test")
    assert report.new_events == 1 and report.new_versions == 0 and report.notice_count == 1
    assert not journal.gaps()
    assert ingest_ready_window(storage, company, window, actor_id="test").new_events == 0
    lead = search_eis_index(storage, company, "бумага", now=now).matched[0]
    assert lead.application_status == "FAIL"
    assert any("epNotificationCancel" in reason for reason in lead.reasons)
    with storage.transaction(f"other-{uuid.uuid4()}") as connection:
        assert connection.scalar(select(func.count()).select_from(eis_procedure_events)) == 0
    with pytest.raises(DBAPIError), storage.transaction(company) as connection:
        connection.execute(update(eis_procedure_events).values(recovery_stage="AP"))
    bad_key = EisDateSelection("50", date(2026, 9, 26), 3, "epNotificationCancel").window_key
    with pytest.raises(EisIndexConflict, match="PROCEDURE_EVENT_CONFLICT"):
        ingest_ready_window(
            storage,
            company,
            EisReadyWindow(
                bad_key, "d" * 64, 1, (event_zip(published="2026-09-26T10:00:00+03:00"),)
            ),
            actor_id="test",
        )
    with storage.transaction(company) as connection:
        assert connection.scalar(select(func.count()).select_from(eis_feed_windows)) == 2
    failure_key = EisDateSelection(
        "50", date(2026, 9, 26), 3, "epNotificationCancelFailure"
    ).window_key
    ingest_ready_window(
        storage,
        company,
        EisReadyWindow(
            failure_key,
            "e" * 64,
            1,
            (
                event_zip(
                    "epNotificationCancelFailure",
                    identifier="2",
                    published="2026-09-26T10:00:00+03:00",
                ),
            ),
        ),
        actor_id="test",
    )
    assert (
        search_eis_index(storage, company, "бумага", now=now).matched[0].application_status
        == "UNKNOWN"
    )


def test_sync_journal_preserves_gaps_and_tenant_isolation(storage: PostgresStorage) -> None:
    company = f"eis-{uuid.uuid4()}"
    other = f"eis-{uuid.uuid4()}"
    journal = EisSyncJournal(storage, company, "eis-test")
    first = EisDateSelection("50", date(2026, 9, 23), 3)
    second = EisDateSelection("50", date(2026, 9, 24), 3)
    assert journal.plan((first, second)) == 2
    assert journal.plan((first, second)) == 0
    assert [gap.window_key for gap in journal.gaps()] == [first.window_key, second.window_key]
    journal.record(second.window_key, "NO_DATA", source_response_sha256="b" * 64)
    gaps = journal.gaps()
    assert gaps[1].last_outcome == "NO_DATA"
    assert gaps[1].last_source_response_sha256 == "b" * 64
    journal.record(first.window_key, "SYNCED")
    assert len(journal.gaps()) == 2  # An attempt cannot close a missing archive checkpoint.
    ingest_ready_window(
        storage,
        company,
        EisReadyWindow(first.window_key, "a" * 64, 1, (_archive("0848300054826000154"),)),
        actor_id="eis-test",
    )
    assert [gap.window_key for gap in journal.gaps()] == [second.window_key]
    with storage.transaction(other) as connection:
        assert connection.scalar(select(func.count()).select_from(eis_sync_targets)) == 0
        assert connection.scalar(select(func.count()).select_from(eis_sync_attempts)) == 0
    with storage.transaction(company) as connection:
        assert connection.scalar(select(func.count()).select_from(eis_sync_targets)) == 2
        assert connection.scalar(select(func.count()).select_from(eis_sync_attempts)) == 2
        assert (
            connection.scalar(
                select(func.count())
                .select_from(audit_events)
                .where(
                    audit_events.c.event_type.in_(
                        ["EIS_SYNC_TARGET_PLANNED", "EIS_SYNC_ATTEMPT_RECORDED"]
                    )
                )
            )
            == 4
        )
    with pytest.raises(DBAPIError), storage.transaction(company) as connection:
        connection.execute(update(eis_sync_targets).values(coverage="UNKNOWN"))
    with pytest.raises(DBAPIError), storage.transaction(company) as connection:
        connection.execute(update(eis_sync_attempts).values(outcome="FAILED"))


def test_corpus_queue_replay_fairness_budget_and_network_stop(
    storage: PostgresStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from procurement.sources import eis_corpus
    from procurement.sources.eis_feed_sync import EisSyncError

    company = f"eis-{uuid.uuid4()}"
    journal = EisSyncJournal(storage, company, "corpus-test")
    now = datetime.now(UTC)
    scope = eis_corpus.EisCorpusScope(
        ("50", "77"), ("epNotificationEF2020",), date(2026, 9, 24), date(2026, 9, 25)
    )
    assert eis_corpus.plan_corpus(journal, scope, now=now) == 4
    assert eis_corpus.plan_corpus(journal, scope, now=now) == 0
    # A manual short plan must not move the baseline past an unplanned date.
    manual = eis_corpus.EisCorpusScope(
        ("50",), ("epNotificationEF2020",), date(2026, 9, 27), date(2026, 9, 27)
    )
    assert eis_corpus.plan_corpus(journal, manual, now=now) == 1
    assert (
        eis_corpus.extend_corpus(journal, scope.sha256, now=datetime(2026, 9, 28, tzinfo=UTC)) == 3
    )
    assert (
        eis_corpus.extend_corpus(journal, scope.sha256, now=datetime(2026, 9, 28, tzinfo=UTC)) == 0
    )
    keys = eis_corpus.eligible_windows(journal, now=now, limit=4)
    assert len(keys) == 4 and "2026-09-27" in keys[0]
    journal.record(keys[0], "NO_DATA", source_response_sha256="b" * 64)
    assert len(eis_corpus.eligible_windows(journal, now=datetime.now(UTC), limit=10)) == 7
    assert (
        len(eis_corpus.eligible_windows(journal, now=now.replace(year=now.year + 1), limit=4)) == 4
    )
    assert (
        eis_corpus.eligible_windows(
            EisSyncJournal(storage, f"other-{uuid.uuid4()}", "test"), now=now, limit=4
        )
        == ()
    )
    result = asyncio.run(
        eis_corpus.run_corpus(
            journal, "test", now=datetime.now(UTC), max_database_bytes=1, min_free_bytes=1
        )
    )
    assert result["attempted"] == 0 and result["reason"] == "DATABASE_BUDGET_REACHED"

    calls = 0

    async def failed(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        raise EisSyncError("SOURCE_TRANSPORT_FAILED")

    monkeypatch.setattr(eis_corpus, "sync_eis_window_via_browser", failed)
    result = asyncio.run(
        eis_corpus.run_corpus(journal, "test", now=datetime.now(UTC), min_free_bytes=1)
    )
    assert calls == 1 and result["attempted"] == 1
    assert result["reason"] == "SOURCE_TRANSPORT_FAILED" and result["coverage"] == "UNKNOWN"
    assert len(journal.gaps()) == 8  # Neither NO_DATA nor a transport failure closes a target.


def test_freshness_rechecks_checkpoint_and_keeps_hour_targets_out_of_backfill(
    storage: PostgresStorage,
) -> None:
    from procurement.sources.eis_corpus import eligible_windows
    from procurement.sources.eis_feed_sync import EisHourSelection
    from procurement.sources.eis_freshness import EisFreshnessScope, eligible_freshness

    company = f"eis-fresh-{uuid.uuid4()}"
    journal = EisSyncJournal(storage, company, "freshness-test")
    now = datetime.now(UTC)
    scope = EisFreshnessScope(("50",), ("epNotificationEF2020",))
    day = next(item.selection for item in scope.targets(now) if item.lane == "RECONCILE_DAY")
    hour = EisHourSelection("50", day.day, 17, 3)
    journal.plan((day, hour))
    first = EisReadyWindow(day.window_key, "c" * 64, 1, (_archive("0848300054826000154"),))
    ingest_ready_window(storage, company, first, actor_id="freshness-test")
    journal.record(day.window_key, "SYNCED", source_response_sha256="c" * 64)
    assert day.window_key not in eligible_windows(journal, now=now, limit=100)
    assert hour.window_key not in eligible_windows(journal, now=now, limit=100)
    due = eligible_freshness(journal, scope, now=now + timedelta(minutes=1), limit=100)
    assert day.window_key not in {item.selection.window_key for item in due}
    due = eligible_freshness(journal, scope, now=now + timedelta(hours=25), limit=100)
    assert day.window_key in {item.selection.window_key for item in due}
    # A new source response for the same date appends a new version atomically.
    second = EisReadyWindow(
        day.window_key, "d" * 64, 1, (_archive("0848300054826000154", version=2),)
    )
    assert (
        ingest_ready_window(storage, company, second, actor_id="freshness-test").new_versions == 1
    )
    with storage.transaction(company) as connection:
        assert connection.scalar(select(func.count()).select_from(eis_notice_versions)) == 2
        assert connection.scalar(select(func.count()).select_from(eis_feed_windows)) == 2
    other = EisSyncJournal(storage, f"eis-other-{uuid.uuid4()}", "freshness-test")
    other_due = eligible_freshness(other, scope, now=now, limit=100)
    assert day.window_key in {item.selection.window_key for item in other_due}
    with storage.transaction(other.company_id) as connection:
        assert connection.scalar(select(func.count()).select_from(eis_sync_attempts)) == 0


def test_freshness_metrics_audit_and_status_preserve_unknown_and_tenant_isolation(
    storage: PostgresStorage,
) -> None:
    from procurement.sources.eis_freshness import EisFreshnessScope
    from procurement.sources.eis_freshness_status import EisWindowObservation, freshness_status

    company = f"eis-status-{uuid.uuid4()}"
    journal = EisSyncJournal(storage, company, "freshness-status-test")
    now = datetime.now(UTC)
    scope = EisFreshnessScope(("50",), ("epNotificationEF2020",))
    target = scope.targets(now)[0]
    key = target.selection.window_key
    journal.plan((target.selection,))
    observation = EisWindowObservation(
        company_id=company,
        window_key=key,
        region="50",
        document_type="epNotificationEF2020",
        lane=target.lane,
        started_at=now - timedelta(seconds=20),
        finished_at=now,
        duration_ms="20000",
        outcome="NO_DATA",
        response_sha256="a" * 64,
        archive_bytes=0,
    )
    first = journal.record(key, "NO_DATA", source_response_sha256="a" * 64, observation=observation)
    conflict = observation.model_copy(
        update={
            "outcome": "FAILED",
            "response_sha256": None,
            "reason": "DUPLICATE_NOTICE_VERSION",
            "archive_bytes": None,
        }
    )
    second = journal.record(
        key, "FAILED", reason_code="DUPLICATE_NOTICE_VERSION", observation=conflict
    )
    with pytest.raises(ValueError, match="JOURNAL_OBSERVATION_MISMATCH"):
        journal.record(
            key,
            "FAILED",
            reason_code="DUPLICATE_NOTICE_VERSION",
            observation=conflict.model_copy(update={"company_id": "other"}),
        )
    status = freshness_status(storage, company, scope, now=datetime.now(UTC) + timedelta(seconds=1))
    assert status.capacity.samples == 2 and status.capacity.failed_samples == 1
    assert status.regional[0].failed == 1 and status.regional[0].latest_no_data_at is not None
    assert status.regional[0].latest_ingested_hour_start is None
    assert status.regional[0].latest_synced_at is None
    assert status.freshness == status.coverage == "UNKNOWN"
    assert status.capacity.overall_feasibility == "UNKNOWN"
    assert len(status.evidence_event_ids) == 2 and second in status.evidence_attempt_ids
    with storage.transaction(company) as connection:
        basis = connection.execute(
            select(audit_events.c.basis).where(
                audit_events.c.company_id == company,
                audit_events.c.basis["attempt_id"].astext == first,
            )
        ).scalar_one()
        assert basis["observation"]["duration_ms"] == "20000"
    other = freshness_status(
        storage,
        f"eis-status-other-{uuid.uuid4()}",
        scope,
        now=datetime.now(UTC) + timedelta(seconds=1),
    )
    assert other.capacity.samples == 0 and not other.evidence_event_ids
    assert other.regional[0].unattempted == len(scope.targets(now))


def test_ready_archive_source_is_immutable_and_tenant_scoped(storage: PostgresStorage) -> None:
    company = f"eis-{uuid.uuid4()}"
    other = f"eis-{uuid.uuid4()}"
    source_url = (
        "https://int.zakupki.gov.ru/dstore/common/download/compound"
        "?docRequestUid=00000000-0000-0000-0000-000000000001"
        "&compoundUid=00000000000000000000000000000001"
    )
    window = EisReadyWindow(
        window_key="getDocsIP/PRIZ/50/2026-09-25+03:00",
        response_sha256="a" * 64,
        expected_archive_count=1,
        archives=(_archive("0848300054826000154"),),
        prepared_response_sha256="b" * 64,
        archive_urls=(source_url,),
    )
    ingest_ready_window(storage, company, window, actor_id="eis-test")
    with storage.transaction(company) as connection:
        row = connection.execute(
            select(eis_feed_archive_sources.c.source_url).where(
                eis_feed_archive_sources.c.company_id == company
            )
        ).scalar_one()
        assert row == source_url
    with storage.transaction(other) as connection:
        count = connection.execute(
            select(func.count()).select_from(eis_feed_archive_sources)
        ).scalar_one()
        assert count == 0
    with pytest.raises(DBAPIError), storage.transaction(company) as connection:
        connection.execute(
            update(eis_feed_archive_sources).values(source_url="https://example.com/")
        )


def test_replay_tenant_isolation_and_immutable_versions(storage: PostgresStorage) -> None:
    company = f"eis-{uuid.uuid4()}"
    other = f"eis-{uuid.uuid4()}"
    number = "0848300054826000154"
    window = _window("17", _archive(number))
    first = ingest_ready_window(storage, company, window, actor_id="eis-test")
    replay = ingest_ready_window(storage, company, window, actor_id="eis-test")
    assert (first.new_versions, first.replayed) == (1, False)
    assert (replay.new_versions, replay.replayed) == (0, True)
    with storage.transaction(company) as connection:
        assert (
            connection.execute(
                select(func.count())
                .select_from(eis_notice_versions)
                .where(eis_notice_versions.c.company_id == company)
            ).scalar_one()
            == 1
        )
    with storage.transaction(other) as connection:
        assert (
            connection.execute(select(func.count()).select_from(eis_notice_versions)).scalar_one()
            == 0
        )
    with pytest.raises(DBAPIError), storage.transaction(company) as connection:
        connection.execute(
            update(eis_notice_versions)
            .where(eis_notice_versions.c.company_id == company)
            .values(title="Changed")
        )


def test_conflict_rolls_back_whole_new_window(storage: PostgresStorage) -> None:
    company = f"eis-{uuid.uuid4()}"
    number = "0848300054826000154"
    ingest_ready_window(storage, company, _window("17", _archive(number)), actor_id="eis-test")
    new_window = _window(
        "18",
        _archive("0848300064126000341"),
        _archive(number, title="Contradictory title"),
    )
    with pytest.raises(EisIndexConflict, match="NOTICE_VERSION_CONFLICT"):
        ingest_ready_window(storage, company, new_window, actor_id="eis-test")
    with storage.transaction(company) as connection:
        assert (
            connection.execute(
                select(func.count())
                .select_from(eis_feed_windows)
                .where(eis_feed_windows.c.window_key == new_window.window_key)
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(select(func.count()).select_from(eis_notice_versions)).scalar_one()
            == 1
        )


def _scope_archive(number: str, deadline: str | None, *, version: int = 1) -> bytes:
    with ZipFile(BytesIO(_archive(number, version=version))) as source:
        xml = source.read(source.namelist()[0])
    if deadline is not None:
        xml = xml.replace(
            b"<notificationInfo/>",
            (
                "<notificationInfo><procedureInfo><collectingInfo><endDT>"
                + deadline
                + "</endDT></collectingInfo></procedureInfo></notificationInfo>"
            ).encode(),
        )
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(f"{number}.xml", xml)
    return output.getvalue()


def test_search_scope_filters_before_hydration_without_resurrecting_versions(
    storage, monkeypatch, tmp_path
):
    from test_eis_notice_variants_pg import batch

    from procurement.storage import eis_notice_index
    from procurement.storage.eis_notice_variants import store_notice_variants
    from test_eis_notice_conflicts import notice

    company, other = f"scope-{uuid.uuid4()}", f"scope-{uuid.uuid4()}"
    now = datetime(2026, 10, 4, tzinfo=UTC)
    future, past = "2026-10-05T00:00:00Z", "2026-10-03T00:00:00Z"
    numbers = [f"90000000000000000{i:02d}" for i in range(9)]
    cancelled = "0848300054826000154"
    # Active, unknown, equal-now, expired, superseded, and two held cards.
    archives = tuple(
        _scope_archive(n, d)
        for n, d in zip(
            numbers[:7], [future, None, now.isoformat(), past, future, future, past], strict=True
        )
    )
    ingest_ready_window(
        storage,
        company,
        _window("10", *archives, _scope_archive(cancelled, future)),
        actor_id="test",
    )
    ingest_ready_window(
        storage,
        company,
        _window("11", _scope_archive(numbers[4], past, version=2)),
        actor_id="test",
    )
    with monkeypatch.context() as patch:
        patch.setattr(eis_notice_index, "insert_search_keys", lambda *args: False)
        ingest_ready_window(
            storage,
            company,
            _window("12", _scope_archive(numbers[7], future), _scope_archive(numbers[8], past)),
            actor_id="test",
        )
    for index, number in enumerate(numbers[5:7]):
        # The ledger diagnostic requires official EPtypes identity namespaces;
        # the older index-only fixture intentionally uses relaxed local names.
        xml = notice(title="Поставка бумаги").replace(b"0373100047426001450", number.encode())
        evidence, diagnosis = batch(
            storage,
            company,
            tmp_path,
            day=str(28 + index),
            members=(
                ("a.xml", xml),
                ("b.xml", xml.replace("Поставка".encode(), "Закупка".encode())),
            ),
        )
        assert all(
            item.purchase_number == number
            and item.version_number == 1
            and item.document_type == "epNotificationEF2020"
            for item in diagnosis.occurrences
        )
        store_notice_variants(storage, company, evidence, diagnosis, actor_id="test")
    event_key = EisDateSelection("50", date(2026, 9, 25), 3, "epNotificationCancel").window_key
    ingest_ready_window(
        storage, company, EisReadyWindow(event_key, "c" * 64, 1, (event_zip(),)), actor_id="test"
    )
    ingest_ready_window(
        storage, other, _window("10", _scope_archive(numbers[0], past)), actor_id="test"
    )
    all_cached = search_eis_index(storage, company, "бумага", now=now, batch_size=1)
    scoped = search_eis_index(
        storage, company, "бумага", now=now, batch_size=1, search_scope="NOT_EXPIRED_OR_UNKNOWN"
    )
    expected = tuple(x for x in all_cached.matched if x.deadline is None or x.deadline > now)
    assert scoped.matched == expected
    assert scoped.total_current_notices == all_cached.total_current_notices == 10
    assert all_cached.inspected_current_notices == 10
    assert all_cached.excluded_expired_current_notices == 0
    assert scoped.inspected_current_notices == scoped.excluded_expired_current_notices == 5
    assert (all_cached.held_current_notices, scoped.held_current_notices) == (2, 1)
    assert scoped.evaluated_candidate_notices == 4
    assert all_cached.evaluated_candidate_notices == 8
    assert scoped.unindexed_versions == all_cached.unindexed_versions == 2
    assert scoped.indexed_windows == all_cached.indexed_windows
    assert scoped.pending_windows == all_cached.pending_windows
    assert scoped.corpus_coverage == scoped.source_freshness == "UNKNOWN"
    assert next(x for x in scoped.matched if x.purchase_number == numbers[1]).deadline is None
    assert (
        next(x for x in scoped.matched if x.purchase_number == cancelled).application_status
        == "FAIL"
    )
    assert numbers[4] not in {x.purchase_number for x in scoped.matched}
    top = search_eis_index(
        storage, company, "бумага", now=now, limit=2, search_scope="NOT_EXPIRED_OR_UNKNOWN"
    )
    assert top.matched == expected[:2]
    isolated = search_eis_index(
        storage, other, "бумага", now=now, search_scope="NOT_EXPIRED_OR_UNKNOWN"
    )
    assert isolated.total_current_notices == isolated.excluded_expired_current_notices == 1
    assert isolated.inspected_current_notices == 0 and isolated.matched == ()

    # Real PostgreSQL named cursor must support event reads between partitions
    # in the same tenant-bound read-only snapshot and close on exhaustion.
    from sqlalchemy import event

    for scope in ("ALL_CACHED", "NOT_EXPIRED_OR_UNKNOWN"):
        results = []
        for size in (1, 500):
            cursors = []
            interleaved = []

            def observe(
                conn,
                cursor,
                statement,
                parameters,
                context,
                many,
                size=size,
                cursors=cursors,
                interleaved=interleaved,
            ):
                if context.execution_options.get("yield_per") == size:
                    assert cursor.name
                    cursors.append(cursor)
                elif "SELECT eis_procedure_events.company_id" in statement:
                    assert len(cursors) == 1 and not cursors[0].closed
                    interleaved.append(True)

            event.listen(storage._engine, "before_cursor_execute", observe)
            try:
                result = search_eis_index(
                    storage, company, "бумага", now=now, batch_size=size, search_scope=scope
                )
            finally:
                event.remove(storage._engine, "before_cursor_execute", observe)
            assert len(cursors) == 1 and cursors[0].closed
            assert len(interleaved) == (result.evaluated_candidate_notices + size - 1) // size
            results.append(result.model_dump(exclude={"search_elapsed_ms"}))
        assert results[0] == results[1]

    from procurement.storage import eis_index_query

    class InvalidSnapshot:
        def validate_python(self, value):
            raise ValueError("SYNTHETIC_SNAPSHOT_INVALID")

    for failure in ("snapshot", "event"):
        cursors = []

        def fail_during_consumption(
            conn,
            cursor,
            statement,
            parameters,
            context,
            many,
            failure=failure,
            cursors=cursors,
        ):
            if context.execution_options.get("yield_per") == 1:
                cursors.append(cursor)
            elif failure == "event" and "SELECT eis_procedure_events.company_id" in statement:
                raise ValueError("SYNTHETIC_EVENT_READ_FAILED")

        event.listen(storage._engine, "before_cursor_execute", fail_during_consumption)
        try:
            with monkeypatch.context() as patch:
                if failure == "snapshot":
                    patch.setattr(eis_index_query, "_SNAPSHOT", InvalidSnapshot())
                with pytest.raises(ValueError, match="SYNTHETIC_"):
                    search_eis_index(storage, company, "бумага", now=now, batch_size=1)
        finally:
            event.remove(storage._engine, "before_cursor_execute", fail_during_consumption)
        assert len(cursors) == 1 and cursors[0].closed


def test_index_search_uses_latest_version_and_tenant_scoped_batches(
    storage: PostgresStorage,
) -> None:
    company = f"eis-{uuid.uuid4()}"
    other = f"eis-{uuid.uuid4()}"
    changed = "0848300054826000154"
    paper = "0848300064126000341"
    ingest_ready_window(
        storage,
        company,
        _window(
            "17", _archive(changed, title="Бумага", version=1), _archive(paper, title="Бумага А4")
        ),
        actor_id="eis-test",
    )
    ingest_ready_window(
        storage,
        company,
        _window("18", _archive(changed, title="Серверное оборудование", version=2)),
        actor_id="eis-test",
    )
    ingest_ready_window(
        storage,
        other,
        _window("17", _archive("0348200077726000176", title="Бумага")),
        actor_id="eis-test",
    )
    paper_result = search_eis_index(
        storage, company, "бумага", now=datetime(2026, 9, 27, tzinfo=UTC), batch_size=1
    )
    assert paper_result.inspected_current_notices == 2
    assert paper_result.indexed_windows == 2
    assert paper_result.matched_count == 1
    assert paper_result.evaluated_candidate_notices == 1
    assert paper_result.unindexed_versions == 0
    assert paper_result.source_freshness == "UNKNOWN"
    assert paper_result.matched[0].purchase_number == paper
    assert paper_result.corpus_coverage == "UNKNOWN"
    servers = search_eis_index(
        storage,
        company,
        "серверное оборудование",
        now=datetime(2026, 9, 27, tzinfo=UTC),
        batch_size=1,
    )
    assert [(lead.purchase_number, lead.version_number) for lead in servers.matched] == [
        (changed, 2)
    ]
    isolated = search_eis_index(
        storage, other, "бумага", now=datetime(2026, 9, 27, tzinfo=UTC), batch_size=1
    )
    assert isolated.inspected_current_notices == 1
    assert isolated.matched[0].purchase_number == "0348200077726000176"


def test_search_keys_fallback_backfill_rls_and_immutability(
    storage: PostgresStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    from procurement.storage import eis_notice_index
    from procurement.storage.eis_search_index import backfill_search_keys

    company = f"eis-{uuid.uuid4()}"
    other = f"eis-{uuid.uuid4()}"
    # Model a pre-migration version without changing or deleting its evidence.
    with monkeypatch.context() as patch:
        patch.setattr(eis_notice_index, "insert_search_keys", lambda *args: False)
        ingest_ready_window(
            storage,
            company,
            _window("17", _archive("0848300054826000154", title="Поставка медицинских масок")),
            actor_id="test",
        )
    now = datetime(2026, 9, 28, tzinfo=UTC)
    before = search_eis_index(storage, company, "маски", now=now)
    assert before.unindexed_versions == 1 and before.matched_count == 1
    assert backfill_search_keys(storage, other, actor_id="test") == 0
    assert backfill_search_keys(storage, company, actor_id="test", batch_size=1) == 1
    assert backfill_search_keys(storage, company, actor_id="test", batch_size=1) == 0
    after = search_eis_index(storage, company, "маски", now=now)
    assert after.matched == before.matched and after.unindexed_versions == 0
    with storage.transaction(other) as connection:
        assert connection.scalar(select(func.count()).select_from(eis_notice_search_keys)) == 0
    with pytest.raises(DBAPIError), storage.transaction(company) as connection:
        connection.execute(update(eis_notice_search_keys).values(keys=["wrong"]))


def test_read_snapshot_does_not_mix_a_concurrent_new_notice_version(
    storage: PostgresStorage,
) -> None:
    company = f"eis-{uuid.uuid4()}"
    number = "0848300054826000154"
    ingest_ready_window(storage, company, _window("17", _archive(number)), actor_id="test")
    with storage.transaction(company, consistent_read=True) as connection:
        assert connection.scalar(select(func.count()).select_from(eis_notice_versions)) == 1
        ingest_ready_window(
            storage,
            company,
            _window("18", _archive(number, title="Серверное оборудование", version=2)),
            actor_id="test",
        )
        assert connection.scalar(select(func.count()).select_from(eis_notice_versions)) == 1
        assert connection.scalar(select(func.count()).select_from(eis_notice_search_keys)) == 1
    with storage.transaction(company) as connection:
        assert connection.scalar(select(func.count()).select_from(eis_notice_versions)) == 2


def test_search_keys_preserve_individual_lot_matches_and_deadlines(
    storage: PostgresStorage,
) -> None:
    company = f"eis-{uuid.uuid4()}"
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(
            "lots.xml",
            """<export xmlns="http://zakupki.gov.ru/oos/export/1">
<epNotificationEF2020><versionNumber>1</versionNumber><commonInfo>
<purchaseNumber>0848300054826000154</purchaseNumber>
<purchaseObjectInfo>Расходные материалы</purchaseObjectInfo>
<publishDTInEIS>2026-09-25T12:00:00+03:00</publishDTInEIS></commonInfo>
<notificationInfo><procedureInfo><collectingInfo><endDT>2026-09-28T12:00:00+03:00</endDT>
</collectingInfo></procedureInfo><purchaseObjectsInfo><notDrugPurchaseObjectsInfo>
<purchaseObject><name>Латексные</name></purchaseObject><purchaseObject><name>Перчатки</name></purchaseObject>
</notDrugPurchaseObjectsInfo></purchaseObjectsInfo></notificationInfo></epNotificationEF2020></export>""",
        )
    ingest_ready_window(storage, company, _window("17", output.getvalue()), actor_id="test")
    before = search_eis_index(
        storage, company, "латексные перчатки", now=datetime(2026, 9, 27, tzinfo=UTC)
    )
    assert before.matched_count == 1 and before.evaluated_candidate_notices == 1
    assert before.matched[0].match_quality == "PARTIAL"  # Never combine separate lot positions.
    assert before.matched[0].application_status == "UNKNOWN"
    assert before.latest_source_publication == datetime(2026, 9, 25, 9, tzinfo=UTC)
    after = search_eis_index(
        storage, company, "латексные перчатки", now=datetime(2026, 9, 28, 10, tzinfo=UTC)
    )
    assert after.matched[0].application_status == "FAIL"
    assert after.matched[0].economic_status == "UNKNOWN"


@pytest.mark.parametrize(
    "case,covered",
    [
        ("final_no_data", True),
        ("final_synced", True),
        ("later_failure", True),
        ("pre_cutoff", False),
        ("failed", False),
        ("missing_hash", False),
        ("foreign_tenant", False),
        ("other_region", False),
        ("other_type", False),
        ("other_offset", False),
        ("other_day", False),
    ],
)
def test_checkpoint_final_daily_observation_covers_only_exact_missed_hours(
    storage, monkeypatch, case, covered
):
    from procurement.sources.eis_feed_sync import EisHourSelection
    from procurement.sources.eis_freshness import EisFreshnessScope, read_due_freshness

    company = "daily-credit-" + uuid.uuid4().hex
    now = datetime(2026, 6, 10, 12, tzinfo=UTC)
    day = date(2026, 6, 9)
    hour = EisHourSelection("50", day, 22, 3)
    journal = EisSyncJournal(storage, company, "test")
    journal.plan((hour,))
    daily = EisDateSelection(
        "77" if case == "other_region" else "50",
        day - timedelta(days=1) if case == "other_day" else day,
        4 if case == "other_offset" else 3,
        "epNotificationEZK2020" if case == "other_type" else "epNotificationEF2020",
    )
    daily_journal = (
        EisSyncJournal(storage, company + "-foreign", "test")
        if case == "foreign_tenant"
        else journal
    )
    daily_journal.plan((daily,))
    at = datetime(2026, 6, 9, 23, 5, tzinfo=UTC)
    if case == "pre_cutoff":
        at -= timedelta(microseconds=1)
    outcome = (
        "FAILED"
        if case == "failed"
        else "SYNCED"
        if case in {"missing_hash", "final_synced"}
        else "NO_DATA"
    )

    class AttemptClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return at.astimezone(tz or UTC)

    # Production permissions intentionally forbid UPDATE of this append-only
    # ledger. Set the fixture clock at insertion, never weaken database grants.
    monkeypatch.setattr("procurement.storage.eis_sync_journal.datetime", AttemptClock)
    daily_journal.record(
        daily.window_key,
        outcome,
        reason_code="SOURCE_TRANSPORT_FAILED" if outcome == "FAILED" else None,
        source_response_sha256=None if case == "missing_hash" else "a" * 64,
    )
    if case == "later_failure":
        at = now - timedelta(minutes=16)
        journal.record(daily.window_key, "FAILED", reason_code="SOURCE_TRANSPORT_FAILED")

    def retained():
        with storage.transaction(company) as conn:
            return tuple(
                conn.scalar(select(func.count()).select_from(t))
                for t in (
                    eis_sync_targets,
                    eis_sync_attempts,
                    audit_events,
                    eis_feed_windows,
                )
            )

    before = retained()
    scope = EisFreshnessScope(
        ("50",), ("epNotificationEF2020",), checkpointed=True, mandatory_only=True
    )
    # Restart has no in-memory coverage. The selector derives it from evidence;
    # it never fabricates an hourly attempt/checkpoint or drops the durable gap.
    restarted = EisSyncJournal(storage, company, "restarted")
    due = read_due_freshness(restarted, scope, now=now, limit=60)
    assert restarted.freshness_recovery_reason is None
    assert (hour.window_key not in {t.selection.window_key for t in due}) is covered
    assert retained() == before
    assert due[0].lane == "RECENT_HOUR"
    assert len({t.selection.window_key for t in due}) == len(due) <= 60
    assert read_due_freshness(restarted, scope, now=now, limit=1) == due[:1]
    if case == "later_failure":
        assert daily.window_key in {t.selection.window_key for t in due}
    with storage.transaction(company) as conn:
        assert (
            conn.scalar(
                select(func.count())
                .select_from(eis_sync_targets)
                .where(
                    eis_sync_targets.c.window_key == hour.window_key,
                )
            )
            == 1
        )
        assert (
            conn.scalar(
                select(func.count())
                .select_from(eis_sync_attempts)
                .where(
                    eis_sync_attempts.c.window_key == hour.window_key,
                )
            )
            == 0
        )


@pytest.mark.parametrize("kind", ["unattempted", "pre_cutoff", "failed"])
def test_mandatory_daily_recovery_precedes_hours_outside_rolling_scope(storage, monkeypatch, kind):
    from procurement.sources.eis_feed_sync import EisHourSelection
    from procurement.sources.eis_freshness import EisFreshnessScope, read_due_freshness

    company = "mandatory-day-" + uuid.uuid4().hex
    now = datetime(2026, 10, 15, 12, tzinfo=UTC)
    old_day = date(2026, 10, 9)
    daily = EisDateSelection("50", old_day, 3)
    hour = EisHourSelection("50", old_day, 20, 3)
    journal = EisSyncJournal(storage, company, "worker")
    journal.plan((daily, hour))
    if kind != "unattempted":
        at = datetime(2026, 10, 9, 14, tzinfo=UTC)

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return at.astimezone(tz or UTC)

        monkeypatch.setattr("procurement.storage.eis_sync_journal.datetime", Clock)
        journal.record(
            daily.window_key,
            "FAILED" if kind == "failed" else "NO_DATA",
            reason_code="SOURCE_TRANSPORT_FAILED" if kind == "failed" else None,
            source_response_sha256="a" * 64 if kind != "failed" else None,
        )
    scope = EisFreshnessScope(
        ("50",), ("epNotificationEF2020",), checkpointed=True, mandatory_only=True
    )
    restarted = EisSyncJournal(storage, company, "restart")
    due = read_due_freshness(restarted, scope, now=now, limit=2)
    assert due[0].lane == "RECENT_HOUR"
    assert due[1].selection.window_key == daily.window_key
    with storage.transaction(company) as conn:
        assert (
            conn.scalar(
                select(func.count())
                .select_from(eis_sync_targets)
                .where(
                    eis_sync_targets.c.company_id == company,
                    eis_sync_targets.c.window_key == hour.window_key,
                )
            )
            == 1
        )
        assert (
            conn.scalar(
                select(func.count())
                .select_from(eis_sync_attempts)
                .where(
                    eis_sync_attempts.c.company_id == company,
                    eis_sync_attempts.c.window_key == hour.window_key,
                )
            )
            == 0
        )


def test_mandatory_recovery_does_not_promote_unobserved_old_history(storage):
    from procurement.sources.eis_freshness import EisFreshnessScope, read_due_freshness

    company = "old-history-" + uuid.uuid4().hex
    now = datetime(2026, 10, 15, 12, tzinfo=UTC)
    historical = EisDateSelection("50", date(2026, 9, 1), 3)
    journal = EisSyncJournal(storage, company, "test")
    journal.plan((historical,))
    due = read_due_freshness(
        journal,
        EisFreshnessScope(
            ("50",), ("epNotificationEF2020",), checkpointed=True, mandatory_only=True
        ),
        now=now,
        limit=60,
    )
    assert historical.window_key not in {x.selection.window_key for x in due}


def test_protected_reconciliation_reads_daily_debt_under_full_hourly_pressure(storage, monkeypatch):
    from procurement.sources.eis_freshness import EisFreshnessScope, read_due_reconciliation

    company = "daily-reserve-" + uuid.uuid4().hex
    now = datetime(2026, 10, 22, 12, tzinfo=UTC)
    journal = EisSyncJournal(storage, company, "test")
    yesterday = EisDateSelection("50", now.date() - timedelta(days=1), 3)
    recent = EisDateSelection("50", now.date() - timedelta(days=2), 3)
    old = EisDateSelection("50", now.date() - timedelta(days=10), 3)
    journal.plan((yesterday, recent, old))
    from procurement.storage import eis_sync_journal

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz or UTC)

    monkeypatch.setattr(eis_sync_journal, "datetime", Clock)
    journal.record(recent.window_key, "NO_DATA", source_response_sha256="a" * 64)
    with storage.transaction(company, consistent_read=True) as conn:
        before = conn.scalar(select(func.count()).select_from(eis_sync_attempts))
    scope = EisFreshnessScope(
        ("50",), ("epNotificationEF2020",), checkpointed=True, mandatory_only=True
    )
    daily = read_due_reconciliation(journal, scope, now=now, limit=1)
    assert tuple(t.selection.window_key for t in daily) == (yesterday.window_key,)
    assert daily[0].lane == "RECONCILE_DAY"
    foreign = EisSyncJournal(storage, company + "-other", "test")
    assert all(
        t.selection.day == yesterday.day
        for t in read_due_reconciliation(foreign, scope, now=now, limit=1)
    )
    with storage.transaction(company, consistent_read=True) as conn:
        assert conn.scalar(select(func.count()).select_from(eis_sync_attempts)) == before
