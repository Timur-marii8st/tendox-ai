"""Synthetic queue inputs; no HTTP, real source bytes or production database."""

import hashlib

import pytest
from lxml import etree as E

from procurement.sources import eis_223_quality_worker as worker
from procurement.sources.eis_223_archive import PURCHASE_NS, parse_notice223_xml
from procurement.sources.eis_223_schema import SchemaTree
from procurement.storage.eis_223_quality import SchemaTarget, pending_schema_targets
from test_eis_223_archive import xml, zip_bytes


def target():
    raw = xml()
    archive = zip_bytes([("notice.xml", raw)])
    return SchemaTarget(
        parse_notice223_xml(raw, source_member="notice.xml"),
        hashlib.sha256(archive).hexdigest(),
        archive,
    )


@pytest.fixture
def queue(monkeypatch):
    writes = []
    monkeypatch.setattr(worker, "pending_schema_targets", lambda *a: (target(),))
    monkeypatch.setattr(worker, "record_schema_check", lambda *a, **k: writes.append(a[2]) or True)

    def schema(path, release):
        return SchemaTree(
            release,
            E.XMLSchema(
                E.fromstring(
                    (
                        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" '
                        f'targetNamespace="{PURCHASE_NS}"><xs:element name="purchaseNoticeAESMBO" '
                        'type="xs:string"/></xs:schema>'
                    ).encode()
                )
            ),
        )

    monkeypatch.setattr(worker, "load_schema_tree", schema)
    return writes


def test_known_schema_fail_is_recorded_without_supplier_pass(queue):
    result = worker.process_quality_batch(object(), "tenant-a", actor_id="worker")
    assert result.attempted == 1 and result.new_checks == result.failed_checks == 2
    assert result.source_requests == 0 and result.eligibility == "UNKNOWN"
    assert len(queue) == 2 and all(c.status == "FAIL" for c in queue)


def test_empty_queue_does_not_read_schema_or_write(monkeypatch):
    monkeypatch.setattr(worker, "pending_schema_targets", lambda *a: ())
    monkeypatch.setattr(worker, "load_schema_tree", lambda *a: pytest.fail("unexpected FS"))
    result = worker.process_quality_batch(object(), "tenant-a", actor_id="worker")
    assert result.reason == "NOT_DUE" and result.new_checks == 0


@pytest.mark.parametrize("change", ["archive", "xml", "member"])
def test_bad_source_binding_cannot_write_quality(monkeypatch, queue, change):
    t = target()
    if change == "archive":
        t = SchemaTarget(t.notice, "f" * 64, t.content)
    else:
        t = SchemaTarget(
            t.notice.model_copy(
                update={"xml_sha256": "f" * 64}
                if change == "xml"
                else {"source_member": "absent.xml"}
            ),
            t.archive_sha256,
            t.content,
        )
    monkeypatch.setattr(worker, "pending_schema_targets", lambda *a: (t,))
    with pytest.raises((ValueError, KeyError)):
        worker.process_quality_batch(object(), "tenant-a", actor_id="worker")
    assert queue == []


def test_soft_time_budget_defers_without_partial_version(monkeypatch, queue):
    ticks = iter((0, 31))
    monkeypatch.setattr(worker, "perf_counter", lambda: next(ticks))
    result = worker.process_quality_batch(object(), "tenant-a", actor_id="worker")
    assert result.reason == "TIME_BUDGET_REACHED" and result.attempted == 0 and not queue


@pytest.mark.parametrize("company", ["../tenant", "", "a/b"])
def test_unsafe_tenant_path_rejected_before_selection(company):
    with pytest.raises(ValueError, match="QUALITY_SCOPE_INVALID"):
        worker.process_quality_batch(object(), company, actor_id="worker")


@pytest.mark.parametrize("limit", [0, 3])
def test_selection_bound_is_checked_before_db(limit):
    with pytest.raises(ValueError, match="QUALITY_BATCH_LIMIT"):
        pending_schema_targets(object(), "tenant-a", limit=limit)
