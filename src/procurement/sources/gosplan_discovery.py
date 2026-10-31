"""Bounded Gosplan discovery. Provider data is a hint, not an official notice."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import httpx

Law = Literal["44", "223"]
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 100
MAX_OFFSET = 1000


class GosplanError(ValueError):
    """A safe error code; retained bytes are never included in its message."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.source_raw: bytes | None = None


@dataclass(frozen=True)
class Candidate:
    law: Law
    number: str
    document_type: str
    updated_raw: str | None
    response_sha256: str
    observed_at: datetime
    position: int


@dataclass(frozen=True)
class Page:
    candidates: tuple[Candidate, ...]
    response_sha256: str
    may_have_more: bool
    raw: bytes


def parse_page(raw: bytes, law: Law, observed_at: datetime, limit: int) -> Page:
    """Parse a complete page without treating provider timestamps as aware facts."""
    if law not in ("44", "223") or not 1 <= limit <= MAX_ROWS:
        raise GosplanError("SCOPE_INVALID")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise GosplanError("OBSERVATION_TIME_INVALID")
    if not raw or len(raw) > MAX_BYTES:
        raise GosplanError("RESPONSE_SIZE_INVALID")
    try:
        rows = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise GosplanError("RESPONSE_JSON_INVALID") from exc
    if not isinstance(rows, list) or len(rows) > limit:
        raise GosplanError("RESPONSE_SHAPE_INVALID")
    digest = hashlib.sha256(raw).hexdigest()
    found: list[Candidate] = []
    seen: set[str] = set()
    for position, row in enumerate(rows):
        if not isinstance(row, dict):
            raise GosplanError("ROW_INVALID")
        number, kind, updated = (
            row.get("purchase_number"),
            row.get("purchase_type"),
            row.get("updated_at"),
        )
        if not isinstance(number, str) or not re.fullmatch(
            r"\d{19}" if law == "44" else r"\d{11}", number
        ):
            raise GosplanError("NUMBER_INVALID")
        if number in seen:
            raise GosplanError("DUPLICATE_NUMBER")
        if not isinstance(kind, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,99}", kind):
            raise GosplanError("TYPE_INVALID")
        if updated is not None and (not isinstance(updated, str) or len(updated) > 80):
            raise GosplanError("UPDATED_INVALID")
        seen.add(number)
        found.append(Candidate(law, number, kind, updated, digest, observed_at, position))
    return Page(tuple(found), digest, len(rows) == limit, raw)


def inspect_null_type_page(
    raw: bytes, law: Law, observed_at: datetime, limit: int
) -> tuple[Page, tuple[tuple[int, str], ...]]:
    """Strictly validate a quarantined page while retaining null rows as unresolved gaps.

    This never makes a null type valid. The original bytes and hash remain the
    provenance for every returned hint; no replacement value is persisted.
    """
    try:
        parse_page(raw, law, observed_at, limit)
    except GosplanError as error:
        if str(error) != "TYPE_INVALID":
            raise
    else:
        raise GosplanError("PAGE_NOT_REJECTED")
    rows = json.loads(raw)
    gaps = tuple(
        (i, row.get("purchase_number"))
        for i, row in enumerate(rows)
        if isinstance(row, dict) and "purchase_type" in row and row["purchase_type"] is None
    )
    if not gaps:
        raise GosplanError("NULL_TYPE_NOT_FOUND")
    checked = [dict(row) if isinstance(row, dict) else row for row in rows]
    for position, _ in gaps:
        checked[position]["purchase_type"] = "UnresolvedType"
    validated = parse_page(
        json.dumps(checked, ensure_ascii=False, separators=(",", ":")).encode(),
        law, observed_at, limit,
    )
    digest = hashlib.sha256(raw).hexdigest()
    gap_positions = {position for position, _ in gaps}
    candidates = tuple(
        Candidate(item.law, item.number, item.document_type, item.updated_raw,
                  digest, item.observed_at, item.position)
        for item in validated.candidates if item.position not in gap_positions
    )
    return Page(candidates, digest, validated.may_have_more, raw), gaps


def fetch_page(
    client: httpx.Client,
    key: str,
    law: Law,
    *,
    start: datetime,
    end: datetime,
    offset: int = 0,
    limit: int = 100,
    now: datetime,
) -> Page:
    """Fetch one explicit update interval with a bounded body and no redirects."""
    if (
        law not in ("44", "223")
        or not key
        or "\n" in key
        or "\r" in key
        or not 1 <= limit <= MAX_ROWS
        or not 0 <= offset <= MAX_OFFSET
        or start.tzinfo is None
        or start.utcoffset() is None
        or end.tzinfo is None
        or end.utcoffset() is None
        or start >= end
    ):
        raise GosplanError("SCOPE_INVALID")
    url = f"https://v2.gosplan.info/fz{law}/purchases"
    try:
        with client.stream(
            "GET",
            url,
            params={
                "updated_after": start.isoformat(),
                "updated_before": end.isoformat(),
                "limit": limit,
                "skip": offset,
            },
            headers={"apikey": key, "Accept": "application/json"},
            follow_redirects=False,
        ) as response:
            if response.status_code != 200:
                raise GosplanError(f"HTTP_{response.status_code}")
            chunks = bytearray()
            for chunk in response.iter_bytes():
                chunks.extend(chunk)
                if len(chunks) > MAX_BYTES:
                    raise GosplanError("RESPONSE_SIZE_INVALID")
    except httpx.HTTPError as exc:
        raise GosplanError("TRANSPORT_ERROR") from exc
    if key.encode() in chunks:
        raise GosplanError("TOKEN_REFLECTION_REJECTED")
    try:
        return parse_page(bytes(chunks), law, now, limit)
    except GosplanError as exc:
        # Only bounded, token-checked response bytes can enter the protected quarantine.
        exc.source_raw = bytes(chunks)
        raise


def classify(page: Page, present: set[str]) -> tuple[tuple[Candidate, str], ...]:
    """Existing IDs still require version verification; missing IDs require EIS intake."""
    return tuple(
        (row, "VERSION_UNKNOWN" if row.number in present else "MISSING_NOTICE")
        for row in page.candidates
    )
