"""Cached 44-FZ source diagnostics; missing outcome bindings never become facts."""

from datetime import datetime
from typing import Any

from procurement.domain.provenance import Extractor, Provenance
from procurement.domain.regional_discount import HistoryFact, HistoryMoney, RegionalObservation
from procurement.storage.eis_document_store import NoticeDocumentRef, load_notice
from procurement.storage.eis_mixed_comparison import MixedNoticeRef
from procurement.storage.eis_protocols import read_historical_protocols
from procurement.storage.repository import PostgresStorage
from procurement.storage.tender_navigation import read_navigation


def read_regional_observation(
    storage: PostgresStorage, company: str, ref: NoticeDocumentRef, *, now: datetime
) -> RegionalObservation:
    """Read one explicit cached reference, no source requests or writes.

    Existing companion facts cannot prove signed price, currency/tax basis,
    applicable notice/lot/volume or current result. These assertions remain
    unknown even when a PlacementResult row says CC. This adapter deliberately
    cannot admit the old S203 samples to financial calibration.
    """
    with storage.transaction(company, consistent_read=True) as connection:
        connection.exec_driver_sql("SET LOCAL statement_timeout = '5000ms'")
        notice = load_notice(connection, company, ref)
    report = read_historical_protocols(storage, company, ref, now=now, statement_timeout_ms=5000)
    navigation = read_navigation(storage, company, MixedNoticeRef(law="44", **ref.model_dump()))
    root = Provenance(
        document_id=notice.xml_sha256,
        locator=f"{notice.source_member} :: {notice.document_type}",
        extractor=Extractor.API,
    )

    def fact(value: Any, path: str) -> HistoryFact[Any]:
        return HistoryFact(
            value=value,
            source=root.model_copy(
                update={"locator": f"{notice.source_member} :: {notice.document_type}/{path}"}
            ),
        )

    item = (
        notice.lot_items[0]
        if notice.lot_parse_status == "PARSED" and len(notice.lot_items) == 1
        else None
    )
    product = f"KTRU:{item.ktru_code}" if item and item.ktru_code else None
    if product is None and item and item.okpd2_code:
        product = f"OKPD2:{item.okpd2_code};NAME:{' '.join(item.name.casefold().split())}"
    # Multiple placement documents/CC rows are ambiguous; do not choose latest.
    placements = [d for d in report.documents if d.document_kind == "PLACEMENT_RESULT"]
    winners = [a for d in placements for a in d.applications if a.result_code.value == "CC"]
    winner = winners[0] if len(placements) == len(winners) == 1 else None
    amount = winner.proposal.amount if winner else None
    final_source = (
        root
        if amount is None
        else Provenance(
            document_id=amount.evidence.xml_sha256,
            locator=f"{amount.evidence.source_member} :: {amount.evidence.locator}",
            extractor=Extractor.API,
        )
    )
    regions = navigation.delivery_regions
    region = HistoryFact(value=None, source=root)
    if len(regions) == 1:
        region = HistoryFact(
            value=regions[0].value,
            source=regions[0].provenance,
            supporting_sources=regions[0].supporting_sources,
        )
    unknown_outcome = HistoryFact(value=None, source=final_source)
    return RegionalObservation(
        company_id=company,
        law="44",
        purchase_number=ref.purchase_number,
        region=region,
        product_key=fact(product, "notificationInfo/purchaseObjectsInfo"),
        procedure=fact(notice.document_type, ""),
        unit=fact(item.unit if item else None, "notificationInfo/purchaseObjectsInfo"),
        quantity=HistoryMoney(
            value=item.quantity if item else None,
            source=fact(
                None,
                (item.locator.split("/", 1)[1] + "/quantity/value")
                if item
                else "notificationInfo/purchaseObjectsInfo",
            ).source,
        ),
        initial=HistoryMoney(
            value=notice.nmck_rub,
            source=fact(
                None, "notificationInfo/contractConditionsInfo/maxPriceInfo/maxPrice"
            ).source,
        ),
        final=HistoryMoney(value=amount.value if amount else None, source=final_source),
        concluded_at=unknown_outcome,
        notice_lot_volume_link=unknown_outcome,
        rub_nominal_totals=unknown_outcome,
        concluded_contract=unknown_outcome,
        current_result=unknown_outcome,
    )
