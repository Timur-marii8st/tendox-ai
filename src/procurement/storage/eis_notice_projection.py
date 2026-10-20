"""Explicit atomic projection of a complete, audited retained variant transport."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Table, insert, null, select, text, tuple_
from sqlalchemy.engine import Connection
from sqlalchemy.sql.elements import ColumnElement

from procurement.sources.eis_feed_archive import EisArchiveInspection
from procurement.sources.eis_notice_conflicts import EisNoticeConflictDiagnosis
from procurement.sources.eis_notice_projection import (
    EisNoticeProjectionBatch,
    EisNoticeProjectionCandidate,
    prepare_notice_projection,
)
from procurement.storage.eis_notice_hold import _incomplete_receipt_clause
from procurement.storage.eis_notice_index import EisReadyWindow, _notice_values
from procurement.storage.eis_notice_variants import (
    MAX_ORIGINS,
    MAX_RECEIPTS,
    MAX_VARIANTS,
    EisNoticeVariantReceipt,
    _facts_from_row,
    read_notice_variant_receipt_connection,
)
from procurement.storage.eis_search_index import insert_search_keys
from procurement.storage.models import (
    audit_events,
    eis_feed_archive_sources,
    eis_feed_archives,
    eis_feed_windows,
    eis_notice_projection_batches,
    eis_notice_projection_decisions,
    eis_notice_variant_origins,
    eis_notice_variants,
    eis_notice_versions,
)
from procurement.storage.repository import PostgresStorage

PARSER_VERSION = "eis-notice-projection-v1"
MAX_BATCH_PAYLOAD_BYTES = 24 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024


class EisNoticeProjectionReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    batch_id: str
    receipt_id: str
    archive_count: int = Field(ge=1)
    occurrence_count: int = Field(ge=1)
    pair_count: int = Field(ge=1)
    projected_count: int = Field(ge=0)
    replayed_count: int = Field(ge=0)
    held_count: int = Field(ge=0)
    replayed: bool
    audit_event_id: str
    coverage: Literal["UNKNOWN"] = "UNKNOWN"


def _json(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    return value


def _sha(value: Any) -> str:
    encoded = json.dumps(_json(value), sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) > MAX_BATCH_PAYLOAD_BYTES:
        raise ValueError("NOTICE_PROJECTION_PAYLOAD_LIMIT")
    return hashlib.sha256(encoded).hexdigest()


def _where(table: Table, company: str, **keys: Any) -> tuple[ColumnElement[bool], ...]:
    return (table.c.company_id == company, *(table.c[key] == value for key, value in keys.items()))


def _receipt_and_diagnosis(
    conn: Connection, company: str, receipt_id: str
) -> tuple[EisNoticeVariantReceipt, EisNoticeConflictDiagnosis]:
    receipt = read_notice_variant_receipt_connection(conn, company, receipt_id)
    if receipt is None:
        raise ValueError("NOTICE_PROJECTION_RECEIPT_NOT_FOUND")
    basis = conn.execute(
        select(audit_events.c.basis).where(
            *_where(audit_events, company, event_id=receipt.diagnosis_audit_event_id)
        )
    ).scalar_one()
    diagnosis = EisNoticeConflictDiagnosis.model_validate(basis["diagnosis"])
    if (
        diagnosis.sha256 != receipt.diagnosis_sha256
        or diagnosis.archive_sha256s != receipt.archive_sha256s
        or diagnosis.occurrence_count != receipt.occurrence_count
    ):
        raise ValueError("NOTICE_PROJECTION_DIAGNOSIS_MISMATCH")
    # Every receipt origin and fact must be exactly the audited diagnosis inventory.
    from procurement.storage.eis_notice_variants import _facts, _origin

    facts = {_sha(_facts(item).model_dump(mode="json")) for item in diagnosis.occurrences}
    origins = [_origin(receipt_id, item).model_dump(mode="json") for item in diagnosis.occurrences]
    origins.sort(key=lambda item: (item["archive_ordinal"], item["member_filename"]))
    if facts != {_sha(item.model_dump(mode="json")) for item in receipt.variants} or origins != [
        item.model_dump(mode="json") for item in receipt.origins
    ]:
        raise ValueError("NOTICE_PROJECTION_INVENTORY_MISMATCH")
    return receipt, diagnosis


def read_reusable_notice_transport(
    storage: PostgresStorage, company: str, window: EisReadyWindow
) -> tuple[EisNoticeVariantReceipt, EisNoticeConflictDiagnosis]:
    """Reuse original audited provenance for an exact transport retry; never choose latest."""
    with storage.transaction(company, consistent_read=True) as conn:
        parent = (
            conn.execute(
                select(eis_feed_windows).where(
                    *_where(
                        eis_feed_windows,
                        company,
                        window_key=window.window_key,
                        response_sha256=window.response_sha256,
                        intake_kind="VARIANT_TRANSPORT",
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        candidates = (
            conn.execute(
                select(eis_notice_projection_batches.c.receipt_id)
                .where(
                    *_where(
                        eis_notice_projection_batches,
                        company,
                        window_key=window.window_key,
                        response_sha256=window.response_sha256,
                        parser_version=PARSER_VERSION,
                    )
                )
                .limit(2)
            )
            .scalars()
            .all()
        )
        if parent is None or len(candidates) != 1:
            raise ValueError("NOTICE_PROJECTION_TRANSPORT_CONFLICT")
        receipt, diagnosis = _receipt_and_diagnosis(conn, company, candidates[0])
        if (
            receipt.window_key != window.window_key
            or receipt.response_sha256 != window.response_sha256
            or receipt.prepared_response_sha256 != window.prepared_response_sha256
            or receipt.evidence.archive_urls != window.archive_urls
            or receipt.archive_sha256s
            != tuple(hashlib.sha256(raw).hexdigest() for raw in window.archives)
            or receipt.archive_count != window.expected_archive_count
            or parent["archive_count"] != receipt.archive_count
            or parent["notice_count"] != receipt.occurrence_count
            or parent["ingested_at"] != receipt.observed_at
        ):
            raise ValueError("NOTICE_PROJECTION_TRANSPORT_CONFLICT")
        # The writer repeats full member inventory, audit, transport and snapshot checks.
        return receipt, diagnosis


def _global_history(
    conn: Connection, company: str, pairs: Sequence[tuple[str, int]]
) -> dict[tuple[str, int], dict[str, list[dict[str, Any]]]]:
    variants = (
        conn.execute(
            select(eis_notice_variants)
            .where(
                eis_notice_variants.c.company_id == company,
                tuple_(
                    eis_notice_variants.c.purchase_number, eis_notice_variants.c.version_number
                ).in_(pairs),
            )
            .order_by(
                eis_notice_variants.c.purchase_number,
                eis_notice_variants.c.version_number,
                eis_notice_variants.c.document_type,
                eis_notice_variants.c.xml_sha256,
            )
            .limit(MAX_VARIANTS + 1)
        )
        .mappings()
        .all()
    )
    origins = (
        conn.execute(
            select(eis_notice_variant_origins)
            .where(
                eis_notice_variant_origins.c.company_id == company,
                tuple_(
                    eis_notice_variant_origins.c.purchase_number,
                    eis_notice_variant_origins.c.version_number,
                ).in_(pairs),
            )
            .order_by(
                eis_notice_variant_origins.c.receipt_id,
                eis_notice_variant_origins.c.archive_ordinal,
                eis_notice_variant_origins.c.member_filename,
            )
            .limit(MAX_ORIGINS + 1)
        )
        .mappings()
        .all()
    )
    receipt_ids = {row["receipt_id"] for row in origins}
    if (
        len(variants) > MAX_VARIANTS
        or len(origins) > MAX_ORIGINS
        or len(receipt_ids) > MAX_RECEIPTS
    ):
        raise ValueError("NOTICE_PROJECTION_HISTORY_LIMIT")
    for receipt_id in sorted(receipt_ids):
        _receipt_and_diagnosis(conn, company, receipt_id)
    # Missing origins are explicit HOLD; orphan origins fail audited receipt validation above.
    history: dict[tuple[str, int], dict[str, list[dict[str, Any]]]] = {
        pair: {"variants": [], "origins": []} for pair in pairs
    }
    for row in variants:
        history[row["purchase_number"], row["version_number"]]["variants"].append(
            _facts_from_row(dict(row)).model_dump(mode="json")
        )
    for row in origins:
        history[row["purchase_number"], row["version_number"]]["origins"].append(dict(row))
    return history


def _decision(
    candidate: EisNoticeProjectionCandidate,
    history: dict[str, list[dict[str, Any]]],
    canonical: Mapping[str, Any] | None,
    archive_sha: str,
) -> dict[str, Any]:
    snapshot = _json(asdict(candidate.snapshot)) if candidate.snapshot is not None else None
    reason = candidate.reason
    variants = {(v["document_type"], v["xml_sha256"]) for v in history["variants"]}
    origins = {(v["document_type"], v["xml_sha256"]) for v in history["origins"]}
    if variants != origins or not origins:
        reason = "VARIANT_ORIGIN_INTEGRITY_UNRESOLVED"
    elif variants != {(candidate.document_type, candidate.xml_sha256)}:
        reason = "GLOBAL_VARIANT_REVIEW_REQUIRED"
    elif any(v["document_id"] is None for v in history["variants"]):
        reason = "SOURCE_ID_UNKNOWN"
    if canonical is not None and (
        canonical["xml_sha256"] != candidate.xml_sha256
        or canonical["document_type"] != candidate.document_type
    ):
        reason = "CANONICAL_SOURCE_CONFLICT"
    if (
        canonical is not None
        and snapshot is not None
        and not _canonical_matches(canonical, snapshot)
    ):
        reason = reason or "CANONICAL_SNAPSHOT_CONFLICT"
    status = "HOLD" if reason else "REPLAYED" if canonical is not None else "PROJECTED"
    if status == "HOLD":
        snapshot = None
    if snapshot is not None and len(json.dumps(snapshot).encode()) > MAX_SNAPSHOT_BYTES:
        raise ValueError("NOTICE_PROJECTION_SNAPSHOT_LIMIT")
    return dict(
        purchase_number=candidate.purchase_number,
        version_number=candidate.version_number,
        document_type=candidate.document_type,
        xml_sha256=candidate.xml_sha256,
        status=status,
        reason=reason,
        input_sha256=_sha(history),
        snapshot_sha256=_sha(snapshot) if snapshot is not None else None,
        snapshot=snapshot,
        archive_sha256=archive_sha,
        member_filename=candidate.member_filename,
    )


def _transport_rows(
    company: str,
    receipt: EisNoticeVariantReceipt,
    prepared: EisNoticeProjectionBatch,
    archives: tuple[bytes, ...],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    when = receipt.observed_at.astimezone(UTC)
    common = dict(
        company_id=company, window_key=receipt.window_key, response_sha256=receipt.response_sha256
    )
    window = dict(
        **common,
        manifest_sha256=_sha(sorted(prepared.archive_sha256s)),
        archive_count=len(archives),
        notice_count=prepared.occurrence_count,
        coverage="UNKNOWN",
        intake_kind="VARIANT_TRANSPORT",
        ingested_at=when,
    )
    blobs, sources = [], []
    for i, content in enumerate(archives):
        digest = prepared.archive_sha256s[i]
        blobs.append(
            dict(
                **common,
                archive_sha256=digest,
                content=content,
                record_count=prepared.archive_member_counts[i],
            )
        )
        sources.append(
            dict(
                **common,
                archive_sha256=digest,
                prepared_response_sha256=receipt.prepared_response_sha256,
                source_url=receipt.evidence.archive_urls[i],
                received_at=when,
            )
        )
    return window, blobs, sources


def _save_or_verify_transport(
    conn: Connection,
    rows: tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]],
    *,
    write: bool,
) -> None:
    window, blobs, sources = rows
    for table, payloads in (
        (eis_feed_windows, [window]),
        (eis_feed_archives, blobs),
        (eis_feed_archive_sources, sources),
    ):
        for payload in payloads:
            keys = {key: payload[key] for key in ("window_key", "response_sha256")}
            if "archive_sha256" in payload:
                keys["archive_sha256"] = payload["archive_sha256"]
            old = (
                conn.execute(select(table).where(*_where(table, payload["company_id"], **keys)))
                .mappings()
                .one_or_none()
            )
            if old is None:
                if not write:
                    raise ValueError("NOTICE_PROJECTION_TRANSPORT_MISSING")
                conn.execute(insert(table).values(**payload))
            elif dict(old) != payload:
                raise ValueError("NOTICE_PROJECTION_TRANSPORT_CONFLICT")


def _report(batch: Mapping[str, Any], replayed: bool) -> EisNoticeProjectionReport:
    return EisNoticeProjectionReport(
        **{
            key: batch[key]
            for key in (
                "batch_id",
                "receipt_id",
                "occurrence_count",
                "pair_count",
                "projected_count",
                "replayed_count",
                "held_count",
                "audit_event_id",
            )
        },
        archive_count=len(batch["archive_sha256s"]),
        replayed=replayed,
    )


def project_retained_notice_variants(
    storage: PostgresStorage,
    company: str,
    receipt_id: str,
    archives: tuple[bytes, ...],
    *,
    actor_id: str = "retained-notice-projection",
) -> EisNoticeProjectionReport:
    """No source calls: admit explicit singleton pairs with full immutable transport evidence."""
    if not company.strip() or not actor_id.strip():
        raise ValueError("TENANT_OR_ACTOR_MISSING")
    with storage.transaction(company, consistent_read=True) as conn:
        receipt, diagnosis = _receipt_and_diagnosis(conn, company, receipt_id)
    prepared = prepare_notice_projection(archives, diagnosis)
    batch_id = str(
        uuid5(NAMESPACE_URL, f"{company}/notice-projection/{receipt_id}/{PARSER_VERSION}")
    )
    audit_id = str(uuid5(NAMESPACE_URL, f"{company}/notice-projection-audit/{batch_id}"))
    transport = _transport_rows(company, receipt, prepared, archives)
    with storage.transaction(company) as conn:
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant, 0))"), {"tenant": company}
        )
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": company + "/eis-notice-variants"},
        )
        locked_receipt, locked_diagnosis = _receipt_and_diagnosis(conn, company, receipt_id)
        if locked_receipt != receipt or locked_diagnosis != diagnosis:
            raise ValueError("NOTICE_PROJECTION_RECEIPT_CHANGED")
        old = (
            conn.execute(
                select(eis_notice_projection_batches).where(
                    *_where(eis_notice_projection_batches, company, batch_id=batch_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        if old is not None:
            return _replay(conn, company, dict(old), receipt, prepared, transport)
        _assert_complete_history(conn, company)
        pairs = [(item.purchase_number, item.version_number) for item in prepared.candidates]
        history = _global_history(conn, company, pairs)
        decisions, notice_rows = [], []
        now = datetime.now(UTC)
        window = EisReadyWindow(
            receipt.window_key, receipt.response_sha256, len(archives), archives
        )
        for candidate in prepared.candidates:
            pair = candidate.purchase_number, candidate.version_number
            canonical = (
                conn.execute(
                    select(eis_notice_versions).where(
                        *_where(
                            eis_notice_versions,
                            company,
                            purchase_number=pair[0],
                            version_number=pair[1],
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            digest = prepared.archive_sha256s[candidate.archive_ordinal]
            decision = _decision(
                candidate, history[pair], dict(canonical) if canonical is not None else None, digest
            )
            decisions.append(dict(company_id=company, batch_id=batch_id, **decision))
            if decision["status"] == "PROJECTED":
                assert candidate.snapshot is not None
                inspection = EisArchiveInspection(
                    digest,
                    receipt.response_sha256,
                    candidate.member_filename,
                    (candidate.snapshot,),
                )
                notice_rows.append(
                    (
                        _notice_values(company, window, inspection, candidate.snapshot, now),
                        candidate.snapshot,
                    )
                )
        batch = dict(
            company_id=company,
            batch_id=batch_id,
            receipt_id=receipt_id,
            window_key=receipt.window_key,
            response_sha256=receipt.response_sha256,
            parser_version=PARSER_VERSION,
            archive_sha256s=list(prepared.archive_sha256s),
            occurrence_count=prepared.occurrence_count,
            pair_count=len(decisions),
            projected_count=sum(d["status"] == "PROJECTED" for d in decisions),
            replayed_count=sum(d["status"] == "REPLAYED" for d in decisions),
            held_count=sum(d["status"] == "HOLD" for d in decisions),
            audit_event_id=audit_id,
            created_at=now,
        )
        inputs = [
            {"purchase_number": pair[0], "version_number": pair[1], **history[pair]}
            for pair in pairs
        ]
        basis = _json(
            dict(
                batch_id=batch_id,
                batch=batch,
                decisions=decisions,
                inputs=inputs,
                receipt_sha256=receipt.receipt_sha256,
            )
        )
        batch["payload_sha256"] = _sha(basis)
        basis["payload_sha256"] = batch["payload_sha256"]
        _save_or_verify_transport(conn, transport, write=True)
        conn.execute(insert(eis_notice_projection_batches).values(**batch))
        for decision in decisions:
            payload = dict(decision)
            if payload["snapshot"] is None:
                payload["snapshot"] = null()
            conn.execute(insert(eis_notice_projection_decisions).values(**payload))
        for values, snapshot in notice_rows:
            conn.execute(insert(eis_notice_versions).values(**values))
            insert_search_keys(
                conn,
                company,
                snapshot.purchase_number,
                snapshot.version_number,
                snapshot.title,
                (item.name for item in snapshot.lot_items),
            )
        conn.execute(
            insert(audit_events).values(
                company_id=company,
                event_id=audit_id,
                actor_id=actor_id,
                event_type="EIS_NOTICE_PROJECTION_RECORDED",
                object_type="eis_notice_projection_batch",
                object_id=batch_id,
                basis=basis,
                occurred_at=now,
            )
        )
    return _report(batch, False)


def _replay(
    conn: Connection,
    company: str,
    batch: dict[str, Any],
    receipt: EisNoticeVariantReceipt,
    prepared: EisNoticeProjectionBatch,
    transport: tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]],
) -> EisNoticeProjectionReport:
    decisions = [
        dict(row)
        for row in conn.execute(
            select(eis_notice_projection_decisions)
            .where(*_where(eis_notice_projection_decisions, company, batch_id=batch["batch_id"]))
            .order_by(
                eis_notice_projection_decisions.c.purchase_number,
                eis_notice_projection_decisions.c.version_number,
            )
        )
        .mappings()
        .all()
    ]
    basis = conn.execute(
        select(audit_events.c.basis).where(
            *_where(
                audit_events,
                company,
                event_id=batch["audit_event_id"],
                event_type="EIS_NOTICE_PROJECTION_RECORDED",
                object_type="eis_notice_projection_batch",
                object_id=batch["batch_id"],
            )
        )
    ).scalar_one_or_none()
    expected_batch = {key: value for key, value in batch.items() if key != "payload_sha256"}
    if (
        not isinstance(basis, dict)
        or _sha({k: v for k, v in basis.items() if k != "payload_sha256"})
        != batch["payload_sha256"]
        or basis.get("payload_sha256") != batch["payload_sha256"]
        or basis.get("batch_id") != batch["batch_id"]
        or basis.get("batch") != _json(expected_batch)
        or basis.get("decisions") != decisions
        or basis.get("receipt_sha256") != receipt.receipt_sha256
        or batch["parser_version"] != PARSER_VERSION
        or batch["archive_sha256s"] != list(prepared.archive_sha256s)
        or batch["occurrence_count"] != prepared.occurrence_count
        or batch["pair_count"] != len(prepared.candidates)
        or len(decisions) != len(prepared.candidates)
    ):
        raise ValueError("NOTICE_PROJECTION_REPLAY_CONFLICT")
    inputs = {
        (i["purchase_number"], i["version_number"]): {
            "variants": i["variants"],
            "origins": i["origins"],
        }
        for i in basis["inputs"]
    }
    for decision, candidate in zip(decisions, prepared.candidates, strict=True):
        pair = candidate.purchase_number, candidate.version_number
        snapshot = (
            _json(asdict(candidate.snapshot))
            if candidate.snapshot is not None and decision["status"] != "HOLD"
            else None
        )
        if (
            (decision["purchase_number"], decision["version_number"]) != pair
            or decision["snapshot"] != snapshot
            or decision["snapshot_sha256"] != (_sha(snapshot) if snapshot is not None else None)
            or decision["document_type"] != candidate.document_type
            or decision["xml_sha256"] != candidate.xml_sha256
            or decision["archive_sha256"] != prepared.archive_sha256s[candidate.archive_ordinal]
            or decision["member_filename"] != candidate.member_filename
            or decision["input_sha256"] != _sha(inputs[pair])
        ):
            raise ValueError("NOTICE_PROJECTION_DECISION_REPLAY_CONFLICT")
        if decision["status"] != "HOLD":
            canonical = (
                conn.execute(
                    select(eis_notice_versions).where(
                        *_where(
                            eis_notice_versions,
                            company,
                            purchase_number=pair[0],
                            version_number=pair[1],
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if (
                canonical is None
                or canonical["xml_sha256"] != decision["xml_sha256"]
                or canonical["document_type"] != decision["document_type"]
                or not _canonical_matches(dict(canonical), snapshot)
            ):
                raise ValueError("NOTICE_PROJECTION_CANONICAL_REPLAY_CONFLICT")
    _save_or_verify_transport(conn, transport, write=False)
    return _report(batch, True)


def _assert_complete_history(conn: Connection, company: str) -> None:
    if conn.scalar(select(_incomplete_receipt_clause(company))):
        raise ValueError("NOTICE_PROJECTION_GLOBAL_RECEIPT_INCOMPLETE")


def _canonical_matches(canonical: Mapping[str, Any], snapshot: Mapping[str, Any] | None) -> bool:
    return snapshot is not None and all(
        _json(canonical.get(key)) == value
        for key, value in snapshot.items()
        if key != "source_member"
    )
