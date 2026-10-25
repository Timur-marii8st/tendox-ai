"""An evidence bridge may expose leads but must not silently approve them."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from procurement.documents.extraction import ExtractedBlock
from procurement.domain.discovery_economics import DiscoveryCostInput
from procurement.domain.provenance import Extractor, Provenance
from procurement.sources.eis_analysis import ConditionSnippet, DocumentAnalysis
from procurement.sources.eis_competition_criteria import unknown_competition_criteria
from procurement.sources.eis_feed_archive import (
    EisLotItem,
    EisNoticeSnapshot,
    EisOfficialAttachment,
    EisProcedureEvent,
)
from procurement.storage.eis_document_store import (
    DocumentCollectionItem,
    DocumentCollectionStatus,
    NoticeDocumentRef,
)
from procurement.storage.eis_evidence_bridge import (
    _conditions,
    build_eis_evidence_bridge,
    calculate_eis_preliminary_estimate,
)

NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)
NUMBER = "0848300054826000154"
SHA = "a" * 64
UID = "A" * 32
URL = f"https://zakupki.gov.ru/44fz/filestore/public/1.0/download/priz/file.html?uid={UID}"


def contextual_analysis(*, following_locator="antiword-0.37-16 utf8 w0 :: line 10"):
    def block(text, locator):
        return ExtractedBlock(
            text=text,
            provenance=Provenance(
                document_id="b" * 64,
                locator=locator,
                extractor=Extractor.LEGACY_DOC_TEXT,
            ),
        )

    header = block("2. Место поставки:", "antiword-0.37-16 utf8 w0 :: line 8")
    address = block("Синтетический город, тестовый адрес", following_locator)
    return DocumentAnalysis(
        filename="spec.doc",
        url=URL,
        sha256="b" * 64,
        byte_count=100,
        status="UNKNOWN",
        reasons=("LAYOUT_NOT_VERIFIED",),
        blocks=(header, address),
        blocks_total=2,
        snippets=(
            ConditionSnippet(kind="Поставка", text=header.text, provenance=header.provenance),
        ),
    )


def test_heading_context_keeps_each_locator_without_approving_relation():
    result = _conditions(contextual_analysis())
    assert len(result) == 1 and len(result[0].context) == 1
    assert result[0].context[0].excerpt == "Синтетический город, тестовый адрес"
    assert result[0].context[0].provenance.locator.endswith("line 10")
    assert result[0].context[0].provenance.document_id == result[0].provenance.document_id
    assert result[0].context_status == "ADJACENT_UNREVIEWED"


@pytest.mark.parametrize(
    "locator",
    [
        'archive member "other.doc" :: antiword-0.37-16 utf8 w0 :: line 10',
        "antiword-0.37-16 utf8 w0 :: line 50",
        "antiword-0.37-16 utf8 w0 :: line 7",
        "page 10",
    ],
)
def test_context_never_crosses_member_or_locator_gap(locator):
    result = _conditions(contextual_analysis(following_locator=locator))
    assert not result[0].context and result[0].context_status == "UNKNOWN"


def test_context_source_digest_mismatch_cannot_become_evidence():
    analysis = contextual_analysis()
    wrong = analysis.blocks[1].model_copy(
        update={
            "provenance": Provenance(
                document_id="c" * 64,
                locator=analysis.blocks[1].provenance.locator,
                extractor=Extractor.LEGACY_DOC_TEXT,
            )
        }
    )
    with pytest.raises(ValueError, match="EIS_EVIDENCE_PROVENANCE_MISMATCH"):
        _conditions(analysis.model_copy(update={"blocks": (analysis.blocks[0], wrong)}))


def test_more_than_one_condition_of_same_kind_and_projection_bounds():
    analysis = contextual_analysis()
    snippets = tuple(
        ConditionSnippet(
            kind="Поставка",
            text=f"Поставка партия {n}",
            provenance=Provenance(
                document_id="b" * 64, locator=f"paragraph {n}", extractor=Extractor.NATIVE_DOCX
            ),
        )
        for n in range(1, 8)
    )
    result = _conditions(analysis.model_copy(update={"snippets": snippets}))
    assert len(result) == 3 and result[2].excerpt == "Поставка партия 3"


@pytest.mark.parametrize("following", ["3. Порядок оплаты:", "5. Новое условие"])
def test_next_section_is_not_header_value(following):
    analysis = contextual_analysis()
    altered = analysis.blocks[1].model_copy(update={"text": following})
    result = _conditions(analysis.model_copy(update={"blocks": (analysis.blocks[0], altered)}))
    assert not result[0].context and result[0].context_status == "UNKNOWN"


def test_ambiguous_header_and_long_context_stay_bounded():
    analysis = contextual_analysis()
    repeated = analysis.model_copy(update={"blocks": (*analysis.blocks, analysis.blocks[0])})
    assert not _conditions(repeated)[0].context
    long = analysis.blocks[1].model_copy(update={"text": "Тест " * 200})
    result = _conditions(analysis.model_copy(update={"blocks": (analysis.blocks[0], long)}))
    assert len(result[0].context[0].excerpt) == 500 and result[0].context[0].truncated


def sample(*, deadline: datetime | None = None, received: bool = True):
    ref = NoticeDocumentRef(purchase_number=NUMBER, version_number=1, notice_xml_sha256=SHA)
    attachment = EisOfficialAttachment(
        UID, "Техническое задание.pdf", 100, URL, None, "xml/file[1]"
    )
    notice = EisNoticeSnapshot(
        purchase_number=NUMBER,
        document_type="epNotificationEF2020",
        version_number=1,
        title="Поставка бумаги",
        published_at=NOW - timedelta(days=1),
        deadline=deadline,
        nmck_rub=Decimal("182420.00"),
        xml_sha256=SHA,
        source_member="notice.xml",
        attachments=(attachment,),
        lot_items=(
            EisLotItem(
                name="Бумага",
                ktru_code=None,
                okpd2_code=None,
                quantity=Decimal("500"),
                unit="уп",
                unit_price_rub=Decimal("364.84"),
                line_sum_rub=Decimal("182420.00"),
                foreign_goods_prohibited=None,
                locator="xml/lot[1]",
            ),
        ),
        lot_parse_status="PARSED",
    )
    item = DocumentCollectionItem(
        content_uid=UID,
        filename=attachment.filename,
        source_url=URL,
        source_locator=attachment.locator,
        declared_byte_count=100,
        received_byte_count=100 if received else None,
        sha256="b" * 64 if received else None,
        fetch_status="RECEIVED" if received else "PENDING",
        extraction_status="PASS" if received else "UNKNOWN",
        condition_snippet_count=1 if received else 0,
    )
    collection = DocumentCollectionStatus(
        notice=ref,
        current_version_number=1,
        current_xml_sha256=SHA,
        version_status="CURRENT_KNOWN_VERSION",
        requested=True,
        listed_count=1,
        received_count=int(received),
        pending_count=int(not received),
        download_status="COMPLETE_LISTED_SET" if received else "QUEUED",
        extraction_status="EXTRACTED" if received else "UNKNOWN",
        documents=(item,),
    )
    analysis = DocumentAnalysis(
        filename=item.filename,
        url=URL,
        sha256="b" * 64,
        byte_count=100,
        status="PASS",
        snippets=(
            ConditionSnippet(
                kind="Оплата",
                text="Оплата в течение 30 дней",
                provenance=Provenance(
                    document_id="b" * 64, locator="page[2]/block[1]", extractor=Extractor.NATIVE_PDF
                ),
            ),
        ),
    )
    return notice, collection, analysis


def test_realistic_leads_link_xml_and_document_without_approval() -> None:
    notice, collection, analysis = sample(deadline=NOW + timedelta(days=1))
    result = build_eis_evidence_bridge(notice, collection, {UID: analysis}, (), now=NOW)
    assert result.nmck_rub == Decimal("182420.00")
    assert result.nmck_provenance is not None
    assert result.nmck_provenance.document_id == SHA
    assert result.lot_items[0].locator == "xml/lot[1]"
    assert result.documents[0].role_hint == "TECHNICAL_SPECIFICATION"
    assert result.documents[0].role_status == "UNKNOWN"
    assert result.documents[0].conditions[0].provenance.document_id == "b" * 64
    assert result.requirement_status == result.completeness_status == "UNKNOWN"
    assert result.economic_status == "UNKNOWN"
    assert "SUPPLIER_QUOTE_MISSING" in result.economic_missing
    assert "DOCUMENT_ROLES_NOT_REVIEWED" in result.review_gaps


def test_missing_document_and_expired_deadline_remain_blocked_or_unknown() -> None:
    notice, collection, _ = sample(deadline=NOW - timedelta(seconds=1), received=False)
    result = build_eis_evidence_bridge(notice, collection, {}, (), now=NOW)
    assert result.application_status == "FAIL"
    assert result.economic_status == "BLOCKED"
    assert "DEADLINE_EXPIRED" in result.application_reasons
    assert "DOCUMENTS_NOT_RECEIVED" in result.review_gaps
    assert result.documents[0].conditions == ()


def test_official_cancellation_is_hard_gate_even_before_deadline() -> None:
    notice, collection, _ = sample(deadline=NOW + timedelta(days=1))
    event = EisProcedureEvent(
        purchase_number=NUMBER,
        document_type="epNotificationCancel",
        document_id="event-1",
        published_at=NOW - timedelta(hours=1),
        recovery_stage=None,
        xml_sha256="c" * 64,
        source_member="cancel.xml",
        locator="epNotificationCancel/commonInfo/purchaseNumber",
    )
    result = build_eis_evidence_bridge(notice, collection, {}, (event,), now=NOW)
    assert result.application_status == "FAIL" and result.economic_status == "BLOCKED"
    assert any("cancel.xml" in reason for reason in result.application_reasons)


def test_conflicting_version_or_content_never_links() -> None:
    notice, collection, analysis = sample()
    with pytest.raises(ValueError, match="EIS_EVIDENCE_VERSION_MISMATCH"):
        build_eis_evidence_bridge(
            notice, collection.model_copy(update={"listed_count": 0}), {}, (), now=NOW
        )
    with pytest.raises(ValueError, match="EIS_EVIDENCE_DOCUMENT_MISMATCH"):
        build_eis_evidence_bridge(
            notice, collection, {UID: analysis.model_copy(update={"sha256": "c" * 64})}, (), now=NOW
        )
    with pytest.raises(ValueError, match="NOW_TIMEZONE_MISSING"):
        build_eis_evidence_bridge(notice, collection, {}, (), now=NOW.replace(tzinfo=None))


def test_exact_supplier_costs_make_only_preliminary_scenarios() -> None:
    notice, collection, _ = sample(deadline=NOW + timedelta(days=1))
    bridge = build_eis_evidence_bridge(notice, collection, {}, (), now=NOW)
    costs = DiscoveryCostInput(
        goods="140000.00",
        expenses="10000.00",
        vat_rate="0.20",
        basis="Оценка оператора без полного КП",
        costs_complete_ack=True,
    )
    result = calculate_eis_preliminary_estimate(bridge, costs)
    assert result.notice.notice_xml_sha256 == SHA
    assert result.nmck_provenance is not None
    assert result.nmck_provenance.document_id == SHA
    assert result.estimate.status == "ESTIMATE"
    assert tuple(item.kind for item in result.estimate.scenarios) == (
        "base",
        "realistic",
        "conservative",
    )
    assert result.estimate.scenarios[-1].profit < Decimal("0")
    assert result.preliminary_guidance == "NEEDS_ANALYSIS"
    assert result.requirement_status == result.quote_status == "UNKNOWN"
    assert result.completeness_status == "UNKNOWN"
    unknown = calculate_eis_preliminary_estimate(
        bridge, costs.model_copy(update={"costs_complete_ack": False})
    )
    assert unknown.estimate.status == "UNKNOWN" and not unknown.estimate.scenarios


def test_expired_and_stale_notice_never_produce_estimate_scenarios() -> None:
    notice, collection, _ = sample(deadline=NOW - timedelta(seconds=1))
    bridge = build_eis_evidence_bridge(notice, collection, {}, (), now=NOW)
    costs = DiscoveryCostInput(
        goods="1", expenses="1", vat_rate="0.20", basis="Тест", costs_complete_ack=True
    )
    blocked = calculate_eis_preliminary_estimate(bridge, costs)
    assert blocked.estimate.status == "BLOCKED"
    assert blocked.preliminary_guidance == "DO_NOT_PARTICIPATE"
    assert not blocked.estimate.scenarios
    with pytest.raises(ValueError, match="NOTICE_VERSION_STALE"):
        calculate_eis_preliminary_estimate(
            bridge.model_copy(
                update={"collection": collection.model_copy(update={"version_status": "STALE"})}
            ),
            costs,
        )
    with pytest.raises(ValueError):
        DiscoveryCostInput(
            goods=1.2, expenses="1", vat_rate="0.20", basis="Тест", costs_complete_ack=True
        )


def test_competition_without_raw_source_keeps_criteria_and_qualification_unknown():
    notice, collection, _ = sample(deadline=NOW + timedelta(days=1))
    notice = replace(notice, document_type="epNotificationEOK2020")
    bridge = build_eis_evidence_bridge(notice, collection, {}, (), now=NOW)
    assert bridge.competition_criteria.source_status == "UNKNOWN"
    assert "COMPETITION_SOURCE_WEIGHTS_UNKNOWN" in bridge.review_gaps
    assert "COMPETITION_QUALIFICATION_NOT_REVIEWED" in bridge.review_gaps
    assert bridge.application_status == bridge.economic_status == "UNKNOWN"
    bad = unknown_competition_criteria(notice, "CRITERIA_SOURCE_NOT_READ").model_copy(
        update={"source_xml_sha256": "c" * 64}
    )
    with pytest.raises(ValueError, match="EIS_CRITERIA_EVIDENCE_MISMATCH"):
        build_eis_evidence_bridge(notice, collection, {}, (), now=NOW, competition_criteria=bad)


def test_unknown_variant_hold_prevents_cached_bridge_economics():
    from procurement.storage.eis_document_store import EisDocumentReadGate

    notice, collection, _ = sample(deadline=NOW + timedelta(days=1))
    gate = EisDocumentReadGate(
        checked_at=NOW,
        notice=collection.notice,
        blocked_reasons=("NOTICE_VARIANT_REVIEW_REQUIRED",),
        evidence=("Evidence-only ledger; source identity requires review.",),
    )
    collection = collection.model_copy(update={"read_gate": gate})
    bridge = build_eis_evidence_bridge(notice, collection, {}, (), now=NOW)
    assert bridge.application_status == "UNKNOWN"
    costs = DiscoveryCostInput(
        goods="1", expenses="1", vat_rate="0.20", basis="Тест", costs_complete_ack=True
    )
    with pytest.raises(ValueError, match="NOTICE_VARIANT_REVIEW_REQUIRED"):
        calculate_eis_preliminary_estimate(bridge, costs)


def test_ambiguous_source_never_reuses_supplied_legacy_analysis():
    from dataclasses import replace

    from procurement.sources.eis_feed_archive import EisAttachmentAlias

    notice, collection, analysis = sample(deadline=NOW + timedelta(days=1))
    attachment = replace(
        notice.attachments[0], aliases=(EisAttachmentAlias("other.pdf", None, "xml/attachment[2]"),)
    )
    notice = replace(notice, attachments=(attachment,))
    result = build_eis_evidence_bridge(notice, collection, {UID: analysis}, (), now=NOW)
    assert result.collection.extraction_status == "UNKNOWN"
    assert result.documents[0].conditions == ()
    assert result.collection.documents[0].reference_status == "UNKNOWN"
    assert "ATTACHMENT_REFERENCE_REQUIRES_REVIEW" in result.review_gaps
