"""Evidence-only immutable ledger for fully audited conflicting EIS notice variants."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Text, and_, cast, func, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection

from procurement.sources.eis_feed_archive import EVENT_TYPES, SUPPORTED_NOTICE_TYPES
from procurement.sources.eis_notice_conflicts import (
    EisNoticeConflictDiagnosis,
    EisNoticeOccurrence,
)
from procurement.sources.eis_rejected_evidence import EisRejectedEvidence
from procurement.storage.models import (
    audit_events,
    eis_notice_variant_origins,
    eis_notice_variant_receipts,
    eis_notice_variants,
)

if TYPE_CHECKING:
    from procurement.storage.repository import PostgresStorage

MAX_VARIANTS = 2000
MAX_ORIGINS = 2000
MAX_RECEIPTS = 20
MAX_READ_PAYLOAD_BYTES = 16 * 1024 * 1024
SCHEMA_VERSION: Literal["eis-notice-variant-ledger-v1"] = "eis-notice-variant-ledger-v1"
NOTICE_TYPES = frozenset(set(SUPPORTED_NOTICE_TYPES) - set(EVENT_TYPES))


class VariantModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EisNoticeVariantFacts(VariantModel):
    purchase_number: str
    version_number: int = Field(ge=1)
    document_type: str
    xml_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    non_timing_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_id: str | None
    published_raw: str | None = Field(default=None, max_length=64)
    start_raw: str | None = Field(default=None, max_length=64)
    published_at: datetime | None
    start_at: datetime | None

    @model_validator(mode="after")
    def _valid_facts(self) -> EisNoticeVariantFacts:
        if (
            re.fullmatch(r"[0-9]{19,23}", self.purchase_number) is None
            or self.document_type not in NOTICE_TYPES
            or (self.published_at is not None and self.published_at.utcoffset() is None)
            or (self.start_at is not None and self.start_at.utcoffset() is None)
            or _source_datetime(self.published_raw) != self.published_at
            or _source_datetime(self.start_raw) != self.start_at
            or (
                self.document_id is not None
                and (
                    re.fullmatch(r"[+-]?[0-9]{1,64}", self.document_id) is None
                    or not -(2**63) <= int(self.document_id) <= 2**63 - 1
                )
            )
        ):
            raise ValueError("NOTICE_VARIANT_FACTS_INVALID")
        return self


class EisNoticeVariantOrigin(VariantModel):
    receipt_id: str
    archive_ordinal: int = Field(ge=0, lt=20)
    member_filename: str = Field(min_length=4, max_length=255)
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    purchase_number: str
    version_number: int = Field(ge=1)
    document_type: str
    xml_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _valid_origin(self) -> EisNoticeVariantOrigin:
        if (
            "/" in self.member_filename
            or "\\" in self.member_filename
            or not self.member_filename.lower().endswith(".xml")
            or re.fullmatch(r"[0-9]{19,23}", self.purchase_number) is None
            or self.document_type not in NOTICE_TYPES
        ):
            raise ValueError("NOTICE_VARIANT_ORIGIN_INVALID")
        return self


class EisNoticeVariantStoreReport(VariantModel):
    receipt_id: str
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    inserted_variants: int = Field(ge=0, le=MAX_VARIANTS)
    inserted_origins: int = Field(ge=0, le=MAX_ORIGINS)
    replayed: bool
    evidence_status: Literal["EVIDENCE_ONLY"] = "EVIDENCE_ONLY"
    resolution: Literal["UNKNOWN"] = "UNKNOWN"
    canonical_admission: Literal["NOT_ENABLED"] = "NOT_ENABLED"
    audit_event_id: str


class EisNoticeVariantState(VariantModel):
    purchase_number: str
    version_number: int = Field(ge=1)
    status: Literal["COMPLETE", "NONE", "OVERFLOW"]
    ambiguity: bool | None
    resolution: Literal["UNKNOWN"] = "UNKNOWN"
    canonical_admission: Literal["NOT_ENABLED"] = "NOT_ENABLED"
    variants: tuple[EisNoticeVariantFacts, ...] = ()
    origins: tuple[EisNoticeVariantOrigin, ...] = ()

    @model_validator(mode="after")
    def _bounded_state(self) -> EisNoticeVariantState:
        complete = self.status == "COMPLETE"
        if complete != bool(self.variants) or (not complete and self.origins):
            raise ValueError("NOTICE_VARIANT_STATE_INVALID")
        if complete != (self.ambiguity is not None):
            raise ValueError("NOTICE_VARIANT_STATE_INVALID")
        return self


class EisNoticeVariantReceipt(VariantModel):
    company_id: str
    receipt_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    diagnosis_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    window_key: str
    response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prepared_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive_sha256s: tuple[str, ...] = Field(min_length=1, max_length=20)
    archive_count: int = Field(ge=1, le=20)
    occurrence_count: int = Field(ge=1, le=MAX_ORIGINS)
    variant_count: int = Field(ge=1, le=MAX_VARIANTS)
    evidence: EisRejectedEvidence
    retention_audit_event_id: str
    diagnosis_audit_event_id: str
    ledger_audit_event_id: str
    schema_version: Literal["eis-notice-variant-ledger-v1"] = SCHEMA_VERSION
    inventory_status: Literal["COMPLETE"] = "COMPLETE"
    canonical_admission: Literal["NOT_ENABLED"] = "NOT_ENABLED"
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    observed_at: datetime
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    variants: tuple[EisNoticeVariantFacts, ...]
    origins: tuple[EisNoticeVariantOrigin, ...]

    @model_validator(mode="after")
    def _complete_receipt(self) -> EisNoticeVariantReceipt:
        keys = {_facts_sort(item) for item in self.variants}
        if (
            self.archive_count != len(self.archive_sha256s)
            or self.occurrence_count != len(self.origins)
            or self.variant_count != len(self.variants)
            or any(origin.receipt_id != self.receipt_id for origin in self.origins)
            or any(origin.archive_ordinal >= self.archive_count for origin in self.origins)
            or any(
                origin.archive_sha256 != self.archive_sha256s[origin.archive_ordinal]
                for origin in self.origins
            )
            or any(
                (
                    origin.purchase_number,
                    origin.version_number,
                    origin.document_type,
                    origin.xml_sha256,
                )
                not in keys
                for origin in self.origins
            )
            or self.observed_at.utcoffset() is None
        ):
            raise ValueError("NOTICE_VARIANT_RECEIPT_INVALID")
        return self


def store_notice_variants(
    storage: PostgresStorage,
    company: str,
    evidence: EisRejectedEvidence,
    diagnosis: EisNoticeConflictDiagnosis,
    *,
    actor_id: str,
) -> EisNoticeVariantStoreReport:
    evidence = EisRejectedEvidence.model_validate(evidence.model_dump())
    diagnosis = EisNoticeConflictDiagnosis.model_validate(diagnosis.model_dump())
    variants, origins = _preflight(company, evidence, diagnosis, actor_id)
    manifest = str(evidence.manifest_sha256)
    receipt_id = str(
        uuid5(NAMESPACE_URL, f"{company}/eis-notice-variants/{manifest}/{diagnosis.sha256}")
    )
    retention_event = str(uuid5(NAMESPACE_URL, f"{company}/eis-rejected/{manifest}"))
    diagnosis_event = str(
        uuid5(NAMESPACE_URL, f"{company}/eis-conflict-diagnosis/{manifest}/{diagnosis.sha256}")
    )
    ledger_event = str(uuid5(NAMESPACE_URL, f"{company}/eis-notice-variant-ledger/{receipt_id}"))
    origins = tuple(origin.model_copy(update={"receipt_id": receipt_id}) for origin in origins)
    origins = tuple(sorted(origins, key=lambda item: (item.archive_ordinal, item.member_filename)))
    receipt_row = _receipt_row(
        receipt_id,
        evidence,
        diagnosis,
        len(variants),
        retention_event,
        diagnosis_event,
        ledger_event,
    )
    receipt_sha = _receipt_sha(receipt_row, variants, origins)
    receipt_row["receipt_sha256"] = receipt_sha
    basis = {
        "receipt": _jsonable(receipt_row),
        "variants": [item.model_dump(mode="json") for item in variants],
        "origins": [item.model_dump(mode="json") for item in origins],
        "evidence_status": "EVIDENCE_ONLY",
        "resolution": "UNKNOWN",
        "canonical_admission": "NOT_ENABLED",
    }
    with storage.transaction(company) as conn:
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant, 0))"),
            {"tenant": company},
        )
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": company + "/eis-notice-variants"},
        )
        _verify_prerequisite_audits(
            conn, company, evidence, diagnosis, retention_event, diagnosis_event
        )
        existing_receipt = (
            conn.execute(
                select(eis_notice_variant_receipts).where(
                    eis_notice_variant_receipts.c.company_id == company,
                    eis_notice_variant_receipts.c.receipt_id == receipt_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if existing_receipt is not None:
            _verify_replay(
                conn,
                company,
                receipt_id,
                receipt_row,
                variants,
                origins,
                ledger_event,
                basis,
            )
            return EisNoticeVariantStoreReport(
                receipt_id=receipt_id,
                receipt_sha256=receipt_sha,
                inserted_variants=0,
                inserted_origins=0,
                replayed=True,
                audit_event_id=ledger_event,
            )
        inserted_variants = 0
        for facts in variants:
            payload = facts.model_dump(mode="json")
            facts_sha = _sha(payload)
            result = conn.execute(
                insert(eis_notice_variants)
                .values(
                    company_id=company,
                    facts=payload,
                    facts_sha256=facts_sha,
                    **_variant_key(facts),
                )
                .on_conflict_do_nothing()
                .returning(eis_notice_variants.c.xml_sha256)
            ).scalar_one_or_none()
            inserted_variants += int(result is not None)
            saved_facts, saved_sha = conn.execute(
                select(eis_notice_variants.c.facts, eis_notice_variants.c.facts_sha256).where(
                    _variant_where(company, facts)
                )
            ).one()
            if saved_facts != payload or saved_sha != facts_sha:
                raise ValueError("NOTICE_VARIANT_FACT_CONFLICT")
        conn.execute(
            insert(eis_notice_variant_receipts)
            .values(company_id=company, **receipt_row)
            .on_conflict_do_nothing()
        )
        inserted_origins = 0
        for origin in origins:
            result = conn.execute(
                insert(eis_notice_variant_origins)
                .values(company_id=company, **origin.model_dump(mode="json"))
                .on_conflict_do_nothing()
                .returning(eis_notice_variant_origins.c.member_filename)
            ).scalar_one_or_none()
            inserted_origins += int(result is not None)
        conn.execute(
            insert(audit_events)
            .values(
                company_id=company,
                event_id=ledger_event,
                actor_id=actor_id,
                event_type="EIS_NOTICE_VARIANT_LEDGER_RECORDED",
                object_type="eis_notice_variant_receipt",
                object_id=receipt_id,
                basis=basis,
                occurred_at=evidence.observed_at.astimezone(UTC),
            )
            .on_conflict_do_nothing()
        )
        _verify_replay(
            conn,
            company,
            receipt_id,
            receipt_row,
            variants,
            origins,
            ledger_event,
            basis,
        )
    return EisNoticeVariantStoreReport(
        receipt_id=receipt_id,
        receipt_sha256=receipt_sha,
        inserted_variants=inserted_variants,
        inserted_origins=inserted_origins,
        replayed=False,
        audit_event_id=ledger_event,
    )


def read_notice_variant_state(
    storage: PostgresStorage, company: str, purchase_number: str, version_number: int
) -> EisNoticeVariantState:
    if version_number < 1:
        raise ValueError("NOTICE_VARIANT_KEY_INVALID")
    with storage.transaction(company, consistent_read=True) as conn:
        rows = (
            conn.execute(
                select(eis_notice_variants)
                .where(
                    eis_notice_variants.c.company_id == company,
                    eis_notice_variants.c.purchase_number == purchase_number,
                    eis_notice_variants.c.version_number == version_number,
                )
                .order_by(eis_notice_variants.c.document_type, eis_notice_variants.c.xml_sha256)
                .limit(MAX_VARIANTS + 1)
            )
            .mappings()
            .all()
        )
        if not rows:
            return EisNoticeVariantState(
                purchase_number=purchase_number,
                version_number=version_number,
                status="NONE",
                ambiguity=None,
            )
        if len(rows) > MAX_VARIANTS:
            return EisNoticeVariantState(
                purchase_number=purchase_number,
                version_number=version_number,
                status="OVERFLOW",
                ambiguity=None,
            )
        variants = tuple(_facts_from_row(dict(row)) for row in rows)
        origins = _read_origins(conn, company, variants)
        if len(origins) > MAX_ORIGINS:
            return EisNoticeVariantState(
                purchase_number=purchase_number,
                version_number=version_number,
                status="OVERFLOW",
                ambiguity=None,
            )
        ambiguity = len({(item.document_type, item.xml_sha256) for item in variants}) > 1
        if {_facts_sort(item) for item in variants} != {
            (
                item.purchase_number,
                item.version_number,
                item.document_type,
                item.xml_sha256,
            )
            for item in origins
        }:
            raise ValueError("NOTICE_VARIANT_ORIGIN_SET_INCOMPLETE")
        if not _verify_state_source_bindings(conn, company, origins):
            return EisNoticeVariantState(
                purchase_number=purchase_number,
                version_number=version_number,
                status="OVERFLOW",
                ambiguity=None,
            )
        return EisNoticeVariantState(
            purchase_number=purchase_number,
            version_number=version_number,
            status="COMPLETE",
            ambiguity=ambiguity,
            variants=variants,
            origins=origins,
        )


def read_notice_variant_receipt(
    storage: PostgresStorage, company: str, receipt_id: str
) -> EisNoticeVariantReceipt | None:
    with storage.transaction(company, consistent_read=True) as conn:
        return read_notice_variant_receipt_connection(conn, company, receipt_id)


def read_notice_variant_receipt_connection(
    conn: Connection, company: str, receipt_id: str
) -> EisNoticeVariantReceipt | None:
    """Verify the full receipt and prerequisite audits in the caller's transaction."""
    receipt_count, payload_bytes = conn.execute(
        select(
            func.count(),
            func.coalesce(
                func.sum(func.octet_length(cast(eis_notice_variant_receipts.c.evidence, Text))),
                0,
            ),
        ).where(
            eis_notice_variant_receipts.c.company_id == company,
            eis_notice_variant_receipts.c.receipt_id == receipt_id,
        )
    ).one()
    if receipt_count == 0:
        return None
    if receipt_count != 1 or payload_bytes > MAX_READ_PAYLOAD_BYTES:
        raise ValueError("NOTICE_VARIANT_RECEIPT_READ_OVERFLOW")
    row = (
        conn.execute(
            select(eis_notice_variant_receipts).where(
                eis_notice_variant_receipts.c.company_id == company,
                eis_notice_variant_receipts.c.receipt_id == receipt_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ValueError("NOTICE_VARIANT_RECEIPT_MISSING_AFTER_PREFLIGHT")
    origin_rows = (
        conn.execute(
            select(eis_notice_variant_origins)
            .where(
                eis_notice_variant_origins.c.company_id == company,
                eis_notice_variant_origins.c.receipt_id == receipt_id,
            )
            .order_by(
                eis_notice_variant_origins.c.archive_ordinal,
                eis_notice_variant_origins.c.member_filename,
            )
            .limit(MAX_ORIGINS + 1)
        )
        .mappings()
        .all()
    )
    if len(origin_rows) > MAX_ORIGINS:
        raise ValueError("NOTICE_VARIANT_RECEIPT_READ_OVERFLOW")
    origins = tuple(_origin_from_row(dict(item)) for item in origin_rows)
    variants = _variants_for_origins(conn, company, origins)
    if len(variants) > MAX_VARIANTS:
        raise ValueError("NOTICE_VARIANT_RECEIPT_READ_OVERFLOW")
    receipt = EisNoticeVariantReceipt.model_validate(
        {**dict(row), "variants": variants, "origins": origins}
    )
    if receipt.receipt_sha256 != _receipt_sha(
        _receipt_payload_from_model(receipt), receipt.variants, receipt.origins
    ):
        raise ValueError("NOTICE_VARIANT_RECEIPT_SHA_INVALID")
    _verify_receipt_audits(conn, receipt, prior_bytes=payload_bytes)
    return receipt


def _preflight(
    company: str,
    evidence: EisRejectedEvidence,
    diagnosis: EisNoticeConflictDiagnosis,
    actor_id: str,
) -> tuple[tuple[EisNoticeVariantFacts, ...], tuple[EisNoticeVariantOrigin, ...]]:
    if (
        not company
        or not actor_id.strip()
        or evidence.company_id != company
        or evidence.status != "RETAINED"
        or evidence.manifest_sha256 is None
        or evidence.prepared_response_sha256 is None
        or diagnosis.archive_sha256s != evidence.archive_sha256s
        or diagnosis.occurrence_count > MAX_ORIGINS
    ):
        raise ValueError("NOTICE_VARIANT_LEDGER_INVALID")
    variants: dict[tuple[str, int, str, str], EisNoticeVariantFacts] = {}
    origins = []
    for item in diagnosis.occurrences:
        if (
            item.purchase_number is None
            or item.version_number is None
            or item.document_type is None
        ):
            raise ValueError("NOTICE_VARIANT_OCCURRENCE_INCOMPLETE")
        if item.document_type not in NOTICE_TYPES:
            raise ValueError("NOTICE_VARIANT_DOCUMENT_TYPE_INVALID")
        facts = _facts(item)
        key = (facts.purchase_number, facts.version_number, facts.document_type, facts.xml_sha256)
        if key in variants and variants[key] != facts:
            raise ValueError("NOTICE_VARIANT_FACT_CONFLICT")
        variants[key] = facts
        origins.append(_origin("pending", item))
    if not variants or len(variants) > MAX_VARIANTS:
        raise ValueError("NOTICE_VARIANT_COUNT_INVALID")
    return tuple(sorted(variants.values(), key=_facts_sort)), tuple(origins)


def _facts(item: EisNoticeOccurrence) -> EisNoticeVariantFacts:
    return EisNoticeVariantFacts.model_validate(
        item.model_dump(exclude={"archive_ordinal", "archive_sha256", "member_filename"})
    )


def _origin(receipt_id: str, item: EisNoticeOccurrence) -> EisNoticeVariantOrigin:
    return EisNoticeVariantOrigin(
        receipt_id=receipt_id,
        archive_ordinal=item.archive_ordinal,
        member_filename=item.member_filename,
        archive_sha256=item.archive_sha256,
        purchase_number=str(item.purchase_number),
        version_number=int(item.version_number or 0),
        document_type=str(item.document_type),
        xml_sha256=item.xml_sha256,
    )


def _facts_sort(item: EisNoticeVariantFacts) -> tuple[str, int, str, str]:
    return item.purchase_number, item.version_number, item.document_type, item.xml_sha256


def _receipt_row(
    receipt_id: str,
    evidence: EisRejectedEvidence,
    diagnosis: EisNoticeConflictDiagnosis,
    variant_count: int,
    retention: str,
    diag: str,
    ledger: str,
) -> dict[str, Any]:
    return {
        "receipt_id": receipt_id,
        "manifest_sha256": evidence.manifest_sha256,
        "diagnosis_sha256": diagnosis.sha256,
        "window_key": evidence.window_key,
        "response_sha256": evidence.response_sha256,
        "prepared_response_sha256": evidence.prepared_response_sha256,
        "archive_sha256s": list(diagnosis.archive_sha256s),
        "archive_count": diagnosis.archive_count,
        "occurrence_count": diagnosis.occurrence_count,
        "variant_count": variant_count,
        "evidence": evidence.model_dump(mode="json"),
        "retention_audit_event_id": retention,
        "diagnosis_audit_event_id": diag,
        "ledger_audit_event_id": ledger,
        "schema_version": SCHEMA_VERSION,
        "inventory_status": "COMPLETE",
        "canonical_admission": "NOT_ENABLED",
        "coverage": "UNKNOWN",
        "observed_at": evidence.observed_at.astimezone(UTC),
    }


def _receipt_sha(
    row: Mapping[str, Any],
    variants: Sequence[EisNoticeVariantFacts],
    origins: Sequence[EisNoticeVariantOrigin],
) -> str:
    return _sha(
        _jsonable(
            {
                "receipt": row,
                "variants": [item.model_dump(mode="json") for item in variants],
                "origins": [item.model_dump(mode="json") for item in origins],
            }
        )
    )


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _source_datetime(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    try:
        value = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("NOTICE_VARIANT_SOURCE_TIME_INVALID") from error
    return value if value.utcoffset() is not None else None


def _jsonable(value: object) -> Any:
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump())
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _variant_key(facts: EisNoticeVariantFacts) -> dict[str, object]:
    return {
        "purchase_number": facts.purchase_number,
        "version_number": facts.version_number,
        "document_type": facts.document_type,
        "xml_sha256": facts.xml_sha256,
    }


def _variant_where(company: str, facts: EisNoticeVariantFacts) -> Any:
    return and_(
        eis_notice_variants.c.company_id == company,
        *[
            getattr(eis_notice_variants.c, key) == value
            for key, value in _variant_key(facts).items()
        ],
    )


def _verify_prerequisite_audits(
    conn: Connection,
    company: str,
    evidence: EisRejectedEvidence,
    diagnosis: EisNoticeConflictDiagnosis,
    retained_id: str,
    diagnosis_id: str,
) -> None:
    retained = conn.execute(
        select(audit_events.c.basis).where(
            audit_events.c.company_id == company,
            audit_events.c.event_id == retained_id,
            audit_events.c.event_type == "EIS_REJECTED_WINDOW_EVIDENCE",
            audit_events.c.object_id == evidence.window_key,
        )
    ).scalar_one_or_none()
    expected_retained = {"evidence": evidence.model_dump(mode="json"), "coverage": "UNKNOWN"}
    if retained != expected_retained:
        raise ValueError("NOTICE_VARIANT_RETENTION_UNAUDITED")
    diagnosed = conn.execute(
        select(audit_events.c.basis).where(
            audit_events.c.company_id == company,
            audit_events.c.event_id == diagnosis_id,
            audit_events.c.event_type == "EIS_NOTICE_CONFLICT_DIAGNOSIS",
            audit_events.c.object_id == evidence.window_key,
        )
    ).scalar_one_or_none()
    expected_diagnosis = {
        "evidence": evidence.model_dump(mode="json"),
        "diagnosis": diagnosis.model_dump(mode="json"),
        "coverage": "UNKNOWN",
        "canonical_admission": "REJECTED",
    }
    if diagnosed != expected_diagnosis:
        raise ValueError("NOTICE_VARIANT_DIAGNOSIS_UNAUDITED")


def _verify_replay(
    conn: Connection,
    company: str,
    receipt_id: str,
    row: Mapping[str, Any],
    variants: Sequence[EisNoticeVariantFacts],
    origins: Sequence[EisNoticeVariantOrigin],
    ledger_id: str,
    basis: Mapping[str, Any],
) -> None:
    saved = (
        conn.execute(
            select(eis_notice_variant_receipts).where(
                eis_notice_variant_receipts.c.company_id == company,
                eis_notice_variant_receipts.c.receipt_id == receipt_id,
            )
        )
        .mappings()
        .one()
    )
    if dict(saved) != {"company_id": company, **row}:
        raise ValueError("NOTICE_VARIANT_RECEIPT_REPLAY_CONFLICT")
    for facts in variants:
        saved_facts, saved_sha = conn.execute(
            select(eis_notice_variants.c.facts, eis_notice_variants.c.facts_sha256).where(
                _variant_where(company, facts)
            )
        ).one()
        payload = facts.model_dump(mode="json")
        if saved_facts != payload or saved_sha != _sha(payload):
            raise ValueError("NOTICE_VARIANT_FACT_REPLAY_CONFLICT")
    saved_origins = (
        conn.execute(
            select(eis_notice_variant_origins)
            .where(
                eis_notice_variant_origins.c.company_id == company,
                eis_notice_variant_origins.c.receipt_id == receipt_id,
            )
            .order_by(
                eis_notice_variant_origins.c.archive_ordinal,
                eis_notice_variant_origins.c.member_filename,
            )
            .limit(MAX_ORIGINS + 1)
        )
        .mappings()
        .all()
    )
    if len(saved_origins) > MAX_ORIGINS:
        raise ValueError("NOTICE_VARIANT_ORIGIN_REPLAY_OVERFLOW")
    expected_origins = [{"company_id": company, **item.model_dump(mode="json")} for item in origins]
    if [dict(item) for item in saved_origins] != expected_origins:
        raise ValueError("NOTICE_VARIANT_ORIGIN_REPLAY_CONFLICT")
    saved_basis = conn.execute(
        select(audit_events.c.basis).where(
            audit_events.c.company_id == company,
            audit_events.c.event_id == ledger_id,
            audit_events.c.event_type == "EIS_NOTICE_VARIANT_LEDGER_RECORDED",
            audit_events.c.object_type == "eis_notice_variant_receipt",
            audit_events.c.object_id == receipt_id,
        )
    ).scalar_one()
    if saved_basis != basis:
        raise ValueError("NOTICE_VARIANT_AUDIT_REPLAY_CONFLICT")


def _read_origins(
    conn: Connection, company: str, variants: Sequence[EisNoticeVariantFacts]
) -> tuple[EisNoticeVariantOrigin, ...]:
    keys = {_facts_sort(item) for item in variants}
    rows = (
        conn.execute(
            select(eis_notice_variant_origins)
            .where(
                eis_notice_variant_origins.c.company_id == company,
                tuple_(
                    eis_notice_variant_origins.c.purchase_number,
                    eis_notice_variant_origins.c.version_number,
                    eis_notice_variant_origins.c.document_type,
                    eis_notice_variant_origins.c.xml_sha256,
                ).in_(keys),
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
    return tuple(
        _origin_from_row(dict(row))
        for row in rows
        if (
            row["purchase_number"],
            row["version_number"],
            row["document_type"],
            row["xml_sha256"],
        )
        in keys
    )


def _variants_for_origins(
    conn: Connection, company: str, origins: Sequence[EisNoticeVariantOrigin]
) -> tuple[EisNoticeVariantFacts, ...]:
    keys = {
        (item.purchase_number, item.version_number, item.document_type, item.xml_sha256)
        for item in origins
    }
    rows = (
        conn.execute(
            select(eis_notice_variants)
            .where(
                eis_notice_variants.c.company_id == company,
                tuple_(
                    eis_notice_variants.c.purchase_number,
                    eis_notice_variants.c.version_number,
                    eis_notice_variants.c.document_type,
                    eis_notice_variants.c.xml_sha256,
                ).in_(keys),
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
    return tuple(
        _facts_from_row(dict(row))
        for row in rows
        if (
            row["purchase_number"],
            row["version_number"],
            row["document_type"],
            row["xml_sha256"],
        )
        in keys
    )


def _origin_from_row(row: Mapping[str, Any]) -> EisNoticeVariantOrigin:
    return EisNoticeVariantOrigin.model_validate(
        {key: value for key, value in dict(row).items() if key != "company_id"}
    )


def _facts_from_row(row: Mapping[str, Any]) -> EisNoticeVariantFacts:
    facts = EisNoticeVariantFacts.model_validate(row["facts"])
    payload = facts.model_dump(mode="json")
    if (
        row["purchase_number"] != facts.purchase_number
        or row["version_number"] != facts.version_number
        or row["document_type"] != facts.document_type
        or row["xml_sha256"] != facts.xml_sha256
        or row["facts_sha256"] != _sha(payload)
    ):
        raise ValueError("NOTICE_VARIANT_FACT_ROW_INVALID")
    return facts


def _verify_receipt_audits(
    conn: Connection, receipt: EisNoticeVariantReceipt, *, prior_bytes: int = 0
) -> None:
    audit_ids = (
        receipt.retention_audit_event_id,
        receipt.diagnosis_audit_event_id,
        receipt.ledger_audit_event_id,
    )
    audit_count, audit_bytes = conn.execute(
        select(
            func.count(),
            func.coalesce(func.sum(func.octet_length(cast(audit_events.c.basis, Text))), 0),
        ).where(
            audit_events.c.company_id == receipt.company_id,
            audit_events.c.event_id.in_(audit_ids),
        )
    ).one()
    if audit_count != 3 or prior_bytes + audit_bytes > MAX_READ_PAYLOAD_BYTES:
        raise ValueError("NOTICE_VARIANT_RECEIPT_READ_OVERFLOW")
    audit_rows = conn.execute(
        select(
            audit_events.c.event_id,
            audit_events.c.event_type,
            audit_events.c.object_type,
            audit_events.c.object_id,
            audit_events.c.basis,
        ).where(
            audit_events.c.company_id == receipt.company_id,
            audit_events.c.event_id.in_(audit_ids),
        )
    ).all()
    rows = {item[0]: (item[1], item[2], item[3], item[4]) for item in audit_rows}
    _validate_receipt_audits(receipt, rows)


def _validate_receipt_audits(
    receipt: EisNoticeVariantReceipt,
    rows: Mapping[str, tuple[str, str, str, Mapping[str, Any]]],
) -> None:
    retention = rows.get(receipt.retention_audit_event_id)
    diagnosis = rows.get(receipt.diagnosis_audit_event_id)
    ledger_row = rows.get(receipt.ledger_audit_event_id)
    expected_retention = {
        "evidence": receipt.evidence.model_dump(mode="json"),
        "coverage": "UNKNOWN",
    }
    if retention != (
        "EIS_REJECTED_WINDOW_EVIDENCE",
        "eis_sync_target",
        receipt.window_key,
        expected_retention,
    ):
        raise ValueError("NOTICE_VARIANT_RETENTION_AUDIT_INVALID")
    if (
        diagnosis is None
        or diagnosis[0] != "EIS_NOTICE_CONFLICT_DIAGNOSIS"
        or diagnosis[1] != "eis_sync_target"
        or diagnosis[2] != receipt.window_key
        or diagnosis[3].get("evidence") != expected_retention["evidence"]
        or diagnosis[3].get("diagnosis", {}).get("sha256") != receipt.diagnosis_sha256
    ):
        raise ValueError("NOTICE_VARIANT_DIAGNOSIS_AUDIT_INVALID")
    basis = {
        "receipt": _jsonable(
            _receipt_payload_from_model(receipt) | {"receipt_sha256": receipt.receipt_sha256}
        ),
        "variants": [item.model_dump(mode="json") for item in receipt.variants],
        "origins": [item.model_dump(mode="json") for item in receipt.origins],
        "evidence_status": "EVIDENCE_ONLY",
        "resolution": "UNKNOWN",
        "canonical_admission": "NOT_ENABLED",
    }
    if ledger_row != (
        "EIS_NOTICE_VARIANT_LEDGER_RECORDED",
        "eis_notice_variant_receipt",
        receipt.receipt_id,
        basis,
    ):
        raise ValueError("NOTICE_VARIANT_LEDGER_AUDIT_INVALID")


def _verify_state_source_bindings(
    conn: Connection,
    company: str,
    origins: Sequence[EisNoticeVariantOrigin],
) -> bool:
    receipt_ids = {item.receipt_id for item in origins}
    receipt_count, payload_bytes = conn.execute(
        select(
            func.count(),
            func.coalesce(
                func.sum(func.octet_length(cast(eis_notice_variant_receipts.c.evidence, Text))),
                0,
            ),
        ).where(
            eis_notice_variant_receipts.c.company_id == company,
            eis_notice_variant_receipts.c.receipt_id.in_(receipt_ids),
        )
    ).one()
    if (
        receipt_count != len(receipt_ids)
        or receipt_count > MAX_RECEIPTS
        or payload_bytes > MAX_READ_PAYLOAD_BYTES
    ):
        return False
    rows = (
        conn.execute(
            select(eis_notice_variant_receipts).where(
                eis_notice_variant_receipts.c.company_id == company,
                eis_notice_variant_receipts.c.receipt_id.in_(receipt_ids),
            )
        )
        .mappings()
        .all()
    )
    if len(rows) != len(receipt_ids):
        raise ValueError("NOTICE_VARIANT_SOURCE_RECEIPT_MISSING")
    full_origin_rows = (
        conn.execute(
            select(eis_notice_variant_origins)
            .where(
                eis_notice_variant_origins.c.company_id == company,
                eis_notice_variant_origins.c.receipt_id.in_(receipt_ids),
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
    if len(full_origin_rows) > MAX_ORIGINS:
        return False
    full_origins = tuple(_origin_from_row(dict(row)) for row in full_origin_rows)
    full_variants = _variants_for_origins(conn, company, full_origins)
    if len(full_variants) > MAX_VARIANTS:
        return False
    audit_ids = {
        row[key]
        for row in rows
        for key in (
            "retention_audit_event_id",
            "diagnosis_audit_event_id",
            "ledger_audit_event_id",
        )
    }
    audit_count, audit_bytes = conn.execute(
        select(
            func.count(),
            func.coalesce(func.sum(func.octet_length(cast(audit_events.c.basis, Text))), 0),
        ).where(
            audit_events.c.company_id == company,
            audit_events.c.event_id.in_(audit_ids),
        )
    ).one()
    if audit_count != len(audit_ids) or payload_bytes + audit_bytes > MAX_READ_PAYLOAD_BYTES:
        return False
    audit_rows = conn.execute(
        select(
            audit_events.c.event_id,
            audit_events.c.event_type,
            audit_events.c.object_type,
            audit_events.c.object_id,
            audit_events.c.basis,
        ).where(
            audit_events.c.company_id == company,
            audit_events.c.event_id.in_(audit_ids),
        )
    ).all()
    audits = {item[0]: (item[1], item[2], item[3], item[4]) for item in audit_rows}
    for row in rows:
        receipt_id = row["receipt_id"]
        receipt_origins = tuple(item for item in full_origins if item.receipt_id == receipt_id)
        keys = {
            (item.purchase_number, item.version_number, item.document_type, item.xml_sha256)
            for item in receipt_origins
        }
        receipt_variants = tuple(item for item in full_variants if _facts_sort(item) in keys)
        receipt = EisNoticeVariantReceipt.model_validate(
            {**dict(row), "variants": receipt_variants, "origins": receipt_origins}
        )
        if receipt.receipt_sha256 != _receipt_sha(
            _receipt_payload_from_model(receipt), receipt.variants, receipt.origins
        ):
            raise ValueError("NOTICE_VARIANT_RECEIPT_SHA_INVALID")
        _validate_receipt_audits(receipt, audits)
    return True


def _receipt_payload_from_model(receipt: EisNoticeVariantReceipt) -> dict[str, Any]:
    payload = receipt.model_dump(
        mode="json", exclude={"company_id", "variants", "origins", "receipt_sha256"}
    )
    # The database column is normalized to UTC while nested evidence retains its
    # exact source timezone representation from the audited JSON.
    payload["observed_at"] = receipt.observed_at.astimezone(UTC).isoformat()
    return payload
