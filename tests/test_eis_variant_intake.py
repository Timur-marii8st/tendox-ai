"""Automatic retained intake is partial, fetch-free and failure-safe."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from procurement.sources import eis_variant_intake as subject
from procurement.storage.eis_notice_projection import EisNoticeProjectionReport


def projection(*, replayed=False, projected=2, held=1):
    return EisNoticeProjectionReport(
        batch_id="batch",
        receipt_id="receipt",
        archive_count=1,
        occurrence_count=4,
        pair_count=3,
        projected_count=projected,
        replayed_count=3 - projected - held,
        held_count=held,
        replayed=replayed,
        audit_event_id="projection-audit",
    )


@pytest.fixture
def deps(monkeypatch):
    ledger = Mock(return_value=SimpleNamespace(receipt_id="receipt", audit_event_id="ledger-audit"))
    project = Mock(return_value=projection())
    monkeypatch.setattr(subject, "store_notice_variants", ledger)
    monkeypatch.setattr(subject, "project_retained_notice_variants", project)
    return ledger, project


def intake():
    archives = (b"already-retained-zip",)
    return subject.intake_notice_variants(
        None, "tenant", SimpleNamespace(status="RETAINED"), object(), archives, actor_id="worker"
    ), archives


@pytest.mark.parametrize(
    "status, diagnosed", [(None, True), ("DISABLED", True), ("FAILED", True), ("RETAINED", False)]
)
def test_missing_prerequisites_never_touch_storage(deps, status, diagnosed):
    evidence = SimpleNamespace(status=status) if status else None
    result = subject.intake_notice_variants(
        None, "tenant", evidence, object() if diagnosed else None, (b"zip",), actor_id="worker"
    )
    assert result.status == "NOT_ATTEMPTED" and result.new_versions == 0
    assert result.coverage == "UNKNOWN"
    for operation in deps:
        operation.assert_not_called()


@pytest.mark.parametrize(
    "replayed, projected, held", [(False, 2, 1), (True, 2, 1), (False, 3, 0), (False, 0, 3)]
)
def test_success_is_always_partial_and_reuses_exact_bytes(deps, replayed, projected, held):
    ledger, project = deps
    project.return_value = projection(replayed=replayed, projected=projected, held=held)
    result, archives = intake()
    assert (
        result.status == "PARTIAL" and result.stage == "COMPLETE" and result.coverage == "UNKNOWN"
    )
    assert result.ledger_receipt_id == "receipt" and result.ledger_audit_event_id == "ledger-audit"
    assert result.new_versions == (0 if replayed else projected)
    assert project.call_args.args[3] is archives
    ledger.assert_called_once()
    project.assert_called_once()


@pytest.mark.parametrize("stage", ["LEDGER", "PROJECTION"])
@pytest.mark.parametrize(
    "failure, code",
    [
        (RuntimeError("secret=credential; source XML and DSN"), None),
        (ValueError("ARBITRARY_SECRET_SHAPED_CODE"), None),
        (ValueError("NOTICE_PROJECTION_HISTORY_LIMIT"), "NOTICE_PROJECTION_HISTORY_LIMIT"),
        (
            OperationalError("sensitive SQL", {"password": "secret"}, RuntimeError("dsn")),
            "DATABASE_FAILED",
        ),
    ],
)
def test_failures_keep_original_stage_and_only_durable_ids(deps, stage, failure, code):
    ledger, project = deps
    (ledger if stage == "LEDGER" else project).side_effect = failure
    result, _ = intake()
    assert result.status == "FAILED" and result.stage == stage
    assert result.reason == (code or f"{stage}_FAILED")
    assert result.new_versions == 0 and result.projection is None
    assert result.ledger_receipt_id == ("receipt" if stage == "PROJECTION" else None)
    assert result.ledger_audit_event_id == ("ledger-audit" if stage == "PROJECTION" else None)
    if stage == "LEDGER":
        project.assert_not_called()
    encoded = result.model_dump_json()
    assert "secret" not in encoded and "dsn" not in encoded and "sensitive" not in encoded


def test_inconsistent_projection_counts_cannot_be_partial(deps):
    deps[1].return_value = projection().model_copy(update={"held_count": 999})
    result, _ = intake()
    assert result.status == "FAILED" and result.stage == "PROJECTION"
    assert result.ledger_receipt_id == "receipt" and result.new_versions == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "PARTIAL", "stage": "COMPLETE", "reason": None},
        {"status": "NOT_ATTEMPTED", "ledger_receipt_id": "receipt"},
        {"status": "FAILED", "stage": "LEDGER", "reason": "secret-dsn"},
        {"status": "FAILED", "stage": "PROJECTION", "reason": "DATABASE_FAILED"},
    ],
)
def test_invalid_report_never_claims_admission(payload):
    with pytest.raises(ValidationError):
        subject.EisVariantIntakeReport(**payload)
