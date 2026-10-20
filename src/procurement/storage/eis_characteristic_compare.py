"""Bounded source0 observation of two exact saved positions in one snapshot."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from time import monotonic
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import Text, and_, case, func, select

from procurement.sources.eis_characteristic_compare import (
    CharacteristicPairReport,
    CharacteristicPairRequest,
    PositionSelection,
    SavedPosition,
    build_characteristic_pair_report,
)
from procurement.sources.eis_feed_archive import EisLotItem, EisNoticeSnapshot
from procurement.sources.eis_position_evidence import PositionEvidenceSet, positions44
from procurement.storage.eis_notice_hold import assert_notice_source_usable
from procurement.storage.eis_position_projection import (
    LEGACY_PARSER_VERSION,
    READABLE_PARSER_VERSIONS,
    _without_range_completeness,
)
from procurement.storage.models import eis_notice_position_projections, eis_notice_versions
from procurement.storage.repository import PostgresStorage

MAX_NOTICE_BYTES = 256 * 1024
MAX_PROJECTION_BYTES = 512 * 1024
MAX_RESPONSE_BYTES = 2 * 1024**2
MAX_READ_SECONDS = 15
_ITEMS = TypeAdapter(tuple[EisLotItem, ...])


def _bounded_fields(value: Any, key: str = "") -> None:
    """Bound scalar work before existing typed source conversion, without rounding."""
    if isinstance(value, str) and len(value) > 4096:
        raise ValueError("CHARACTERISTIC_SCALAR_LIMIT")
    if (
        key in {"quantity", "unit_price_rub", "line_sum_rub", "minimum", "maximum", "value"}
        and value is not None
        and not isinstance(value, (dict, list))
    ):
        if isinstance(value, (float, bool)):
            raise ValueError("CHARACTERISTIC_INEXACT_NUMBER")
        try:
            number = Decimal(value)
        except (InvalidOperation, TypeError, ValueError) as error:
            raise ValueError("CHARACTERISTIC_INVALID_NUMBER") from error
        if (
            not number.is_finite()
            or len(number.as_tuple().digits) > 30
            or abs(int(number.as_tuple().exponent)) > 12
        ):
            raise ValueError("CHARACTERISTIC_NUMBER_LIMIT")
    if isinstance(value, dict):
        for child_key, child in value.items():
            _bounded_fields(child, child_key)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _bounded_fields(child)


def read_saved_position_connection(
    conn: Any, company: str, selection: PositionSelection, *, budget: Any
) -> SavedPosition:
    """Read one exact saved position; caller supplies transaction and freshness policy.

    Historical comparison intentionally does not require the latest notice version.
    """
    n, p = eis_notice_versions, eis_notice_position_projections
    budget()
    ref = selection.notice
    assert_notice_source_usable(conn, company, ref.purchase_number, ref.version_number)
    identity = and_(
        n.c.company_id == company,
        n.c.purchase_number == ref.purchase_number,
        n.c.version_number == ref.version_number,
    )
    metadata = (
        conn.execute(
            select(
                n.c.xml_sha256,
                n.c.document_type,
                n.c.source_member,
                n.c.lot_parse_status,
                func.octet_length(n.c.lot_items.cast(Text)).label("payload_bytes"),
            ).where(identity)
        )
        .mappings()
        .one_or_none()
    )
    if metadata is None or metadata["xml_sha256"] != ref.notice_xml_sha256:
        raise ValueError("CHARACTERISTIC_NOTICE_NOT_FOUND_OR_MISMATCH")
    if metadata["document_type"] not in {
        "epNotificationEF2020",
        "epNotificationEZK2020",
        "epNotificationEOK2020",
    }:
        raise ValueError("CHARACTERISTIC_NOTICE_TYPE_UNSUPPORTED")
    projection_identity = and_(
        p.c.company_id == company,
        p.c.purchase_number == ref.purchase_number,
        p.c.version_number == ref.version_number,
        p.c.parser_version.in_(READABLE_PARSER_VERSIONS),
    )
    budget()
    projection = (
        conn.execute(
            select(
                p.c.parser_version,
                p.c.notice_xml_sha256,
                p.c.projection_sha256,
                func.octet_length(p.c.position_set.cast(Text)).label("payload_bytes"),
            )
            .where(projection_identity)
            .order_by(
                case(
                    *(
                        (p.c.parser_version == version, priority)
                        for priority, version in enumerate(READABLE_PARSER_VERSIONS)
                    ),
                    else_=len(READABLE_PARSER_VERSIONS),
                )
            )
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    if projection is not None:
        if projection["notice_xml_sha256"] != ref.notice_xml_sha256:
            raise ValueError("CHARACTERISTIC_PROJECTION_IDENTITY_MISMATCH")
        if projection["payload_bytes"] > MAX_PROJECTION_BYTES:
            raise ValueError("CHARACTERISTIC_PROJECTION_PAYLOAD_LIMIT")
        budget()
        payload = conn.scalar(
            select(p.c.position_set).where(
                projection_identity, p.c.parser_version == projection["parser_version"]
            )
        )
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if digest != projection["projection_sha256"]:
            raise ValueError("CHARACTERISTIC_PROJECTION_DIGEST_MISMATCH")
        # Existing typed facts reject floats; bound scalar work separately.
        _projection_scalars(payload)
        result = PositionEvidenceSet.model_validate(payload)
        if (
            result.law != "44"
            or result.purchase_number != ref.purchase_number
            or result.version_number != ref.version_number
            or result.notice_xml_sha256 != ref.notice_xml_sha256
            or result.native_tables
        ):
            raise ValueError("CHARACTERISTIC_PROJECTION_IDENTITY_MISMATCH")
        if projection["parser_version"] == LEGACY_PARSER_VERSION:
            result = _without_range_completeness(result)
        legacy = False
        kind = "SAVED_PROJECTION"
    else:
        if metadata["payload_bytes"] > MAX_NOTICE_BYTES:
            raise ValueError("CHARACTERISTIC_NOTICE_PAYLOAD_LIMIT")
        budget()
        payload = conn.scalar(select(n.c.lot_items).where(identity))
        if not isinstance(payload, list):
            raise ValueError("CHARACTERISTIC_POSITIONS_INVALID")
        if selection.source_index > len(payload):
            raise ValueError("CHARACTERISTIC_POSITION_NOT_FOUND")
        _bounded_fields(payload)
        items = _ITEMS.validate_python(payload)
        item = payload[selection.source_index - 1]
        legacy = "characteristics" not in item or any(
            "concrete_values" not in value
            for characteristic in item.get("characteristics", [])
            for value in characteristic.get("values", [])
        )
        result = positions44(
            EisNoticeSnapshot(
                purchase_number=ref.purchase_number,
                document_type=metadata["document_type"],
                version_number=ref.version_number,
                title="",
                published_at=None,
                deadline=None,
                nmck_rub=None,
                xml_sha256=ref.notice_xml_sha256,
                source_member=metadata["source_member"],
                lot_items=items,
                lot_parse_status=metadata["lot_parse_status"],
            )
        )
        kind = "SAVED_NOTICE_FIELDS"
    position = next((x for x in result.positions if x.source_index == selection.source_index), None)
    if position is None:
        raise ValueError("CHARACTERISTIC_POSITION_NOT_FOUND")
    return SavedPosition(
        selection=selection,
        position=position,
        storage_kind=kind,
        legacy_values_unknown=legacy,
    )


def read_characteristic_pair(
    storage: PostgresStorage, company: str, request: CharacteristicPairRequest, *, now: datetime
) -> CharacteristicPairReport:
    if not company.strip() or now.utcoffset() is None:
        raise ValueError("CHARACTERISTIC_REQUEST_INVALID")
    started = monotonic()
    with storage.transaction(company, consistent_read=True) as conn:

        def budget() -> None:
            remaining = int((MAX_READ_SECONDS - (monotonic() - started)) * 1000)
            if remaining <= 0:
                raise ValueError("CHARACTERISTIC_TIME_LIMIT")
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = '{min(remaining, 5000)}ms'")

        budget()
        conn.exec_driver_sql("SET LOCAL lock_timeout = '1s'")
        conn.exec_driver_sql("SET LOCAL jit = 'off'")

        def read(selection: PositionSelection) -> SavedPosition:
            return read_saved_position_connection(conn, company, selection, budget=budget)

        target, candidate = read(request.target), read(request.candidate)
        budget()
        report = build_characteristic_pair_report(request, target, candidate, now=now)
        if len(report.model_dump_json().encode()) > MAX_RESPONSE_BYTES:
            raise ValueError("CHARACTERISTIC_RESPONSE_LIMIT")
        budget()
        return report


def _projection_scalars(value: Any) -> None:
    """Projection fact values include text as well as numbers; inspect exact type."""
    if isinstance(value, str) and len(value) > 4096:
        raise ValueError("CHARACTERISTIC_SCALAR_LIMIT")
    if isinstance(value, dict):
        if isinstance(value.get("value"), (float, bool)):
            raise ValueError("CHARACTERISTIC_INEXACT_NUMBER")
        for child in value.values():
            _projection_scalars(child)
    elif isinstance(value, list):
        for child in value:
            _projection_scalars(child)
