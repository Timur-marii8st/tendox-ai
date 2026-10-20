"""Foreground scope cannot promise full EIS or starve baseline refresh."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from procurement.sources.eis_feed_archive import SUPPORTED_NOTICE_TYPES
from procurement.sources.eis_freshness import EisFreshnessScope
from procurement.storage.eis_freshness_requests import (
    EisRefreshRequest,
    EisRefreshRequestPayload,
    _status,
    fair_targets,
    request_targets,
)

NOW = datetime(2026, 10, 1, 10, 15, tzinfo=UTC)


def test_request_validates_scope_and_never_selects_ineligible_hours():
    for regions in (("00",), ("all",), ("50", "50"), ("50", "77", "78", "66")):
        with pytest.raises(ValidationError):
            EisRefreshRequestPayload(query="бумага", regions=regions)
    with pytest.raises(ValidationError):
        EisRefreshRequestPayload(query="  ", regions=("50",))
    with pytest.raises(ValidationError):
        EisRefreshRequestPayload(query="бумага", regions=("50",), company_id="other")
    targets = request_targets(EisRefreshRequestPayload(query="бумага", regions=("50",)), NOW)
    assert len(targets) == 3 * len(SUPPORTED_NOTICE_TYPES)
    assert {item.lane for item in targets} == {"RECENT_HOUR", "RECONCILE_DAY"}
    assert all(item.selection.day <= NOW.date() for item in targets)
    midnight = request_targets(
        EisRefreshRequestPayload(query="бумага", regions=("50",)),
        datetime(2026, 10, 1, 21, 1, tzinfo=UTC),
    )
    assert len(midnight) == len(SUPPORTED_NOTICE_TYPES) and all(
        item.lane == "RECONCILE_DAY" for item in midnight
    )


def test_fair_slots_are_unique_and_both_queues_progress():
    baseline = EisFreshnessScope(("50",)).targets(NOW)
    foreground = request_targets(EisRefreshRequestPayload(query="сервер", regions=("66",)), NOW)
    picked = fair_targets(foreground, baseline, limit=8)
    assert len(picked) == len({item.selection.window_key for item in picked}) == 8
    assert sum(item.selection.region == "66" for item in picked) == 4
    assert sum(item.selection.region == "50" for item in picked) == 4
    assert fair_targets(baseline, baseline, limit=8) == baseline[:8]
    assert fair_targets((), baseline, limit=8) == baseline[:8]


def test_poll_result_needs_post_request_evidence_and_expiry_never_becomes_pass():
    from datetime import timedelta

    payload = EisRefreshRequestPayload(query="бумага", regions=("50",))
    request = EisRefreshRequest(
        request_id="00000000-0000-0000-0000-000000000001",
        company_id="tenant-a",
        payload=payload,
        requested_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        window_keys=tuple(item.selection.window_key for item in request_targets(payload, NOW)),
    )
    row = {
        "outcome": "NO_DATA",
        "attempt_id": "attempt-1",
        "attempted_at": NOW,
        "source_response_sha256": "a" * 64,
        "reason_code": None,
    }
    status = _status(request, dict.fromkeys(request.window_keys, row), NOW)
    assert status.status == "POLLED" and status.no_data_windows == len(request.window_keys)
    assert status.coverage == status.freshness == "UNKNOWN"
    for changes in (
        {"attempted_at": NOW - timedelta(seconds=1)},
        {"attempted_at": NOW + timedelta(seconds=1)},
        {"source_response_sha256": None},
        {"outcome": "FAILED"},
    ):
        status = _status(request, {key: {**row, **changes} for key in request.window_keys}, NOW)
        assert status.polled_windows == 0 and status.pending_windows == len(request.window_keys)
    expired = _status(request, {}, NOW + timedelta(hours=1))
    assert expired.status == "EXPIRED" and expired.freshness == "UNKNOWN"
