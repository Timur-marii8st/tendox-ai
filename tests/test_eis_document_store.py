"""Notice variant guards for document reads and writes; no database calls."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import procurement.storage.eis_document_store as subject
from procurement.storage.eis_document_store import NoticeDocumentRef
from procurement.storage.eis_notice_hold import EisNoticeSourceHold

REF = NoticeDocumentRef(purchase_number="0" * 19, version_number=3, notice_xml_sha256="a" * 64)


def test_load_notice_checks_variant_hold_before_read(monkeypatch):
    calls = []

    def guard(connection, company_id, purchase_number, version_number):
        calls.append((company_id, purchase_number, version_number))
        raise ValueError("NOTICE_VARIANT_REVIEW_REQUIRED")

    monkeypatch.setattr(subject, "assert_notice_source_usable", guard)
    monkeypatch.setattr(
        subject,
        "_load_notice_raw",
        lambda *args: pytest.fail("notice row must not be read after a hold"),
    )
    with pytest.raises(ValueError, match=r"^NOTICE_VARIANT_REVIEW_REQUIRED$"):
        subject.load_notice(object(), "tenant-a", REF)
    assert calls == [("tenant-a", REF.purchase_number, REF.version_number)]


def test_read_gate_includes_typed_variant_blocker_without_full_report(monkeypatch):
    monkeypatch.setattr(
        subject,
        "resolve_procedure_state",
        lambda *args, **kwargs: SimpleNamespace(application_status="UNKNOWN", reasons=()),
    )
    notice = SimpleNamespace(
        xml_sha256=REF.notice_xml_sha256,
        source_member="notice.xml",
        version_number=REF.version_number,
        deadline=datetime.now(UTC) + timedelta(days=1),
        document_type="epNotificationEF2020",
    )
    hold = EisNoticeSourceHold(
        purchase_number=REF.purchase_number,
        selected_version_number=REF.version_number,
        status="HOLD",
        variant_count=1,
        origin_count=1,
        receipt_ids=("receipt-1",),
    )
    gate = subject._build_read_gate(
        notice,
        REF,
        (REF.version_number, REF.notice_xml_sha256),
        (),
        datetime.now(UTC),
        hold,
    )
    assert gate.blocked_reasons == ("NOTICE_VARIANT_REVIEW_REQUIRED",)
    assert "variants=1" in gate.evidence[-1]
    assert "receipt-1" not in gate.evidence[-1]
    assert gate.source_hold is not None
    assert gate.source_hold.receipt_ids == ("receipt-1",)


def test_document_read_gate_retains_audit_instead_of_raising_on_variant_hold(monkeypatch):
    notice = SimpleNamespace(
        xml_sha256=REF.notice_xml_sha256,
        source_member="notice.xml",
        version_number=REF.version_number,
        deadline=datetime.now(UTC) + timedelta(days=1),
        document_type="epNotificationEF2020",
    )
    hold = EisNoticeSourceHold(
        purchase_number=REF.purchase_number,
        selected_version_number=REF.version_number,
        status="HOLD",
        variant_count=1,
        origin_count=1,
        receipt_ids=("receipt-1",),
    )
    monkeypatch.setattr(subject, "_load_notice_raw", lambda *args: notice)
    monkeypatch.setattr(
        subject,
        "load_notice",
        lambda *args: pytest.fail("read gate must use the private raw load"),
    )
    monkeypatch.setattr(subject, "_latest", lambda *args: (3, "a" * 64))
    monkeypatch.setattr(subject, "_procedure_events", lambda *args: ())
    monkeypatch.setattr(subject, "read_notice_source_hold_connection", lambda *args: hold)
    monkeypatch.setattr(
        subject,
        "resolve_procedure_state",
        lambda *args, **kwargs: SimpleNamespace(application_status="UNKNOWN", reasons=()),
    )

    class Result:
        def first(self):
            return (REF.purchase_number,)

    class Connection:
        def __init__(self):
            self.statements = []

        def execute(self, statement, *args):
            self.statements.append(statement)
            return Result()

    connection = Connection()

    class Storage:
        @contextmanager
        def transaction(self, company_id):
            assert company_id == "tenant-a"
            yield connection

    gate = subject.document_read_gate(
        Storage(), "tenant-a", REF, actor_id="worker", now=datetime.now(UTC)
    )
    assert gate.blocked_reasons == ("NOTICE_VARIANT_REVIEW_REQUIRED",)
    assert any("audit_events" in str(statement) for statement in connection.statements)


def test_public_load_guard_is_shared_by_status_and_write_paths():
    # All entry points use the single strict loader; document_read_gate alone uses
    # the private loader so it can retain its idempotent blocked audit.
    guarded = (
        subject.plan_document_job,
        subject.read_document_status,
        subject.reanalyze_received_document,
        subject.record_document_outcome,
        subject.get_document_analysis,
    )
    for function in guarded:
        assert "load_notice" in function.__code__.co_names
    assert "_load_notice_raw" in subject.document_read_gate.__code__.co_names
    assert "load_notice" not in subject.document_read_gate.__code__.co_names
