"""Immutable no-dispatch RFQ drafts bound to exact reviewed manufacturer evidence."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, insert, select, text
from sqlalchemy.engine import Connection

from procurement.domain.manufacturer_directory import ManufacturerDirectory
from procurement.domain.manufacturer_review import ReviewStatus
from procurement.domain.manufacturer_rfq import (
    ManualProvenance,
    ManualTextFact,
    ManufacturerRfqCommand,
    ManufacturerRfqDraft,
    RfqRegistrySnapshot,
    canonical_bytes,
    canonical_quantity,
    canonical_sha256,
    render_rfq_text,
)
from procurement.storage.manufacturer_directory import build_manufacturer_directory
from procurement.storage.models import audit_events
from procurement.storage.models import manufacturer_rfq_drafts as drafts
from procurement.storage.repository import PostgresStorage


class ManufacturerRfqConflict(ValueError):
    pass


class ManufacturerRfqNotFound(LookupError):
    pass


class ManufacturerRfqSourceMismatch(ValueError):
    pass


class ManufacturerRfqIneligible(ValueError):
    pass


class SavedManufacturerRfqDraft(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    draft: ManufacturerRfqDraft
    current_status: ReviewStatus
    created: bool = Field(strict=True)


def _lock(conn: Connection, company_id: str, command_id: str) -> None:
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": company_id + "/manufacturer-rfq/" + command_id},
    )


def _audit(conn, company_id, actor_id, draft_id, draft_sha, at):
    conn.execute(
        insert(audit_events).values(
            event_id=str(uuid.uuid4()), company_id=company_id, actor_id=actor_id,
            event_type="manufacturer_rfq.draft_created", object_type="MANUFACTURER_RFQ",
            object_id=draft_id, object_version=1,
            basis={"draft_sha256": draft_sha, "status": "DRAFT_NO_DISPATCH",
                   "external_action_performed": False}, occurred_at=at,
        )
    )


def _validated_row(row) -> ManufacturerRfqDraft:
    try:
        draft = ManufacturerRfqDraft.model_validate(row["draft"])
    except ValueError as error:
        raise ManufacturerRfqSourceMismatch("MANUFACTURER_RFQ_STORED_INVALID") from error
    canonical = canonical_bytes(draft.model_dump(mode="json", exclude={"draft_sha256"}))
    encoded = draft.text.encode()
    command = ManufacturerRfqCommand(
        command_id=draft.command_id, run_id=draft.run_id,
        record_id=draft.registry_snapshot.record_id, proposal_id=draft.proposal_id,
        decision_id=draft.decision_id, quantity=draft.quantity_input.value,
        unit_raw=draft.unit.value, quantity_basis_raw=draft.quantity_basis.value,
        requirements=tuple(item.value for item in draft.requirements),
        delivery_address_raw=draft.delivery_address.value,
        desired_delivery_raw=draft.desired_delivery.value,
        reply_due_at=draft.reply_due_at,
    )
    facts = (
        (draft.quantity_input, "quantity"),
        (draft.unit, "unit_raw"),
        (draft.quantity_basis, "quantity_basis_raw"),
        *tuple(
            (fact, f"requirements[{index}]")
            for index, fact in enumerate(draft.requirements)
        ),
        (draft.delivery_address, "delivery_address_raw"),
        (draft.desired_delivery, "desired_delivery_raw"),
    )
    provenance_valid = all(
        fact.provenance.document_id == draft.draft_id
        and fact.provenance.locator == locator
        and fact.provenance.extractor == "manual"
        and fact.provenance.actor_id == draft.created_by
        and fact.provenance.recorded_at == draft.created_at
        for fact, locator in facts
    ) and (
        draft.reply_due_provenance.document_id == draft.draft_id
        and draft.reply_due_provenance.locator == "reply_due_at"
        and draft.reply_due_provenance.extractor == "manual"
        and draft.reply_due_provenance.actor_id == draft.created_by
        and draft.reply_due_provenance.recorded_at == draft.created_at
    )
    if (
        bytes(row["draft_canonical"]) != canonical
        or hashlib.sha256(canonical).hexdigest() != row["draft_sha256"]
        or bytes(row["text_content"]) != encoded
        or hashlib.sha256(encoded).hexdigest() != row["text_sha256"]
        or draft.draft_id != row["draft_id"]
        or draft.command_id != row["command_id"]
        or draft.run_id != row["run_id"]
        or draft.registry_snapshot.record_id != row["record_id"]
        or draft.proposal_id != row["proposal_id"]
        or draft.decision_id != row["decision_id"]
        or draft.created_by != row["created_by"]
        or draft.created_at != row["created_at"]
        or draft.manual_inputs_sha256
        != canonical_sha256(command.model_dump(mode="json"))
        or draft.text
        != render_rfq_text(draft.manufacturer_identity, draft.registry_snapshot, command)
        or not provenance_valid
    ):
        raise ManufacturerRfqSourceMismatch("MANUFACTURER_RFQ_STORED_INVALID")
    return draft


def _selected(directory: ManufacturerDirectory, command: ManufacturerRfqCommand):
    record = next((item for item in directory.records if item.record_id == command.record_id), None)
    if directory.coverage != "COMPLETE" or record is None or record.status is not ReviewStatus.PASS:
        raise ManufacturerRfqIneligible("MANUFACTURER_RFQ_RECORD_NOT_VERIFIED")
    evidence = next(
        (
            item for item in record.review_evidence
            if item.proposal_id == command.proposal_id and item.decision_id == command.decision_id
        ),
        None,
    )
    if evidence is None or evidence.current_status is not ReviewStatus.PASS:
        raise ManufacturerRfqIneligible("MANUFACTURER_RFQ_REVIEW_NOT_CURRENT")
    group = next(
        (
            item for item in directory.groups
            if command.record_id in item.record_ids
            and command.proposal_id in item.proposal_ids
            and evidence.decision_sha256 in item.decision_sha256s
        ),
        None,
    )
    if group is None or group.status != "PASS":
        raise ManufacturerRfqIneligible("MANUFACTURER_RFQ_GROUP_NOT_VERIFIED")
    return record, evidence, group


def _current_status(
    storage: PostgresStorage, company_id: str, draft: ManufacturerRfqDraft, at: datetime
) -> ReviewStatus:
    if at >= draft.reply_due_at:
        return ReviewStatus.FAIL
    try:
        directory = build_manufacturer_directory(
            storage, company_id, draft.run_id, evaluated_at=at
        )
        command = ManufacturerRfqCommand(
            command_id=draft.command_id, run_id=draft.run_id,
            record_id=draft.registry_snapshot.record_id, proposal_id=draft.proposal_id,
            decision_id=draft.decision_id, quantity=draft.quantity_input.value,
            unit_raw=draft.unit.value, quantity_basis_raw=draft.quantity_basis.value,
            requirements=tuple(item.value for item in draft.requirements),
            delivery_address_raw=draft.delivery_address.value,
            desired_delivery_raw=draft.desired_delivery.value,
            reply_due_at=draft.reply_due_at,
        )
        if directory.coverage != "COMPLETE":
            return ReviewStatus.UNKNOWN
        record = next(
            (item for item in directory.records if item.record_id == command.record_id), None
        )
        if record is None:
            return ReviewStatus.UNKNOWN
        if record.status is ReviewStatus.FAIL:
            return ReviewStatus.FAIL
        if record.status is ReviewStatus.UNKNOWN:
            return ReviewStatus.UNKNOWN
        evidence = next(
            (
                item
                for item in record.review_evidence
                if item.proposal_id == command.proposal_id
                and item.decision_id == command.decision_id
            ),
            None,
        )
        if evidence is None:
            return ReviewStatus.UNKNOWN
        if evidence.current_status is ReviewStatus.FAIL:
            return ReviewStatus.FAIL
        if evidence.current_status is ReviewStatus.UNKNOWN:
            return ReviewStatus.UNKNOWN
        group = next(
            (
                item
                for item in directory.groups
                if command.record_id in item.record_ids
                and command.proposal_id in item.proposal_ids
                and evidence.decision_sha256 in item.decision_sha256s
            ),
            None,
        )
        if group is None or group.status == "UNKNOWN":
            return ReviewStatus.UNKNOWN
        if (
            directory.response_sha256 != draft.source_response_sha256
            or evidence.dossier_sha256 != draft.dossier_sha256
            or evidence.proposal_sha256 != draft.proposal_sha256
            or evidence.decision_sha256 != draft.decision_sha256
            or evidence.identity != draft.manufacturer_identity
            or record.registry_number != draft.registry_snapshot.registry_number
            or record.product_name != draft.registry_snapshot.product_name
            or record.source_manufacturer_name
            != draft.registry_snapshot.source_manufacturer_name
            or record.record_url != draft.registry_snapshot.record_url
            or (
                record.document_expires_on.isoformat()
                if record.document_expires_on is not None
                else None
            )
            != draft.registry_snapshot.document_expires_on
        ):
            return ReviewStatus.UNKNOWN
        return ReviewStatus.PASS
    except (ValueError, LookupError):
        return ReviewStatus.UNKNOWN


def _manual(draft_id: str, locator: str, value: str, actor: str, at: datetime):
    return ManualTextFact(
        value=value,
        provenance=ManualProvenance(
            document_id=draft_id, locator=locator, actor_id=actor, recorded_at=at
        ),
    )


def _build_draft(command, actor_id, at, directory, record, evidence):
    draft_id = str(uuid.uuid4())
    snapshot = RfqRegistrySnapshot(
        record_id=record.record_id, registry_number=record.registry_number,
        product_name=record.product_name,
        source_manufacturer_name=record.source_manufacturer_name,
        record_url=record.record_url,
        document_expires_on=(record.document_expires_on.isoformat()
                             if record.document_expires_on else None),
    )
    identity = evidence.identity
    text_content = render_rfq_text(identity, snapshot, command)
    manual_sha = canonical_sha256(command.model_dump(mode="json"))
    payload = {
        "schema_version": "manufacturer-rfq-draft-v1", "draft_id": draft_id,
        "command_id": command.command_id, "status": "DRAFT_NO_DISPATCH",
        "run_id": command.run_id, "proposal_id": command.proposal_id,
        "decision_id": command.decision_id,
        "manufacturer_identity": identity.model_dump(mode="json"),
        "registry_snapshot": snapshot.model_dump(mode="json"),
        "quantity_input": _manual(
            draft_id, "quantity", command.quantity, actor_id, at
        ).model_dump(mode="json"),
        "quantity": canonical_quantity(command.quantity),
        "unit": _manual(
            draft_id, "unit_raw", command.unit_raw, actor_id, at
        ).model_dump(mode="json"),
        "quantity_basis": _manual(
            draft_id, "quantity_basis_raw", command.quantity_basis_raw, actor_id, at
        ).model_dump(mode="json"),
        "requirements": [
            _manual(draft_id, f"requirements[{index}]", value, actor_id, at).model_dump(mode="json")
            for index, value in enumerate(command.requirements)
        ],
        "delivery_address": _manual(
            draft_id, "delivery_address_raw", command.delivery_address_raw, actor_id, at
        ).model_dump(mode="json"),
        "desired_delivery": _manual(
            draft_id, "desired_delivery_raw", command.desired_delivery_raw, actor_id, at
        ).model_dump(mode="json"),
        "reply_due_at": command.reply_due_at.isoformat().replace("+00:00", "Z"),
        "reply_due_provenance": ManualProvenance(
            document_id=draft_id, locator="reply_due_at", actor_id=actor_id, recorded_at=at
        ).model_dump(mode="json"),
        "source_response_sha256": directory.response_sha256,
        "dossier_sha256": evidence.dossier_sha256,
        "proposal_sha256": evidence.proposal_sha256,
        "decision_sha256": evidence.decision_sha256,
        "manual_inputs_sha256": manual_sha, "text": text_content,
        "text_sha256": hashlib.sha256(text_content.encode()).hexdigest(),
        "created_by": actor_id, "created_at": at.isoformat().replace("+00:00", "Z"),
        "contact": "UNKNOWN", "website": "UNKNOWN", "price": "UNKNOWN",
        "quote": "UNKNOWN", "technical": "UNKNOWN", "participation": "UNKNOWN",
    }
    payload["draft_sha256"] = canonical_sha256(payload)
    return ManufacturerRfqDraft.model_validate(payload)


def create_manufacturer_rfq_draft(
    storage: PostgresStorage, company_id: str, command: ManufacturerRfqCommand,
    actor_id: str,
) -> SavedManufacturerRfqDraft:
    actor_id = actor_id.strip()
    if not actor_id or len(actor_id) > 200:
        raise ValueError("MANUFACTURER_RFQ_ACTOR_INVALID")
    with storage.transaction(company_id) as conn:
        _lock(conn, company_id, command.command_id)
        row = conn.execute(
            select(drafts).where(and_(drafts.c.company_id == company_id,
                                      drafts.c.command_id == command.command_id))
        ).mappings().one_or_none()
        if row is not None:
            draft = _validated_row(row)
            if (
                draft.manual_inputs_sha256
                != canonical_sha256(command.model_dump(mode="json"))
                or draft.created_by != actor_id
            ):
                raise ManufacturerRfqConflict("MANUFACTURER_RFQ_COMMAND_CONFLICT")
            return SavedManufacturerRfqDraft(
                draft=draft,
                current_status=_current_status(storage, company_id, draft, datetime.now(UTC)),
                created=False,
            )
    now = datetime.now(UTC)
    if command.reply_due_at <= now:
        raise ValueError("MANUFACTURER_RFQ_REPLY_DUE_NOT_FUTURE")
    directory = build_manufacturer_directory(storage, company_id, command.run_id, evaluated_at=now)
    record, evidence, _ = _selected(directory, command)
    draft = _build_draft(command, actor_id, now, directory, record, evidence)
    canonical = canonical_bytes(draft.model_dump(mode="json", exclude={"draft_sha256"}))
    with storage.transaction(company_id) as conn:
        _lock(conn, company_id, command.command_id)
        replay = conn.execute(
            select(drafts).where(and_(drafts.c.company_id == company_id,
                                      drafts.c.command_id == command.command_id))
        ).mappings().one_or_none()
        if replay is not None:
            saved = _validated_row(replay)
            if (
                saved.manual_inputs_sha256 != draft.manual_inputs_sha256
                or saved.created_by != actor_id
            ):
                raise ManufacturerRfqConflict("MANUFACTURER_RFQ_COMMAND_CONFLICT")
            return SavedManufacturerRfqDraft(
                draft=saved, current_status=_current_status(storage, company_id, saved, now),
                created=False,
            )
        conn.execute(insert(drafts).values(
            company_id=company_id, draft_id=draft.draft_id, command_id=draft.command_id,
            run_id=draft.run_id, record_id=draft.registry_snapshot.record_id,
            proposal_id=draft.proposal_id, decision_id=draft.decision_id,
            manual_inputs_sha256=draft.manual_inputs_sha256,
            draft_sha256=draft.draft_sha256, draft_canonical=canonical,
            text_sha256=draft.text_sha256, text_content=draft.text.encode(),
            draft=draft.model_dump(mode="json"), created_by=actor_id, created_at=draft.created_at,
        ))
        _audit(conn, company_id, actor_id, draft.draft_id, draft.draft_sha256, draft.created_at)
    return SavedManufacturerRfqDraft(
        draft=draft,
        current_status=_current_status(storage, company_id, draft, datetime.now(UTC)),
        created=True,
    )


def read_manufacturer_rfq_draft(storage, company_id: str, draft_id: str):
    with storage.transaction(company_id, consistent_read=True) as conn:
        row = conn.execute(
            select(drafts).where(
                and_(drafts.c.company_id == company_id, drafts.c.draft_id == draft_id)
            )
        ).mappings().one_or_none()
    if row is None:
        raise ManufacturerRfqNotFound("MANUFACTURER_RFQ_NOT_FOUND")
    draft = _validated_row(row)
    return SavedManufacturerRfqDraft(
        draft=draft,
        current_status=_current_status(storage, company_id, draft, datetime.now(UTC)),
        created=False,
    )
