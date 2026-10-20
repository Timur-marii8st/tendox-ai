"""Polling capacity and lag must not become a false source-completeness PASS."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from procurement.sources.eis_freshness_status import EisWindowObservation, capacity_estimate
from procurement.sources.eis_variant_intake import EisVariantIntakeReport
from procurement.storage.eis_notice_projection import EisNoticeProjectionReport

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


def variant_intake(*, replayed: bool = False) -> EisVariantIntakeReport:
    projection = EisNoticeProjectionReport(
        batch_id="batch-1",
        receipt_id="receipt-1",
        archive_count=2,
        occurrence_count=3,
        pair_count=2,
        projected_count=0 if replayed else 2,
        replayed_count=2 if replayed else 0,
        held_count=0,
        replayed=replayed,
        audit_event_id="audit-1",
    )
    return EisVariantIntakeReport(
        status="PARTIAL",
        stage="COMPLETE",
        reason=None,
        ledger_receipt_id="receipt-1",
        ledger_audit_event_id="ledger-audit-1",
        projection=projection,
    )


def retained_variant_observation(*, replayed: bool = False, **changes) -> EisWindowObservation:
    intake = variant_intake(replayed=replayed)
    values = {
        "outcome": "FAILED",
        "rejection_retention_status": "RETAINED",
        "rejection_manifest_sha256": "c" * 64,
        "rejection_audit_status": "RECORDED",
        "rejection_diagnosis_audit_status": "RECORDED",
        "rejection_diagnosis_sha256": "d" * 64,
        "variant_intake": intake,
        "new_versions": intake.new_versions,
        **changes,
    }
    return observation(**values)


def test_conflict_diagnosis_reference_requires_failed_audited_full_retention():
    retained = dict(
        outcome="FAILED",
        rejection_retention_status="RETAINED",
        rejection_manifest_sha256="c" * 64,
        rejection_audit_status="RECORDED",
        rejection_diagnosis_audit_status="RECORDED",
        rejection_diagnosis_sha256="d" * 64,
    )
    assert observation(**retained).rejection_diagnosis_sha256 == "d" * 64
    for invalid in (
        {"outcome": "SYNCED"},
        {"rejection_audit_status": "FAILED"},
        {"rejection_diagnosis_sha256": None},
        {"rejection_diagnosis_audit_status": "FAILED"},
        {"rejection_retention_status": "UNAVAILABLE", "rejection_manifest_sha256": None},
    ):
        with pytest.raises(ValidationError):
            observation(**{**retained, **invalid})


def test_partial_variant_intake_requires_failed_full_audited_evidence_and_matching_versions():
    assert retained_variant_observation().variant_intake == variant_intake()
    for changes in (
        {"outcome": "SYNCED"},
        {"rejection_retention_status": "FAILED", "rejection_manifest_sha256": None},
        {"rejection_audit_status": "FAILED"},
        {"rejection_diagnosis_audit_status": "FAILED", "rejection_diagnosis_sha256": None},
        {"new_versions": 1},
    ):
        with pytest.raises(ValidationError):
            retained_variant_observation(**changes)


def test_replayed_variant_intake_requires_zero_new_versions():
    replay = retained_variant_observation(replayed=True)
    assert replay.new_versions == 0
    assert replay.variant_intake is not None and replay.variant_intake.new_versions == 0
    with pytest.raises(ValidationError):
        retained_variant_observation(replayed=True, new_versions=1)


def test_historical_observation_without_variant_field_remains_compatible():
    payload = observation().model_dump(mode="json", exclude={"variant_intake"})
    restored = EisWindowObservation.model_validate(payload)
    assert restored.variant_intake is None and restored.outcome == "SYNCED"


def test_partial_failed_projection_versions_do_not_become_completed_capacity():
    partial = retained_variant_observation()
    estimate = capacity_estimate((observation(), partial), regions=2, document_types=4)
    assert partial.new_versions == 2
    assert estimate.samples == 2
    assert estimate.completed_samples == 1
    assert estimate.failed_samples == 1
    assert estimate.p95_ms == Decimal(20000)


def observation(**changes) -> EisWindowObservation:
    return EisWindowObservation.model_validate(
        {
            "company_id": "tenant-a",
            "window_key": "getDocsIP/PRIZ/50/2026-10-01/10+03:00",
            "region": "50",
            "document_type": "epNotificationEF2020",
            "lane": "RECENT_HOUR",
            "started_at": NOW,
            "finished_at": NOW + timedelta(seconds=20),
            "duration_ms": "20000",
            "outcome": "SYNCED",
            "response_sha256": "a" * 64,
            **changes,
        }
    )


def test_missing_or_invalid_evidence_does_not_make_a_success() -> None:
    for changes in (
        {"started_at": NOW.replace(tzinfo=None)},
        {"finished_at": NOW - timedelta(seconds=1)},
        {"response_sha256": None},
        {"response_sha256": "bad"},
        {"duration_ms": "-1"},
        {"duration_ms": "NaN"},
    ):
        with pytest.raises(ValidationError):
            observation(**changes)
    assert observation(outcome="FAILED", response_sha256=None).archive_bytes is None


def test_unknown_capacity_until_measured_and_all_failures_are_counted() -> None:
    estimate = capacity_estimate((), regions=2, document_types=4)
    assert estimate.samples == 0 and estimate.p95_ms is None
    assert estimate.recent_poll_budget_fit == estimate.overall_feasibility == "UNKNOWN"
    failed = observation(outcome="FAILED", response_sha256=None, duration_ms="300000")
    estimate = capacity_estimate((observation(), failed), regions=2, document_types=4)
    assert estimate.failed_samples == 1 and estimate.completed_samples == 1
    assert estimate.p95_ms == Decimal(20000)
    assert estimate.measured_slots_per_hour is None
    assert estimate.peak_budget_fit == "UNKNOWN"


def test_projected_budget_accounts_for_every_hour_lane_and_cadence() -> None:
    samples = tuple(observation() for _ in range(8))
    estimate = capacity_estimate(samples, regions=4, document_types=4, run_slots=8)
    assert estimate.measured_slots_per_hour == 96
    assert estimate.conservative_peak_slots_per_hour == Decimal("87.333")
    assert estimate.recent_poll_budget_fit == estimate.peak_budget_fit == "PASS"
    assert estimate.overall_feasibility == "UNKNOWN"
    wide = capacity_estimate(samples, regions=99, document_types=4)
    assert wide.peak_budget_fit == wide.recent_poll_budget_fit == "FAIL"
    assert wide.overall_feasibility == "UNKNOWN"
    slow = capacity_estimate(
        tuple(observation(duration_ms="50000") for _ in range(8)), regions=4, document_types=4
    )
    assert slow.measured_slots_per_hour == 48 and slow.peak_budget_fit == "FAIL"


def test_capacity_uses_explicit_runtime_budget_instead_of_old_eight_slots() -> None:
    samples = tuple(observation(duration_ms="8000") for _ in range(8))
    expanded = capacity_estimate(
        samples, regions=3, document_types=4, run_slots=24, run_seconds=240, cadence_seconds=300
    )
    assert expanded.nominal_slots_per_hour == expanded.measured_slots_per_hour == 288
    limited = capacity_estimate(
        samples, regions=3, document_types=4, run_slots=24, run_seconds=60, cadence_seconds=600
    )
    assert limited.nominal_slots_per_hour == 144
    assert limited.measured_slots_per_hour == 36
    assert limited.overall_feasibility == "UNKNOWN"


def test_capacity_accepts_actual_default_family_scope_and_rejects_unsupported_count() -> None:
    from procurement.sources.eis_freshness import EisFreshnessScope

    scope = EisFreshnessScope(("50", "77", "78"))
    estimate = capacity_estimate(
        (), regions=len(scope.regions), document_types=len(scope.document_types)
    )
    assert estimate.required_latest_hour_slots_per_hour == len(scope.regions) * len(
        scope.document_types
    )
    assert estimate.overall_feasibility == estimate.recent_poll_budget_fit == "UNKNOWN"
    with pytest.raises(ValueError, match="CAPACITY_SCOPE_INVALID"):
        capacity_estimate((), regions=3, document_types=len(scope.document_types) + 1)
