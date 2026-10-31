"""Bounded parameterized notice/event refresh under the shared server lease."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from xml.etree.ElementTree import Element

from pydantic import ValidationError
from sqlalchemy import create_engine, select, text, union_all
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DataError, IntegrityError, OperationalError, SQLAlchemyError

from procurement.eis_freshness_dispatch_cli import joint_mandatory_status, urgent44_status
from procurement.eis_joint_budget import NATIONAL_RECOVERY_START, JointStartBudget
from procurement.sources.eis_223_archive import SUPPORTED_DOCUMENT_TYPES, Eis223ContractError
from procurement.sources.eis_223_catalog_fetch import fetch_region_selector
from procurement.sources.eis_223_event_quality_worker import process_event_quality_batch
from procurement.sources.eis_223_event_sync import fetch_purchase_rejection_day
from procurement.sources.eis_223_lot_event_quality_worker import process_lot_event_quality_batch
from procurement.sources.eis_223_lot_event_sync import fetch_purchase_lot_cancellation_day
from procurement.sources.eis_223_quality_worker import process_quality_batch
from procurement.sources.eis_223_sync import fetch_notice223_day
from procurement.sources.eis_223_window_limits import (
    MAX_ARCHIVE_BYTES,
    MAX_ARCHIVE_EXPANDED_BYTES,
    MAX_ARCHIVE_MEMBERS,
)
from procurement.sources.eis_corpus import priority_requested
from procurement.sources.eis_feed_sync import EisFeedTransport, EisSyncError, eis_browser_transport
from procurement.sources.eis_rejected_evidence import (
    QuotaError,
    _quota,
    _safe_root,
    _sync_tree_path,
    _write_immutable,
)
from procurement.storage.eis_223_catalog_checks import catalog_refresh_due, record_catalog_check
from procurement.storage.eis_223_events import ingest_event223_window
from procurement.storage.eis_223_index import (
    Eis223IndexConflict,
    Eis223SourceBinding,
    bind_notice223_window,
    ingest_notice223_window,
    preflight_notice223_window,
)
from procurement.storage.eis_223_lot_events import ingest_lot_event223_window
from procurement.storage.eis_223_regions import (
    _accepted_catalog,
    ensure_region_wave,
    read_region_coverage,
    regional_due_windows,
)
from procurement.storage.eis_223_sync import (
    MSK,
    Eis223EventRefreshTarget,
    Outcome,
    RefreshTarget,
    due_windows,
    record_attempt,
    refresh_window_key,
)
from procurement.storage.models import (
    audit_events,
    eis_223_event_sync_attempts,
    eis_223_lot_event_sync_attempts,
    eis_223_region_targets,
    eis_223_sync_attempts,
)
from procurement.storage.repository import PostgresStorage

COMPANY = "local-eis-supplier"
ACTOR = "223-refresh"
MAX_WINDOWS = 2
MAX_SECONDS = 180
REGIONAL_MAX_WINDOWS = 32
REGIONAL_MAX_BATCHES = 8
REGIONAL_MAX_SECONDS = 180
WINDOW_TIMEOUT = 180

# Capture a single already-scheduled FAILED retry; it never creates a source turn.
CAPTURE_KEY = "getDocsIP/RI223/16/2026-10-29+03:00/purchaseNoticeKESMBO"
CAPTURE_ROOT = Path("/var/lib/eis-browser/research/223-failed-window-20261030")


def _private_capture_root(root: Path) -> Path:
    root = root.absolute()
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("CAPTURE_PATH_UNSAFE")
    root.mkdir(mode=0o700, exist_ok=True)
    info = root.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise ValueError("CAPTURE_ROOT_UNSAFE")
    return _safe_root(root)


def _private_capture_directory(path: Path) -> None:
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise ValueError("CAPTURE_DIRECTORY_UNSAFE")


@contextmanager
def _capture_lock(root: Path):
    """Serialize writers sharing this store and its byte quota across processes."""
    fd = os.open(root / ".capture.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            raise ValueError("CAPTURE_LOCK_UNSAFE")
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _capture_failure_reason(error: Exception) -> str:
    if isinstance(error, QuotaError) or (
        type(error) is ValueError and str(error) == "CAPTURE_QUOTA_REACHED"
    ):
        return "QUOTA_REACHED"
    if isinstance(error, FileNotFoundError):
        return "INCOMPLETE"
    return "OTHER"


def _audit_capture_failure(storage, key: str, response_sha: str, checked_at: datetime, reason: str):
    """Audit only a safe category for one uniquely bound failed attempt."""
    from uuid import NAMESPACE_URL, uuid5

    if key != CAPTURE_KEY or reason not in {"QUOTA_REACHED", "INCOMPLETE", "OTHER"}:
        raise ValueError("CAPTURE_DIAGNOSTIC_INVALID")
    with storage.transaction(COMPANY) as conn:
        attempts = conn.execute(select(eis_223_sync_attempts.c.attempt_id).where(
            eis_223_sync_attempts.c.company_id == COMPANY,
            eis_223_sync_attempts.c.window_key == key,
            eis_223_sync_attempts.c.response_sha256 == response_sha,
            eis_223_sync_attempts.c.checked_at == checked_at,
            eis_223_sync_attempts.c.status == "FAILED",
            eis_223_sync_attempts.c.reason == "SYNC_FAILED",
        ).limit(2)).scalars().all()
        if len(attempts) != 1:
            raise ValueError("CAPTURE_ATTEMPT_INVALID")
        attempt_id = attempts[0]
        event_id = str(uuid5(NAMESPACE_URL, "tendox:eis-223-capture-failure:" + attempt_id))
        basis = {"attempt_id": attempt_id, "reason": reason, "coverage": "UNKNOWN"}
        conn.execute(pg_insert(audit_events).values(
            company_id=COMPANY, event_id=event_id, actor_id=ACTOR,
            event_type="EIS_223_FAILED_CAPTURE_DIAGNOSTIC", object_type="EIS_223_SOURCE_WINDOW",
            object_id=key, occurred_at=checked_at, basis=basis,
        ).on_conflict_do_nothing(index_elements=["company_id", "event_id"]))
        row = conn.execute(select(
            audit_events.c.basis, audit_events.c.object_id, audit_events.c.actor_id,
            audit_events.c.event_type, audit_events.c.object_type, audit_events.c.occurred_at,
        ).where(audit_events.c.company_id == COMPANY, audit_events.c.event_id == event_id)).one()
        if (row.basis != basis or row.object_id != key or row.actor_id != ACTOR
                or row.event_type != "EIS_223_FAILED_CAPTURE_DIAGNOSTIC"
                or row.object_type != "EIS_223_SOURCE_WINDOW" or row.occurred_at != checked_at):
            raise ValueError("CAPTURE_DIAGNOSTIC_CONFLICT")


def reconcile_failed_223(storage, root: Path, token: str) -> str:
    """Verify a retained manifest and complete its audit without an EIS request."""
    from io import BytesIO
    from uuid import NAMESPACE_URL, UUID, uuid5
    from zipfile import ZipFile

    safe_root = _private_capture_root(root)
    tenant = safe_root / COMPANY
    _private_capture_directory(tenant)
    entries = list(tenant.iterdir())
    if len(entries) != 1 or entries[0].is_symlink():
        raise ValueError("CAPTURE_PENDING_OR_AMBIGUOUS")
    directory = entries[0]
    _private_capture_directory(directory)
    attempt_id = directory.name
    if str(UUID(attempt_id)) != attempt_id:
        raise ValueError("CAPTURE_ATTEMPT_INVALID")
    path = directory / "manifest.json"
    if (path.is_symlink() or not path.is_file() or path.stat().st_size > 65536
            or path.stat().st_uid != os.geteuid() or stat.S_IMODE(path.stat().st_mode) != 0o440):
        raise ValueError("CAPTURE_MANIFEST_INVALID")
    encoded = path.read_bytes()
    if not token or token.encode() in encoded:
        raise ValueError("CAPTURE_METADATA_INVALID")
    manifest = json.loads(encoded)
    if (manifest.get("company_id") != COMPANY or manifest.get("attempt_id") != attempt_id
            or manifest.get("window_key") != CAPTURE_KEY or manifest.get("coverage") != "UNKNOWN"
            or manifest.get("soap_bytes_retained") is not False):
        raise ValueError("CAPTURE_MANIFEST_INVALID")
    digests, urls = manifest.get("archive_sha256"), manifest.get("archive_urls")
    if (not isinstance(digests, list) or not 1 <= len(digests) <= 8
            or len(set(digests)) != len(digests) or not isinstance(urls, list)
            or len(urls) != len(digests)):
        raise ValueError("CAPTURE_MANIFEST_INVALID")
    archives = []
    for digest in digests:
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("CAPTURE_MANIFEST_INVALID")
        blob = directory / (digest + ".zip")
        if (blob.is_symlink() or not blob.is_file() or blob.stat().st_size > 16 * 1024 * 1024
                or blob.stat().st_uid != os.geteuid()
                or stat.S_IMODE(blob.stat().st_mode) != 0o440):
            raise ValueError("CAPTURE_BLOB_INVALID")
        raw = blob.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest or token.encode() in raw:
            raise ValueError("CAPTURE_BLOB_INVALID")
        archives.append(raw)
    binding = Eis223SourceBinding.model_validate(manifest["source_binding"])
    window = bind_notice223_window(
        CAPTURE_KEY, binding.initial, binding.prepared, dict(zip(urls, archives, strict=True))
    )
    if (window.response_sha256 != manifest.get("response_sha256")
            or window.prepared_sha256 != manifest.get("prepared_sha256")):
        raise ValueError("CAPTURE_BINDING_INVALID")
    preflight_notice223_window(COMPANY, window)
    for raw in archives:
        with ZipFile(BytesIO(raw)) as bundle:
            if any(token.encode() in bundle.read(i) for i in bundle.infolist()):
                raise ValueError("CAPTURE_TOKEN_REFLECTION")
    checked_at = datetime.fromisoformat(manifest["checked_at"])
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("CAPTURE_TIME_INVALID")
    with storage.transaction(COMPANY, consistent_read=True) as conn:
        match = conn.execute(select(eis_223_sync_attempts.c.attempt_id).where(
            eis_223_sync_attempts.c.company_id == COMPANY,
            eis_223_sync_attempts.c.attempt_id == attempt_id,
            eis_223_sync_attempts.c.window_key == CAPTURE_KEY,
            eis_223_sync_attempts.c.response_sha256 == window.response_sha256,
            eis_223_sync_attempts.c.checked_at == checked_at,
            eis_223_sync_attempts.c.status == "FAILED",
            eis_223_sync_attempts.c.reason == "SYNC_FAILED",
        )).scalars().all()
    if match != [attempt_id]:
        raise ValueError("CAPTURE_ATTEMPT_INVALID")
    _sync_tree_path(path, safe_root)
    digest = hashlib.sha256(encoded).hexdigest()
    event_id = str(uuid5(NAMESPACE_URL, "tendox:eis-223-capture:" + attempt_id))
    basis = {"attempt_id": attempt_id, "manifest_sha256": digest,
             "response_sha256": window.response_sha256, "coverage": "UNKNOWN"}
    with storage.transaction(COMPANY) as conn:
        conn.execute(pg_insert(audit_events).values(
            company_id=COMPANY, event_id=event_id, actor_id=ACTOR,
            event_type="EIS_223_FAILED_WINDOW_RETAINED", object_type="EIS_223_SOURCE_WINDOW",
            object_id=CAPTURE_KEY, occurred_at=checked_at, basis=basis,
        ).on_conflict_do_nothing(index_elements=["company_id", "event_id"]))
        row = conn.execute(select(
            audit_events.c.basis, audit_events.c.object_id, audit_events.c.actor_id,
            audit_events.c.event_type, audit_events.c.object_type, audit_events.c.occurred_at,
        ).where(
            audit_events.c.company_id == COMPANY, audit_events.c.event_id == event_id
        )).one()
        if (row.basis != basis or row.object_id != CAPTURE_KEY or row.actor_id != ACTOR
                or row.event_type != "EIS_223_FAILED_WINDOW_RETAINED"
                or row.object_type != "EIS_223_SOURCE_WINDOW" or row.occurred_at != checked_at):
            raise ValueError("CAPTURE_AUDIT_CONFLICT")
    return digest


def retain_failed_223(storage, window, token: str, checked_at: datetime, *, root=CAPTURE_ROOT):
    """Retain a validated set after its FAILED attempt exists; reconcile audit on replay."""
    from io import BytesIO
    from uuid import UUID
    from zipfile import ZipFile

    if window.window_key != CAPTURE_KEY or not token or window.source_binding is None:
        raise ValueError("CAPTURE_BINDING_INVALID")
    preflight_notice223_window(COMPANY, window)
    for raw in window.archives:
        with ZipFile(BytesIO(raw)) as bundle:
            if token.encode() in raw or any(
                token.encode() in bundle.read(i) for i in bundle.infolist()
            ):
                raise ValueError("CAPTURE_TOKEN_REFLECTION")
    with storage.transaction(COMPANY, consistent_read=True) as conn:
        attempts = conn.execute(
            select(eis_223_sync_attempts.c.attempt_id).where(
                eis_223_sync_attempts.c.company_id == COMPANY,
                eis_223_sync_attempts.c.window_key == window.window_key,
                eis_223_sync_attempts.c.response_sha256 == window.response_sha256,
                eis_223_sync_attempts.c.checked_at == checked_at,
                eis_223_sync_attempts.c.status == "FAILED",
                eis_223_sync_attempts.c.reason == "SYNC_FAILED",
            ).limit(2)
        ).scalars().all()
    if len(attempts) != 1:
        raise ValueError("CAPTURE_ATTEMPT_INVALID")
    attempt_id = attempts[0]
    if str(UUID(attempt_id)) != attempt_id:
        raise ValueError("CAPTURE_ATTEMPT_INVALID")
    digests = [hashlib.sha256(raw).hexdigest() for raw in window.archives]
    manifest = {
        "company_id": COMPANY, "attempt_id": attempt_id, "window_key": window.window_key,
        "response_sha256": window.response_sha256, "prepared_sha256": window.prepared_sha256,
        "source_binding": window.source_binding.model_dump(mode="json"),
        "archive_sha256": digests, "archive_urls": window.archive_urls,
        "checked_at": checked_at.isoformat(), "coverage": "UNKNOWN",
        "soap_bytes_retained": False,
    }
    encoded = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if token.encode() in encoded or len(encoded) > 65536:
        raise ValueError("CAPTURE_METADATA_INVALID")
    safe_root = _private_capture_root(root)
    directory = safe_root / COMPANY / attempt_id
    with _capture_lock(safe_root):
        # Bound to one failed attempt. Existing partial data is reconciled, never replaced.
        tenant_dir = safe_root / COMPANY
        _private_capture_directory(tenant_dir)
        if tenant_dir.exists() and any(p.name != attempt_id for p in tenant_dir.iterdir()):
            raise ValueError("CAPTURE_QUOTA_REACHED")
        _private_capture_directory(directory)
        paths = [directory / (digest + ".zip") for digest in digests]
        manifest_path = directory / "manifest.json"
        # Existing bytes are already counted by _quota; _write_immutable below
        # still verifies that a replay's manifest is exactly the same.
        _quota(safe_root, paths, window.archives, 0 if manifest_path.exists() else len(encoded))
        for path, raw, digest in zip(paths, window.archives, digests, strict=True):
            _write_immutable(path, raw, digest, safe_root, 16 * 1024 * 1024)
        digest = hashlib.sha256(encoded).hexdigest()
        _write_immutable(manifest_path, encoded, digest, safe_root, 65536)
        _sync_tree_path(manifest_path, safe_root)
        return reconcile_failed_223(storage, safe_root, token)
MAX_DB_BYTES = 100 * 1024**3
MIN_FREE_BYTES = 40 * 1024**3
PRIORITY_REQUEST = Path("/var/lib/eis-browser/eis-priority.request")
SAFE_REASONS = frozenset(
    {
        "SOURCE_TRANSPORT_FAILED",
        "SOURCE_WSDL_UNAVAILABLE",
        "SOURCE_RESPONSE_REJECTED",
        "SOURCE_CONTRACT_CHANGED",
        "INITIAL_REQUEST_MISMATCH",
        "PREPARED_REQUEST_MISMATCH",
        "ARCHIVE_CONTENT_REJECTED",
        "ARCHIVE_DOWNLOAD_REJECTED",
        "SOURCE_BINDING_INVALID",
        "ARCHIVE_SET_MISMATCH",
        "ARCHIVE_COUNT_LIMIT",
        "WINDOW_BYTES_LIMIT",
        "WINDOW_EXPANSION_LIMIT",
        "WINDOW_EXPANDED_LIMIT",
        "WINDOW_MEMBER_LIMIT",
        "ARCHIVE_RESOURCE_LIMIT",
        "ARCHIVE_INVALID",
        "NOTICE_VERSION_CONFLICT",
        "XML_TOKEN_REFLECTION_REJECTED",
        "ARCHIVE_BYTES_LIMIT",
        "ARCHIVE_EXPANSION_LIMIT",
    }
)
SAFE_DIAGNOSTIC_CODES = SAFE_REASONS | frozenset(
    {
        "ARCHIVE_DIGEST_DUPLICATE", "ARCHIVE_MEMBER_REJECTED", "ARCHIVE_UID_MISMATCH",
        "ARCHIVE_URL_DUPLICATE", "DOCUMENT_TYPE_UNSUPPORTED", "FIELD_DUPLICATE",
        "FIELD_MISSING_OR_DUPLICATE", "FIELD_NAMESPACE_INVALID", "NOTICE_COLLECTION_LIMIT",
        "NOTICE_IDENTITY_INVALID", "NOTICE_VERSION_DUPLICATE", "PERSISTED_IDENTITY_MISMATCH",
        "PRICE_BRANCH_CONFLICT", "SCALAR_NESTED", "TEXT_LIMIT", "WINDOW_INVALID",
        "WINDOW_REPLAY_CONFLICT", "XML_BYTES_INVALID", "XML_BYTES_LIMIT", "XML_INVALID",
        "XML_REJECTED", "223_POSITION_ARCHIVE_DIGEST", "223_POSITION_ARCHIVE_LIMIT",
        "223_POSITION_DIGEST_MISMATCH", "223_POSITION_IDENTITY_MISMATCH",
        "223_POSITION_MEMBER_LIMIT", "223_POSITION_NOTICE_NOT_FOUND", "223_POSITION_PAGE_CHANGED",
        "223_POSITION_PAGE_DUPLICATE", "223_POSITION_PAGE_LIMIT", "223_POSITION_REPLAY_CONFLICT",
        "223_POSITION_TENANT_ACTOR", "223_POSITION_TIME", "223_POSITION_XML_DIGEST",
        "223_POSITION_XML_IDENTITY",
        "JOINT_XML_IDENTITY", "JOINT_XML_DECLARATION", "JOINT_ROOT_NAMESPACE",
        "JOINT_NOTICE_IDENTITY", "JOINT_FOREIGN_QNAME", "JOINT_AMBIGUOUS_LOT_SHAPES",
        "JOINT_FLAG_UNSUPPORTED", "JOINT_ITEM_LIMIT", "JOINT_CUSTOMER_LIMIT",
        "JOINT_CUSTOMERS_MISSING", "JOINT_UNMAPPED_ITEMS", "JOINT_SOURCE_INVALID",
    }
)
SAFE_DIAGNOSTIC_MODULES = frozenset(
    {
        "procurement.sources.eis_223_archive",
        "procurement.sources.eis_223_sync",
        "procurement.sources.eis_223_joint_positions",
        "procurement.sources.eis_223_event_sync",
        "procurement.sources.eis_223_lot_event_sync",
        "procurement.sources.eis_feed_sync",
        "procurement.storage.eis_223_index",
        "procurement.storage.eis_223_position_projection",
        "procurement.storage.eis_223_events",
        "procurement.storage.eis_223_lot_events",
    }
)


def failure_diagnostic(error: Exception, phase: str) -> dict[str, object]:
    """Expose only a bounded failure category, never source or exception text."""
    if phase not in {"FETCH", "INGEST"}:
        raise ValueError("DIAGNOSTIC_PHASE_INVALID")
    categories = (
        (IntegrityError, "SQL_INTEGRITY"),
        (DataError, "SQL_DATA"),
        (OperationalError, "SQL_OPERATIONAL"),
        (SQLAlchemyError, "SQL_OTHER"),
        (EisSyncError, "EIS_SYNC"),
        (Eis223ContractError, "EIS_223_CONTRACT"),
        (Eis223IndexConflict, "EIS_223_INDEX"),
        (ValidationError, "VALIDATION"),
        (TimeoutError, "TIMEOUT"),
        (KeyError, "KEY_ERROR"),
        (TypeError, "TYPE_ERROR"),
        (AttributeError, "ATTRIBUTE_ERROR"),
        (AssertionError, "ASSERTION_ERROR"),
        (LookupError, "LOOKUP_ERROR"),
        (ValueError, "VALUE_ERROR"),
        (OSError, "OS_ERROR"),
    )
    category = next((name for cls, name in categories if isinstance(error, cls)), "OTHER")
    sqlstate = getattr(getattr(error, "orig", None), "sqlstate", None)
    if not isinstance(sqlstate, str) or not re.fullmatch(r"[0-9A-Z]{5}", sqlstate):
        sqlstate = None
    message = str(error)
    code = message if message in SAFE_DIAGNOSTIC_CODES else None
    location = None
    joint_shape = None
    fetch_detail = None
    traceback = error.__traceback__
    while traceback is not None:
        module = traceback.tb_frame.f_globals.get("__name__")
        if module in SAFE_DIAGNOSTIC_MODULES and 1 <= traceback.tb_lineno <= 100000:
            location = f"{module}:{traceback.tb_lineno}"
        # Extract only bounded classifications from the exact frame that raised.
        # Never retain source identifiers, archive bytes, URLs, or exception text.
        frame = traceback.tb_frame
        values = frame.f_locals
        if (
            phase == "FETCH"
            and code == "ARCHIVE_RESOURCE_LIMIT"
            and module == "procurement.storage.eis_223_index"
            and frame.f_code.co_name == "preflight_notice223_window"
        ):
            raw = values.get("raw")
            if type(raw) is bytes and len(raw) > MAX_ARCHIVE_BYTES:
                fetch_detail = {"kind": "ARCHIVE_RESOURCE", "cause": "ARCHIVE_BYTES"}
            elif type(raw) is bytes:
                members, expanded = values.get("members"), values.get("archive_expanded")
                if type(members) is list and type(expanded) is int:
                    cause = (
                        "MEMBER_COUNT"
                        if len(members) > MAX_ARCHIVE_MEMBERS
                        else "EXPANDED_BYTES"
                        if expanded > MAX_ARCHIVE_EXPANDED_BYTES
                        else "MEMBER_BYTES"
                    )
                    fetch_detail = {"kind": "ARCHIVE_RESOURCE", "cause": cause}
        elif (
            phase == "FETCH"
            and code == "WINDOW_BYTES_LIMIT"
            and module == "procurement.sources.eis_223_sync"
            and frame.f_code.co_name == "fetch_notice223_day"
        ):
            size, downloaded = values.get("compressed_bytes"), values.get("downloaded")
            if (
                type(size) is int
                and type(downloaded) is dict
                and 40 * 1024**2 < size <= 64 * 1024**2
                and 0 <= len(downloaded) < 8
            ):
                fetch_detail = {
                    "kind": "WINDOW_BYTES",
                    "downloaded_count": len(downloaded) + 1,
                    "compressed_mib_floor": size // (1024**2),
                }
        elif (
            phase == "FETCH"
            and code == "ARCHIVE_SET_MISMATCH"
            and module == "procurement.sources.eis_223_event_sync"
            and frame.f_code.co_name == "bind_purchase_rejection_window"
        ):
            initial, refs, downloaded = (
                values.get("initial_uids"),
                values.get("references"),
                values.get("downloaded"),
            )
            if (
                type(initial) is list
                and isinstance(refs, (tuple, list))
                and type(downloaded) is dict
            ):
                if not 1 <= len(initial) <= 8:
                    cause = "INITIAL_COUNT"
                elif len(set(initial)) != len(initial):
                    cause = "INITIAL_DUPLICATE"
                elif len(refs) > 8:
                    cause = "PREPARED_COUNT"
                elif not (
                    all(type(uid) is str for uid in initial)
                    and all(
                        type(getattr(ref, "archive_uid", None)) is str
                        and type(getattr(ref, "url", None)) is str
                        for ref in refs
                    )
                    and all(type(url) is str for url in downloaded)
                ):
                    cause = None
                else:
                    uids = [ref.archive_uid for ref in refs]
                    cause = (
                        "PREPARED_DUPLICATE"
                        if len(set(uids)) != len(uids)
                        else "UID_MISMATCH"
                        if set(initial) != set(uids)
                        else "DOWNLOADED_MISMATCH"
                        if set(downloaded) != {ref.url for ref in refs}
                        else None
                    )
                if cause is not None:
                    fetch_detail = {"kind": "ARCHIVE_SET", "cause": cause}
        if (
            code == "JOINT_FLAG_UNSUPPORTED"
            and module == "procurement.sources.eis_223_joint_positions"
        ):
            flag = traceback.tb_frame.f_locals.get("flag")
            joint = traceback.tb_frame.f_locals.get("joint")
            if flag == "false" and isinstance(joint, Element):
                names = {
                    element.tag.rsplit("}", 1)[-1]
                    for element in joint.iter()
                    if isinstance(element.tag, str)
                }
                joint_shape = (
                    "ITEM_PRESENT"
                    if "lotItem" in names
                    else "CUSTOMER_PRESENT"
                    if "lotCustomer" in names
                    else "CONTAINER_ONLY"
                    if "lotCustomers" in names
                    else "OTHER"
                )
            code = (
                {
                    "true": "JOINT_FLAG_TRUE",
                    "false": "JOINT_FLAG_FALSE_WITH_CONTENT",
                    "1": "JOINT_FLAG_NUMERIC_TRUE",
                    "0": "JOINT_FLAG_NUMERIC_FALSE",
                }.get(flag, "JOINT_FLAG_OTHER")
                if isinstance(flag, str)
                else "JOINT_FLAG_OTHER"
            )
        traceback = traceback.tb_next
    result = {
        "phase": phase,
        "category": category,
        "sqlstate": sqlstate,
        "code": code,
        "location": location,
    }
    if joint_shape is not None:
        result["joint_shape"] = joint_shape
    if fetch_detail is not None:
        result["fetch_detail"] = fetch_detail
    return result


class CountedTransport:
    def __init__(self, transport: EisFeedTransport):
        self.transport = transport
        self.posts = 0
        self.downloads = 0

    async def post(self, xml: bytes) -> tuple[int, bytes]:
        self.posts += 1
        return await self.transport.post(xml)

    async def download(self, url: str, token: str) -> tuple[int, bytes]:
        self.downloads += 1
        return await self.transport.download(url, token)


async def refresh_catalog(storage: PostgresStorage) -> dict[str, object]:
    if not catalog_refresh_due(storage, COMPANY, datetime.now(UTC)):
        return {"status": "NOT_DUE", "source_requests": 0}
    fetched = await fetch_region_selector()
    check = record_catalog_check(
        storage,
        COMPANY,
        fetched.body or None,
        checked_at=fetched.observed_at,
        actor_id=ACTOR,
        reason=fetched.reason,
        http_status=fetched.http_status,
    )
    return {**check.model_dump(mode="json"), "source_requests": fetched.source_requests}


def recovery_windows(
    storage: PostgresStorage, now: datetime, *, limit: int
) -> tuple[RefreshTarget, ...]:
    """Only accepted national final-day debt can bypass the history guard."""
    return tuple(
        t
        for t in regional_due_windows(
            storage, COMPANY, now, limit=limit, fresh_first=True, recovery_only=True
        )
        if NATIONAL_RECOVERY_START <= t.day < now.astimezone(MSK).date() - timedelta(days=1)
    )


def mandatory_targets(
    storage: PostgresStorage,
    now: datetime,
    *,
    limit: int,
    budget: JointStartBudget | None,
) -> tuple[tuple[RefreshTarget, ...], str]:
    if budget is not None and budget.recovery_reserved("223"):
        daily = regional_due_windows(
            storage,
            COMPANY,
            now,
            limit=limit,
            fresh_first=True,
            reconciliation_only=True,
        )
        if daily:
            return daily, "RECONCILIATION"
    due = regional_due_windows(
        storage,
        COMPANY,
        now,
        limit=limit,
        fresh_first=True,
        fresh_only=True,
    )
    if due:
        return due, "MANDATORY"
    return recovery_windows(storage, now, limit=limit), "OUTAGE_RECOVERY"


def reconciliation_demand(storage: PostgresStorage, now: datetime) -> tuple[str, ...]:
    from procurement.sources.eis_freshness import EisFreshnessScope, read_due_reconciliation
    from procurement.storage.eis_sync_journal import EisSyncJournal

    with storage.transaction(COMPANY, consistent_read=True) as conn:
        catalog = _accepted_catalog(conn, COMPANY)
    if catalog is None:
        raise ValueError("OFFICIAL_REGION_CATALOG_MISSING")
    daily44 = read_due_reconciliation(
        EisSyncJournal(storage, COMPANY, ACTOR),
        EisFreshnessScope(
            tuple(sorted(catalog["regions"])), checkpointed=True, mandatory_only=True
        ),
        now=now,
        limit=1,
    )
    daily223 = regional_due_windows(
        storage,
        COMPANY,
        now,
        limit=2,
        fresh_first=True,
        reconciliation_only=True,
    )
    return tuple(law for law, due in (("44", daily44), ("223", daily223)) if due)


def recent_reconciliation_due(storage: PostgresStorage, now: datetime) -> bool:
    """Read only exact recent planned coordinates; uncertainty never means idle."""
    if now.utcoffset() is None:
        raise ValueError("PROBE_TIMEZONE_MISSING")
    local_day = now.astimezone(MSK).date()
    families = (*SUPPORTED_DOCUMENT_TYPES, "purchaseRejection", "purchaseLotCancellation")
    with storage.transaction(COMPANY, consistent_read=True) as conn:
        conn.execute(text("SET LOCAL statement_timeout = '5000ms'"))
        catalog = _accepted_catalog(conn, COMPANY)
        if catalog is None:
            raise ValueError("OFFICIAL_REGION_CATALOG_MISSING")
        coordinates = {
            f"getDocsIP/RI223/{region}/{day.isoformat()}+03:00/{family}": day
            for days in range(1, 4)
            for day in (local_day - timedelta(days=days),)
            if datetime.combine(day, datetime.min.time(), MSK)
            + timedelta(days=1, hours=2, minutes=5)
            <= now
            for region in catalog["regions"]
            for family in families
        }
        planned = set(
            conn.scalars(
                select(eis_223_region_targets.c.window_key)
                .where(
                    eis_223_region_targets.c.company_id == COMPANY,
                    eis_223_region_targets.c.window_key.in_(coordinates),
                )
                .distinct()
            )
        )
        if not planned:
            return False
        combined = union_all(
            *(
                select(
                    table.c.window_key,
                    table.c.checked_at,
                    table.c.status,
                    table.c.attempt_id,
                    table.c.response_sha256,
                ).where(
                    table.c.company_id == COMPANY,
                    table.c.window_key.in_(planned),
                )
                for table in (
                    eis_223_sync_attempts,
                    eis_223_event_sync_attempts,
                    eis_223_lot_event_sync_attempts,
                )
            )
        ).subquery()
        rows = (
            conn.execute(
                select(combined)
                .distinct(combined.c.window_key)
                .order_by(
                    combined.c.window_key,
                    combined.c.checked_at.desc(),
                    combined.c.status.not_in(("SYNCED", "NO_DATA")).desc(),
                    combined.c.attempt_id.desc(),
                )
            )
            .mappings()
            .all()
        )
    latest = {row["window_key"]: row for row in rows}
    for key in sorted(planned):
        row = latest.get(key)
        if row is None:
            return True
        if row["status"] not in {"SYNCED", "NO_DATA"}:
            if row["checked_at"] <= now - timedelta(hours=1):
                return True
            continue
        if not row["response_sha256"]:
            raise ValueError("RECONCILIATION_EVIDENCE_UNKNOWN")
        cutoff = datetime.combine(coordinates[key], datetime.min.time(), MSK) + timedelta(
            days=1,
            hours=2,
            minutes=5,
        )
        if row["checked_at"] < cutoff:
            return True
        if coordinates[key] == local_day - timedelta(days=1) and row[
            "checked_at"
        ] <= now - timedelta(hours=24):
            return True
    return False


def probe() -> dict[str, object]:
    """Read-only demand check: an idle cron must not preempt the corpus worker."""
    engine = create_engine(
        os.environ["DATABASE_URL"],
        connect_args={"options": "-c default_transaction_read_only=on -c statement_timeout=5000"},
    )
    try:
        storage = PostgresStorage(engine)
        now = datetime.now(UTC)
        coverage = read_region_coverage(storage, COMPANY, now=now)
        catalog_due = catalog_refresh_due(storage, COMPANY, now)
        # A new calendar wave is materialized only by run() under the import lease.
        new_wave_due = (
            coverage.catalog_sha256 is not None or accepted_catalog_present(storage)
        ) and (
            coverage.wave_id is None
            or (coverage.end_day is not None and coverage.end_day < now.astimezone(MSK).date())
        )
        due = regional_due_windows(
            storage, COMPANY, now, limit=2, fresh_first=True, fresh_only=True
        )
        urgent = catalog_due or new_wave_due or bool(due)
        # Recent protected work must not wait for the all-history recovery selector.
        recent_due = not urgent and recent_reconciliation_due(storage, now)
        # Final-day debt is mandatory recovery even outside the rolling pair.
        if not urgent and not recent_due and accepted_catalog_present(storage):
            due = recovery_windows(storage, now, limit=2)
        # True old history remains behind the original joint guard.
        if (
            not urgent
            and not recent_due
            and accepted_catalog_present(storage)
            and joint_mandatory_status(storage, COMPANY, now) == "IDLE"
        ):
            due = regional_due_windows(storage, COMPANY, now, limit=2, fresh_first=True)
        ready = urgent or recent_due or bool(due)
        return {
            "status": "READY" if ready else "IDLE",
            "company_id": COMPANY,
            "checked_at": now.isoformat(),
            "catalog_due": catalog_due,
            "new_wave_due": new_wave_due,
            "due_windows": len(due),
            "urgent": urgent,
            "recent_reconciliation_due": recent_due,
            "source_requests": 0,
            "coverage": "UNKNOWN",
        }
    finally:
        engine.dispose()


def accepted_catalog_present(storage: PostgresStorage) -> bool:
    # Coverage before the first wave deliberately has no catalog fields.
    with storage.transaction(COMPANY, consistent_read=True) as conn:
        return _accepted_catalog(conn, COMPANY) is not None


def optional_quality(storage: PostgresStorage, *, regional: bool) -> dict[str, object]:
    if regional and priority_requested(PRIORITY_REQUEST, now=datetime.now(UTC)):
        return {"reason": "DEFERRED_FOR_PRIORITY", "source_requests": 0}
    return quality_report(storage)


def quality_report(storage: PostgresStorage) -> dict[str, object]:
    try:
        # Alternate event families between cron slots; same two-event offline budget.
        event_worker = (
            process_event_quality_batch
            if datetime.now(UTC).minute < 30
            else process_lot_event_quality_batch
        )
        event = event_worker(storage, COMPANY, actor_id=ACTOR)
        notice = process_quality_batch(storage, COMPANY, actor_id=ACTOR).model_dump(mode="json")
        return {"events": event, "notices": notice, "source_requests": 0}
    except Exception:
        # Quality failures never rewrite the independently recorded source outcome.
        return {"reason": "QUALITY_UNAVAILABLE", "source_requests": 0, "eligibility": "UNKNOWN"}


async def run() -> dict[str, object]:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    storage = PostgresStorage(engine)
    started = perf_counter()
    regional = os.environ.get("EIS_223_REGIONAL_ENABLED") == "1"
    max_windows = REGIONAL_MAX_WINDOWS if regional else MAX_WINDOWS
    max_seconds = 2 * REGIONAL_MAX_SECONDS if regional else MAX_SECONDS
    report: dict[str, object] = {
        "company_id": COMPANY,
        "region_scope": "OFFICIAL_CATALOG" if regional else "PILOT_50",
        "document_types": list(SUPPORTED_DOCUMENT_TYPES),
        "event_types": ["purchaseRejection", "purchaseLotCancellation"],
        "coverage": "UNKNOWN",
        "freshness": "UNKNOWN",
        "attempted": 0,
    }
    budget = None
    pending_daily = ()
    try:
        if regional and os.environ.get("EIS_JOINT_BUDGET_ENABLED") == "1":
            budget = JointStartBudget(Path("/var/lib/eis-browser"), COMPANY, reservation=540)
            if not budget.can_start():
                return {**report, "reason": "JOINT_START_BUDGET_REACHED"}
        with engine.connect() as conn:
            size = conn.scalar(text("SELECT pg_database_size(current_database())"))
        if size is None or size >= MAX_DB_BYTES:
            return {**report, "reason": "DATABASE_BUDGET_REACHED"}
        if shutil.disk_usage("/var/lib/eis-browser").free < MIN_FREE_BYTES:
            return {**report, "reason": "DISK_RESERVE_REACHED"}
        if regional:
            # The public GET shares the lease and start/resource budget with this batch.
            # Rejected membership leaves the last accepted catalog usable.
            report["catalog_check"] = await refresh_catalog(storage)
            wave = ensure_region_wave(
                storage, COMPANY, datetime.now(UTC), actor_id=ACTOR, fresh_first=True
            )
            if wave is None:
                return {**report, "reason": "OFFICIAL_REGION_CATALOG_MISSING"}
            if budget is not None and budget.protected_reconciliation:
                pending_daily = reconciliation_demand(storage, datetime.now(UTC))
            due, report["lane"] = mandatory_targets(
                storage,
                datetime.now(UTC),
                limit=max_windows,
                budget=budget,
            )
            if not due:
                joint = joint_mandatory_status(storage, COMPANY, datetime.now(UTC))
                if joint != "IDLE":
                    return {
                        **report,
                        "reason": "MANDATORY_FRESH_WORK_READY"
                        if joint == "READY"
                        else "MANDATORY_DEMAND_UNAVAILABLE",
                    }
                due = regional_due_windows(
                    storage, COMPANY, datetime.now(UTC), limit=max_windows, fresh_first=True
                )
                report["lane"] = "HISTORY"
            report["wave_id"] = wave
            report["regional_coverage"] = read_region_coverage(
                storage, COMPANY, now=datetime.now(UTC)
            ).model_dump(mode="json")
        else:
            due = due_windows(storage, COMPANY, datetime.now(UTC), include_events=True)
        targets = due[:max_windows]
        report.update(
            selected_windows=len(targets),
            max_windows=max_windows,
            start_budget_seconds=max_seconds,
        )
        if not regional:
            report.update(due_windows=len(due), deferred_windows=max(0, len(due) - max_windows))
        if not targets:
            return {
                **report,
                "reason": "NOT_DUE",
                "quality": optional_quality(storage, regional=regional),
            }
        outcomes = []
        async with eis_browser_transport() as underlying_transport:
            transport = CountedTransport(underlying_transport)
            pending = list(targets)
            attempted_keys: set[str] = set()
            batches = 1
            batch_sizes = [len(pending)]
            while pending:
                if report.get("lane") == "RECONCILIATION" and (
                    budget is None or not budget.recovery_reserved("223")
                ):
                    # The bounded share ended; resume current-day updates in this turn.
                    due, report["lane"] = mandatory_targets(
                        storage,
                        datetime.now(UTC),
                        limit=max_windows,
                        budget=budget,
                    )
                    pending = [t for t in due if refresh_window_key(t) not in attempted_keys]
                    if not pending:
                        break
                    batches += 1
                    batch_sizes.append(len(pending))
                    if batches > REGIONAL_MAX_BATCHES:
                        report["stop_reason"] = "BATCH_RESELECTION_LIMIT"
                        break
                if report.get("lane") == "OUTAGE_RECOVERY":
                    current = regional_due_windows(
                        storage,
                        COMPANY,
                        datetime.now(UTC),
                        limit=max_windows,
                        fresh_first=True,
                        fresh_only=True,
                    )
                    if current:
                        if batches >= REGIONAL_MAX_BATCHES:
                            report["stop_reason"] = "BATCH_RESELECTION_LIMIT"
                            break
                        pending = [
                            t for t in current if refresh_window_key(t) not in attempted_keys
                        ]
                        if not pending:
                            break
                        report["lane"] = "MANDATORY"
                        batches += 1
                        batch_sizes.append(len(pending))
                target = pending.pop(0)
                if refresh_window_key(target) in attempted_keys:
                    continue
                # Do not starve223 with44's next cron marker: this already acquired
                # turn has a bounded180s share. A started atomic window finishes.
                if (
                    regional
                    and outcomes
                    and perf_counter() - started >= REGIONAL_MAX_SECONDS
                    and priority_requested(PRIORITY_REQUEST, now=datetime.now(UTC))
                ):
                    report["stop_reason"] = "PRIORITY_REFRESH_REQUESTED"
                    break
                if regional and report.get("lane") == "HISTORY":
                    joint = joint_mandatory_status(storage, COMPANY, datetime.now(UTC))
                    if joint != "IDLE":
                        report["stop_reason"] = (
                            "MANDATORY_FRESH_WORK_READY"
                            if joint == "READY"
                            else "MANDATORY_DEMAND_UNAVAILABLE"
                        )
                        break
                remaining = max_seconds - (perf_counter() - started)
                if remaining < 1:
                    report["stop_reason"] = "SHARED_TURN_BUDGET_REACHED"
                    break
                if regional:
                    with engine.connect() as conn:
                        size = conn.scalar(text("SELECT pg_database_size(current_database())"))
                    if size is None or size >= MAX_DB_BYTES:
                        report["stop_reason"] = "DATABASE_BUDGET_REACHED"
                        break
                    if shutil.disk_usage("/var/lib/eis-browser").free < MIN_FREE_BYTES:
                        report["stop_reason"] = "DISK_RESERVE_REACHED"
                        break
                recovery_law = (
                    "223" if report.get("lane") in {"OUTAGE_RECOVERY", "RECONCILIATION"} else None
                )
                if (
                    report.get("lane") == "OUTAGE_RECOVERY"
                    and urgent44_status(storage, COMPANY, datetime.now(UTC)) != "IDLE"
                ):
                    report["stop_reason"] = "FRESH_44_WORK_READY"
                    break
                if budget is not None:
                    if not budget.can_start(
                        recovery_law,
                        borrow=report.get("lane") == "OUTAGE_RECOVERY",
                        pending_reconciliation=pending_daily,
                    ):
                        report["stop_reason"] = "JOINT_START_BUDGET_REACHED"
                        break
                    budget.begin_window(recovery_law)
                if perf_counter() - started >= max_seconds:
                    report["stop_reason"] = "SHARED_TURN_BUDGET_REACHED"
                    break
                if (
                    regional
                    and outcomes
                    and perf_counter() - started >= REGIONAL_MAX_SECONDS
                    and priority_requested(PRIORITY_REQUEST, now=datetime.now(UTC))
                ):
                    report["stop_reason"] = "PRIORITY_REFRESH_REQUESTED"
                    break
                key = refresh_window_key(target)
                response_sha = None
                reason = None
                source_error = None
                diagnostic = None
                observed = None
                capture_allowed = False
                phase = "FETCH"
                new_versions = 0
                new_events = 0
                outcome: Outcome
                try:
                    request = (
                        (
                            fetch_purchase_lot_cancellation_day
                            if target.document_type == "purchaseLotCancellation"
                            else fetch_purchase_rejection_day
                        )(
                            COMPANY,
                            target.day,
                            os.environ["EIS_GETDOCS_IP_TOKEN"],
                            transport,
                            region=target.region,
                        )
                        if isinstance(target, Eis223EventRefreshTarget)
                        else fetch_notice223_day(
                            COMPANY,
                            target.day,
                            os.environ["EIS_GETDOCS_IP_TOKEN"],
                            transport,
                            region=target.region,
                            document_type=target.document_type,
                        )
                    )
                    # A started bounded full-set intake gets its own timeout; crossing
                    # the batch start deadline does not cancel a READY set halfway.
                    observed = await asyncio.wait_for(
                        request, timeout=WINDOW_TIMEOUT if regional else remaining
                    )
                    outcome = observed.status
                    source_error = getattr(observed, "source_error", None)
                    if outcome == "SERVICE_ERROR":
                        reason = "SERVICE_ERROR"
                    response_sha = observed.response_sha256
                    if outcome == "SYNCED":
                        phase = "INGEST"
                        if observed.window is None:
                            raise ValueError("SOURCE_WINDOW_MISSING")
                        if isinstance(target, Eis223EventRefreshTarget):
                            event_ingest = (
                                ingest_lot_event223_window
                                if target.document_type == "purchaseLotCancellation"
                                else ingest_event223_window
                            )
                            result_event = event_ingest(
                                storage, COMPANY, observed.window, actor_id=ACTOR
                            )
                            new_events = result_event.new_events
                        else:
                            result = ingest_notice223_window(
                                storage, COMPANY, observed.window, actor_id=ACTOR
                            )
                            new_versions = result.new_versions
                except TimeoutError:
                    outcome = "FAILED"
                    reason = "RUN_TIME_BUDGET_REACHED"
                    diagnostic = {
                        "phase": phase, "category": "TIMEOUT", "sqlstate": None,
                        "code": None, "location": None,
                    }
                except Exception as error:
                    # Never log raw transport/SQL details or outgoing SOAP/token.
                    outcome = "FAILED"
                    value = str(error)
                    reason = value if value in SAFE_REASONS else "SYNC_FAILED"
                    diagnostic = failure_diagnostic(error, phase)
                    capture_allowed = (
                        key == CAPTURE_KEY
                        and phase == "INGEST"
                        and observed is not None
                        and observed.status == "SYNCED"
                        and observed.window is not None
                        and getattr(observed.window, "window_key", None) == key
                        and diagnostic.get("code") == "JOINT_AMBIGUOUS_LOT_SHAPES"
                        and str(diagnostic.get("location", "")).startswith(
                            "procurement.sources.eis_223_joint_positions:"
                        )
                    )
                    if isinstance(error, EisSyncError) and value in SAFE_REASONS:
                        source_error = error.source_error
                    failure_sha = getattr(error, "source_response_sha256", None)
                    if isinstance(failure_sha, str) and re.fullmatch(r"[0-9a-f]{64}", failure_sha):
                        response_sha = failure_sha
                recorded_reason = (
                    source_error.persisted_reason(reason)
                    if source_error is not None and reason is not None
                    else reason
                )
                recorded_at = datetime.now(UTC)
                record_attempt(
                    storage,
                    COMPANY,
                    key,
                    outcome,
                    actor_id=ACTOR,
                    checked_at=recorded_at,
                    response_sha256=response_sha,
                    reason=recorded_reason,
                    **(
                        {"fetch_detail": diagnostic["fetch_detail"]}
                        if diagnostic and "fetch_detail" in diagnostic
                        else {}
                    ),
                )
                if capture_allowed:
                    try:
                        report["diagnostic_capture"] = {
                            "status": "RETAINED_AND_AUDITED",
                            "manifest_sha256": retain_failed_223(
                                storage, observed.window,
                                os.environ["EIS_GETDOCS_IP_TOKEN"], recorded_at,
                            ),
                        }
                    except Exception as error:
                        # Original FAILED is already committed; never log the payload.
                        category = _capture_failure_reason(error)
                        report["diagnostic_capture"] = {
                            "status": "UNKNOWN", "reason": category, "audit": "UNKNOWN"
                        }
                        try:
                            _audit_capture_failure(
                                storage, key, response_sha, recorded_at, category
                            )
                            report["diagnostic_capture"]["audit"] = "RECORDED"
                        except Exception:
                            pass
                attempted_keys.add(key)
                outcomes.append(
                    {
                        "window_key": key,
                        "lane": report.get("lane", "PILOT"),
                        "status": outcome,
                        "reason": recorded_reason,
                        "source_error": source_error.safe_metadata() if source_error else None,
                        "diagnostic": diagnostic,
                        "response_sha256": response_sha,
                        "new_versions": new_versions,
                        "new_events": new_events,
                    }
                )
                if budget is not None:
                    budget.end_window()
                if outcome == "SERVICE_ERROR" or (
                    outcome not in {"SYNCED", "NO_DATA"}
                    and (
                        not regional
                        or reason in {"SOURCE_TRANSPORT_FAILED", "XML_TOKEN_REFLECTION_REJECTED"}
                    )
                ):
                    break
                # Re-select bounded32 batches after their successful intake; never
                # revisit a terminal row before its existing recheck deadline.
                if regional and not pending and perf_counter() - started < max_seconds:
                    due, report["lane"] = mandatory_targets(
                        storage,
                        datetime.now(UTC),
                        limit=max_windows,
                        budget=budget,
                    )
                    pending = [t for t in due if refresh_window_key(t) not in attempted_keys]
                    if pending and batches >= REGIONAL_MAX_BATCHES:
                        report["stop_reason"] = "BATCH_RESELECTION_LIMIT"
                        break
                    if pending:
                        batches += 1
                        batch_sizes.append(len(pending))
            report["max_selected_batches"] = REGIONAL_MAX_BATCHES
            report["selected_batches"] = batches
            report["selected_windows_per_batch"] = batch_sizes
            report["selected_windows_total"] = sum(batch_sizes)
            report.update(source_posts=transport.posts, archive_gets=transport.downloads)
        if regional:
            report["regional_coverage"] = read_region_coverage(
                storage, COMPANY, now=datetime.now(UTC)
            ).model_dump(mode="json")
        return {
            **report,
            "attempted": len(outcomes),
            "outcomes": outcomes,
            "seconds": perf_counter() - started,
            "budget_overrun_seconds": max(0, perf_counter() - started - max_seconds),
            "quality": (
                {"reason": "DEFERRED_FOR_PRIORITY", "source_requests": 0}
                if report.get("stop_reason") == "PRIORITY_REFRESH_REQUESTED"
                else optional_quality(storage, regional=regional)
            ),
        }
    finally:
        try:
            if budget is not None:
                budget.close()
        finally:
            engine.dispose()


if __name__ == "__main__":
    try:
        import argparse

        parser = argparse.ArgumentParser(description=__doc__)
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--probe", action="store_true")
        mode.add_argument("--capture-reconcile", action="store_true")
        arguments = parser.parse_args()
        if arguments.capture_reconcile:
            engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
            try:
                digest = reconcile_failed_223(
                    PostgresStorage(engine), CAPTURE_ROOT, os.environ["EIS_GETDOCS_IP_TOKEN"]
                )
                result = {"status": "RETAINED_AND_AUDITED", "manifest_sha256": digest,
                          "source_requests": 0, "coverage": "UNKNOWN"}
            finally:
                engine.dispose()
        else:
            result = probe() if arguments.probe else asyncio.run(run())
        print(json.dumps(result, ensure_ascii=False))
    except Exception:
        print(
            json.dumps(
                {
                    "company_id": COMPANY,
                    "reason": "REFRESH_UNAVAILABLE",
                    "coverage": "UNKNOWN",
                    "freshness": "UNKNOWN",
                }
            )
        )
        raise SystemExit(1) from None
