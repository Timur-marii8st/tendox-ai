"""Append-only catalog observations; failed checks never replace accepted membership."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from sqlalchemy import func, insert, select

from procurement.sources.eis_223_regions import REGION_SELECTOR_URL, inspect_region_catalog
from procurement.sources.eis_feed_sync import EisSyncError
from procurement.storage.eis_223_regions import _accepted_catalog, _audit
from procurement.storage.eis_223_sync import _aware
from procurement.storage.models import eis_223_region_catalog_checks as checks
from procurement.storage.models import eis_223_region_catalogs as catalogs

if TYPE_CHECKING:
    from procurement.storage.repository import PostgresStorage

FETCH_FAILURES = frozenset(
    {
        "BODY_BYTES_LIMIT",
        "HTTP_REJECTED",
        "REDIRECT_REJECTED",
        "SOURCE_URL_MISMATCH",
        "TIMEOUT",
        "TRANSPORT_FAILED",
    }
)


class CatalogCheck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    company_id: str
    attempt_id: str
    checked_at: datetime
    status: Literal["ACCEPTED", "FAILED", "REVIEW_REQUIRED"]
    catalog_sha256: str | None
    response_sha256: str | None
    http_status: int | None
    reason: str | None

    @field_validator("checked_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        _aware(value)
        return value

    @model_validator(mode="after")
    def consistent(self) -> CatalogCheck:
        if self.status == "ACCEPTED":
            if (
                not self.catalog_sha256
                or self.response_sha256 != self.catalog_sha256
                or self.http_status != 200
                or self.reason is not None
            ):
                raise ValueError("CATALOG_CHECK_OUTCOME_INVALID")
        elif self.catalog_sha256 is not None or not self.reason:
            raise ValueError("CATALOG_CHECK_OUTCOME_INVALID")
        return self


def catalog_refresh_due(storage: PostgresStorage, company: str, now: datetime) -> bool:
    _aware(now)
    with storage.transaction(company, consistent_read=True) as conn:
        last = (
            conn.execute(
                select(checks.c.checked_at, checks.c.status)
                .where(checks.c.company_id == company)
                .order_by(
                    checks.c.checked_at.desc(),
                    (checks.c.status != "ACCEPTED").desc(),
                    checks.c.attempt_id.desc(),
                )
                .limit(1)
            )
            .mappings()
            .first()
        )
        if last is None:
            return True  # Bootstrap lacks an observation journal; make one real check.
        if now < last["checked_at"]:
            raise ValueError("CATALOG_CHECK_CLOCK_SKEW")
        return bool(
            now - last["checked_at"] >= timedelta(hours=24 if last["status"] == "ACCEPTED" else 1)
        )


def record_catalog_check(
    storage: PostgresStorage,
    company: str,
    content: bytes | None,
    *,
    checked_at: datetime,
    actor_id: str,
    reason: str | None = None,
    attempt_id: str | None = None,
    http_status: int | None = 200,
) -> CatalogCheck:
    _aware(checked_at)
    identity = attempt_id or str(uuid4())
    if not identity.strip() or len(identity) > 100 or not actor_id.strip():
        raise ValueError("CATALOG_CHECK_IDENTITY_INVALID")
    if reason is not None and reason not in FETCH_FAILURES:
        raise ValueError("CATALOG_CHECK_REASON_INVALID")
    if content is not None and not 1 <= len(content) <= 524288:
        raise ValueError("CATALOG_CHECK_BODY_INVALID")
    if content is None and reason is None:
        raise ValueError("CATALOG_CHECK_EVIDENCE_REQUIRED")
    if http_status is not None and not 100 <= http_status <= 599:
        raise ValueError("CATALOG_CHECK_HTTP_INVALID")
    if reason is None and http_status != 200:
        raise ValueError("CATALOG_CHECK_HTTP_INVALID")
    response_sha = hashlib.sha256(content).hexdigest() if content is not None else None
    catalog = None
    if reason is None:
        assert content is not None and response_sha is not None
        try:
            catalog = inspect_region_catalog(
                content,
                source_url=REGION_SELECTOR_URL,
                response_sha256=response_sha,
                observed_at=checked_at,
            )
        except EisSyncError:
            reason = "REGION_CATALOG_REJECTED"
    with storage.transaction(company) as conn:
        conn.scalar(
            select(func.pg_advisory_xact_lock(func.hashtextextended(company + "/223-regions", 0)))
        )
        previous = (
            conn.execute(
                select(checks).where(
                    checks.c.company_id == company, checks.c.attempt_id == identity
                )
            )
            .mappings()
            .first()
        )
        if previous is not None:
            if (
                previous["checked_at"] != checked_at
                or previous["response_sha256"] != response_sha
                or previous["http_status"] != http_status
            ):
                raise ValueError("CATALOG_CHECK_REPLAY_CONFLICT")
            # Parser failure has a canonical persisted reason; never reinterpret replay.
            if reason is not None and previous["reason"] != reason:
                raise ValueError("CATALOG_CHECK_REPLAY_CONFLICT")
            if reason is None and previous["status"] == "FAILED":
                raise ValueError("CATALOG_CHECK_REPLAY_CONFLICT")
            return CatalogCheck.model_validate(
                {key: previous[key] for key in CatalogCheck.model_fields}
            )
        accepted = _accepted_catalog(conn, company)
        status: Literal["ACCEPTED", "FAILED", "REVIEW_REQUIRED"] = "FAILED"
        if catalog is not None:
            if accepted and not set(accepted["regions"]) <= set(catalog.regions):
                status, reason = "REVIEW_REQUIRED", "REGION_CATALOG_MEMBERSHIP_REVIEW_REQUIRED"
            else:
                status = "ACCEPTED"
                exists = conn.scalar(
                    select(catalogs.c.catalog_sha256).where(
                        catalogs.c.company_id == company, catalogs.c.catalog_sha256 == response_sha
                    )
                )
                if exists is None:
                    conn.execute(
                        insert(catalogs).values(
                            company_id=company, content=content, **catalog.model_dump()
                        )
                    )
                    _audit(
                        conn,
                        company,
                        actor_id,
                        "EIS_223_REGION_CATALOG_RETAINED",
                        catalog.catalog_sha256,
                        checked_at,
                        {
                            "catalog_sha256": response_sha,
                            "regions": len(catalog.regions),
                            "coverage": "UNKNOWN",
                        },
                    )
        result = CatalogCheck(
            company_id=company,
            attempt_id=identity,
            checked_at=checked_at,
            status=status,
            catalog_sha256=response_sha if status == "ACCEPTED" else None,
            response_sha256=response_sha,
            http_status=http_status,
            reason=reason,
        )
        conn.execute(
            insert(checks).values(
                **result.model_dump(), rejected_content=content if status != "ACCEPTED" else None
            )
        )
        _audit(
            conn,
            company,
            actor_id,
            "EIS_223_REGION_CATALOG_CHECKED",
            identity,
            checked_at,
            result.model_dump(mode="json"),
        )
        return result
