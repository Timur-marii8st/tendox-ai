"""Recover a bounded set of verified public candidates through exact-number SOAP."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Literal, Protocol, cast
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import create_engine, func, insert, select, text
from sqlalchemy.exc import SQLAlchemyError

from procurement.sources.eis_feed import EisFeedResponse, parse_get_docs_ip_response
from procurement.sources.eis_feed_archive import EisFeedArchiveError
from procurement.sources.eis_feed_sync import (
    MAX_RESPONSE_BYTES,
    EisFeedTransport,
    eis_browser_transport,
)
from procurement.sources.eis_no_data_evidence import no_data_evidence_root, verify_no_data_reply
from procurement.sources.eis_number_sync import sync_eis_number
from procurement.sources.eis_rejected_evidence import (
    EisRejectedEvidence,
    RejectionReason,
    _safe_root,
    retain_rejected_window,
)
from procurement.storage.eis_document_store import NoticeDocumentRef, plan_document_job
from procurement.storage.eis_notice_index import EisReadyWindow, bind_ready_window
from procurement.storage.models import (
    audit_events,
    eis_notice_search_keys,
    eis_notice_versions,
)
from procurement.storage.repository import PostgresStorage

COMPANY: Literal["local-eis-supplier"] = "local-eis-supplier"
ACTOR = "s201-public-candidate-recovery"
ROOT = Path("/var/lib/eis-browser/research/rejected")
MAX_NUMBERS = 3
MAX_POSTS = 18
MAX_DOWNLOADS = 20
MAX_BYTES = 64 * 1024**2
NETWORK_SECONDS = 180
MAX_PROOF_BYTES = 1024**2
_SHA = r"^[0-9a-f]{64}$"
_ROUTES = frozenset({"ea20", "zk20", "ok20"})
RecoveryStatus = Literal[
    "ROUTE_UNSUPPORTED",
    "ALREADY_INDEXED",
    "DEFERRED",
    "SYNCED",
    "NO_DATA",
    "PREPARING",
    "SERVICE_ERROR",
    "REJECTED",
    "UNKNOWN",
]


class CandidateHint(Protocol):
    purchase_number: str
    detail_url: str


class InputPage(Protocol):
    candidates: Sequence[CandidateHint]


class InputArtifact(Protocol):
    sha256: str


class InputReport(Protocol):
    not_indexed_candidates: Sequence[str]
    page: InputPage
    artifact: InputArtifact
    observed_at: datetime


def public_module() -> ModuleType:
    # This is trusted repository code, never a path taken from a source document.
    path = Path(__file__).with_name("server-eis-no-data-public-check.py")
    spec = importlib.util.spec_from_file_location("s201_public_input", path)
    if spec is None or spec.loader is None:
        raise ValueError("INPUT_READER_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Indexed(Evidence):
    versions: int = Field(ge=0)
    lexical_rows: int = Field(ge=0)
    latest: NoticeDocumentRef | None = None


class Outcome(Evidence):
    purchase_number: str = Field(pattern=r"^[0-9]{19,23}$")
    route_hint: str = Field(max_length=32)
    status: RecoveryStatus
    reason: str | None = Field(default=None, pattern=r"^[A-Z0-9_]{1,100}$")
    before: Indexed
    after: Indexed
    source_response_sha256: str | None = Field(default=None, pattern=_SHA)
    prepared_response_sha256: str | None = Field(default=None, pattern=_SHA)
    archive_sha256s: tuple[str, ...] = Field(default=(), max_length=20)
    rejection_evidence: EisRejectedEvidence | None = None
    document_ref: NoticeDocumentRef | None = None
    document_queue: Literal["PLANNED", "NOT_REQUESTED", "UNKNOWN"] = "NOT_REQUESTED"
    document_queue_reason: str | None = Field(default=None, pattern=r"^[A-Z0-9_]{1,100}$")
    audit_event_id: str | None = None
    audit_status: Literal["RECORDED", "NOT_REQUIRED", "FAILED"] = "NOT_REQUIRED"

    @model_validator(mode="after")
    def bound(self) -> Outcome:
        if any(
            ref is not None and ref.purchase_number != self.purchase_number
            for ref in (self.before.latest, self.after.latest, self.document_ref)
        ):
            raise ValueError("OUTCOME_NUMBER_MISMATCH")
        if self.document_queue == "PLANNED" and (
            self.status != "SYNCED" or self.document_ref is None
        ):
            raise ValueError("QUEUE_BINDING_INVALID")
        if (self.audit_status == "RECORDED") != (self.audit_event_id is not None):
            raise ValueError("AUDIT_BINDING_INVALID")
        if self.rejection_evidence and (
            self.rejection_evidence.company_id != COMPANY
            or self.rejection_evidence.window_key
            != f"getDocsIP/PRIZ/by-number/{self.purchase_number}"
            or self.rejection_evidence.response_sha256 != self.source_response_sha256
        ):
            raise ValueError("REJECTION_BINDING_INVALID")
        return self


class Report(Evidence):
    schema_version: Literal["eis-public-candidate-recovery-v1"] = "eis-public-candidate-recovery-v1"
    company_id: Literal["local-eis-supplier"] = COMPANY
    observed_at: AwareDatetime
    input_sha256: str = Field(pattern=_SHA)
    input_dom_sha256: str = Field(pattern=_SHA)
    input_observed_at: AwareDatetime
    outcomes: tuple[Outcome, ...] = Field(max_length=50)
    attempted_numbers: int = Field(ge=0, le=MAX_NUMBERS)
    soap_attempts: int = Field(ge=0, le=MAX_POSTS)
    download_attempts: int = Field(ge=0, le=MAX_DOWNLOADS)
    received_archive_bytes: int = Field(ge=0)
    accepted_archive_bytes: int = Field(ge=0, le=MAX_BYTES)
    elapsed_seconds: float = Field(ge=0)
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    participation: Literal["UNKNOWN"] = "UNKNOWN"
    public_scope: Literal["NATIONAL_44_PUBLICATION_DAY_FIRST_PAGE"] = (
        "NATIONAL_44_PUBLICATION_DAY_FIRST_PAGE"
    )

    @model_validator(mode="after")
    def bound(self) -> Report:
        if len({v.purchase_number for v in self.outcomes}) != len(self.outcomes):
            raise ValueError("DUPLICATE_OUTCOME")
        return self


def load_input(path: Path, expected_sha: str, now: datetime) -> InputReport:
    if not re.fullmatch(_SHA, expected_sha):
        raise ValueError("INPUT_SHA_INVALID")
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_PROOF_BYTES:
        raise ValueError("INPUT_FILE_UNSAFE")
    blob = path.read_bytes()
    if hashlib.sha256(blob).hexdigest() != expected_sha:
        raise ValueError("INPUT_SHA_MISMATCH")
    public = public_module()
    report = public.Report.model_validate_json(blob)
    if not now - timedelta(days=7) <= report.observed_at <= now:
        raise ValueError("INPUT_AGE_INVALID")
    body = path.parent / "public-no-data" / COMPANY / report.artifact.relative_path
    if body.is_symlink() or not body.is_file() or body.stat().st_size > public.MAX_PAGE_BYTES:
        raise ValueError("INPUT_DOM_UNSAFE")
    raw = body.read_bytes()
    if (
        len(raw) != report.artifact.bytes
        or hashlib.sha256(raw).hexdigest() != report.artifact.sha256
    ):
        raise ValueError("INPUT_DOM_SHA_MISMATCH")
    if public.parse_page(raw, report.page.day) != report.page:
        raise ValueError("INPUT_DOM_REPARSE_MISMATCH")
    evidence_root = no_data_evidence_root()
    if evidence_root is None:
        raise ValueError("INPUT_SOAP_BINDING_INVALID")
    verified = verify_no_data_reply(
        evidence_root,
        COMPANY,
        report.target.receipt.window_key,
        report.target.receipt.source_response_sha256,
    )
    if (
        verified.status != "PASS"
        or verified.manifest != report.target.receipt.manifest
        or verified.manifest_sha256 != report.target.receipt.manifest_sha256
    ):
        raise ValueError("INPUT_SOAP_BINDING_INVALID")
    return cast(InputReport, report)


def route_hint(candidate: CandidateHint) -> str:
    # A page route is only a hint. Admission still checks every XML in the set.
    path = urlsplit(candidate.detail_url).path
    match = re.fullmatch(r"/epz/order/notice/([a-z0-9]{1,32})/view/common-info\.html", path)
    return match.group(1) if match else "unknown"


def candidate_order(candidates: Sequence[CandidateHint]) -> list[CandidateHint]:
    # Sample each supported public route before spending remaining slots on one route.
    first = {}
    for c in candidates:
        route = route_hint(c)
        if route in _ROUTES and route not in first:
            first[route] = c.purchase_number
    preferred = tuple(first.values())
    return sorted(
        candidates,
        key=lambda c: (
            preferred.index(c.purchase_number) if c.purchase_number in preferred else len(preferred)
        ),
    )


def read_indexed(storage: PostgresStorage, number: str) -> Indexed:
    with storage.transaction(COMPANY, consistent_read=True) as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        condition = (eis_notice_versions.c.company_id == COMPANY) & (
            eis_notice_versions.c.purchase_number == number
        )
        count = conn.scalar(select(func.count()).select_from(eis_notice_versions).where(condition))
        latest = conn.execute(
            select(eis_notice_versions.c.version_number, eis_notice_versions.c.xml_sha256)
            .where(condition)
            .order_by(eis_notice_versions.c.version_number.desc())
            .limit(1)
        ).first()
        lexical = conn.scalar(
            select(func.count())
            .select_from(eis_notice_search_keys)
            .where(
                (eis_notice_search_keys.c.company_id == COMPANY)
                & (eis_notice_search_keys.c.purchase_number == number)
            )
        )
    return Indexed(
        versions=count,
        lexical_rows=lexical,
        latest=NoticeDocumentRef(
            purchase_number=number, version_number=latest[0], notice_xml_sha256=latest[1]
        )
        if latest
        else None,
    )


def source_guard(storage: PostgresStorage) -> None:
    with storage.transaction(COMPANY, consistent_read=True) as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        size = conn.scalar(text("SELECT pg_database_size(current_database())"))
    if size is None or size >= 100 * 1024**3 or shutil.disk_usage(ROOT).free < 40 * 1024**3:
        raise ValueError("SOURCE_CAPACITY_GUARD")


class Budget:
    def __init__(self) -> None:
        self.posts = 0
        self.downloads = 0
        self.bytes = 0
        self.accepted_bytes = 0
        self.deadline = time.monotonic() + NETWORK_SECONDS

    def check(self) -> None:
        if time.monotonic() >= self.deadline:
            raise ValueError("NETWORK_BUDGET_EXHAUSTED")


class CaptureTransport:
    """Observe existing transport without changing the source admission function."""

    def __init__(self, transport: EisFeedTransport, budget: Budget, token: str):
        self.transport = transport
        self.budget = budget
        self.token = token
        self.initial: EisFeedResponse | None = None
        self.prepared: EisFeedResponse | None = None
        self.archives: dict[str, bytes] = {}

    async def post(self, xml: bytes) -> tuple[int, bytes]:
        self.budget.check()
        if self.budget.posts >= MAX_POSTS:
            raise ValueError("SOAP_BUDGET_EXHAUSTED")
        self.budget.posts += 1  # Attempts include transport errors, never just successes.
        status, raw = await self.transport.post(xml)
        if status == 200 and len(raw) <= MAX_RESPONSE_BYTES and self.token.encode() not in raw:
            reply = parse_get_docs_ip_response(raw)
            if reply.kind == "BY_NUMBER":
                self.initial = reply
            elif reply.kind == "PREPARED" and reply.state == "READY":
                self.prepared = reply
        return status, raw

    async def download(self, url: str, token: str) -> tuple[int, bytes]:
        self.budget.check()
        if self.budget.downloads >= MAX_DOWNLOADS:
            raise ValueError("DOWNLOAD_BUDGET_EXHAUSTED")
        if self.budget.bytes >= MAX_BYTES:
            raise ValueError("ARCHIVE_BATCH_SIZE_LIMIT")
        self.budget.downloads += 1
        status, raw = await self.transport.download(url, token)
        self.budget.bytes += len(raw)
        # Transport returns a whole response. Count even a rejected overshoot honestly;
        # this is an admission/next-download allowance, not a wire streaming limit.
        if self.budget.bytes > MAX_BYTES:
            raise ValueError("ARCHIVE_BATCH_SIZE_LIMIT")
        self.budget.accepted_bytes += len(raw)
        if status == 200:
            self.archives[url] = raw
        return status, raw

    def bound_window(self, number: str) -> EisReadyWindow | None:
        if self.initial is None or self.prepared is None:
            return None
        try:
            return bind_ready_window(
                f"getDocsIP/PRIZ/by-number/{number}",
                self.initial,
                self.prepared,
                self.archives,
            )
        except ValueError:
            return None


def safe_reason(error: Exception) -> str:
    # No arbitrary exception text or source content is persisted or printed.
    code = str(error)
    allowed = {
        "NETWORK_BUDGET_EXHAUSTED",
        "SOAP_BUDGET_EXHAUSTED",
        "DOWNLOAD_BUDGET_EXHAUSTED",
        "ARCHIVE_BATCH_SIZE_LIMIT",
        "BY_NUMBER_PURCHASE_MISMATCH",
        "BY_NUMBER_EMPTY_ARCHIVES",
        "DOCUMENT_TYPE_UNSUPPORTED",
        "DUPLICATE_NOTICE_VERSION_IN_WINDOW",
        "NOTICE_VERSION_CONFLICT",
        "PROCEDURE_EVENT_CONFLICT",
        "NOTICE_VARIANT_REVIEW_REQUIRED",
        "NUMBER_ARCHIVE_CONTENT_REJECTED",
        "NUMBER_RESPONSE_MISMATCH",
        "PREPARED_REQUEST_MISMATCH",
        "SOURCE_TRANSPORT_FAILED",
        "SOURCE_CONTRACT_CHANGED",
        "SOURCE_RESPONSE_REJECTED",
        "NUMBER_ARCHIVE_DOWNLOAD_FAILED",
        "SOURCE_WSDL_UNAVAILABLE",
        "NOTICE_VERSION_STALE",
        "DOCUMENT_SET_RESOURCE_LIMIT",
        "NOTICE_VERSION_UNKNOWN",
        "NOTICE_NOT_FOUND",
        "SOURCE_CAPACITY_GUARD",
        "DUPLICATE_NOTICE_VERSION",
        "DUPLICATE_PROCEDURE_EVENT",
        "FIELD_MISSING_OR_DUPLICATE",
        "FIELD_DUPLICATE",
        "FIELD_EMPTY",
        "XML_UNSAFE",
        "XML_INVALID",
        "EXPORT_ENVELOPE_INVALID",
        "PURCHASE_NUMBER_INVALID",
        "VERSION_INVALID",
        "TITLE_LIMIT",
        "MEMBER_UNSUPPORTED",
        "ARCHIVE_INVALID",
        "ARCHIVE_EXPANSION_LIMIT",
        "MEMBER_COUNT_INVALID",
        "ARCHIVE_SIZE_OR_TYPE_INVALID",
    }
    if isinstance(error, TimeoutError):
        return "NETWORK_BUDGET_EXHAUSTED"
    return code if code in allowed else "RECOVERY_UNAVAILABLE"


def record_outcome(storage: PostgresStorage, outcome: Outcome, input_sha: str) -> Outcome:
    event_id = str(uuid4())
    try:
        with storage.transaction(COMPANY) as conn:
            conn.execute(
                insert(audit_events).values(
                    event_id=event_id,
                    company_id=COMPANY,
                    actor_id=ACTOR,
                    event_type="EIS_PUBLIC_CANDIDATE_RECOVERY",
                    object_type="EIS_NOTICE",
                    object_id=outcome.purchase_number,
                    object_version=outcome.after.latest.version_number
                    if outcome.after.latest
                    else None,
                    basis={"input_sha256": input_sha, "outcome": outcome.model_dump(mode="json")},
                    occurred_at=datetime.now(UTC),
                )
            )
        return Outcome.model_validate(
            outcome.model_dump()
            | {
                "audit_status": "RECORDED",
                "audit_event_id": event_id,
            }
        )
    except SQLAlchemyError:
        return Outcome.model_validate(outcome.model_dump() | {"audit_status": "FAILED"})


async def recover_one(
    storage: PostgresStorage,
    candidate: CandidateHint,
    transport: EisFeedTransport,
    budget: Budget,
    token: str,
    before: Indexed,
    input_sha: str,
) -> Outcome:
    number = candidate.purchase_number
    capture = CaptureTransport(transport, budget, token)
    status: RecoveryStatus = "UNKNOWN"
    reason = None
    ref = None
    queue = "NOT_REQUESTED"
    queue_reason = None
    evidence = None
    try:
        source_guard(storage)
        async with asyncio.timeout(min(60, max(0, budget.deadline - time.monotonic()))):
            synced = await sync_eis_number(
                storage,
                COMPANY,
                ACTOR,
                number,
                token,
                capture,
                poll_attempts=5,
                poll_delay_seconds=3,
            )
        status = synced.status
        reason = synced.reason
        if status == "SYNCED" and synced.latest_version_number and synced.latest_xml_sha256:
            ref = NoticeDocumentRef(
                purchase_number=number,
                version_number=synced.latest_version_number,
                notice_xml_sha256=synced.latest_xml_sha256,
            )
            try:
                plan_document_job(storage, COMPANY, ref, actor_id=ACTOR)
                queue = "PLANNED"
            except (ValueError, LookupError, SQLAlchemyError) as error:
                queue, queue_reason = "UNKNOWN", safe_reason(error)
    except Exception as error:
        reason = safe_reason(error)
        window = capture.bound_window(number)
        rejected = isinstance(error, EisFeedArchiveError) or reason in {
            "BY_NUMBER_PURCHASE_MISMATCH",
            "BY_NUMBER_EMPTY_ARCHIVES",
            "DOCUMENT_TYPE_UNSUPPORTED",
            "DUPLICATE_NOTICE_VERSION_IN_WINDOW",
            "NOTICE_VERSION_CONFLICT",
            "PROCEDURE_EVENT_CONFLICT",
        }
        status = "REJECTED" if window is not None and rejected else "UNKNOWN"
        if window is not None and rejected:
            rejection = (
                reason
                if reason
                in {
                    "DUPLICATE_NOTICE_VERSION",
                    "DUPLICATE_NOTICE_VERSION_IN_WINDOW",
                    "NOTICE_VERSION_CONFLICT",
                }
                else "TRANSPORT_WINDOW_NOT_CANONICAL"
            )
            evidence = retain_rejected_window(
                window,
                COMPANY,
                cast(RejectionReason, rejection),
                token,
                datetime.now(UTC),
                Path(os.environ["EIS_REJECTED_EVIDENCE_DIR"])
                if os.environ.get("EIS_REJECTED_EVIDENCE_DIR")
                else None,
            )
    after = read_indexed(storage, number)  # Post-ingest failures do not imply zero writes.
    return record_outcome(
        storage,
        Outcome(
            purchase_number=number,
            route_hint=route_hint(candidate),
            status=status,
            reason=reason,
            before=before,
            after=after,
            source_response_sha256=capture.initial.source_sha256 if capture.initial else None,
            prepared_response_sha256=capture.prepared.source_sha256 if capture.prepared else None,
            archive_sha256s=tuple(
                hashlib.sha256(raw).hexdigest() for raw in capture.archives.values()
            ),
            rejection_evidence=evidence,
            document_ref=ref,
            document_queue=queue,
            document_queue_reason=queue_reason,
        ),
        input_sha,
    )


async def recover(
    storage: PostgresStorage,
    input_report: InputReport,
    token: str,
    input_sha: str,
    *,
    transport: EisFeedTransport | None = None,
) -> Report:
    if not re.fullmatch(_SHA, input_sha):
        raise ValueError("INPUT_SHA_INVALID")
    if not re.fullmatch(r"[A-Za-z0-9-]{16,128}", token):
        raise ValueError("SOURCE_TOKEN_UNAVAILABLE")
    budget = Budget()
    started = time.monotonic()
    attempted = 0
    outcomes = []

    async def run(inner: EisFeedTransport) -> None:
        nonlocal attempted
        missing = set(input_report.not_indexed_candidates)
        candidates = [c for c in input_report.page.candidates if c.purchase_number in missing]
        for candidate in candidate_order(candidates):
            before = read_indexed(storage, candidate.purchase_number)
            route = route_hint(candidate)
            status = (
                "ALREADY_INDEXED"
                if before.versions
                else "ROUTE_UNSUPPORTED"
                if route not in _ROUTES
                else "DEFERRED"
                if attempted >= MAX_NUMBERS or time.monotonic() >= budget.deadline
                else None
            )
            if status is not None:
                outcomes.append(
                    Outcome(
                        purchase_number=candidate.purchase_number,
                        route_hint=route,
                        status=cast(RecoveryStatus, status),
                        before=before,
                        after=before,
                    )
                )
                continue
            attempted += 1
            outcomes.append(
                await recover_one(
                    storage,
                    candidate,
                    inner,
                    budget,
                    token,
                    before,
                    input_sha,
                )
            )

    if transport is None:
        async with eis_browser_transport() as inner:
            await run(inner)
    else:
        await run(transport)
    return Report(
        observed_at=datetime.now(UTC),
        input_sha256=input_sha,
        input_dom_sha256=input_report.artifact.sha256,
        input_observed_at=input_report.observed_at,
        outcomes=tuple(outcomes),
        attempted_numbers=attempted,
        soap_attempts=budget.posts,
        download_attempts=budget.downloads,
        received_archive_bytes=budget.bytes,
        accepted_archive_bytes=budget.accepted_bytes,
        elapsed_seconds=time.monotonic() - started,
    )


def write_report(report: Report, token: str) -> tuple[str, str]:
    blob = report.model_dump_json(indent=2).encode()
    if len(blob) > MAX_PROOF_BYTES or token.encode() in blob:
        raise ValueError("PROOF_REJECTED")
    root = _safe_root(ROOT / "addressed-recovery" / COMPANY)
    files = tuple(root.iterdir())
    if any(p.is_symlink() or not p.is_file() for p in files) or len(files) >= 128:
        raise ValueError("PROOF_STORE_UNAVAILABLE")
    path = root / f"s201-{uuid4()}.json"
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(blob)
        stream.flush()
        os.fsync(stream.fileno())
    return str(path), hashlib.sha256(blob).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--input-sha256", required=True)
    args = parser.parse_args(argv)
    input_report = load_input(args.input, args.input_sha256, datetime.now(UTC))
    token = os.environ.get("EIS_GETDOCS_IP_TOKEN", "")
    engine = create_engine(
        os.environ["DATABASE_URL"],
        connect_args={
            "options": "-c statement_timeout=20000 -c lock_timeout=2000",
        },
    )
    try:
        report = asyncio.run(
            recover(PostgresStorage(engine), input_report, token, args.input_sha256)
        )
        proof, digest = write_report(report, token)
        print(json.dumps(report.model_dump(mode="json") | {"proof": proof, "sha256": digest}))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print('{"status":"UNKNOWN","reason":"RECOVERY_UNAVAILABLE","coverage":"UNKNOWN"}')
        raise SystemExit(65) from None
