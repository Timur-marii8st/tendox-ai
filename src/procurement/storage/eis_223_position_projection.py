"""Immutable cached-source223 customer positions; bounded main-page reads."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from io import BytesIO
from typing import TYPE_CHECKING
from uuid import uuid4
from zipfile import ZipFile

from sqlalchemy import Text, cast, func, insert, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from procurement.sources.eis_223_archive import (
    MAX_ARCHIVE_BYTES,
    MAX_NOTICE_XML_BYTES,
    Eis223NoticeSnapshot,
)
from procurement.sources.eis_223_joint_positions import (
    PARSER_VERSION,
    Eis223PositionProjection,
    joint_positions223,
)
from procurement.storage.models import (
    audit_events,
    eis_223_blobs,
    eis_223_notice_versions,
    eis_223_position_projections,
)

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from procurement.storage.repository import PostgresStorage

RECORD_BYTES = 512 * 1024
PAGE_BYTES = 2 * 1024**2


def _digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _validated(notice: Eis223NoticeSnapshot, sha: str, digest: str, payload: dict):
    if sha != notice.xml_sha256 or _digest(payload) != digest:
        raise ValueError("223_POSITION_DIGEST_MISMATCH")
    result = Eis223PositionProjection.model_validate(payload)
    if (
        result.purchase_number,
        result.version_number,
        result.notice_xml_sha256,
        result.source_member,
        result.document_type,
    ) != (
        notice.purchase_number,
        notice.version_number,
        notice.xml_sha256,
        notice.source_member,
        notice.document_type,
    ):
        raise ValueError("223_POSITION_IDENTITY_MISMATCH")
    return result


def derive_positions223(
    conn: Connection,
    company: str,
    notice: Eis223NoticeSnapshot,
    raw: bytes,
    *,
    actor_id: str,
    now: datetime | None = None,
) -> bool:
    if not company.strip() or not actor_id.strip():
        raise ValueError("223_POSITION_TENANT_ACTOR")
    at = now or datetime.now(UTC)
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("223_POSITION_TIME")
    projection = joint_positions223(raw, notice)
    if projection is None:
        return False
    payload = projection.model_dump(mode="json")
    digest = _digest(payload)
    t = eis_223_position_projections
    identity = (
        t.c.company_id == company,
        t.c.purchase_number == notice.purchase_number,
        t.c.version_number == notice.version_number,
        t.c.parser_version == PARSER_VERSION,
    )
    inserted = conn.scalar(
        pg_insert(t)
        .values(
            company_id=company,
            purchase_number=notice.purchase_number,
            version_number=notice.version_number,
            notice_xml_sha256=notice.xml_sha256,
            parser_version=PARSER_VERSION,
            position_set=payload,
            projection_sha256=digest,
            created_at=at,
        )
        .on_conflict_do_nothing()
        .returning(t.c.projection_sha256)
    )
    if inserted is None:
        old = conn.execute(
            select(t.c.notice_xml_sha256, t.c.projection_sha256).where(*identity)
        ).one()
        if (old.notice_xml_sha256, old.projection_sha256) != (notice.xml_sha256, digest):
            raise ValueError("223_POSITION_REPLAY_CONFLICT")
        return False
    conn.execute(
        insert(audit_events).values(
            event_id=str(uuid4()),
            company_id=company,
            actor_id=actor_id,
            event_type="EIS_223_POSITIONS_PROJECTED",
            object_type="EIS_223_NOTICE",
            object_id=notice.purchase_number,
            object_version=notice.version_number,
            basis={
                "law": "223",
                "xml_sha256": notice.xml_sha256,
                "source_member": notice.source_member,
                "parser_version": PARSER_VERSION,
                "projection_sha256": digest,
                "source_item_coverage": projection.source_item_coverage,
                "specification_completeness": "UNKNOWN",
                "economics_status": "UNKNOWN",
            },
            occurred_at=at,
        )
    )
    return True


def xml_from_archive223(content: bytes, archive_sha256: str, notice: Eis223NoticeSnapshot) -> bytes:
    if len(content) > MAX_ARCHIVE_BYTES or hashlib.sha256(content).hexdigest() != archive_sha256:
        raise ValueError("223_POSITION_ARCHIVE_DIGEST")
    with ZipFile(BytesIO(content)) as archive:
        members = [m for m in archive.infolist() if m.filename == notice.source_member]
        if len(members) != 1 or members[0].file_size > MAX_NOTICE_XML_BYTES:
            raise ValueError("223_POSITION_MEMBER_LIMIT")
        with archive.open(members[0]) as member:
            raw = member.read(MAX_NOTICE_XML_BYTES + 1)
    if len(raw) > MAX_NOTICE_XML_BYTES or hashlib.sha256(raw).hexdigest() != notice.xml_sha256:
        raise ValueError("223_POSITION_XML_DIGEST")
    return raw


def project_stored_positions223(
    storage: PostgresStorage,
    company: str,
    number: str,
    version: int,
    xml_sha256: str,
    *,
    actor_id: str,
) -> bool:
    """Explicit exact-ref backfill; no RPC or canonical writes; same result is no-write."""
    with storage.transaction(company, consistent_read=True) as conn:
        n, b = eis_223_notice_versions, eis_223_blobs
        row = (
            conn.execute(
                select(n).where(
                    n.c.company_id == company,
                    n.c.purchase_number == number,
                    n.c.version_number == version,
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise LookupError("223_POSITION_NOTICE_NOT_FOUND")
        if row["xml_sha256"] != xml_sha256:
            raise ValueError("223_POSITION_XML_IDENTITY")
        notice = Eis223NoticeSnapshot.model_validate(row["snapshot"])
        scope = (b.c.company_id == company, b.c.archive_sha256 == row["archive_sha256"])
        size = conn.scalar(select(func.octet_length(b.c.content)).where(*scope))
        if size is None or size > MAX_ARCHIVE_BYTES:
            raise ValueError("223_POSITION_ARCHIVE_LIMIT")
        content = bytes(conn.scalar(select(b.c.content).where(*scope)))
    raw = xml_from_archive223(content, row["archive_sha256"], notice)
    # Source rows and blobs are immutable; writes use a separate ordinary tenant transaction.
    with storage.transaction(company) as conn:
        return derive_positions223(conn, company, notice, raw, actor_id=actor_id)


def read_position223_page(
    conn: Connection, company: str, notices: Sequence[Eis223NoticeSnapshot]
) -> tuple[Eis223PositionProjection | None, ...]:
    """Two fixed SQL reads, metadata before hydration; deterministic stored/wire budgets."""
    if not company.strip() or len(notices) > 100:
        raise ValueError("223_POSITION_PAGE_LIMIT")
    refs = {(n.purchase_number, n.version_number): n for n in notices}
    if len(refs) != len(notices):
        raise ValueError("223_POSITION_PAGE_DUPLICATE")
    if not refs:
        return ()
    t = eis_223_position_projections
    scope = (t.c.company_id == company, t.c.parser_version == PARSER_VERSION)
    metadata = (
        conn.execute(
            select(
                t.c.purchase_number,
                t.c.version_number,
                t.c.notice_xml_sha256,
                t.c.projection_sha256,
                func.octet_length(cast(t.c.position_set, Text)).label("size"),
            ).where(*scope, tuple_(t.c.purchase_number, t.c.version_number).in_(list(refs)))
        )
        .mappings()
        .all()
    )
    by_key = {(m["purchase_number"], m["version_number"]): m for m in metadata}
    accepted = {}
    remaining = PAGE_BYTES
    for key, notice in refs.items():
        meta = by_key.get(key)
        if meta is None:
            continue
        if meta["notice_xml_sha256"] != notice.xml_sha256:
            raise ValueError("223_POSITION_XML_IDENTITY")
        if meta["size"] > min(RECORD_BYTES, remaining):
            continue
        accepted[key] = meta
        remaining -= meta["size"]
    results = {}
    if accepted:
        rows = (
            conn.execute(
                select(t.c.purchase_number, t.c.version_number, t.c.position_set).where(
                    *scope, tuple_(t.c.purchase_number, t.c.version_number).in_(list(accepted))
                )
            )
            .mappings()
            .all()
        )
        if len(rows) != len(accepted):
            raise ValueError("223_POSITION_PAGE_CHANGED")
        for row in rows:
            key = row["purchase_number"], row["version_number"]
            meta = accepted[key]
            results[key] = _validated(
                refs[key], meta["notice_xml_sha256"], meta["projection_sha256"], row["position_set"]
            )
    remaining = PAGE_BYTES
    output = []
    for key in refs:
        result = results.get(key)
        if result is not None:
            size = len(result.model_dump_json().encode())
            if size > min(RECORD_BYTES, remaining):
                result = None
            else:
                remaining -= size
        output.append(result)
    return tuple(output)
