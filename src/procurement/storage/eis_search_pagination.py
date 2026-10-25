"""Read-only continuation bound to tenant, query, clock and exact result evidence."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections import OrderedDict
from collections.abc import Iterable
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import chain
from threading import Lock
from time import monotonic
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StrictInt

Rank44 = tuple[StrictBool, StrictBool, StrictBool, Decimal, StrictInt, str]
Rank223 = tuple[StrictBool, StrictBool, StrictBool, StrictInt, str]
GlobalRank = tuple[StrictBool, StrictBool, Decimal, str, str]
Rank = Rank44 | Rank223 | GlobalRank
PAGE_TTL = timedelta(minutes=15)


class SearchComparisonMemo:
    """Process-local disposable comparison bytes; never caches live SQL evidence."""

    def __init__(self, *, max_bytes: int = 32 * 1024**2, max_entries: int = 128) -> None:
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self._entries: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
        self._bytes = 0
        self._lock = Lock()

    @staticmethod
    def key(
        company: str,
        law: str,
        query: str,
        at: datetime,
        *inputs: bytes,
        chunks: Iterable[bytes] = (),
    ) -> str:
        digest = hashlib.sha256(_canonical((company, law, query, at.isoformat())))
        for value in chain(inputs, chunks):
            digest.update(len(value).to_bytes(8, "big"))
            digest.update(value)
        return digest.hexdigest()

    def get(self, key: str) -> bytes | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires, value = entry
            if expires <= monotonic():
                self._bytes -= len(self._entries.pop(key)[1])
                return None
            self._entries.move_to_end(key)
            return value

    def put(self, key: str, value: bytes) -> None:
        # Retained payload bytes are bounded independently of source batch size.
        # Oversize values and eviction are misses, never truncated comparisons.
        if len(value) > self.max_bytes:
            return
        with self._lock:
            previous = self._entries.pop(key, None)
            if previous is not None:
                self._bytes -= len(previous[1])
            self._entries[key] = (monotonic() + PAGE_TTL.total_seconds(), value)
            self._bytes += len(value)
            while self._bytes > self.max_bytes or len(self._entries) > self.max_entries:
                self._bytes -= len(self._entries.popitem(last=False)[1][1])

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._bytes = 0


PAGE_COMPARISONS = SearchComparisonMemo()


class SearchPageError(ValueError):
    """An invalid or changed continuation must not silently mix result pages."""


class SearchCursor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    version: Literal[1] = 1
    law: Literal["44", "223", "all"]
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_at: AwareDatetime
    after: Rank

    def encode(self) -> str:
        return base64.urlsafe_b64encode(self.model_dump_json().encode()).decode().rstrip("=")


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


class SearchPagination:
    """Hash the full matching stream while keeping only one bounded result page."""

    def __init__(
        self,
        *,
        company: str,
        law: Literal["44", "223", "all"],
        query: str,
        scope: str,
        now: datetime,
        cursor: str | None,
    ) -> None:
        if not company.strip() or now.utcoffset() is None:
            raise SearchPageError("SEARCH_PAGE_INVALID")
        self.law = law
        self.context = hashlib.sha256(
            _canonical(
                {
                    "company": company,
                    "law": law,
                    "query": query.strip(),
                    "scope": scope,
                    "order_version": 1,
                }
            )
        ).hexdigest()
        self.cursor: SearchCursor | None = None
        if cursor is not None:
            try:
                if not 1 <= len(cursor) <= 2048 or re.fullmatch(r"[A-Za-z0-9_-]+", cursor) is None:
                    raise ValueError
                decoded = base64.b64decode(
                    cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True
                )
                self.cursor = SearchCursor.model_validate_json(decoded)
                if (
                    self.cursor.law != law
                    or (law == "223" and type(self.cursor.after[2]) is not bool)
                    or (
                        law == "all"
                        and (
                            len(self.cursor.after) != 5 or self.cursor.after[3] not in {"44", "223"}
                        )
                    )
                    or self.cursor.context_sha256 != self.context
                    or len(self.cursor.after) != (6 if law == "44" else 5)
                    or re.fullmatch(r"[0-9]{11,23}", self.cursor.after[-1]) is None
                ):
                    raise ValueError
            except ValueError as error:
                raise SearchPageError("SEARCH_PAGE_INVALID") from error
            if self.cursor.snapshot_at > now or now - self.cursor.snapshot_at > PAGE_TTL:
                raise SearchPageError("SEARCH_PAGE_EXPIRED")
        self.at = self.cursor.snapshot_at if self.cursor else now
        self.digest = hashlib.sha256(
            _canonical({"context": self.context, "at": self.at.isoformat()})
        )
        self.boundary_seen = self.cursor is None
        self.remaining = 0

    def observe(self, key: Rank, evidence: object) -> bool:
        """Hash every match, including those before the current page boundary."""
        payload = _canonical(evidence)
        self.digest.update(len(payload).to_bytes(8, "big"))
        self.digest.update(payload)
        if self.cursor is not None and key == self.cursor.after:
            self.boundary_seen = True
        after = self.cursor is None or key > self.cursor.after
        self.remaining += after
        return after

    def finish(self, last_key: Rank | None, returned: int) -> tuple[str, str | None]:
        fingerprint = self.digest.hexdigest()
        if self.cursor is not None and (
            not self.boundary_seen or fingerprint != self.cursor.snapshot_sha256
        ):
            raise SearchPageError("SEARCH_PAGE_CHANGED")
        next_cursor = None
        if last_key is not None and self.remaining > returned:
            next_cursor = SearchCursor(
                law=self.law,
                context_sha256=self.context,
                snapshot_sha256=fingerprint,
                snapshot_at=self.at,
                after=last_key,
            ).encode()
        return fingerprint, next_cursor
