"""Bounded read-only lookup in the EAEU public manufacturer collection."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from procurement.sources.eaeu_registry import (
    RegistryFetchStatus,
    RegistrySourceError,
    _validated_query,
)
from procurement.sources.http_transport import public_source_client

EAEU_MANUFACTURERS_URL = (
    "https://goszakupki.eaeunion.org/spd/find"
    "?collection=erpt.v_RegisterOfManufacturers_publish&limit=10"
)
EAEU_MANUFACTURERS_PAGE = "https://goszakupki.eaeunion.org/erpt/ru/registers/products/map"
_MAX_RESPONSE_BYTES = 512 * 1024
_RECORD_ID = re.compile(r"[0-9a-f]{24}\Z")


class ManufacturerCandidate(BaseModel):
    """Source-named manufacturer; product fit and current standing remain unknown."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_record_index: int = Field(ge=1, le=10)
    record_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    identity_code: str = Field(min_length=1, max_length=80)
    manufacturer_name: str = Field(min_length=1, max_length=500)
    member_state_code: str | None = None
    suitability: Literal["UNKNOWN"] = "UNKNOWN"


class ManufacturerSearchResult(BaseModel):
    """Ephemeral lookup with exact request and response provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str
    fetch_status: RegistryFetchStatus
    source_url: str = EAEU_MANUFACTURERS_URL
    observed_at: datetime
    request_sha256: str
    response_sha256: str | None = None
    response_byte_size: int | None = None
    matched_count: int | None = None
    candidates: tuple[ManufacturerCandidate, ...] = ()
    error_code: str | None = None


def _request_body(terms: tuple[str, ...]) -> bytes:
    filters = [{"name": {"$regex": re.escape(term), "$options": "i"}} for term in terms]
    if len(filters) == 1:
        value: object = filters[0]
    else:
        value = {"$and": filters}
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def parse_manufacturer_response(
    content: bytes, *, query: str, request_body: bytes, observed_at: datetime
) -> ManufacturerSearchResult:
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
    candidates: list[ManufacturerCandidate] = []
    seen: set[str] = set()
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict) or not isinstance(record.get("_id"), dict):
            raise RegistrySourceError("manufacturer record shape changed")
        record_id = record["_id"].get("$oid")
        name = record.get("name")
        identity = record.get("identitycode")
        state = record.get("statemember")
        if (
            not isinstance(record_id, str)
            or not _RECORD_ID.fullmatch(record_id)
            or record_id in seen
            or not isinstance(name, str)
            or not name.strip()
            or not isinstance(identity, str)
            or not identity.strip()
            or (state is not None and (not isinstance(state, str) or len(state) > 10))
        ):
            raise RegistrySourceError("manufacturer record fields changed")
        candidates.append(
            ManufacturerCandidate(
                source_record_index=index,
                record_id=record_id,
                identity_code=identity.strip(),
                manufacturer_name=name.strip(),
                member_state_code=state,
            )
        )
        seen.add(record_id)
    return ManufacturerSearchResult(
        query=query,
        fetch_status=RegistryFetchStatus.COMPLETED,
        observed_at=observed_at,
        request_sha256=hashlib.sha256(request_body).hexdigest(),
        response_sha256=hashlib.sha256(content).hexdigest(),
        response_byte_size=len(content),
        matched_count=matched,
        candidates=tuple(candidates),
    )


def search_eaeu_manufacturers(query: str) -> ManufacturerSearchResult:
    """Search company names only; never convert errors into zero matches."""
    terms = _validated_query(query)
    normalized = " ".join(terms)
    body = _request_body(terms)
    observed_at = datetime.now(UTC)
    try:
        with (
            public_source_client() as client,
            client.stream(
                "POST", EAEU_MANUFACTURERS_URL, content=body,
                headers={"Content-Type": "text/plain"},
            ) as response,
        ):
            if response.status_code != 200 or "application/json" not in response.headers.get(
                "content-type", ""
            ):
                raise RegistrySourceError("manufacturer registry did not return JSON 200")
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > _MAX_RESPONSE_BYTES:
                    raise RegistrySourceError("manufacturer response exceeds the limit")
                chunks.append(chunk)
        return parse_manufacturer_response(
            b"".join(chunks), query=normalized, request_body=body, observed_at=observed_at
        )
    except (httpx.HTTPError, RegistrySourceError):
        return ManufacturerSearchResult(
            query=normalized,
            fetch_status=RegistryFetchStatus.SOURCE_ERROR,
            observed_at=observed_at,
            request_sha256=hashlib.sha256(body).hexdigest(),
            error_code="SOURCE_UNAVAILABLE_OR_CHANGED",
        )
