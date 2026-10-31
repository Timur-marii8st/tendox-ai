"""Pure history-demand classification; these outcomes never authorize a source call."""

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone

import pytest

from procurement.eis_history_demand import classify_history_demand
from procurement.storage.eis_223_regions import FAMILIES

NOW = datetime(2026, 10, 28, 5, 0, tzinfo=UTC)


def scope(law, checked_at=NOW - timedelta(seconds=2)):
    zone = timezone(timedelta(hours=3))
    local = checked_at.astimezone(zone)
    days = [local.date() - timedelta(days=n) for n in range(1, 4)]
    if law == "44":
        days = [
            d
            for d in days
            if datetime.combine(d, datetime.min.time(), zone)
            + timedelta(days=1, hours=2, minutes=5)
            <= checked_at
        ]
    data = {
        "company_id": "tenant",
        "law": law,
        "regions": ("50", "77"),
        "document_types": (
            ("epNotificationEF2020", "epNotificationEZK2020")
            if law == "44"
            else tuple(sorted(FAMILIES))
        ),
        "catalog_sha256": "a" * 64,
        "query_at": checked_at.astimezone(UTC).isoformat(),
        "timezone": "+03:00",
        "days": [d.isoformat() for d in days],
        "cutoff": "completed-day-plus-02:05" if law == "44" else "recent-three-msk-days",
    }
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def observation():
    return {
        "company_id": "tenant",
        "regions": ["50", "77"],
        "document_types": ["epNotificationEF2020", "epNotificationEZK2020"],
        "read_started_at": NOW - timedelta(seconds=5),
        "checked_at": NOW - timedelta(seconds=1),
        "catalog_sha256": "a" * 64,
        "catalog_observation_id": "catalog-observation-1",
        "catalog_usable": True,
        "catalog_refresh_due": False,
        "checkpointed": True,
        "mandatory_only": True,
        "include_regional": True,
        "regional_scope_complete": True,
        "regional_document_types": sorted(FAMILIES),
        "probe": {
            "status": "READY",
            "company_id": "tenant",
            "regions": ["50", "77"],
            "document_types": ["epNotificationEF2020", "epNotificationEZK2020"],
            "checked_at": NOW - timedelta(seconds=2),
            "baseline_due": 1,
            "urgent_due": 0,
            "foreground_due": 0,
            "regional_due": 0,
            "regional_new_wave_due": False,
            "reason": None,
            "attempted": 0,
            "coverage": "UNKNOWN",
            "freshness": "UNKNOWN",
        },
        "reconciliation44": {
            "company_id": "tenant",
            "law": "44",
            "scope_sha256": scope("44"),
            "catalog_sha256": "a" * 64,
            "evidence_id": "reconcile44",
            "status": "CLEAR",
            "checked_at": NOW - timedelta(seconds=2),
            "scope_complete": True,
            "coordinates": [],
        },
        "reconciliation223": {
            "company_id": "tenant",
            "law": "223",
            "scope_sha256": scope("223"),
            "catalog_sha256": "a" * 64,
            "evidence_id": "reconcile223",
            "status": "CLEAR",
            "checked_at": NOW - timedelta(seconds=2),
            "scope_complete": True,
            "coordinates": [],
        },
    }


def classify(value, now=NOW):
    return classify_history_demand(
        value,
        company_id="tenant",
        regions=("50", "77"),
        document_types=("epNotificationEF2020", "epNotificationEZK2020"),
        regional_document_types=tuple(sorted(FAMILIES)),
        expected_catalog_sha256="a" * 64,
        expected_catalog_observation_id="catalog-observation-1",
        now=now,
    )


def test_known_ready_and_idle_are_descriptions_not_admission():
    value = observation()
    result = classify(value)
    assert result.status == "READY" and result.reason is None
    value["probe"]["status"] = "IDLE"
    value["probe"]["baseline_due"] = 0
    assert classify(value).status == "IDLE"
    value["catalog_refresh_due"] = True
    assert classify(value).status == "READY"


@pytest.mark.parametrize(
    "change",
    [
        "deferred",
        "blocked",
        "wrong_tenant",
        "wrong_scope",
        "missing_catalog",
        "bad_catalog",
        "unusable_catalog",
        "unknown_refresh",
        "naive_read",
        "future_read",
        "stale_read",
        "probe_outside_read",
        "unknown_reconciliation",
        "partial_clear",
        "due_without_evidence",
        "inconsistent_ready",
        "idle_with_due",
        "duplicate_region",
        "invalid_now",
        "extra_field",
        "regional_not_read",
        "region_partial",
        "wrong_reconciliation_tenant",
        "wrong_reconciliation_law",
        "wrong_reconciliation_scope",
        "wrong_expected_catalog",
        "missing_probe_field",
        "coerced_counter",
        "naive_nested_probe",
    ],
)
def test_uncertain_or_inconsistent_observations_fail_closed(change):
    value = deepcopy(observation())
    now = NOW
    if change == "deferred":
        value["probe"]["reason"] = "DEFERRED"
    elif change == "blocked":
        value["probe"]["status"] = "BLOCKED"
    elif change == "wrong_tenant":
        value["probe"]["company_id"] = "foreign"
    elif change == "wrong_scope":
        value["probe"]["regions"] = ["50"]
    elif change == "missing_catalog":
        value["catalog_observation_id"] = None
    elif change == "bad_catalog":
        value["catalog_sha256"] = "x" * 64
    elif change == "unusable_catalog":
        value["catalog_usable"] = False
    elif change == "unknown_refresh":
        value["catalog_refresh_due"] = None
    elif change == "naive_read":
        value["read_started_at"] = NOW.replace(tzinfo=None)
    elif change == "future_read":
        value["checked_at"] = NOW + timedelta(seconds=1)
    elif change == "stale_read":
        value["read_started_at"] = NOW - timedelta(seconds=31)
    elif change == "probe_outside_read":
        value["probe"]["checked_at"] = NOW - timedelta(seconds=6)
    elif change == "unknown_reconciliation":
        value["reconciliation44"]["status"] = "UNKNOWN"
    elif change == "partial_clear":
        value["reconciliation223"]["scope_complete"] = False
    elif change == "due_without_evidence":
        value["reconciliation44"]["status"] = "DUE"
    elif change == "inconsistent_ready":
        value["probe"]["baseline_due"] = 0
    elif change == "idle_with_due":
        value["probe"]["status"] = "IDLE"
    elif change == "duplicate_region":
        value["regions"] = ["50", "50", "77"]
    elif change == "invalid_now":
        now = NOW.replace(tzinfo=None)
    elif change == "extra_field":
        value["probe"]["unexpected"] = True
    elif change == "regional_not_read":
        value["include_regional"] = False
    elif change == "region_partial":
        value["regional_scope_complete"] = False
    elif change == "wrong_reconciliation_tenant":
        value["reconciliation44"]["company_id"] = "foreign"
    elif change == "wrong_reconciliation_law":
        value["reconciliation44"]["law"] = "223"
    elif change == "wrong_reconciliation_scope":
        value["reconciliation44"]["scope_sha256"] = "0" * 64
    elif change == "wrong_expected_catalog":
        value["catalog_sha256"] = "b" * 64
    elif change == "missing_probe_field":
        del value["probe"]["regional_due"]
    elif change == "coerced_counter":
        value["probe"]["baseline_due"] = "1"
    elif change == "naive_nested_probe":
        value["probe"]["checked_at"] = NOW.replace(tzinfo=None)
    assert classify(value, now).status == "BLOCKED"


def test_due_reconciliation_requires_a_concrete_coordinate():
    value = observation()
    value["probe"]["status"] = "IDLE"
    value["probe"]["baseline_due"] = 0
    value["reconciliation44"].update(
        {
            "status": "DUE",
            "checked_at": NOW - timedelta(seconds=2),
            "scope_complete": False,
            "coordinates": ["getDocsIP/PRIZ/50/2026-10-27+03:00"],
        }
    )
    assert classify(value).status == "READY"


def test_ready_cannot_be_invented_by_urgent_count_alone():
    value = observation()
    value["probe"]["baseline_due"] = 0
    value["probe"]["urgent_due"] = 100000
    assert classify(value).status == "BLOCKED"


def test_reconciliation_cannot_claim_foreign_coordinate():
    value = observation()
    value["probe"]["status"] = "IDLE"
    value["probe"]["baseline_due"] = 0
    value["reconciliation44"].update(
        {
            "status": "DUE",
            "checked_at": NOW - timedelta(seconds=2),
            "scope_complete": False,
            "coordinates": ["223/foreign/garbage"],
        }
    )
    assert classify(value).status == "BLOCKED"


def test_observation_digest_is_bound_to_tenant_and_expiring_read():
    value = observation()
    value["read_started_at"] = NOW - timedelta(seconds=30)
    result = classify(value)
    assert result.status == "READY" and result.company_id == "tenant"
    assert (
        len(result.observation_sha256) == 64 and result.read_started_at == value["read_started_at"]
    )
    assert classify(value, NOW + timedelta(microseconds=1)).status == "BLOCKED"


@pytest.mark.parametrize(
    "key",
    [
        "getDocsIP/PRIZ/50/2026-10-29+03:00",
        "getDocsIP/PRIZ/50/2000-01-01+03:00",
        "getDocsIP/PRIZ/50/2026-10-27+05:00",
        "getDocsIP/RI223/50/2026-10-28+03:00/purchaseNotice",
        "getDocsIP/RI223/50/2026-10-24+03:00/purchaseNotice",
    ],
)
def test_reconciliation_coordinate_outside_time_scope_is_blocked(key):
    value = observation()
    law = "223" if "/RI223/" in key else "44"
    value[f"reconciliation{law}"].update(status="DUE", coordinates=[key])
    assert classify(value).status == "BLOCKED"


def test_clear_scope_binds_query_time():
    value = observation()
    value["reconciliation44"]["scope_sha256"] = scope("44", NOW - timedelta(seconds=3))
    assert classify(value).status == "BLOCKED"


def test_foreground_must_be_included_in_urgent_count():
    value = observation()
    value["probe"].update(foreground_due=2, urgent_due=0)
    assert classify(value).status == "BLOCKED"


def test_223_event_families_are_in_scope():
    value = observation()
    value["reconciliation223"].update(
        status="DUE", coordinates=["getDocsIP/RI223/50/2026-10-27+03:00/purchaseRejection"]
    )
    assert classify(value).status == "READY"


def test_44_cutoff_and_223_differ_before_0205_moscow():
    now = datetime(2026, 10, 27, 22, 0, tzinfo=UTC)
    value = observation()
    for field in ("read_started_at", "checked_at"):
        value[field] = now - timedelta(seconds=5 if field == "read_started_at" else 1)
    value["probe"]["checked_at"] = now - timedelta(seconds=2)
    for law in ("44", "223"):
        value[f"reconciliation{law}"].update(
            checked_at=now - timedelta(seconds=2),
            scope_sha256=scope(law, now - timedelta(seconds=2)),
        )
    value["reconciliation44"].update(
        status="DUE", coordinates=["getDocsIP/PRIZ/50/2026-10-27+03:00"]
    )
    assert classify(value, now).status == "BLOCKED"
    value["reconciliation44"].update(status="CLEAR", coordinates=[])
    value["reconciliation223"].update(
        status="DUE", coordinates=["getDocsIP/RI223/50/2026-10-27+03:00/purchaseNotice"]
    )
    assert classify(value, now).status == "READY"


def test_scope_change_during_read_is_blocked():
    now = datetime(2026, 10, 27, 21, 0, 10, tzinfo=UTC)
    value = observation()
    value["read_started_at"] = now - timedelta(seconds=20)
    value["checked_at"] = now - timedelta(seconds=1)
    value["probe"]["checked_at"] = now - timedelta(seconds=2)
    for law in ("44", "223"):
        value[f"reconciliation{law}"].update(
            checked_at=now - timedelta(seconds=2),
            scope_sha256=scope(law, now - timedelta(seconds=2)),
        )
    assert classify(value, now).status == "BLOCKED"
