"""Real isolated PostgreSQL catalog revalidation, frozen scope and tenant safety."""

from datetime import timedelta
from uuid import uuid4

import pytest
from migration_support import assert_direct_downgrade_guard
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import DBAPIError
from test_eis_223_regions_pg import attempt, seed
from test_eis_223_regions_pg import storage as pg_storage

from procurement.storage.eis_223_catalog_checks import catalog_refresh_due, record_catalog_check
from procurement.storage.eis_223_regions import (
    ensure_region_wave,
    read_region_coverage,
    regional_due_windows,
)
from procurement.storage.models import (
    audit_events,
)
from procurement.storage.models import (
    eis_223_region_catalog_checks as checks,
)
from procurement.storage.models import (
    eis_223_region_catalogs as catalogs,
)
from test_eis_223_regions import NOW, catalog_html


@pytest.fixture(scope="module")
def storage():
    yield from pg_storage.__wrapped__()


def check(storage, company, raw=None, now=NOW, **kwargs):
    return record_catalog_check(storage, company, raw, checked_at=now, actor_id="test", **kwargs)


def counts(storage, company):
    with storage.transaction(company) as conn:
        return tuple(
            conn.scalar(select(func.count()).select_from(t))
            for t in (catalogs, checks, audit_events)
        )


def test_same_sha_recheck_replay_and_cooldown_do_not_mutate_retained_body(storage):
    company = "recheck-" + uuid4().hex
    wave = seed(storage, company)
    assert catalog_refresh_due(storage, company, NOW)
    first = check(storage, company, catalog_html(), attempt_id="first")
    before = counts(storage, company)
    assert check(storage, company, catalog_html(), attempt_id="first") == first
    assert counts(storage, company) == before
    with pytest.raises(ValueError, match="REPLAY_CONFLICT"):
        check(storage, company, catalog_html(), now=NOW + timedelta(seconds=1), attempt_id="first")
    assert not catalog_refresh_due(storage, company, NOW + timedelta(hours=23, minutes=59))
    later = NOW + timedelta(days=1)
    assert catalog_refresh_due(storage, company, later)
    second = check(storage, company, catalog_html(), now=later)
    assert second.catalog_sha256 == first.catalog_sha256
    assert counts(storage, company)[0:2] == (1, 2)
    status = read_region_coverage(storage, company, now=later)
    assert status.wave_id == wave and status.catalog_observed_at == NOW
    assert status.catalog_last_success_at == later and status.latest_catalog_checked_at == later
    with pytest.raises(ValueError, match="CLOCK_SKEW"):
        catalog_refresh_due(storage, company, NOW)


@pytest.mark.parametrize("case", ["malformed", "removal", "http"])
def test_failed_or_removed_membership_retains_last_success_and_frozen_wave(storage, case):
    company = "rejected-" + uuid4().hex
    wave = seed(storage, company)
    first = check(storage, company, catalog_html())
    later = NOW + timedelta(hours=1)
    raw = b"<html>challenge</html>" if case == "malformed" else catalog_html(("50", "77"))
    rejected = check(
        storage,
        company,
        None if case == "http" else raw,
        now=later,
        **({"reason": "HTTP_REJECTED", "http_status": 503} if case == "http" else {}),
    )
    assert rejected.status == ("REVIEW_REQUIRED" if case == "removal" else "FAILED")
    assert rejected.catalog_sha256 is None and counts(storage, company)[0] == 1
    assert not catalog_refresh_due(storage, company, later + timedelta(minutes=59))
    assert catalog_refresh_due(storage, company, later + timedelta(hours=1))
    coverage = read_region_coverage(storage, company, now=later)
    assert coverage.wave_id == wave and coverage.catalog_regions == 3
    assert coverage.catalog_last_success_at == NOW
    assert coverage.latest_catalog_sha256 == first.catalog_sha256
    assert coverage.catalog_check_status == rejected.status


def test_added_catalog_applies_next_wave_and_rollback_cannot_drop_new_members(storage):
    company = "added-" + uuid4().hex
    wave = seed(storage, company)
    first = check(storage, company, catalog_html())
    added = check(
        storage, company, catalog_html(("50", "77", "78", "99")), now=NOW + timedelta(hours=1)
    )
    status = read_region_coverage(storage, company, now=NOW + timedelta(hours=1))
    assert status.planned == 30 and status.catalog_sha256 == first.catalog_sha256
    assert status.latest_catalog_sha256 == added.catalog_sha256
    assert status.catalog_last_success_at == NOW
    assert ensure_region_wave(storage, company, NOW + timedelta(days=1), actor_id="test") == wave
    for target in regional_due_windows(storage, company, NOW):
        attempt(storage, company, target)
    assert ensure_region_wave(storage, company, NOW + timedelta(days=1), actor_id="test") != wave
    assert read_region_coverage(storage, company, now=NOW + timedelta(days=1)).planned == 40
    reverting = check(storage, company, catalog_html(), now=NOW + timedelta(days=1))
    assert reverting.status == "REVIEW_REQUIRED"
    assert (
        read_region_coverage(storage, company, now=NOW + timedelta(days=1)).latest_catalog_sha256
        == added.catalog_sha256
    )


def test_name_only_a_b_a_uses_latest_observation_not_initial_content_time(storage):
    company = "revert-name-" + uuid4().hex
    seed(storage, company)
    first = check(storage, company, catalog_html())
    other = catalog_html().replace(b"Region 50", b"Renamed 50")
    check(storage, company, other, now=NOW + timedelta(hours=1))
    last = check(storage, company, catalog_html(), now=NOW + timedelta(hours=2))
    status = read_region_coverage(storage, company, now=NOW + timedelta(hours=2))
    assert last.status == "ACCEPTED" and status.latest_catalog_sha256 == first.catalog_sha256
    assert counts(storage, company)[0] == 2


def test_journal_rls_immutable_fk_and_null_response_cannot_create_false_accepted(storage):
    company = "journal-" + uuid4().hex
    accepted = check(storage, company, catalog_html())
    for stmt in (delete(checks), update(checks).values(status="FAILED")):
        with pytest.raises(DBAPIError), storage.transaction(company) as conn:
            conn.execute(stmt)
    other = "other-" + uuid4().hex
    with storage.transaction(other) as conn:
        assert conn.scalar(select(func.count()).select_from(checks)) == 0
    for change in (
        {"company_id": other},
        {"response_sha256": None},
        {"catalog_sha256": "f" * 64},
        {"http_status": None},
    ):
        payload = {**accepted.model_dump(), "attempt_id": uuid4().hex, **change}
        with pytest.raises(DBAPIError), storage.transaction(company) as conn:
            conn.execute(insert(checks).values(**payload))


def test_catalog_observation_history_blocks_downgrade_any_tenant(storage):
    company = "catalog-downgrade-" + uuid4().hex
    seed(storage, company)
    check(storage, company, catalog_html())
    before = counts(storage, company)
    assert_direct_downgrade_guard(
        "20261003_05_eis_223_catalog_checks",
        expected_database="procurement_eis_test_20261005_s209",
        match="catalog observation history must be preserved",
        tenant_context="unrelated-" + uuid4().hex,
    )
    assert counts(storage, company) == before
