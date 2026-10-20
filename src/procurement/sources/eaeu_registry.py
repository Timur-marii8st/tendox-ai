"""Bounded read-only search in the EAEU public industrial-product registry.

The registry publishes its collection URL in the official /erpt/assets/config.json.
These records identify possible manufacturers, not offers, stock or quotes.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from procurement.sources.http_transport import public_source_client

EAEU_REGISTRY_URL = (
    "https://goszakupki.eaeunion.org/spd/find"
    "?collection=erpt.v_goodscollection_prod_public"
    "&limit=10&sort=%7B%22publishdate%22%3A-1%7D"
)
EAEU_RECORD_BASE = "https://goszakupki.eaeunion.org/erpt/ru/registers/products/list/card/"
_MAX_RESPONSE_BYTES = 512 * 1024
_RECORD_ID = re.compile(r"[0-9a-f]{24}\Z")


class RegistrySourceError(ValueError):
    """The public registry was unavailable or changed its response contract."""


class RegistryFetchStatus(StrEnum):
    COMPLETED = "COMPLETED"
    SOURCE_ERROR = "SOURCE_ERROR"


class RegistryCandidate(BaseModel):
    """One source-reported product and company; suitability stays UNKNOWN."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_record_index: int = Field(ge=1, le=10)
    record_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    registry_number: str = Field(min_length=1, max_length=80)
    product_name: str = Field(min_length=1, max_length=500)
    manufacturer_name: str = Field(min_length=1, max_length=500)
    record_url: str
    document_expires_on: date | None
    suitability: Literal["UNKNOWN"] = "UNKNOWN"


class RegistrySearchResult(BaseModel):
    """Ephemeral, exact-response provenance for a single authenticated search."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str
    fetch_status: RegistryFetchStatus
    source_url: str = EAEU_REGISTRY_URL
    observed_at: datetime
    request_sha256: str
    response_sha256: str | None = None
    response_byte_size: int | None = None
    matched_count: int | None = None
    candidates: tuple[RegistryCandidate, ...] = ()
    error_code: str | None = None


def _validated_query(query: str) -> tuple[str, ...]:
    normalized = " ".join(query.split())
    terms = tuple(normalized.split(" "))
    if (
        not normalized
        or len(normalized) > 80
        or not 1 <= len(terms) <= 5
        or any(ord(character) < 32 for character in query)
    ):
        raise ValueError("query must contain 1–5 printable words and at most 80 characters")
    return terms


def _request_body(terms: tuple[str, ...]) -> bytes:
    filters = [
        {"goodsname": {"$regex": re.escape(term), "$options": "i"}} for term in terms
    ]
    if len(filters) == 1:
        value: object = filters[0]
    else:
        value = {"$and": filters}
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def parse_eaeu_registry_response(
    content: bytes, *, query: str, request_body: bytes, observed_at: datetime
) -> RegistrySearchResult:
    """Reject malformed/truncated JSON rather than reporting an empty search."""
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise RegistrySourceError("observed_at must be timezone-aware")
    if not content or len(content) > _MAX_RESPONSE_BYTES:
        raise RegistrySourceError("response size is invalid")
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, ValueError) as error:
        raise RegistrySourceError("response is not valid JSON") from error
    if not isinstance(payload, dict):
        raise RegistrySourceError("response is not an object")
    records = payload.get("result")
    matched = payload.get("matchedDocuments")
    if (
        not isinstance(records, list)
        or len(records) > 10
        or not isinstance(matched, int)
        or isinstance(matched, bool)
        or matched < len(records)
    ):
        raise RegistrySourceError("response count or result shape changed")
    candidates: list[RegistryCandidate] = []
    seen: set[str] = set()
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict) or not isinstance(record.get("_id"), dict):
            raise RegistrySourceError("registry record shape changed")
        record_id = record["_id"].get("$oid")
        name = record.get("goodsname")
        manufacturer = record.get("name")
        number = record.get("registrynumber")
        expiry = record.get("expertactenddate")
        if (
            not isinstance(record_id, str)
            or not _RECORD_ID.fullmatch(record_id)
            or record_id in seen
            or not isinstance(name, str)
            or not name.strip()
            or not isinstance(manufacturer, str)
            or not manufacturer.strip()
            or not isinstance(number, str)
            or not number.strip()
            or (expiry is not None and not isinstance(expiry, str))
        ):
            raise RegistrySourceError("registry record fields changed")
        try:
            expiry_date = date.fromisoformat(expiry) if expiry else None
            candidate = RegistryCandidate(
                source_record_index=index,
                record_id=record_id,
                registry_number=number.strip(),
                product_name=name.strip(),
                manufacturer_name=manufacturer.strip(),
                record_url=EAEU_RECORD_BASE + record_id,
                document_expires_on=expiry_date,
            )
        except ValueError as error:
            raise RegistrySourceError("registry record date or value is invalid") from error
        seen.add(record_id)
        candidates.append(candidate)
    return RegistrySearchResult(
        query=query,
        fetch_status=RegistryFetchStatus.COMPLETED,
        observed_at=observed_at,
        request_sha256=hashlib.sha256(request_body).hexdigest(),
        response_sha256=hashlib.sha256(content).hexdigest(),
        response_byte_size=len(content),
        matched_count=matched,
        candidates=tuple(candidates),
    )


def search_eaeu_registry(query: str) -> RegistrySearchResult:
    """Call only the published EAEU collection, once, without redirects or credentials."""
    terms = _validated_query(query)
    normalized = " ".join(terms)
    body = _request_body(terms)
    observed_at = datetime.now(UTC)
    try:
        with (
            public_source_client() as client,
            client.stream(
                "POST", EAEU_REGISTRY_URL, content=body,
                headers={"Content-Type": "text/plain"},
            ) as response,
        ):
            if response.status_code != 200 or "application/json" not in response.headers.get(
                "content-type", ""
            ):
                raise RegistrySourceError("registry did not return JSON 200")
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > _MAX_RESPONSE_BYTES:
                    raise RegistrySourceError("registry response exceeds the limit")
                chunks.append(chunk)
        return parse_eaeu_registry_response(
            b"".join(chunks), query=normalized, request_body=body, observed_at=observed_at
        )
    except (httpx.HTTPError, RegistrySourceError):
        return RegistrySearchResult(
            query=normalized,
            fetch_status=RegistryFetchStatus.SOURCE_ERROR,
            observed_at=observed_at,
            request_sha256=hashlib.sha256(body).hexdigest(),
            error_code="SOURCE_UNAVAILABLE_OR_CHANGED",
        )
