"""A saved CC proposal cannot silently become a verified final contract price."""

from contextlib import contextmanager
from types import SimpleNamespace

from procurement.sources.eis_feed_archive import EisNoticeSnapshot
from procurement.sources.tender_navigation import NavigationFact
from procurement.storage import regional_discount as module
from procurement.storage.eis_document_store import NoticeDocumentRef
from test_eis_protocols import PLACEMENT, parse, protocol_xml, result_row
from test_regional_discount import NOW, SOURCE


class Storage:
    def __init__(self):
        self.sql = []

    @contextmanager
    def transaction(self, company, *, consistent_read):
        assert company == "tenant-a" and consistent_read
        yield SimpleNamespace(exec_driver_sql=self.sql.append)


def test_cc_proposal_keeps_price_evidence_but_cannot_enter_financial_history(monkeypatch):
    document = parse(
        protocol_xml(
            PLACEMENT, "<n:applications>" + result_row(kind=PLACEMENT) + "</n:applications>"
        )
    )
    ref = NoticeDocumentRef(
        purchase_number=document.purchase_number, version_number=1, notice_xml_sha256="a" * 64
    )
    notice = EisNoticeSnapshot(
        purchase_number=ref.purchase_number,
        document_type="epNotificationEOK2020",
        version_number=1,
        title="Synthetic",
        published_at=NOW,
        deadline=NOW,
        nmck_rub=None,
        xml_sha256=ref.notice_xml_sha256,
        source_member="notice.xml",
    )
    monkeypatch.setattr(module, "load_notice", lambda *args: notice)
    observed_timeouts = []

    def protocols(*args, **kwargs):
        observed_timeouts.append(kwargs["statement_timeout_ms"])
        return SimpleNamespace(documents=[document])

    monkeypatch.setattr(module, "read_historical_protocols", protocols)
    monkeypatch.setattr(
        module,
        "read_navigation",
        lambda *args: SimpleNamespace(
            delivery_regions=(
                NavigationFact(value="Region A", provenance=SOURCE, supporting_sources=(SOURCE,)),
            )
        ),
    )
    storage = Storage()
    observation = module.read_regional_observation(storage, "tenant-a", ref, now=NOW)
    assert observation.final.value == document.applications[0].proposal.amount.value
    assert observation.final.source.document_id == document.source.xml_sha256
    assert observation.region.supporting_sources == (SOURCE,)
    for name in (
        "notice_lot_volume_link",
        "rub_nominal_totals",
        "concluded_contract",
        "current_result",
        "concluded_at",
    ):
        assert getattr(observation, name).value is None
    assert observation.product_key.value is observation.quantity.value is None
    assert observed_timeouts == [5000]
    assert storage.sql == ["SET LOCAL statement_timeout = '5000ms'"]

    # A second placement document makes even the proposal ambiguous.
    monkeypatch.setattr(
        module,
        "read_historical_protocols",
        lambda *a, **k: SimpleNamespace(documents=[document, document]),
    )
    assert module.read_regional_observation(storage, "tenant-a", ref, now=NOW).final.value is None


def test_protocol_timeout_override_rejects_unbounded_or_inexact_values_before_sql():
    import pytest

    from procurement.storage.eis_protocols import read_historical_protocols

    for value in (True, 0, 20001, 1.5, "5000; SELECT 1"):
        with pytest.raises(ValueError, match="PROTOCOL_TIMEOUT_INVALID"):
            read_historical_protocols(None, "tenant-a", None, now=NOW, statement_timeout_ms=value)
