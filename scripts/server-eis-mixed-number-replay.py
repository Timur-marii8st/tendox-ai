"""Source-free replay of three S201 complete archives; preview precedes apply."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import create_engine, select, text

from procurement.sources.eis_procedure_state import resolve_procedure_state
from procurement.sources.eis_rejected_evidence import EisRejectedEvidence
from procurement.storage.eis_document_store import NoticeDocumentRef, plan_document_job
from procurement.storage.eis_notice_hold import assert_notice_source_usable
from procurement.storage.eis_notice_index import (
    EisReadyWindow,
    ingest_ready_window,
    preflight_ready_window,
)
from procurement.storage.models import audit_events, eis_notice_search_keys, eis_notice_versions
from procurement.storage.repository import PostgresStorage

COMPANY: Literal["local-eis-supplier"] = "local-eis-supplier"
ACTOR = "s202-mixed-number-replay"
ROOT = Path("/var/lib/eis-browser/research/rejected")
INPUT = ROOT / "addressed-recovery" / COMPANY / "s201-600fa7d0-9b22-41ce-9c02-1a0fb250eed2.json"
INPUT_SHA = "6ed2d640b90c005e9d30d6ef8b008ece90c8ffe30b9d8636aa98b6246f0026e0"


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Outcome(Evidence):
    purchase_number: str = Field(pattern=r"^[0-9]{19,23}$")
    archive_sha256s: tuple[str, ...]
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parsed_notices: int = Field(ge=0)
    parsed_companions: int = Field(ge=0)
    new_versions: int = Field(ge=0)
    new_events: int = Field(ge=0)
    notice_refs: tuple[NoticeDocumentRef, ...]
    lexical_refs: tuple[NoticeDocumentRef, ...]
    document_queue: Literal["NOT_REQUESTED", "PLANNED", "BLOCKED", "UNKNOWN"]
    queue_reason: str | None = None
    application_status: Literal["FAIL", "UNKNOWN"]


class Report(Evidence):
    company_id: Literal["local-eis-supplier"] = COMPANY
    schema_version: Literal["eis-mixed-number-replay-v1"] = "eis-mixed-number-replay-v1"
    observed_at: AwareDatetime
    applied: bool
    input_sha256: str = INPUT_SHA
    outcomes: tuple[Outcome, ...] = Field(min_length=3, max_length=3)
    source_requests: Literal[0] = 0
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    participation: Literal["UNKNOWN"] = "UNKNOWN"


def bounded(path: Path, size: int) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > size:
        raise ValueError("REPLAY_ARTIFACT_UNSAFE")
    return path.read_bytes()


def windows(storage: PostgresStorage) -> tuple[EisReadyWindow, ...]:
    raw = bounded(INPUT, 1024**2)
    if hashlib.sha256(raw).hexdigest() != INPUT_SHA:
        raise ValueError("REPLAY_INPUT_MISMATCH")
    spec = importlib.util.spec_from_file_location(
        "s202_input", Path(__file__).with_name("server-eis-public-candidate-recovery.py")
    )
    if spec is None or spec.loader is None:
        raise ValueError("REPLAY_INPUT_READER_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    report = module.Report.model_validate_json(raw)
    root = Path(os.environ["EIS_REJECTED_EVIDENCE_DIR"])
    result = []
    with storage.transaction(COMPANY, consistent_read=True) as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        for out in report.outcomes:
            e = out.rejection_evidence
            if e is None:
                continue
            if out.audit_status != "RECORDED" or e.status != "RETAINED" or not e.complete_set:
                raise ValueError("REPLAY_EVIDENCE_INCOMPLETE")
            basis = conn.execute(
                select(audit_events.c.basis).where(
                    audit_events.c.company_id == COMPANY,
                    audit_events.c.event_id == out.audit_event_id,
                    audit_events.c.event_type == "EIS_PUBLIC_CANDIDATE_RECOVERY",
                    audit_events.c.actor_id == "s201-public-candidate-recovery",
                )
            ).scalar_one()
            if basis["input_sha256"] != report.input_sha256 or basis["outcome"][
                "rejection_evidence"
            ] != e.model_dump(mode="json"):
                raise ValueError("REPLAY_AUDIT_MISMATCH")
            manifest = bounded(root / e.relative_manifest_path, 64 * 1024)
            if hashlib.sha256(manifest).hexdigest() != e.manifest_sha256:
                raise ValueError("REPLAY_MANIFEST_MISMATCH")
            receipt = EisRejectedEvidence.model_validate(
                json.loads(manifest) | {"manifest_sha256": e.manifest_sha256}
            )
            if receipt != e or e.company_id != COMPANY:
                raise ValueError("REPLAY_TENANT_MISMATCH")
            archives = tuple(
                bounded(root / COMPANY / "blobs" / f"{sha}.zip", 50 * 1024**2)
                for sha in e.archive_sha256s
            )
            if tuple(hashlib.sha256(raw).hexdigest() for raw in archives) != e.archive_sha256s:
                raise ValueError("REPLAY_ARCHIVE_MISMATCH")
            window = EisReadyWindow(
                e.window_key,
                e.response_sha256,
                len(archives),
                archives,
                e.prepared_response_sha256,
                e.archive_urls,
            )
            preflight_ready_window(window)
            result.append(window)
    if len(result) != 3:
        raise ValueError("REPLAY_COHORT_INVALID")
    return tuple(result)


def replay(storage: PostgresStorage, *, apply: bool) -> Report:
    selected = windows(storage)  # Verify every set before any canonical mutation.
    outcomes = []
    for window in selected:
        flight = preflight_ready_window(window)
        number = window.window_key.rsplit("/", 1)[-1]
        notices = tuple(n for inspection in flight.inspections for n in inspection.records)
        events = tuple(e for inspection in flight.inspections for e in inspection.events)
        now = datetime.now(UTC)
        state = resolve_procedure_state(events, purchase_number=number, now=now)
        latest_notice = max(notices, key=lambda n: n.version_number) if notices else None
        expired = bool(latest_notice and latest_notice.deadline and latest_notice.deadline <= now)
        refs = tuple(
            NoticeDocumentRef(
                purchase_number=n.purchase_number,
                version_number=n.version_number,
                notice_xml_sha256=n.xml_sha256,
            )
            for n in notices
        )
        lexical: tuple[NoticeDocumentRef, ...] = ()
        new_versions = new_events = 0
        queue: Literal["NOT_REQUESTED", "PLANNED", "BLOCKED", "UNKNOWN"] = "NOT_REQUESTED"
        reason = None
        if apply:
            with storage.transaction(COMPANY, consistent_read=True) as conn:
                conn.execute(text("SET TRANSACTION READ ONLY"))
                size = conn.scalar(text("SELECT pg_database_size(current_database())"))
            if size >= 100 * 1024**3 or shutil.disk_usage(ROOT).free < 40 * 1024**3:
                raise ValueError("REPLAY_CAPACITY_GUARD")
            ingested = ingest_ready_window(storage, COMPANY, window, actor_id=ACTOR)
            new_versions, new_events = ingested.new_versions, ingested.new_events
            with storage.transaction(COMPANY, consistent_read=True) as conn:
                conn.execute(text("SET TRANSACTION READ ONLY"))
                rows = conn.execute(
                    select(
                        eis_notice_versions.c.purchase_number,
                        eis_notice_versions.c.version_number,
                        eis_notice_versions.c.xml_sha256,
                    )
                    .join(
                        eis_notice_search_keys,
                        (eis_notice_search_keys.c.company_id == eis_notice_versions.c.company_id)
                        & (
                            eis_notice_search_keys.c.purchase_number
                            == eis_notice_versions.c.purchase_number
                        )
                        & (
                            eis_notice_search_keys.c.version_number
                            == eis_notice_versions.c.version_number
                        ),
                    )
                    .where(
                        eis_notice_versions.c.company_id == COMPANY,
                        eis_notice_versions.c.purchase_number == number,
                    )
                ).all()
                lexical = tuple(
                    NoticeDocumentRef(
                        purchase_number=row[0], version_number=row[1], notice_xml_sha256=row[2]
                    )
                    for row in rows
                )
            if not set(refs).issubset(set(lexical)):
                raise ValueError("REPLAY_LEXICAL_BINDING_MISMATCH")
            latest = max(refs, key=lambda ref: ref.version_number) if refs else None
            if latest:
                try:
                    with storage.transaction(COMPANY, consistent_read=True) as conn:
                        assert_notice_source_usable(conn, COMPANY, number, latest.version_number)
                    if expired or state.application_status == "FAIL":
                        queue, reason = (
                            "BLOCKED",
                            "DEADLINE_EXPIRED" if expired else "PROCEDURE_BLOCKED",
                        )
                    else:
                        plan_document_job(storage, COMPANY, latest, actor_id=ACTOR)
                        queue = "PLANNED"
                except (ValueError, LookupError):
                    queue, reason = "UNKNOWN", "DOCUMENT_QUEUE_UNAVAILABLE"
        outcomes.append(
            Outcome(
                purchase_number=number,
                archive_sha256s=tuple(i.archive_sha256 for i in flight.inspections),
                manifest_sha256=flight.manifest_sha256,
                parsed_notices=len(notices),
                parsed_companions=len(events),
                new_versions=new_versions,
                new_events=new_events,
                notice_refs=refs,
                lexical_refs=lexical,
                document_queue=queue,
                queue_reason=reason,
                application_status="FAIL"
                if expired or state.application_status == "FAIL"
                else "UNKNOWN",
            )
        )
    return Report(observed_at=datetime.now(UTC), applied=apply, outcomes=tuple(outcomes))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    engine = create_engine(
        os.environ["DATABASE_URL"],
        connect_args={
            "options": "-c statement_timeout=20000 -c lock_timeout=2000",
        },
    )
    try:
        report = replay(PostgresStorage(engine), apply=args.apply)
    finally:
        engine.dispose()
    path = ROOT / f"s202-mixed-replay-{uuid4()}.json"
    blob = report.model_dump_json(indent=2).encode()
    if len(blob) > 1024**2:
        raise ValueError("REPLAY_PROOF_SIZE_LIMIT")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(blob)
    print(
        json.dumps(
            report.model_dump(mode="json")
            | {
                "proof": str(path),
                "sha256": hashlib.sha256(blob).hexdigest(),
            }
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print('{"status":"UNKNOWN","reason":"MIXED_REPLAY_UNAVAILABLE","coverage":"UNKNOWN"}')
        raise SystemExit(65) from None
