"""Bounded offline queue under the existing server import lock; no source requests."""

from __future__ import annotations

import hashlib
import re
from contextlib import ExitStack
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Literal
from zipfile import ZipFile

from pydantic import BaseModel, ConfigDict, Field

from procurement.sources.eis_223_archive import inspect_notice223_archive
from procurement.sources.eis_223_schema import load_schema_tree, validate_notice223_schema
from procurement.storage.eis_223_quality import pending_schema_targets, record_schema_check

if TYPE_CHECKING:
    from procurement.storage.repository import PostgresStorage


class QualityBatchResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    selected: int = Field(ge=0, le=2)
    attempted: int = Field(ge=0, le=2)
    new_checks: int = Field(ge=0, le=4)
    failed_checks: int = Field(ge=0, le=4)
    source_requests: Literal[0] = 0
    eligibility: Literal["UNKNOWN"] = "UNKNOWN"
    reason: Literal["COMPLETED", "NOT_DUE", "TIME_BUDGET_REACHED"]


def process_quality_batch(
    storage: PostgresStorage,
    company: str,
    *,
    actor_id: str,
    schema_base: Path = Path("/var/lib/eis-browser/research/223"),
) -> QualityBatchResult:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", company) or not actor_id.strip():
        raise ValueError("QUALITY_SCOPE_INVALID")
    started = perf_counter()
    targets = pending_schema_targets(storage, company)
    if not targets:
        return QualityBatchResult(
            selected=0, attempted=0, new_checks=0, failed_checks=0, reason="NOT_DUE"
        )
    if len(targets) > 2:
        raise ValueError("QUALITY_BATCH_LIMIT")
    archives = {target.archive_sha256: target.content for target in targets}
    if sum(len(raw) for raw in archives.values()) > 32 * 1024**2:
        raise ValueError("QUALITY_BYTE_BUDGET_REACHED")
    trees = tuple(
        load_schema_tree(schema_base / company / f"schemas-{release}", release)
        for release in ("16.2", "16.3")
    )
    validated: set[tuple[str, str]] = set()
    attempted = new = failed = 0
    now = datetime.now(UTC)
    with ExitStack() as stack:
        opened: dict[str, ZipFile] = {}
        for target in targets:
            if perf_counter() - started >= 30:
                break
            digest, notice = target.archive_sha256, target.notice
            raw = archives[digest]
            key = (digest, notice.document_type)
            if key not in validated:
                if hashlib.sha256(raw).hexdigest() != digest:
                    raise ValueError("QUALITY_ARCHIVE_SHA_MISMATCH")
                inspect_notice223_archive(
                    raw,
                    company_id=company,
                    source_response_sha256="0" * 64,
                    source_locator="saved-immutable-archive",
                    document_type=notice.document_type,
                )
                validated.add(key)
            if digest not in opened:
                opened[digest] = stack.enter_context(ZipFile(BytesIO(raw)))
            content = opened[digest].read(notice.source_member)
            for tree in trees:
                check = validate_notice223_schema(notice, content, tree, now=now)
                new += record_schema_check(storage, company, check, actor_id=actor_id)
                failed += check.status == "FAIL"
            attempted += 1
    return QualityBatchResult(
        selected=len(targets),
        attempted=attempted,
        new_checks=new,
        failed_checks=failed,
        reason="COMPLETED" if attempted == len(targets) else "TIME_BUDGET_REACHED",
    )
