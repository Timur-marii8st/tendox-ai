"""Conservative grouping of exact reviewed manufacturer identities."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from procurement.domain.manufacturer_review import LegalIdentity, ReviewStatus


class DirectoryCoverage(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class DirectoryReason(StrEnum):
    REVIEW_COVERAGE_INCOMPLETE = "REVIEW_COVERAGE_INCOMPLETE"
    REGISTRY_DOCUMENT_EXPIRED = "REGISTRY_DOCUMENT_EXPIRED"
    REGISTRY_DOCUMENT_CURRENT_STATUS_UNKNOWN = "REGISTRY_DOCUMENT_CURRENT_STATUS_UNKNOWN"
    REVIEW_MISSING = "REVIEW_MISSING"
    REVIEW_UNKNOWN = "REVIEW_UNKNOWN"
    REVIEW_FAIL = "REVIEW_FAIL"
    IDENTITY_CONFLICT = "IDENTITY_CONFLICT"
    LEGAL_NAME_CONFLICT = "LEGAL_NAME_CONFLICT"
    INDEPENDENT_REVIEW_PASS = "INDEPENDENT_REVIEW_PASS"


class ManufacturerKey(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    country_code: str
    identifier_scheme: str
    registration_id: str


class DirectoryReviewEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    proposal_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")
    decision_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    dossier_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    identity: LegalIdentity
    current_status: ReviewStatus

    @model_validator(mode="after")
    def decision_pair(self) -> DirectoryReviewEvidence:
        if (self.decision_id is None) != (self.decision_sha256 is None):
            raise ValueError("MANUFACTURER_DIRECTORY_DECISION_PAIR_INVALID")
        if self.decision_id is None and self.current_status is not ReviewStatus.UNKNOWN:
            raise ValueError("MANUFACTURER_DIRECTORY_MISSING_DECISION_NOT_UNKNOWN")
        return self


class DirectoryRecordInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    record_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    source_record_index: int = Field(ge=1, le=10)
    registry_number: str
    product_name: str
    source_manufacturer_name: str
    record_url: str
    document_expires_on: date | None
    reviews: tuple[DirectoryReviewEvidence, ...] = Field(max_length=20)


class DirectoryRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    record_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    source_record_index: int = Field(ge=1, le=10)
    registry_number: str
    product_name: str
    source_manufacturer_name: str
    record_url: str
    document_expires_on: date | None
    source_status: Literal["FAIL", "UNKNOWN"]
    review_status: ReviewStatus
    status: ReviewStatus
    reason_codes: tuple[DirectoryReason, ...]
    review_evidence: tuple[DirectoryReviewEvidence, ...]


class ManufacturerGroup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    key: ManufacturerKey
    legal_name: str
    record_ids: tuple[str, ...]
    product_names: tuple[str, ...]
    status: Literal["PASS", "UNKNOWN"]
    reason_codes: tuple[DirectoryReason, ...]
    proposal_ids: tuple[str, ...]
    decision_sha256s: tuple[str, ...]


class ManufacturerDirectory(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["manufacturer-directory-v1"] = "manufacturer-directory-v1"
    run_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    evaluated_at: AwareDatetime
    coverage: DirectoryCoverage
    overall_status: ReviewStatus
    review_count: int = Field(ge=0, le=20)
    records: tuple[DirectoryRecord, ...] = Field(max_length=10)
    groups: tuple[ManufacturerGroup, ...] = Field(max_length=10)
    unreviewed_record_ids: tuple[str, ...]
    technical: Literal["UNKNOWN"] = "UNKNOWN"
    seller: Literal["UNKNOWN"] = "UNKNOWN"
    website: Literal["UNKNOWN"] = "UNKNOWN"
    quote: Literal["UNKNOWN"] = "UNKNOWN"
    participation: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def coverage_is_conservative(self) -> ManufacturerDirectory:
        if self.coverage is DirectoryCoverage.INCOMPLETE and (
            self.groups or any(record.status is ReviewStatus.PASS for record in self.records)
        ):
            raise ValueError("MANUFACTURER_DIRECTORY_INCOMPLETE_HAS_PASS")
        return self


def _key(identity: LegalIdentity) -> ManufacturerKey:
    return ManufacturerKey(
        country_code=identity.country_code,
        identifier_scheme=identity.identifier_scheme,
        registration_id=identity.registration_id,
    )


def build_directory(
    run_id: str,
    inputs: tuple[DirectoryRecordInput, ...],
    *,
    response_sha256: str | None,
    coverage: DirectoryCoverage,
    review_count: int,
    reviewed_record_ids: frozenset[str] | None = None,
    evaluated_at: datetime | None = None,
) -> ManufacturerDirectory:
    """Apply fail precedence and group only exact confirmed legal-identity keys."""
    instant = evaluated_at or datetime.now(UTC)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("MANUFACTURER_DIRECTORY_TIME_NAIVE")
    if len(inputs) > 10 or len({item.record_id for item in inputs}) != len(inputs):
        raise ValueError("MANUFACTURER_DIRECTORY_RECORDS_INVALID")
    records: list[DirectoryRecord] = []
    resolved: dict[str, tuple[ManufacturerKey, str, tuple[DirectoryReviewEvidence, ...]]] = {}
    for item in sorted(inputs, key=lambda value: value.source_record_index):
        source_fail = (
            item.document_expires_on is not None
            and item.document_expires_on < instant.astimezone(UTC).date()
        )
        reasons = [
            DirectoryReason.REGISTRY_DOCUMENT_EXPIRED
            if source_fail
            else DirectoryReason.REGISTRY_DOCUMENT_CURRENT_STATUS_UNKNOWN
        ]
        review_status = ReviewStatus.UNKNOWN
        if coverage is DirectoryCoverage.INCOMPLETE:
            reasons.append(DirectoryReason.REVIEW_COVERAGE_INCOMPLETE)
        elif not item.reviews:
            reasons.append(DirectoryReason.REVIEW_MISSING)
        elif any(review.current_status is ReviewStatus.FAIL for review in item.reviews):
            review_status = ReviewStatus.FAIL
            reasons.append(DirectoryReason.REVIEW_FAIL)
        elif any(review.current_status is ReviewStatus.UNKNOWN for review in item.reviews):
            reasons.append(DirectoryReason.REVIEW_UNKNOWN)
        else:
            identities = {
                (_key(review.identity), review.identity.legal_name) for review in item.reviews
            }
            keys = {key.model_dump_json() for key, _ in identities}
            names = {name for _, name in identities}
            if len(keys) > 1:
                reasons.append(DirectoryReason.IDENTITY_CONFLICT)
            elif len(names) > 1:
                reasons.append(DirectoryReason.LEGAL_NAME_CONFLICT)
            else:
                review_status = ReviewStatus.PASS
                key, name = next(iter(identities))
                resolved[item.record_id] = (key, name, item.reviews)
                reasons.append(DirectoryReason.INDEPENDENT_REVIEW_PASS)
        status = (
            ReviewStatus.FAIL
            if source_fail or review_status is ReviewStatus.FAIL
            else review_status
        )
        records.append(
            DirectoryRecord(
                **item.model_dump(exclude={"reviews"}),
                source_status="FAIL" if source_fail else "UNKNOWN",
                review_status=review_status,
                status=status,
                reason_codes=tuple(reasons),
                review_evidence=item.reviews,
            )
        )

    GroupValue = tuple[
        DirectoryRecord, ManufacturerKey, str, tuple[DirectoryReviewEvidence, ...]
    ]
    by_key: dict[str, list[GroupValue]] = {}
    for record in records:
        if record.status is ReviewStatus.PASS and record.record_id in resolved:
            key, name, reviews = resolved[record.record_id]
            by_key.setdefault(key.model_dump_json(), []).append((record, key, name, reviews))
    groups: list[ManufacturerGroup] = []
    conflicted_records: set[str] = set()
    for values in by_key.values():
        names = {value[2] for value in values}
        conflict = len(names) > 1
        if conflict:
            conflicted_records.update(value[0].record_id for value in values)
        reviews = tuple(review for value in values for review in value[3])
        groups.append(
            ManufacturerGroup(
                key=values[0][1],
                legal_name=sorted(names)[0] if len(names) == 1 else "UNKNOWN",
                record_ids=tuple(value[0].record_id for value in values),
                product_names=tuple(value[0].product_name for value in values),
                status="UNKNOWN" if conflict else "PASS",
                reason_codes=(
                    (DirectoryReason.LEGAL_NAME_CONFLICT,)
                    if conflict
                    else (DirectoryReason.INDEPENDENT_REVIEW_PASS,)
                ),
                proposal_ids=tuple(review.proposal_id for review in reviews),
                decision_sha256s=tuple(
                    review.decision_sha256
                    for review in reviews
                    if review.decision_sha256 is not None
                ),
            )
        )
    if conflicted_records:
        records = [
            record.model_copy(
                update={
                    "review_status": ReviewStatus.UNKNOWN,
                    "status": ReviewStatus.UNKNOWN,
                    "reason_codes": (
                        *(
                            reason
                            for reason in record.reason_codes
                            if reason is not DirectoryReason.INDEPENDENT_REVIEW_PASS
                        ),
                        DirectoryReason.LEGAL_NAME_CONFLICT,
                    ),
                }
            )
            if record.record_id in conflicted_records
            else record
            for record in records
        ]
    if coverage is DirectoryCoverage.INCOMPLETE:
        groups = []
    statuses = {record.status for record in records}
    overall = (
        ReviewStatus.UNKNOWN
        if coverage is DirectoryCoverage.INCOMPLETE or not records
        else ReviewStatus.FAIL
        if ReviewStatus.FAIL in statuses
        else ReviewStatus.UNKNOWN
        if ReviewStatus.UNKNOWN in statuses
        else ReviewStatus.PASS
    )
    linked = reviewed_record_ids or frozenset(
        record.record_id for record in records if record.review_evidence
    )
    return ManufacturerDirectory(
        run_id=run_id,
        response_sha256=response_sha256,
        evaluated_at=instant,
        coverage=coverage,
        overall_status=overall,
        review_count=review_count,
        records=tuple(records),
        groups=tuple(groups),
        unreviewed_record_ids=tuple(
            record.record_id for record in records if record.record_id not in linked
        ),
    )
