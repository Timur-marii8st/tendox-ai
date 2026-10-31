"""Fail-closed evidence-only hold for notices with retained source variants."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Text, case, cast, column, exists, func, literal, or_, select, true, union
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import CTE

from procurement.storage.models import (
    audit_events,
    eis_feed_windows,
    eis_notice_projection_batches,
    eis_notice_projection_decisions,
    eis_notice_variant_origins,
    eis_notice_variant_receipts,
    eis_notice_variants,
    eis_notice_versions,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

    from procurement.storage.repository import PostgresStorage

CompanyExpression = str | ColumnElement[str]
NumberExpression = str | ColumnElement[str]
VersionExpression = int | ColumnElement[int]

MAX_HOLD_RECEIPTS = 20


class EisNoticeSourceHold(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    purchase_number: str = Field(pattern=r"^[0-9]{19,23}$")
    selected_version_number: int = Field(ge=1)
    status: Literal["HOLD", "NO_HOLD", "INTEGRITY_ERROR"]
    evidence_scope: Literal["EVIDENCE_ONLY"] = "EVIDENCE_ONLY"
    resolution: Literal["UNKNOWN"] = "UNKNOWN"
    variant_count: int = Field(ge=0)
    origin_count: int = Field(ge=0)
    receipt_ids: tuple[str, ...] = Field(default=(), max_length=MAX_HOLD_RECEIPTS)

    @model_validator(mode="after")
    def _consistent(self) -> EisNoticeSourceHold:
        if self.status == "NO_HOLD" and (
            self.variant_count or self.origin_count or self.receipt_ids
        ):
            raise ValueError("NOTICE_SOURCE_HOLD_INVALID")
        if self.status == "HOLD" and not (self.variant_count or self.origin_count):
            raise ValueError("NOTICE_SOURCE_HOLD_INVALID")
        return self


def _incomplete_receipt_clause(company_id: CompanyExpression) -> ColumnElement[bool]:
    origin_count = (
        select(func.count())
        .select_from(eis_notice_variant_origins)
        .where(
            eis_notice_variant_origins.c.company_id == eis_notice_variant_receipts.c.company_id,
            eis_notice_variant_origins.c.receipt_id == eis_notice_variant_receipts.c.receipt_id,
        )
        .correlate(eis_notice_variant_receipts)
        .scalar_subquery()
    )
    return exists(
        select(1).where(
            eis_notice_variant_receipts.c.company_id == company_id,
            eis_notice_variant_receipts.c.occurrence_count != origin_count,
        )
    )


def notice_receipt_integrity_hold_clause(
    company_id: CompanyExpression,
) -> ColumnElement[bool]:
    """Tenant-wide fail-closed predicate for incomplete evidence receipts."""
    return _incomplete_receipt_clause(company_id)


def notice_variant_hold_clause(
    company_id: CompanyExpression,
    purchase_number: NumberExpression,
    version_number: VersionExpression,
    *,
    _resolution_scope: CTE | None = None,
) -> ColumnElement[bool]:
    """Unresolved same-or-newer evidence; explicit decisions are revalidated live."""
    variant = eis_notice_variants
    origin = eis_notice_variant_origins
    pairs = (
        _scoped_resolution_pairs(company_id, _resolution_scope)
        if _resolution_scope is not None
        else None
    )
    resolved = _resolved_projection_pairs(
        company_id, _audited_projection_decisions(company_id, _pairs=pairs), _pairs=pairs
    )
    return or_(
        exists(
            select(1).where(
                eis_notice_variants.c.company_id == company_id,
                eis_notice_variants.c.purchase_number == purchase_number,
                eis_notice_variants.c.version_number >= version_number,
                ~notice_pair_projection_resolved_clause(
                    variant.c.company_id,
                    variant.c.purchase_number,
                    variant.c.version_number,
                    _resolved=resolved,
                ),
            )
        ),
        exists(
            select(1).where(
                eis_notice_variant_origins.c.company_id == company_id,
                eis_notice_variant_origins.c.purchase_number == purchase_number,
                eis_notice_variant_origins.c.version_number >= version_number,
                ~notice_pair_projection_resolved_clause(
                    origin.c.company_id,
                    origin.c.purchase_number,
                    origin.c.version_number,
                    _resolved=resolved,
                ),
            )
        ),
        notice_receipt_integrity_hold_clause(company_id),
    )


def _scoped_resolution_pairs(company_id: CompanyExpression, scope: CTE) -> CTE:
    """All same/newer retained pairs, without date/receipt/branch restrictions.

    The scope only narrows proofs of resolution. Hold existence and tenant-wide
    receipt integrity remain independent; an omitted pair therefore fails closed.
    """
    statements = []
    for source in (eis_notice_variants, eis_notice_variant_origins):
        relevant = exists(
            select(1).where(
                scope.c.company_id == source.c.company_id,
                scope.c.purchase_number == source.c.purchase_number,
                scope.c.version_number <= source.c.version_number,
            )
        ).correlate(source)
        statements.append(
            select(source.c.company_id, source.c.purchase_number, source.c.version_number).where(
                source.c.company_id == company_id, relevant
            )
        )
    return union(*statements).cte("scoped_resolution_pairs").prefix_with("MATERIALIZED")


def _audited_projection_decisions(
    company_id: CompanyExpression, *, _pairs: CTE | None = None
) -> CTE:
    """Expand bounded audited arrays once; retain exact JSON and indexed join keys."""
    b = eis_notice_projection_batches.alias("audited_batch")
    a = audit_events.alias("audited_batch_event")
    tenant = (
        company_id
        if isinstance(company_id, str)
        else func.nullif(func.current_setting("app.company_id", True), "")
    )
    safe_array = case(
        (func.jsonb_typeof(a.c.basis["decisions"]) == "array", a.c.basis["decisions"]),
        else_=cast(literal("[]", type_=Text), JSONB),
    )
    scope_predicates = []
    if _pairs is not None:
        d = eis_notice_projection_decisions.alias("scoped_audit_decision")
        pair = exists(
            select(1).where(
                _pairs.c.company_id == d.c.company_id,
                _pairs.c.purchase_number == d.c.purchase_number,
                _pairs.c.version_number == d.c.version_number,
            )
        ).correlate(d)
        scope_predicates.append(
            exists(
                select(1).where(
                    d.c.company_id == b.c.company_id, d.c.batch_id == b.c.batch_id, pair
                )
            ).correlate(b)
        )
    # Keep the complete authenticated audit binding, then expand its array.
    # A WHERE predicate around a lateral JSON function is not an execution
    # boundary: PostgreSQL can expand unrelated tenant audit rows first.
    bindings = (
        select(b.c.company_id, b.c.batch_id, a.c.basis.label("audit_basis"))
        .select_from(
            b.join(a, (a.c.company_id == b.c.company_id) & (a.c.event_id == b.c.audit_event_id))
        )
        .where(
            b.c.company_id == tenant,
            b.c.projected_count + b.c.replayed_count > 0,
            b.c.parser_version == "eis-notice-projection-v1",
            a.c.event_type == "EIS_NOTICE_PROJECTION_RECORDED",
            a.c.object_type == "eis_notice_projection_batch",
            a.c.object_id == b.c.batch_id,
            a.c.basis["payload_sha256"].astext == b.c.payload_sha256,
            func.jsonb_array_length(safe_array) == b.c.pair_count,
            *scope_predicates,
        )
        .cte("audited_batch_bindings")
        .prefix_with("MATERIALIZED")
    )
    bound_array = case(
        (
            func.jsonb_typeof(bindings.c.audit_basis["decisions"]) == "array",
            bindings.c.audit_basis["decisions"],
        ),
        else_=cast(literal("[]", type_=Text), JSONB),
    )
    member = (
        func.jsonb_array_elements(bound_array)
        .table_valued(column("value", JSONB))
        .lateral("audited_member")
    )
    return (
        select(
            bindings.c.company_id,
            bindings.c.batch_id,
            member.c.value["purchase_number"].astext.label("purchase_number"),
            member.c.value["version_number"].astext.label("version_number"),
            member.c.value.label("decision"),
        )
        .select_from(bindings.join(member, true()))
        .cte("audited_projection_decisions")
        .prefix_with("MATERIALIZED")
    )


def _resolved_projection_pairs(
    company_id: CompanyExpression, audited: CTE, *, _pairs: CTE | None = None
) -> CTE:
    """One audited projection matching canonical bytes and all current origins."""
    d = eis_notice_projection_decisions.alias("projection_decision")
    b = eis_notice_projection_batches.alias("projection_batch")
    n = eis_notice_versions.alias("projected_notice")
    v = eis_notice_variants.alias("projection_variant")
    o = eis_notice_variant_origins.alias("projection_origin")
    w = eis_feed_windows.alias("projection_transport")
    invalid_variant = exists(
        select(1).where(
            v.c.company_id == d.c.company_id,
            v.c.purchase_number == d.c.purchase_number,
            v.c.version_number == d.c.version_number,
            or_(v.c.xml_sha256 != d.c.xml_sha256, v.c.document_type != d.c.document_type),
        )
    ).correlate(d)
    invalid_origin = exists(
        select(1).where(
            o.c.company_id == d.c.company_id,
            o.c.purchase_number == d.c.purchase_number,
            o.c.version_number == d.c.version_number,
            or_(o.c.xml_sha256 != d.c.xml_sha256, o.c.document_type != d.c.document_type),
        )
    ).correlate(d)
    exact_origin = exists(
        select(1).where(
            o.c.company_id == d.c.company_id,
            o.c.receipt_id == b.c.receipt_id,
            o.c.purchase_number == d.c.purchase_number,
            o.c.version_number == d.c.version_number,
            o.c.xml_sha256 == d.c.xml_sha256,
            o.c.document_type == d.c.document_type,
            o.c.archive_sha256 == d.c.archive_sha256,
            o.c.member_filename == d.c.member_filename,
        )
    ).correlate(d, b)
    exact_variant = exists(
        select(1).where(
            v.c.company_id == d.c.company_id,
            v.c.purchase_number == d.c.purchase_number,
            v.c.version_number == d.c.version_number,
            v.c.xml_sha256 == d.c.xml_sha256,
            v.c.document_type == d.c.document_type,
            v.c.facts["document_id"].astext.is_not(None),
        )
    ).correlate(d)
    audited_decision = audited.c.decision == func.jsonb_build_object(
        *[
            part
            for column in d.c
            for part in (cast(literal(str(column.name), type_=Text), Text), column)
        ]
    )
    tenant = (
        company_id
        if isinstance(company_id, str)
        else func.nullif(func.current_setting("app.company_id", True), "")
    )
    scope_predicates = []
    if _pairs is not None:
        scope_predicates.append(
            exists(
                select(1).where(
                    _pairs.c.company_id == d.c.company_id,
                    _pairs.c.purchase_number == d.c.purchase_number,
                    _pairs.c.version_number == d.c.version_number,
                )
            ).correlate(d)
        )
    return (
        select(d.c.company_id, d.c.purchase_number, d.c.version_number)
        .select_from(
            d.join(b, (b.c.company_id == d.c.company_id) & (b.c.batch_id == d.c.batch_id))
            .join(
                n,
                (n.c.company_id == d.c.company_id)
                & (n.c.purchase_number == d.c.purchase_number)
                & (n.c.version_number == d.c.version_number)
                & (n.c.xml_sha256 == d.c.xml_sha256)
                & (n.c.document_type == d.c.document_type),
            )
            .join(
                audited,
                (audited.c.company_id == d.c.company_id)
                & (audited.c.batch_id == d.c.batch_id)
                & (audited.c.purchase_number == d.c.purchase_number)
                & (audited.c.version_number == cast(d.c.version_number, Text)),
            )
            .join(
                w,
                (w.c.company_id == b.c.company_id)
                & (w.c.window_key == b.c.window_key)
                & (w.c.response_sha256 == b.c.response_sha256),
            )
        )
        .where(
            d.c.company_id == tenant,
            d.c.status.in_(("PROJECTED", "REPLAYED")),
            b.c.parser_version == "eis-notice-projection-v1",
            w.c.intake_kind == "VARIANT_TRANSPORT",
            audited_decision,
            exact_origin,
            exact_variant,
            ~invalid_variant,
            ~invalid_origin,
            *scope_predicates,
        )
        .distinct()
        .cte("resolved_projection_pairs")
        .prefix_with("MATERIALIZED")
    )


def notice_pair_projection_resolved_clause(
    company_id: CompanyExpression,
    purchase_number: NumberExpression,
    version_number: VersionExpression,
    *,
    _resolved: CTE | None = None,
) -> ColumnElement[bool]:
    resolved = (
        _resolved
        if _resolved is not None
        else _resolved_projection_pairs(company_id, _audited_projection_decisions(company_id))
    )
    return exists(
        select(1).where(
            resolved.c.company_id == company_id,
            resolved.c.purchase_number == purchase_number,
            resolved.c.version_number == version_number,
        )
    )


def assert_notice_source_usable(
    connection: Connection,
    company_id: str,
    purchase_number: str,
    version_number: int,
) -> None:
    held = connection.scalar(
        select(notice_variant_hold_clause(company_id, purchase_number, version_number))
    )
    if held:
        raise ValueError("NOTICE_VARIANT_REVIEW_REQUIRED")


def read_notice_source_hold(
    storage: PostgresStorage,
    company_id: str,
    purchase_number: str,
    version_number: int,
) -> EisNoticeSourceHold:
    if version_number < 1:
        raise ValueError("NOTICE_SOURCE_HOLD_INPUT_INVALID")
    with storage.transaction(company_id, consistent_read=True) as connection:
        return read_notice_source_hold_connection(
            connection, company_id, purchase_number, version_number
        )


def read_notice_source_hold_connection(
    connection: Connection,
    company_id: str,
    purchase_number: str,
    version_number: int,
) -> EisNoticeSourceHold:
    """Read bounded hold metadata in an existing consistent tenant transaction."""
    if version_number < 1:
        raise ValueError("NOTICE_SOURCE_HOLD_INPUT_INVALID")
    incomplete = bool(connection.scalar(select(_incomplete_receipt_clause(company_id))))
    variant_count = int(
        connection.scalar(
            select(func.count())
            .select_from(eis_notice_variants)
            .where(
                eis_notice_variants.c.company_id == company_id,
                eis_notice_variants.c.purchase_number == purchase_number,
                eis_notice_variants.c.version_number >= version_number,
            )
        )
        or 0
    )
    origin_count = int(
        connection.scalar(
            select(func.count())
            .select_from(eis_notice_variant_origins)
            .where(
                eis_notice_variant_origins.c.company_id == company_id,
                eis_notice_variant_origins.c.purchase_number == purchase_number,
                eis_notice_variant_origins.c.version_number >= version_number,
            )
        )
        or 0
    )
    receipt_ids = tuple(
        connection.execute(
            select(eis_notice_variant_origins.c.receipt_id)
            .where(
                eis_notice_variant_origins.c.company_id == company_id,
                eis_notice_variant_origins.c.purchase_number == purchase_number,
                eis_notice_variant_origins.c.version_number >= version_number,
            )
            .distinct()
            .order_by(eis_notice_variant_origins.c.receipt_id)
            .limit(MAX_HOLD_RECEIPTS + 1)
        ).scalars()
    )
    resolution_scope = select(
        literal(company_id).label("company_id"),
        literal(purchase_number).label("purchase_number"),
        literal(version_number).label("version_number"),
    ).cte("single_notice_hold_scope")
    held = (
        bool(
            connection.scalar(
                select(
                    notice_variant_hold_clause(
                        company_id,
                        purchase_number,
                        version_number,
                        _resolution_scope=resolution_scope,
                    )
                )
            )
        )
        if not incomplete and (variant_count or origin_count)
        else False
    )
    if incomplete or (held and len(receipt_ids) > MAX_HOLD_RECEIPTS):
        return EisNoticeSourceHold(
            purchase_number=purchase_number,
            selected_version_number=version_number,
            status="INTEGRITY_ERROR",
            variant_count=variant_count,
            origin_count=origin_count,
        )
    if held:
        return EisNoticeSourceHold(
            purchase_number=purchase_number,
            selected_version_number=version_number,
            status="HOLD",
            variant_count=variant_count,
            origin_count=origin_count,
            receipt_ids=receipt_ids,
        )
    return EisNoticeSourceHold(
        purchase_number=purchase_number,
        selected_version_number=version_number,
        status="NO_HOLD",
        variant_count=0,
        origin_count=0,
    )
