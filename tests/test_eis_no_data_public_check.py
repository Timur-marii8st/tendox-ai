"""Different official access paths never silently become identical corpus scopes."""

import hashlib
import importlib.util
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from test_eis_no_data_evidence import NOW, TOKEN, retain

spec = importlib.util.spec_from_file_location(
    "no_data_public_check", Path(__file__).parents[1] / "scripts/server-eis-no-data-public-check.py"
)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
DAY = date(2026, 9, 27)
NUMBER = "0360300131926000262"
FOREIGN = "0360300131926000263"


def controls():
    values = dict(
        publishDateFrom="27.09.2026",
        publishDateTo="27.09.2026",
        pageNumber="1",
        recordsPerPage="_50",
        searchString="",
    )
    return (
        "".join(f'<input name="{k}" value="{v}">' for k, v in values.items())
        + "".join(
            f'<input name="{k}" type="checkbox" checked>' for k in ("fz44", "af", "ca", "pc", "pa")
        )
        + '<input name="fz223" type="checkbox">'
    )


def card(number=NUMBER, day="27.09.2026", law="44-ФЗ", url=None):
    url = (
        url
        or f"https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber={number}"
    )
    return (
        '<div class="search-registry-entry-block">'
        '<div class="registry-entry__header-top__title">'
        f"{law} Электронный аукцион</div>"
        '<div class="registry-entry__header-mid__number">'
        f'<a href="{url}">№ {number}</a></div>'
        f"<div>Размещено {day} Обновлено 05.10.2026</div></div>"
    )


def page(cards=None, total="77 записей"):
    return (
        controls()
        + f'<div class="search-results__total">{total}</div>'
        + (card() if cards is None else cards)
    ).encode()


def test_exact_date_law_stage_echo_and_first_page_only():
    result = m.parse_page(page(), DAY)
    assert result.scanned_cards == 1 and result.unparsed_cards == 0
    assert result.source_count_floor == 77 and result.source_count_exact
    assert result.candidates[0].purchase_number == NUMBER
    assert result.source_sha256 == hashlib.sha256(page()).hexdigest()
    assert result.scope == "NATIONAL_44_PUBLICATION_DAY_FIRST_PAGE"
    assert "fz223=on" not in result.search_url and "recordsPerPage=_50" in result.search_url


@pytest.mark.parametrize(
    "name",
    [
        "publishDateFrom",
        "publishDateTo",
        "pageNumber",
        "recordsPerPage",
        "searchString",
        "fz44",
        "fz223",
        "af",
        "ca",
        "pc",
        "pa",
    ],
)
def test_missing_or_duplicate_filter_is_not_verified(name):
    blob = page().replace(f'name="{name}"'.encode(), f'name="wrong-{name}"'.encode())
    with pytest.raises(ValueError, match="FILTER_UNVERIFIED"):
        m.parse_page(blob, DAY)
    with pytest.raises(ValueError, match="FILTER_UNVERIFIED"):
        m.parse_page(page() + f'<input name="{name}">'.encode(), DAY)


@pytest.mark.parametrize(
    "blob",
    [
        page(card(day="26.09.2026")),
        page(card(law="223-ФЗ")),
        page().replace(b'"fz223" type="checkbox"', b'"fz223" type="checkbox" checked'),
    ],
)
def test_scope_mismatch_is_rejected(blob):
    with pytest.raises(ValueError, match="FILTER_UNVERIFIED"):
        m.parse_page(blob, DAY)


def test_untrusted_or_unparseable_number_is_counted_not_admitted():
    parsed = m.parse_page(page(card(url="https://example.org/card")), DAY)
    assert parsed.unparsed_cards == 1 and not parsed.candidates
    with pytest.raises(ValueError):
        m.parse_page(page(card() + card()), DAY)
    with pytest.raises(ValueError):
        m.parse_page(page(card() * 51), DAY)


def test_empty_page_never_becomes_no_data_corroboration():
    parsed = m.parse_page(page("Поиск не дал результатов", total="0 записей"), DAY)
    assert not parsed.candidates and parsed.source_count_floor == 0
    with pytest.raises(ValueError, match="MARKUP_CHANGED"):
        m.parse_page(page("", total="0 записей"), DAY)
    with pytest.raises(ValueError, match="BLOCKED_PAGE"):
        m.parse_page(page("Подтвердите, что вы не робот"), DAY)
    floor = m.parse_page(page(total="более 1000 записей"), DAY)
    assert floor.source_count_floor == 1000 and not floor.source_count_exact


def test_capture_exact_dom_and_bounded_quota_preserves_old_files(tmp_path, monkeypatch):
    root = tmp_path / "private"
    blob = page()
    artifact = m.retain_page(root, blob, TOKEN)
    assert (root / artifact.relative_path).read_bytes() == blob
    assert artifact.sha256 == hashlib.sha256(blob).hexdigest()
    monkeypatch.setattr(m, "MAX_CAPTURES", 1)
    with pytest.raises(ValueError, match="QUOTA_REACHED"):
        m.retain_page(root, blob, TOKEN)
    assert (root / artifact.relative_path).read_bytes() == blob and not (
        root / ".capture.lock"
    ).exists()
    monkeypatch.setattr(m, "MAX_CAPTURES", 8)
    monkeypatch.setattr(m, "MAX_STORE_BYTES", len(blob) * 2 - 1)
    with pytest.raises(ValueError, match="QUOTA_REACHED"):
        m.retain_page(root, blob, TOKEN)


@pytest.mark.parametrize(
    "reflection",
    [TOKEN, TOKEN.replace("s", "&#115;", 1), TOKEN[:10] + "<span></span>" + TOKEN[10:]],
)
def test_secret_reflection_rejected_before_storage(tmp_path, reflection):
    root = tmp_path / "private"
    with pytest.raises(ValueError, match="SECRET_REFLECTION"):
        m.retain_page(root, page() + reflection.encode(), TOKEN)
    assert not root.exists()


def test_typed_report_binds_day_partition_and_hash_without_false_pass(tmp_path):
    receipt = retain(tmp_path / "raw", company_id=m.COMPANY)
    target = m.Target(
        audit_event_id=uuid4(),
        journal_attempt_id=uuid4(),
        journal_attempted_at=NOW,
        receipt=receipt,
        day=DAY,
    )
    parsed = m.parse_page(page(), DAY)
    artifact = m.retain_page(tmp_path / "public", page(), TOKEN)
    args = dict(
        observed_at=NOW,
        since=NOW - timedelta(hours=1),
        target=target,
        page=parsed,
        artifact=artifact,
        indexed_numbers=(),
        not_indexed_candidates=(NUMBER,),
        pg_snapshot="1:2:",
    )
    result = m.Report(**args)
    assert result.source_absence == result.coverage == result.independent_corroboration == "UNKNOWN"
    with pytest.raises(ValidationError):
        m.Report(**(args | {"indexed_numbers": (NUMBER,)}))
    with pytest.raises(ValidationError):
        m.Target(
            audit_event_id=uuid4(),
            journal_attempt_id=uuid4(),
            journal_attempted_at=NOW,
            receipt=receipt,
            day=date(2026, 9, 28),
        )
    with pytest.raises(ValidationError):
        m.Report(**(args | {"independent_corroboration": "PASS"}))


def test_isolated_pg_target_latest_tenant_and_index_partition(tmp_path, monkeypatch):
    app_url, admin_url = os.getenv("DATABASE_URL"), os.getenv("DATABASE_ADMIN_URL")
    if not app_url or not admin_url:
        pytest.skip("isolated PostgreSQL required")
    if any("procurement_eis_test_" not in url for url in (app_url, admin_url)):
        pytest.fail("explicit isolated DB required")
    from sqlalchemy import create_engine, func, select, text

    from procurement.sources.eis_feed_sync import EisDateSelection
    from procurement.storage.eis_no_data_evidence import record_no_data_evidence
    from procurement.storage.eis_notice_index import bind_ready_window, ingest_ready_window
    from procurement.storage.eis_sync_journal import EisSyncJournal
    from procurement.storage.models import audit_events, eis_notice_versions, eis_sync_attempts
    from procurement.storage.repository import PostgresStorage
    from test_eis_notice_index import URL, WINDOW, _responses, _zip

    engine = create_engine(app_url)
    storage = PostgresStorage(engine)
    root = tmp_path / "raw"
    monkeypatch.setenv("EIS_NO_DATA_EVIDENCE_DIR", str(root))
    try:
        with storage.transaction(m.COMPANY, consistent_read=True) as conn:
            now = conn.scalar(text("SELECT clock_timestamp()"))
        key = "getDocsIP/PRIZ/50/2026-09-27+03:00"
        receipt = retain(root, company_id=m.COMPANY, observed_at=now)
        record_no_data_evidence(storage, m.COMPANY, receipt, actor_id="worker")
        journal = EisSyncJournal(storage, m.COMPANY, "worker")
        journal.plan((EisDateSelection("50", DAY, 3),))
        journal.record(key, "NO_DATA", source_response_sha256=receipt.source_response_sha256)
        foreign = retain(root, company_id="foreign-tenant", observed_at=now)
        record_no_data_evidence(storage, "foreign-tenant", foreign, actor_id="worker")
        for company, number in [(m.COMPANY, NUMBER), ("foreign-tenant", FOREIGN)]:
            initial, prepared = _responses()
            ingest_ready_window(
                storage,
                company,
                bind_ready_window(WINDOW, initial, prepared, {URL: _zip(number)}),
                actor_id="worker",
            )
        parsed = m.parse_page(page(card() + card(FOREIGN)), DAY)
        with storage.transaction(m.COMPANY, consistent_read=True) as conn:
            before = tuple(
                conn.scalar(select(func.count()).select_from(t))
                for t in (audit_events, eis_sync_attempts, eis_notice_versions)
            )
            selected = m.select_target(conn, now)
            known = m.read_indexed(conn, parsed)
            after = tuple(
                conn.scalar(select(func.count()).select_from(t))
                for t in (audit_events, eis_sync_attempts, eis_notice_versions)
            )
        assert selected.receipt == receipt and before == after and known == {NUMBER}
        journal.record(key, "FAILED", reason_code="SOURCE_FAILURE")
        with (
            storage.transaction(m.COMPANY, consistent_read=True) as conn,
            pytest.raises(ValueError, match="NO_VERIFIED_DAILY_TARGET"),
        ):
            m.select_target(conn, now)
    finally:
        engine.dispose()
