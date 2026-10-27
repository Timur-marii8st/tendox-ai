"""Explicit cached-source projection; ordinary comparison never parses source bytes."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from io import BytesIO
from typing import TYPE_CHECKING
from zipfile import ZipFile

from sqlalchemy import Integer, Text, and_, cast, column, func, insert, select, text, tuple_, values
from sqlalchemy.dialects.postgresql import insert as pg_insert

from procurement.sources.eis_drug_positions import drug_positions44
from procurement.sources.eis_feed_archive import EisNoticeSnapshot, _notice
from procurement.sources.eis_position_evidence import PositionEvidenceSet, positions44
from procurement.storage.eis_notice_hold import (
    assert_notice_source_usable,
    notice_variant_hold_clause,
)
from procurement.storage.models import (
    audit_events,
    eis_feed_archives,
    eis_notice_position_projections,
    eis_notice_versions,
)

if TYPE_CHECKING:
    from sqlalchemy import Connection
    from sqlalchemy.sql.elements import ColumnElement

    from procurement.storage.eis_document_store import NoticeDocumentRef
    from procurement.storage.repository import PostgresStorage

PARSER_VERSION = "eis-position-v4-drug-source-r1"
R2_PARSER_VERSION = "eis-position-v3-range-evidence-r2"
R1_PARSER_VERSION = "eis-position-v3-range-evidence-r1"
PREVIOUS_PARSER_VERSION = "eis-position-v3-range-evidence"
LEGACY_PARSER_VERSION = "eis-position-v2-concrete"
READABLE_PARSER_VERSIONS = (
    PARSER_VERSION,
    R2_PARSER_VERSION,
    R1_PARSER_VERSION,
    PREVIOUS_PARSER_VERSION,
    LEGACY_PARSER_VERSION,
)
MAX_XML_BYTES = 32 * 1024**2
MAX_ARCHIVE_BYTES = 50 * 1024**2


def _digest(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _where(
    company: str, ref: NoticeDocumentRef, *, parser_version: str = PARSER_VERSION
) -> ColumnElement[bool]:
    t = eis_notice_position_projections
    return and_(
        t.c.company_id == company,
        t.c.purchase_number == ref.purchase_number,
        t.c.version_number == ref.version_number,
        t.c.parser_version == parser_version,
    )


def read_position_projection(
    conn: Connection,
    company: str,
    ref: NoticeDocumentRef,
    *,
    parser_version: str | None = None,
    max_payload_bytes: int | None = None,
) -> PositionEvidenceSet | None:
    assert_notice_source_usable(conn, company, ref.purchase_number, ref.version_number)
    versions = (parser_version,) if parser_version is not None else READABLE_PARSER_VERSIONS
    if any(version not in READABLE_PARSER_VERSIONS for version in versions):
        raise ValueError("POSITION_PARSER_VERSION_UNSUPPORTED")
    row = None
    selected_version = None
    for version in versions:
        if max_payload_bytes is not None:
            # Inspect length in PostgreSQL before hydrating untrusted JSON.
            size = conn.scalar(
                select(
                    func.octet_length(cast(eis_notice_position_projections.c.position_set, Text))
                ).where(_where(company, ref, parser_version=version))
            )
            if size is not None and size > max_payload_bytes:
                return None
        row = (
            conn.execute(
                select(eis_notice_position_projections).where(
                    _where(company, ref, parser_version=version)
                )
            )
            .mappings()
            .first()
        )
        if row is not None:
            selected_version = version
            break
    if row is None:
        return None
    return _validated_projection(
        ref,
        row["notice_xml_sha256"],
        row["projection_sha256"],
        row["position_set"],
        selected_version,
    )


def _validated_projection(
    ref: NoticeDocumentRef,
    notice_sha: str,
    digest: str,
    payload: dict[str, object],
    parser_version: str | None,
) -> PositionEvidenceSet:
    if notice_sha != ref.notice_xml_sha256 or _digest(payload) != digest:
        raise ValueError("POSITION_PROJECTION_DIGEST_MISMATCH")
    result = PositionEvidenceSet.model_validate(payload)
    if (result.law, result.purchase_number, result.version_number, result.notice_xml_sha256) != (
        "44",
        ref.purchase_number,
        ref.version_number,
        ref.notice_xml_sha256,
    ) or result.native_tables:
        raise ValueError("POSITION_PROJECTION_IDENTITY_MISMATCH")
    return (
        _without_range_completeness(result) if parser_version == LEGACY_PARSER_VERSION else result
    )


def read_position_projection_page(
    conn: Connection,
    company: str,
    refs: Sequence[NoticeDocumentRef],
) -> tuple[PositionEvidenceSet | None, ...]:
    """Three bounded reads: scoped HOLD, metadata budget, selected immutable JSON.

    No per-notice fallback queries or JSON hydration before a byte budget is set.
    The caller keeps this page in one consistent tenant transaction.
    """
    if not company.strip() or len(refs) > 100:
        raise ValueError("POSITION_PAGE_SIZE_LIMIT")
    if not refs:
        return ()
    by_pair = {(r.purchase_number, r.version_number): r for r in refs}
    if len(by_pair) != len(refs):
        raise ValueError("POSITION_PAGE_DUPLICATE_REF")
    scope = (
        values(
            column("company_id", Text),
            column("purchase_number", Text),
            column("version_number", Integer),
        )
        .data([(company, r.purchase_number, r.version_number) for r in refs])
        .cte("position_page_scope")
    )
    held = (
        conn.execute(
            select(
                notice_variant_hold_clause(
                    company,
                    scope.c.purchase_number,
                    scope.c.version_number,
                    _resolution_scope=scope,
                )
            ).select_from(scope)
        )
        .scalars()
        .all()
    )
    if any(held):
        raise ValueError("NOTICE_VARIANT_REVIEW_REQUIRED")
    t = eis_notice_position_projections
    metadata = (
        conn.execute(
            select(
                t.c.purchase_number,
                t.c.version_number,
                t.c.parser_version,
                t.c.notice_xml_sha256,
                t.c.projection_sha256,
                func.octet_length(cast(t.c.position_set, Text)).label("payload_bytes"),
            ).where(
                t.c.company_id == company,
                tuple_(t.c.purchase_number, t.c.version_number).in_(list(by_pair)),
                t.c.parser_version.in_(READABLE_PARSER_VERSIONS),
            )
        )
        .mappings()
        .all()
    )
    priority = {version: index for index, version in enumerate(READABLE_PARSER_VERSIONS)}
    selected = {}
    for row in metadata:
        key = row["purchase_number"], row["version_number"]
        if (
            key not in selected
            or priority[row["parser_version"]] < priority[selected[key]["parser_version"]]
        ):
            selected[key] = row
    remaining = 2 * 1024**2
    accepted = {}
    for key, ref in by_pair.items():
        row = selected.get(key)
        if row is None:
            continue
        if row["notice_xml_sha256"] != ref.notice_xml_sha256:
            raise ValueError("POSITION_PROJECTION_DIGEST_MISMATCH")
        size = row["payload_bytes"]
        if size > min(512 * 1024, remaining):
            continue
        accepted[(*key, row["parser_version"])] = row
        remaining -= size
    results = {}
    if accepted:
        rows = (
            conn.execute(
                select(
                    t.c.purchase_number,
                    t.c.version_number,
                    t.c.parser_version,
                    t.c.position_set,
                ).where(
                    t.c.company_id == company,
                    tuple_(t.c.purchase_number, t.c.version_number, t.c.parser_version).in_(
                        list(accepted)
                    ),
                )
            )
            .mappings()
            .all()
        )
        if len(rows) != len(accepted):
            raise ValueError("POSITION_PROJECTION_PAGE_CHANGED")
        for row in rows:
            key = row["purchase_number"], row["version_number"]
            meta = accepted[(*key, row["parser_version"])]
            results[key] = _validated_projection(
                by_pair[key],
                meta["notice_xml_sha256"],
                meta["projection_sha256"],
                row["position_set"],
                row["parser_version"],
            )
    # Older payloads can acquire model defaults on validation. Bound the wire
    # representation too, retaining the caller's deterministic page order.
    remaining_output = 2 * 1024**2
    output = []
    for key in by_pair:
        result = results.get(key)
        if result is not None:
            size = len(result.model_dump_json().encode())
            if size > min(512 * 1024, remaining_output):
                result = None
            else:
                remaining_output -= size
        output.append(result)
    return tuple(output)


def _without_range_completeness(result: PositionEvidenceSet) -> PositionEvidenceSet:
    """Old parser identity cannot establish absent opposite-bound source evidence."""
    return result.model_copy(
        update={
            "positions": tuple(
                position.model_copy(
                    update={
                        "characteristics": tuple(
                            characteristic.model_copy(
                                update={
                                    "values": tuple(
                                        value.model_copy(update={"range_source_complete": False})
                                        for value in characteristic.values
                                    )
                                }
                            )
                            for characteristic in position.characteristics
                        )
                    }
                )
                for position in result.positions
            )
        }
    )


def project_notice_positions(
    storage: PostgresStorage,
    company: str,
    ref: NoticeDocumentRef,
    *,
    actor_id: str,
    parser_version: str = PARSER_VERSION,
) -> bool:
    """One exact selected XML, bounded memory, no EIS HTTP; replay performs no writes."""
    if not company.strip() or not actor_id.strip():
        raise ValueError("TENANT_OR_ACTOR_MISSING")
    if parser_version not in {PARSER_VERSION, LEGACY_PARSER_VERSION}:
        raise ValueError("POSITION_PARSER_VERSION_UNSUPPORTED")
    with storage.transaction(company, consistent_read=True) as conn:
        assert_notice_source_usable(conn, company, ref.purchase_number, ref.version_number)
        # Validate existence/digest before the cached shortcut, including replay.
        n, a = eis_notice_versions, eis_feed_archives
        source = (
            conn.execute(
                select(n).where(
                    n.c.company_id == company,
                    n.c.purchase_number == ref.purchase_number,
                    n.c.version_number == ref.version_number,
                )
            )
            .mappings()
            .first()
        )
        if source is None:
            raise LookupError("NOTICE_NOT_FOUND")
        if source["xml_sha256"] != ref.notice_xml_sha256:
            raise ValueError("NOTICE_DIGEST_CONFLICT")
        if read_position_projection(conn, company, ref, parser_version=parser_version) is not None:
            return False
        archive_identity = and_(
            a.c.company_id == company,
            a.c.window_key == source["window_key"],
            a.c.response_sha256 == source["response_sha256"],
            a.c.archive_sha256 == source["archive_sha256"],
        )
        archive_size = conn.scalar(select(func.octet_length(a.c.content)).where(archive_identity))
        if archive_size is None or archive_size > MAX_ARCHIVE_BYTES:
            raise ValueError("POSITION_ARCHIVE_SIZE_LIMIT")
        row = conn.execute(select(a.c.content, a.c.archive_sha256).where(archive_identity)).one()
        raw = bytes(row.content)
    if len(raw) > MAX_ARCHIVE_BYTES or hashlib.sha256(raw).hexdigest() != row.archive_sha256:
        raise ValueError("POSITION_ARCHIVE_DIGEST_MISMATCH")
    with ZipFile(BytesIO(raw)) as archive:
        members = [m for m in archive.infolist() if m.filename == source["source_member"]]
        if len(members) != 1 or members[0].file_size > MAX_XML_BYTES or members[0].is_dir():
            raise ValueError("POSITION_SOURCE_MEMBER_INVALID")
        with archive.open(members[0]) as stream:
            xml = stream.read(MAX_XML_BYTES + 1)
        if (
            len(xml) != members[0].file_size
            or hashlib.sha256(xml).hexdigest() != ref.notice_xml_sha256
        ):
            raise ValueError("POSITION_XML_DIGEST_MISMATCH")
    notice = _notice(xml, source["source_member"], source["document_type"])
    if not isinstance(notice, EisNoticeSnapshot) or (
        notice.purchase_number,
        notice.version_number,
    ) != (ref.purchase_number, ref.version_number):
        raise ValueError("POSITION_SOURCE_IDENTITY_MISMATCH")
    result = (
        drug_positions44(notice, xml) if parser_version == PARSER_VERSION else None
    ) or positions44(notice)
    if parser_version == LEGACY_PARSER_VERSION:
        result = _without_range_completeness(result)
    with storage.transaction(company) as conn:
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant, 0))"),
            {"tenant": company},
        )
        return insert_position_projection(
            conn, company, ref, result, actor_id=actor_id, parser_version=parser_version
        )


def insert_position_projection(
    conn: Connection,
    company: str,
    ref: NoticeDocumentRef,
    result: PositionEvidenceSet,
    *,
    actor_id: str,
    parser_version: str = PARSER_VERSION,
) -> bool:
    """Persist immutable derived evidence in the caller's canonical transaction."""
    if (
        not company.strip()
        or not actor_id.strip()
        or parser_version not in {PARSER_VERSION, LEGACY_PARSER_VERSION}
    ):
        raise ValueError("POSITION_PROJECTION_CONTEXT_INVALID")
    if (result.law, result.purchase_number, result.version_number, result.notice_xml_sha256) != (
        "44",
        ref.purchase_number,
        ref.version_number,
        ref.notice_xml_sha256,
    ):
        raise ValueError("POSITION_PROJECTION_IDENTITY_MISMATCH")
    assert_notice_source_usable(conn, company, ref.purchase_number, ref.version_number)
    source_sha = conn.scalar(
        select(eis_notice_versions.c.xml_sha256).where(
            eis_notice_versions.c.company_id == company,
            eis_notice_versions.c.purchase_number == ref.purchase_number,
            eis_notice_versions.c.version_number == ref.version_number,
        )
    )
    if source_sha != ref.notice_xml_sha256:
        raise ValueError("NOTICE_DIGEST_CONFLICT")
    payload = result.model_dump(mode="json")
    digest = _digest(payload)
    at = datetime.now(UTC)
    inserted = conn.execute(
        pg_insert(eis_notice_position_projections)
        .values(
            company_id=company,
            purchase_number=ref.purchase_number,
            version_number=ref.version_number,
            notice_xml_sha256=ref.notice_xml_sha256,
            parser_version=parser_version,
            position_set=payload,
            projection_sha256=digest,
            created_at=at,
        )
        .on_conflict_do_nothing()
        .returning(eis_notice_position_projections.c.purchase_number)
    ).scalar_one_or_none()
    if inserted is None:
        existing = read_position_projection(conn, company, ref, parser_version=parser_version)
        if existing != result:
            raise ValueError("POSITION_PROJECTION_CONFLICT")
        return False
    conn.execute(
        insert(audit_events).values(
            event_id=str(uuid.uuid4()),
            company_id=company,
            actor_id=actor_id,
            event_type="EIS_POSITION_PROJECTED",
            object_type="EIS_NOTICE_POSITIONS",
            object_id=ref.purchase_number,
            object_version=ref.version_number,
            basis={
                **ref.model_dump(),
                "parser_version": parser_version,
                "projection_sha256": digest,
            },
            occurred_at=at,
        )
    )
    return True


def derive_new_drug_positions(
    conn: Connection,
    company: str,
    notice: EisNoticeSnapshot,
    archive_bytes: bytes,
    *,
    actor_id: str,
) -> bool:
    """Only newly admitted notices; source bytes already belong to this transaction."""
    from procurement.storage.eis_document_store import NoticeDocumentRef

    if notice.lot_items:
        return False
    if len(archive_bytes) > MAX_ARCHIVE_BYTES:
        raise ValueError("POSITION_ARCHIVE_SIZE_LIMIT")
    with ZipFile(BytesIO(archive_bytes)) as archive:
        members = [m for m in archive.infolist() if m.filename == notice.source_member]
        if len(members) != 1 or members[0].is_dir():
            raise ValueError("POSITION_SOURCE_MEMBER_INVALID")
        if members[0].file_size > MAX_XML_BYTES:
            # Canonical intake has its own larger bound; absent derivation is UNKNOWN.
            return False
        with archive.open(members[0]) as stream:
            xml = stream.read(MAX_XML_BYTES + 1)
        if len(xml) != members[0].file_size:
            raise ValueError("POSITION_XML_SIZE_MISMATCH")
    result = drug_positions44(notice, xml)
    if result is None:
        return False
    if conn.scalar(
        select(notice_variant_hold_clause(company, notice.purchase_number, notice.version_number))
    ):
        # Canonical admission and its history retain their original semantics;
        # unresolved same/newer evidence cannot receive a usable derivation.
        return False
    ref = NoticeDocumentRef(
        purchase_number=notice.purchase_number,
        version_number=notice.version_number,
        notice_xml_sha256=notice.xml_sha256,
    )
    return insert_position_projection(conn, company, ref, result, actor_id=actor_id)
