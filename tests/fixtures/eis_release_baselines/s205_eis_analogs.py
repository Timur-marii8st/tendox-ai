"""Bounded source0 historical prefilter; no archive reads, jobs or projection writes."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from time import monotonic
from typing import Any

from sqlalchemy import Text, and_, exists, func, or_, select, tuple_

from procurement.domain.provenance import Extractor, Provenance
from procurement.sources.eis_analogs import (
    MAX_CANDIDATES,
    MAX_POSITIONS,
    AnalogFact,
    AnalogNotice,
    AnalogPosition,
    AnalogReport,
    AnalogRequest,
    analog_period,
    build_analog_report,
)
from procurement.sources.eis_index_search import search_query_keys_v1, search_query_terms
from procurement.storage.eis_document_store import NoticeDocumentRef
from procurement.storage.eis_notice_hold import (
    assert_notice_source_usable,
    notice_variant_hold_clause,
)
from procurement.storage.models import eis_notice_search_keys, eis_notice_versions
from procurement.storage.repository import PostgresStorage

MAX_NOTICE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 2 * 1024**2
MAX_RESPONSE_BYTES = 4 * 1024**2
MAX_READ_SECONDS = 15


def _notice(row: Any) -> AnalogNotice:
    ref = NoticeDocumentRef(
        purchase_number=row["purchase_number"],
        version_number=row["version_number"],
        notice_xml_sha256=row["xml_sha256"],
    )
    member, kind = row["source_member"], row["document_type"]
    if len(member.encode()) > 255:
        raise ValueError("ANALOG_MEMBER_LIMIT")

    def fact(value: Any, locator: str) -> AnalogFact[Any]:
        if isinstance(value, str) and len(value) > 500:
            raise ValueError("ANALOG_SCALAR_LIMIT")
        return AnalogFact(
            value=value,
            provenance=Provenance(
                document_id=ref.notice_xml_sha256,
                locator=f"{member} :: {locator}",
                extractor=Extractor.API,
            ),
        )

    items = row["lot_items"]
    if not isinstance(items, list):
        raise ValueError("ANALOG_POSITIONS_INVALID")
    positions = []
    for index, item in enumerate(items[:MAX_POSITIONS], 1):
        locator = item.get("locator")
        if not isinstance(locator, str) or len(locator) > 500:
            raise ValueError("ANALOG_LOCATOR_INVALID")
        quantity = item.get("quantity")
        if isinstance(quantity, (float, bool)):
            raise ValueError("ANALOG_INEXACT_QUANTITY")
        if quantity is not None and len(str(quantity)) > 64:
            raise ValueError("ANALOG_QUANTITY_LIMIT")
        try:
            quantity = Decimal(quantity) if quantity is not None else None
        except (InvalidOperation, TypeError):
            quantity = None
        if quantity is not None and not quantity.is_finite():
            quantity = None
        positions.append(
            AnalogPosition(
                source_index=index,
                name=fact(item.get("name"), locator + "/name"),
                ktru=fact(item.get("ktru_code"), locator + "/KTRU/code"),
                okpd2=fact(item.get("okpd2_code"), locator + "/KTRU/OKPD2/OKPDCode"),
                quantity=fact(quantity, locator + "/quantity/value"),
                unit=fact(item.get("unit"), locator + "/OKEI/name"),
            )
        )
    return AnalogNotice(
        notice=ref,
        document_type=kind,
        source_member=member,
        published_at=fact(row["published_at"], kind + "/commonInfo/publishDTInEIS"),
        deadline=fact(
            row["deadline"], kind + "/notificationInfo/procedureInfo/collectingInfo/endDT"
        ),
        positions=tuple(positions),
        positions_total=len(items),
        lot_parse_status=row["lot_parse_status"],
    )


def read_analog_candidates(
    storage: PostgresStorage, company: str, request: AnalogRequest, *, now: datetime
) -> AnalogReport:
    """Only latest saved historical leads, selected before bounded payload hydration."""
    if not company.strip() or now.utcoffset() is None:
        raise ValueError("ANALOG_REQUEST_INVALID")
    search_query_terms(request.query)
    keys = list(search_query_keys_v1(request.query))
    started = monotonic()
    n, k = eis_notice_versions, eis_notice_search_keys
    metadata = [
        n.c.purchase_number,
        n.c.version_number,
        n.c.xml_sha256,
        n.c.source_member,
        n.c.document_type,
        n.c.published_at,
        n.c.deadline,
        n.c.lot_parse_status,
        func.octet_length(n.c.lot_items.cast(Text)).label("payload_bytes"),
    ]
    with storage.transaction(company, consistent_read=True) as conn:

        def budget() -> None:
            remaining = int((MAX_READ_SECONDS - (monotonic() - started)) * 1000)
            if remaining <= 0:
                raise ValueError("ANALOG_TIME_LIMIT")
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = '{min(remaining, 5000)}ms'")

        budget()
        conn.exec_driver_sql("SET LOCAL lock_timeout = '1s'")
        assert_notice_source_usable(
            conn, company, request.target.purchase_number, request.target.version_number
        )
        target_row = (
            conn.execute(
                select(*metadata).where(
                    n.c.company_id == company,
                    n.c.purchase_number == request.target.purchase_number,
                    n.c.version_number == request.target.version_number,
                )
            )
            .mappings()
            .one_or_none()
        )
        if target_row is None or target_row["xml_sha256"] != request.target.notice_xml_sha256:
            raise ValueError("ANALOG_TARGET_NOT_FOUND_OR_MISMATCH")
        if target_row["payload_bytes"] > MAX_NOTICE_BYTES:
            raise ValueError("ANALOG_NOTICE_PAYLOAD_LIMIT")
        budget()
        target_payload = conn.execute(
            select(n.c.lot_items).where(
                n.c.company_id == company,
                n.c.purchase_number == request.target.purchase_number,
                n.c.version_number == request.target.version_number,
            )
        ).scalar_one()
        target = _notice(dict(target_row) | {"lot_items": target_payload})
        # Validate position/time before candidate SQL; never anchor a missing date to now.
        empty = build_analog_report(request, target, (), now=now, selection_truncated=False)
        period = analog_period(target, request)
        if period is None:
            budget()
            if len(empty.model_dump_json().encode()) > MAX_RESPONSE_BYTES:
                raise ValueError("ANALOG_RESPONSE_LIMIT")
            return empty
        newer = n.alias("analog_newer")
        latest = ~exists(
            select(newer.c.purchase_number).where(
                newer.c.company_id == n.c.company_id,
                newer.c.purchase_number == n.c.purchase_number,
                newer.c.version_number > n.c.version_number,
            )
        )
        key_join = and_(
            k.c.company_id == n.c.company_id,
            k.c.purchase_number == n.c.purchase_number,
            k.c.version_number == n.c.version_number,
        )
        budget()
        leads = (
            conn.execute(
                select(*metadata)
                .outerjoin(k, key_join)
                .where(
                    n.c.company_id == company,
                    n.c.purchase_number != request.target.purchase_number,
                    latest,
                    ~notice_variant_hold_clause(company, n.c.purchase_number, n.c.version_number),
                    n.c.document_type == target.document_type,
                    n.c.deadline <= now,
                    n.c.published_at >= period[0],
                    n.c.published_at <= period[1],
                    or_(k.c["keys"].overlap(keys), k.c.company_id.is_(None)),
                )
                .order_by(n.c.published_at.desc(), n.c.purchase_number.asc())
                .limit(MAX_CANDIDATES + 1)
            )
            .mappings()
            .all()
        )
        selected = leads[:MAX_CANDIDATES]
        if any(r["payload_bytes"] > MAX_NOTICE_BYTES for r in selected):
            raise ValueError("ANALOG_NOTICE_PAYLOAD_LIMIT")
        if (
            target_row["payload_bytes"] + sum(r["payload_bytes"] for r in selected)
            > MAX_TOTAL_BYTES
        ):
            raise ValueError("ANALOG_TOTAL_PAYLOAD_LIMIT")
        for row in selected:
            budget()
            assert_notice_source_usable(
                conn, company, row["purchase_number"], row["version_number"]
            )
        payloads = {}
        if selected:
            budget()
            payloads = {
                (r.purchase_number, r.version_number): r.lot_items
                for r in conn.execute(
                    select(n.c.purchase_number, n.c.version_number, n.c.lot_items).where(
                        n.c.company_id == company,
                        tuple_(n.c.purchase_number, n.c.version_number).in_(
                            [(r["purchase_number"], r["version_number"]) for r in selected]
                        ),
                    )
                )
            }
        candidates = tuple(
            _notice(dict(r) | {"lot_items": payloads[(r["purchase_number"], r["version_number"])]})
            for r in selected
        )
        budget()
        result = build_analog_report(
            request, target, candidates, now=now, selection_truncated=len(leads) > MAX_CANDIDATES
        )
        if len(result.model_dump_json().encode()) > MAX_RESPONSE_BYTES:
            raise ValueError("ANALOG_RESPONSE_LIMIT")
        return result
