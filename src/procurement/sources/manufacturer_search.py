"""Persistable bounded capture of the fixed EAEU product-registry search."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from time import monotonic
from typing import Literal

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from procurement.sources.eaeu_registry import (
    EAEU_REGISTRY_URL,
    RegistryCandidate,
    RegistrySourceError,
    _request_body,
    _validated_query,
    parse_eaeu_registry_response,
)
from procurement.sources.http_transport import public_source_client

MAX_RESPONSE_BYTES = 512 * 1024


class ManufacturerCandidate(BaseModel):
    """Source-declared manufacturer; no commercial or identity inference."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_record_index: int = Field(ge=1, le=10)
    record_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    registry_number: str = Field(min_length=1, max_length=80)
    product_name: str = Field(min_length=1, max_length=500)
    manufacturer_name: str = Field(min_length=1, max_length=500)
    record_url: str
    document_expires_on: date | None
    document_validity: Literal["FAIL", "UNKNOWN"]
    document_validity_reason: Literal[
        "EXPIRED", "EXPIRY_UNKNOWN", "CURRENT_STATUS_UNVERIFIED"
    ]
    role: Literal["MANUFACTURER_SOURCE_DECLARATION"] = "MANUFACTURER_SOURCE_DECLARATION"
    identity: Literal["UNKNOWN"] = "UNKNOWN"
    website: Literal["UNKNOWN"] = "UNKNOWN"
    seller: Literal["UNKNOWN"] = "UNKNOWN"
    brand: Literal["UNKNOWN"] = "UNKNOWN"
    technical: Literal["UNKNOWN"] = "UNKNOWN"
    quote: Literal["UNKNOWN"] = "UNKNOWN"


class ManufacturerSourceCapture(BaseModel):
    """Exact request/response capture returned by one network attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    query: str
    observed_at: AwareDatetime
    request_body: bytes
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["COMPLETED", "SOURCE_ERROR"]
    reason_code: Literal["VERIFIED_RESPONSE", "SOURCE_UNAVAILABLE_OR_CHANGED"]
    response_body: bytes | None = None
    response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    matched_count: int | None = Field(default=None, ge=0)
    candidates: tuple[RegistryCandidate, ...] = ()

    @model_validator(mode="after")
    def consistent(self) -> ManufacturerSourceCapture:
        if hashlib.sha256(self.request_body).hexdigest() != self.request_sha256:
            raise ValueError("MANUFACTURER_REQUEST_DIGEST_CONFLICT")
        if self.response_body is not None:
            if len(self.response_body) > MAX_RESPONSE_BYTES:
                raise ValueError("MANUFACTURER_RESPONSE_TOO_LARGE")
            if hashlib.sha256(self.response_body).hexdigest() != self.response_sha256:
                raise ValueError("MANUFACTURER_RESPONSE_DIGEST_CONFLICT")
        elif self.response_sha256 is not None:
            raise ValueError("MANUFACTURER_RESPONSE_DIGEST_CONFLICT")
        if self.status == "COMPLETED":
            if self.response_body is None or self.matched_count is None:
                raise ValueError("MANUFACTURER_COMPLETED_EVIDENCE_MISSING")
        elif self.matched_count is not None or self.candidates:
            raise ValueError("MANUFACTURER_ERROR_CANNOT_HAVE_RESULTS")
        return self


def normalized_manufacturer_query(query: str) -> tuple[str, bytes]:
    """Validate the public query contract and return its exact request bytes."""
    terms = _validated_query(query)
    normalized = " ".join(terms)
    return normalized, _request_body(terms)


def capture_manufacturer_search(query: str) -> ManufacturerSourceCapture:
    """Perform exactly one bounded request to the fixed EAEU collection."""
    normalized, body = normalized_manufacturer_query(query)
    observed_at = datetime.now(UTC)
    deadline = monotonic() + 30
    content: bytes | None = None
    try:
        with (
            public_source_client() as client,
            client.stream(
                "POST",
                EAEU_REGISTRY_URL,
                content=body,
                headers={"Content-Type": "text/plain"},
            ) as response,
        ):
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                if monotonic() > deadline:
                    raise RegistrySourceError("registry response exceeded wall budget")
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise RegistrySourceError("registry response exceeds the limit")
                chunks.append(chunk)
            content = b"".join(chunks)
            if response.status_code != 200 or "application/json" not in response.headers.get(
                "content-type", ""
            ):
                raise RegistrySourceError("registry did not return JSON 200")
        if monotonic() > deadline:
            raise RegistrySourceError("registry response exceeded wall budget")
        parsed = parse_eaeu_registry_response(
            content, query=normalized, request_body=body, observed_at=observed_at
        )
        return ManufacturerSourceCapture(
            query=normalized,
            observed_at=observed_at,
            request_body=body,
            request_sha256=parsed.request_sha256,
            status="COMPLETED",
            reason_code="VERIFIED_RESPONSE",
            response_body=content,
            response_sha256=parsed.response_sha256,
            matched_count=parsed.matched_count,
            candidates=parsed.candidates,
        )
    except (httpx.HTTPError, RegistrySourceError):
        return ManufacturerSourceCapture(
            query=normalized,
            observed_at=observed_at,
            request_body=body,
            request_sha256=hashlib.sha256(body).hexdigest(),
            status="SOURCE_ERROR",
            reason_code="SOURCE_UNAVAILABLE_OR_CHANGED",
            response_body=content,
            response_sha256=hashlib.sha256(content).hexdigest() if content is not None else None,
        )
