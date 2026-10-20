"""Idempotent immutable tenant full-XSD evidence; no rewrite of source metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import and_, insert, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from procurement.sources.eis_223_archive import Eis223NoticeSnapshot
from procurement.sources.eis_223_schema import SCHEMAS, VALIDATOR, Eis223SchemaCheck
from procurement.storage.models import (
    audit_events,
    eis_223_blobs,
    eis_223_notice_versions,
    eis_223_schema_checks,
)

if TYPE_CHECKING:
    from procurement.storage.repository import PostgresStorage


@dataclass(frozen=True)
class SchemaTarget:
    notice: Eis223NoticeSnapshot
    archive_sha256: str
    content: bytes


def pending_schema_targets(
    storage: PostgresStorage, company: str, *, limit: int = 2
) -> tuple[SchemaTarget, ...]:
    """Latest versions only; a recorded FAIL completes that exact validator policy."""
    if not 1 <= limit <= 2:
        raise ValueError("QUALITY_BATCH_LIMIT")
    notices, checks, blobs = eis_223_notice_versions, eis_223_schema_checks, eis_223_blobs
    newer = notices.alias("quality_newer")
    missing = []
    for release, (_, _, tree) in SCHEMAS.items():
        missing.append(
            ~select(checks.c.xml_sha256)
            .where(
                checks.c.company_id == company,
                checks.c.purchase_number == notices.c.purchase_number,
                checks.c.version_number == notices.c.version_number,
                checks.c.xml_sha256 == notices.c.xml_sha256,
                checks.c.schema_release == release,
                checks.c.tree_sha256 == tree,
                checks.c.validator_version == VALIDATOR,
            )
            .exists()
        )
    query = (
        select(notices, blobs.c.content)
        .select_from(
            notices.join(
                blobs,
                and_(
                    blobs.c.company_id == notices.c.company_id,
                    blobs.c.archive_sha256 == notices.c.archive_sha256,
                ),
            )
        )
        .where(
            notices.c.company_id == company,
            ~select(newer.c.purchase_number)
            .where(
                newer.c.company_id == company,
                newer.c.purchase_number == notices.c.purchase_number,
                newer.c.version_number > notices.c.version_number,
            )
            .exists(),
            or_(*missing),
        )
        .order_by(notices.c.ingested_at, notices.c.purchase_number)
        .limit(limit)
    )
    with storage.transaction(company, consistent_read=True) as conn:
        rows = list(conn.execute(query).mappings())
    archives: dict[str, bytes] = {}
    result = []
    for row in rows:
        notice = Eis223NoticeSnapshot.model_validate(row["snapshot"])
        if (notice.purchase_number, notice.version_number, notice.xml_sha256) != (
            row["purchase_number"],
            row["version_number"],
            row["xml_sha256"],
        ):
            raise ValueError("QUALITY_SOURCE_BINDING_INVALID")
        content = archives.setdefault(row["archive_sha256"], bytes(row["content"]))
        result.append(SchemaTarget(notice, row["archive_sha256"], content))
    return tuple(result)


def record_schema_check(
    storage: PostgresStorage, company: str, check: Eis223SchemaCheck, *, actor_id: str
) -> bool:
    if not actor_id.strip():
        raise ValueError("ACTOR_MISSING")
    check = Eis223SchemaCheck.model_validate(check.model_dump())
    table = eis_223_schema_checks
    report = check.model_dump(mode="json")
    with storage.transaction(company) as conn:
        row = conn.execute(
            pg_insert(table)
            .values(
                company_id=company,
                purchase_number=check.purchase_number,
                version_number=check.version_number,
                xml_sha256=check.xml_sha256,
                schema_release=check.schema_release,
                tree_sha256=check.tree_sha256,
                validator_version=check.validator_version,
                status=check.status,
                report=report,
                checked_at=check.checked_at,
            )
            .on_conflict_do_nothing(index_elements=list(table.primary_key.columns))
            .returning(table.c.xml_sha256)
        ).first()
        if row is None:
            from sqlalchemy import select

            existing = conn.scalar(
                select(table.c.report).where(
                    table.c.company_id == company,
                    table.c.purchase_number == check.purchase_number,
                    table.c.version_number == check.version_number,
                    table.c.xml_sha256 == check.xml_sha256,
                    table.c.schema_release == check.schema_release,
                    table.c.tree_sha256 == check.tree_sha256,
                    table.c.validator_version == check.validator_version,
                )
            )
            if existing is None or {k: v for k, v in existing.items() if k != "checked_at"} != {
                k: v for k, v in report.items() if k != "checked_at"
            }:
                raise ValueError("SCHEMA_CHECK_CONFLICT")
            return False
        conn.execute(
            insert(audit_events).values(
                company_id=company,
                event_id=str(uuid4()),
                actor_id=actor_id,
                event_type="EIS_223_SCHEMA_CHECKED",
                object_type="EIS_223_NOTICE",
                object_id=check.purchase_number,
                object_version=check.version_number,
                occurred_at=check.checked_at,
                basis={
                    "xml_sha256": check.xml_sha256,
                    "schema_release": check.schema_release,
                    "tree_sha256": check.tree_sha256,
                    "validator_version": check.validator_version,
                    "source_schema_status": check.status,
                    "eligibility": "UNKNOWN",
                },
            )
        )
    return True
