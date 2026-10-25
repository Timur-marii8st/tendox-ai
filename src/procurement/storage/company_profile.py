"""Самостоятельные immutable версии и выбор профиля на существующей tenant transaction."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert, select, text
from sqlalchemy.engine import Connection

from procurement.access import AccessRole
from procurement.domain.actions import payload_digest
from procurement.domain.company_profile_snapshot import (
    CRITICAL_PATHS,
    CompanyProfileSnapshot,
    ProfilePolicyConfirmation,
    ProfileSaveCommand,
    ProfileSelection,
    ProfileSelectionCommand,
    ProfileVersionRef,
    new_snapshot,
    snapshot_payload,
)
from procurement.storage.company_profile_schema import company_profile_selections as selections
from procurement.storage.company_profile_schema import company_profile_versions as versions
from procurement.storage.models import audit_events
from procurement.storage.repository import IdempotencyConflict, PostgresStorage


class ProfileConflict(ValueError):
    pass


class ProfileNotFound(LookupError):
    pass


class ProfileForbidden(PermissionError):
    pass


class ProfileEvidenceInvalid(ValueError):
    pass


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()


def _read(row: Any) -> CompanyProfileSnapshot:
    snapshot = CompanyProfileSnapshot.model_validate(row["snapshot"])
    if (
        snapshot.company_id != row["company_id"]
        or snapshot.version != row["version"]
        or snapshot.snapshot_sha256 != row["snapshot_sha256"]
        or _canonical(snapshot_payload(snapshot))
        != bytes(row["snapshot_canonical"])
        or snapshot.created_by != row["created_by"]
        or snapshot.created_at != row["created_at"]
        or snapshot.audit_event_id != row["audit_event_id"]
    ):
        raise ProfileEvidenceInvalid("stored_profile_invalid")
    return snapshot


def _latest(conn: Connection, company: str) -> CompanyProfileSnapshot | None:
    row = (
        conn.execute(
            select(versions)
            .where(versions.c.company_id == company)
            .order_by(versions.c.version.desc())
            .limit(1)
        )
        .mappings()
        .first()
    )
    return _read(row) if row else None


def _exact(conn: Connection, company: str, version: int) -> CompanyProfileSnapshot:
    row = (
        conn.execute(
            select(versions).where(versions.c.company_id == company, versions.c.version == version)
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ProfileNotFound("profile_not_found")
    return _read(row)


def _verify_sources(conn: Connection, snapshot: CompanyProfileSnapshot) -> None:
    refs = {source.source_sha256 for fact in snapshot.facts.values() for source in fact.sources}
    confirmation = snapshot.policy_confirmation
    command_hashes = refs | ({confirmation.command_sha256} if confirmation else set())
    if not command_hashes:
        return
    rows = (
        conn.execute(
            select(versions).where(
                versions.c.company_id == snapshot.company_id,
                versions.c.command_sha256.in_(command_hashes),
            )
        )
        .mappings()
        .all()
    )
    commands = {row["command_sha256"]: row for row in rows}
    for path, fact in snapshot.facts.items():
        for source in fact.sources:
            row = commands.get(source.source_sha256)
            if row is None:
                raise ProfileEvidenceInvalid("profile_source_missing")
            command = ProfileSaveCommand.model_validate(row["command"])
            incoming = command.normalized_changes().get(path)
            if (
                command.digest() != source.source_sha256
                or incoming is None
                or source.provenance.document_id != f"profile-command:{source.source_sha256}"
                or source.provenance.locator != path
                or source.recorded_by != row["created_by"]
                or source.recorded_at != row["created_at"]
                or (incoming.knowledge, incoming.value, incoming.reason)
                != (fact.knowledge, fact.value, fact.reason)
            ):
                raise ProfileEvidenceInvalid("profile_source_mismatch")
    if confirmation is None:
        return
    owner_row = commands.get(confirmation.command_sha256)
    if owner_row is None:
        raise ProfileEvidenceInvalid("policy_confirmation_command_missing")
    command = ProfileSaveCommand.model_validate(owner_row["command"])
    critical_paths = tuple(sorted(set(command.changes) & CRITICAL_PATHS))
    expected = command.confirmation_digest(snapshot.company_id, confirmation.confirmed_by)
    if (
        not critical_paths
        or command.confirmation_sha256 != expected
        or confirmation.command_sha256 != command.digest()
        or confirmation.confirmation_sha256 != expected
        or confirmation.confirmed_by != owner_row["created_by"]
        or confirmation.changed_paths != critical_paths
    ):
        raise ProfileEvidenceInvalid("policy_confirmation_mismatch")
    audit = (
        conn.execute(
            select(audit_events).where(
                audit_events.c.company_id == snapshot.company_id,
                audit_events.c.event_id == owner_row["audit_event_id"],
            )
        )
        .mappings()
        .one_or_none()
    )
    if (
        audit is None
        or audit["actor_id"] != confirmation.confirmed_by
        or audit["event_type"] != "company_profile.version_saved"
        or audit["object_type"] != "COMPANY_PROFILE"
        or audit["object_id"] != snapshot.company_id
        or audit["object_version"] != owner_row["version"]
        or audit["basis"].get("command_sha256") != command.digest()
        or audit["basis"].get("policy_confirmation") != confirmation.model_dump(mode="json")
    ):
        raise ProfileEvidenceInvalid("policy_confirmation_audit_mismatch")


def read_profile(
    storage: PostgresStorage, company: str, version: int | None = None
) -> CompanyProfileSnapshot:
    with storage.transaction(company) as conn:
        snapshot = _latest(conn, company) if version is None else _exact(conn, company, version)
        if snapshot is None:
            raise ProfileNotFound("profile_not_found")
        _verify_sources(conn, snapshot)
        return snapshot


def list_versions(
    storage: PostgresStorage, company: str, before: int | None = None
) -> list[dict[str, Any]]:
    with storage.transaction(company) as conn:
        query = select(versions).where(versions.c.company_id == company)
        if before is not None:
            query = query.where(versions.c.version < before)
        rows = conn.execute(query.order_by(versions.c.version.desc()).limit(50)).mappings().all()
        return [
            {
                "version": _read(row).version,
                "created_at": row["created_at"].isoformat(),
                "created_by": row["created_by"],
            }
            for row in rows
        ]


def _audit(
    conn: Connection,
    company: str,
    actor: str,
    event_id: str,
    action: str,
    version: int,
    at: datetime,
    basis: dict[str, Any],
) -> None:
    conn.execute(
        insert(audit_events).values(
            event_id=event_id,
            company_id=company,
            actor_id=actor,
            event_type=action,
            object_type="COMPANY_PROFILE",
            object_id=company,
            object_version=version,
            occurred_at=at,
            basis=basis,
        )
    )


def save_profile(
    storage: PostgresStorage,
    company: str,
    actor: str,
    role: AccessRole,
    command: ProfileSaveCommand,
    key: str,
) -> CompanyProfileSnapshot:
    if role not in {AccessRole.OPERATOR, AccessRole.COMPANY_PROFILE_OWNER}:
        raise ProfileForbidden("profile_writer_required")
    critical_paths = tuple(sorted(set(command.changes) & CRITICAL_PATHS))
    if critical_paths and role is not AccessRole.COMPANY_PROFILE_OWNER:
        raise ProfileForbidden("company_profile_owner_required")
    expected_confirmation = command.confirmation_digest(company, actor)
    if critical_paths and command.confirmation_sha256 != expected_confirmation:
        raise ProfileForbidden("profile_confirmation_required")
    receipt_payload: dict[str, Any] = {"actor_id": actor, "command": command.digest()}
    if command.confirmation_sha256 is not None:
        receipt_payload["confirmation_sha256"] = command.confirmation_sha256
    digest = payload_digest(receipt_payload)
    with storage.transaction(company) as conn:
        storage._lock_idempotency(conn, company, "company_profile.save", key)
        replay = storage._existing_receipt(conn, company, "company_profile.save", key, digest)
        if replay is not None:
            result = _exact(conn, company, int(replay["version"]))
            _verify_sources(conn, result)
            return result
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"company-profile-head:{company}"},
        )
        previous = _latest(conn, company)
        if command.expected_version != (previous.version if previous else 0):
            raise ProfileConflict("profile_version_conflict")
        if previous:
            _verify_sources(conn, previous)
        event_id = str(uuid.uuid4())
        policy_confirmation = (
            ProfilePolicyConfirmation(
                command_sha256=command.digest(),
                confirmation_sha256=expected_confirmation,
                confirmed_by=actor,
                confirmed_at=datetime.now(UTC),
                changed_paths=critical_paths,
            )
            if critical_paths
            else None
        )
        snapshot = new_snapshot(
            company,
            actor,
            command,
            previous,
            event_id,
            policy_confirmation=policy_confirmation,
        )
        if previous and snapshot.facts == previous.facts:
            snapshot = previous
        else:
            _audit(
                conn,
                company,
                actor,
                event_id,
                "company_profile.version_saved",
                snapshot.version,
                snapshot.created_at,
                {
                    "snapshot_sha256": snapshot.snapshot_sha256,
                    "command_sha256": command.digest(),
                    "changed_paths": sorted(command.changes),
                    "critical_settings_applied": bool(critical_paths),
                    "policy_confirmation": (
                        policy_confirmation.model_dump(mode="json")
                        if policy_confirmation is not None
                        else None
                    ),
                },
            )
            conn.execute(
                insert(versions).values(
                    company_id=company,
                    version=snapshot.version,
                    parent_version=snapshot.parent_version,
                    snapshot=snapshot.model_dump(mode="json"),
                    snapshot_sha256=snapshot.snapshot_sha256,
                    snapshot_canonical=_canonical(snapshot_payload(snapshot)),
                    command=command.model_dump(mode="json"),
                    command_sha256=command.digest(),
                    created_by=actor,
                    created_at=snapshot.created_at,
                    audit_event_id=event_id,
                )
            )
        storage._insert_receipt(
            conn,
            tenant=company,
            operation="company_profile.save",
            idempotency_key=key,
            request_sha256=digest,
            response={"version": snapshot.version},
        )
        return snapshot


def select_profile(
    storage: PostgresStorage,
    company: str,
    actor: str,
    role: AccessRole,
    command: ProfileSelectionCommand,
    key: str,
) -> ProfileSelection:
    if role not in {AccessRole.OPERATOR, AccessRole.COMPANY_PROFILE_OWNER}:
        raise ProfileForbidden("profile_writer_required")
    digest = payload_digest({"actor_id": actor, "command": command.model_dump(mode="json")})
    with storage.transaction(company) as conn:
        storage._lock_idempotency(conn, company, "company_profile.select", key)
        replay = storage._existing_receipt(conn, company, "company_profile.select", key, digest)
        if replay is not None:
            return _selection(conn, company, str(replay["selection_id"]))
        snapshot = _exact(conn, company, command.version)
        _verify_sources(conn, snapshot)
        if snapshot.snapshot_sha256 != command.snapshot_sha256:
            raise ProfileConflict("profile_digest_conflict")
        at, event_id, selection_id = datetime.now(UTC), str(uuid.uuid4()), str(uuid.uuid4())
        selection = ProfileSelection(
            company_id=company,
            selection_id=selection_id,
            profile_ref=ProfileVersionRef(
                company_id=company,
                version=snapshot.version,
                snapshot_sha256=snapshot.snapshot_sha256,
            ),
            selected_at=at,
            selected_by=actor,
            audit_event_id=event_id,
        )
        _audit(
            conn,
            company,
            actor,
            event_id,
            "company_profile.version_selected",
            snapshot.version,
            at,
            {
                "selection_id": selection_id,
                "profile_ref": selection.profile_ref.model_dump(),
                "comparison_performed": False,
            },
        )
        conn.execute(
            insert(selections).values(
                company_id=company,
                selection_id=selection_id,
                profile_version=snapshot.version,
                profile_sha256=snapshot.snapshot_sha256,
                selection=selection.model_dump(mode="json"),
                selected_by=actor,
                selected_at=at,
                audit_event_id=event_id,
            )
        )
        storage._insert_receipt(
            conn,
            tenant=company,
            operation="company_profile.select",
            idempotency_key=key,
            request_sha256=digest,
            response={"selection_id": selection_id},
        )
        return selection


def _selection(conn: Connection, company: str, selection_id: str | None) -> ProfileSelection:
    query = select(selections).where(selections.c.company_id == company)
    if selection_id:
        query = query.where(selections.c.selection_id == selection_id)
    row = (
        conn.execute(
            query.order_by(selections.c.selected_at.desc(), selections.c.selection_id).limit(1)
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ProfileNotFound("profile_selection_not_found")
    selection = ProfileSelection.model_validate(row["selection"])
    snapshot = _exact(conn, company, selection.profile_ref.version)
    if (
        selection.company_id != company
        or selection.selection_id != row["selection_id"]
        or selection.profile_ref.snapshot_sha256 != snapshot.snapshot_sha256
        or selection.selected_by != row["selected_by"]
        or selection.selected_at != row["selected_at"]
        or selection.audit_event_id != row["audit_event_id"]
    ):
        raise ProfileEvidenceInvalid("profile_selection_invalid")
    _verify_sources(conn, snapshot)
    return selection


def read_selection(
    storage: PostgresStorage, company: str, selection_id: str | None = None
) -> ProfileSelection:
    with storage.transaction(company) as conn:
        return _selection(conn, company, selection_id)


__all__ = [
    "IdempotencyConflict",
    "ProfileConflict",
    "ProfileEvidenceInvalid",
    "ProfileForbidden",
    "ProfileNotFound",
    "list_versions",
    "read_profile",
    "read_selection",
    "save_profile",
    "select_profile",
]
