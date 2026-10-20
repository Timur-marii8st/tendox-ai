"""Whole-queue census, latest state and RLS verified on isolated PostgreSQL."""

import uuid
from datetime import timedelta

from sqlalchemy import insert
from test_eis_corpus_fairness_pg import (
    NOW,
    _attempt,
    _counts,
    _key,
    _target,
    storage,  # noqa: F401 -- shared isolated fixture
)

from procurement.storage.eis_gap_status import read_eis_gap_status
from procurement.storage.models import eis_feed_windows, eis_sync_attempts, eis_sync_targets


def test_exact_totals_latest_provenance_bounded_samples_and_tenant_scope(storage):  # noqa: F811
    company, other = f"gap-{uuid.uuid4().hex}", f"gap-{uuid.uuid4().hex}"
    keys = [_key(n, "2026-09-20") for n in range(1, 10)]
    with storage.transaction(company) as conn:
        conn.execute(insert(eis_sync_targets), [_target(company, k) for k in keys])
        attempts = []
        for n, outcome, code in (
            (1, "NO_DATA", None),
            (2, "FAILED", "SOURCE_TRANSPORT_FAILED"),
            (3, "FAILED", "SOURCE_TRANSPORT_FAILED"),
            (4, "FAILED", "NOTICE_VERSION_CONFLICT"),
            (5, "FAILED", "SOURCE_WSDL_UNAVAILABLE"),
            (6, "SERVICE_ERROR", None),
            (7, "FAILED", "ATTACHMENT_REFERENCE_INVALID"),
            (8, "PREPARING", None),
        ):
            row = _attempt(company, keys[n], outcome, NOW - timedelta(hours=48))
            row["reason_code"] = code
            if n == 5:
                row["attempted_at"] = NOW - timedelta(hours=23)
            attempts.append(row)
        shadow = _attempt(company, keys[3], "NO_DATA", NOW - timedelta(hours=25))
        attempts.append(shadow)
        # Immutable ID is the deterministic tie-break, not insertion order.
        older = _attempt(company, keys[7], "FAILED", NOW - timedelta(hours=48))
        older["reason_code"] = "SOURCE_TRANSPORT_FAILED"
        older["attempt_id"] = "00000000-0000-0000-0000-000000000000"
        attempts.append(older)
        conn.execute(insert(eis_sync_attempts), attempts)
        for index, kind in ((2, "LEGACY_CANONICAL"), (4, "VARIANT_TRANSPORT")):
            conn.execute(
                insert(eis_feed_windows).values(
                    company_id=company,
                    window_key=keys[index],
                    response_sha256="b" * 64,
                    manifest_sha256="c" * 64,
                    archive_count=1,
                    notice_count=0,
                    intake_kind=kind,
                    coverage="UNKNOWN",
                    ingested_at=NOW,
                )
            )
    with storage.transaction(other) as conn:
        conn.execute(insert(eis_sync_targets), [_target(other, keys[0])])
        conn.execute(insert(eis_sync_attempts), [_attempt(other, keys[0], "NO_DATA", NOW)])
    before = _counts(storage, company)
    result = read_eis_gap_status(storage, company, now=NOW, sample_limit=3)
    assert (result.planned_targets, result.completed_targets, result.pending_targets) == (9, 1, 8)
    assert result.unattempted_targets == 1 and result.no_data_targets == 2
    assert result.historical_source_retry_due == 2 and result.transport_only_targets == 1
    assert result.invalid_source_coordinates == 0 and result.candidate_region_codes == 8
    assert result.samples_truncated and len(result.samples) == 3
    assert {s.window_key for s in result.samples[:2]} == {keys[6], keys[8]}
    assert all(s.historical_source_retry_due for s in result.samples[:2])
    assert sum(g.targets for g in result.groups) == 8
    assert result.status == "OBSERVED" and result.coverage == result.freshness == "UNKNOWN"
    full = read_eis_gap_status(storage, company, now=NOW, sample_limit=100)
    sample = {s.window_key: s for s in full.samples}
    assert sample[keys[0]].outcome is None
    assert sample[keys[3]].attempt_id == shadow["attempt_id"]
    assert sample[keys[7]].reason_code == "ATTACHMENT_REFERENCE_INVALID"
    assert not sample[keys[4]].historical_source_retry_due
    assert not sample[keys[5]].historical_source_retry_due
    assert keys[2] not in sample and not full.samples_truncated
    assert _counts(storage, company) == before
    assert read_eis_gap_status(storage, other, now=NOW).pending_targets == 1


def test_invalid_dates_hour_windows_and_empty_queue_remain_safe(storage):  # noqa: F811
    company = f"gap-coordinates-{uuid.uuid4().hex}"
    valid = _key(77, "2026-09-20")
    hourly = valid.replace("+03:00", "/10+03:00")
    keys = (valid, hourly, _key(78, "2026-99-99"), "unknown-window")
    with storage.transaction(company) as conn:
        conn.execute(insert(eis_sync_targets), [_target(company, k) for k in keys])
        conn.execute(
            insert(eis_sync_attempts),
            [_attempt(company, k, "SERVICE_ERROR", NOW - timedelta(hours=25)) for k in keys],
        )
    result = read_eis_gap_status(storage, company, now=NOW)
    assert result.pending_targets == 4 and result.invalid_source_coordinates == 2
    assert result.status == "UNKNOWN" and result.historical_source_retry_due == 1
    assert sum(s.historical_source_retry_due for s in result.samples) == 1
    empty = read_eis_gap_status(storage, f"gap-empty-{uuid.uuid4().hex}", now=NOW)
    assert empty.pending_targets == empty.planned_targets == empty.completed_targets == 0
    assert empty.groups == empty.samples == () and empty.coverage == "UNKNOWN"
