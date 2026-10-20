"""Directory grouping uses exact reviewed identity keys and fail precedence."""

from __future__ import annotations

from datetime import UTC, date, datetime

from procurement.domain.manufacturer_directory import (
    DirectoryCoverage,
    DirectoryReason,
    DirectoryRecordInput,
    DirectoryReviewEvidence,
    build_directory,
)
from procurement.domain.manufacturer_review import LegalIdentity, ReviewStatus

NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)


def review(
    *,
    proposal: int = 1,
    name: str = "Factory LLC",
    country: str = "RU",
    scheme: str = "INN",
    registration: str = "123",
    status: ReviewStatus = ReviewStatus.PASS,
) -> DirectoryReviewEvidence:
    return DirectoryReviewEvidence(
        proposal_id=f"00000000-0000-0000-0000-{proposal:012d}",
        proposal_sha256=f"{proposal:x}".rjust(64, "0"),
        decision_id=f"10000000-0000-0000-0000-{proposal:012d}",
        decision_sha256=f"{proposal + 20:x}".rjust(64, "0"),
        dossier_sha256=f"{proposal + 40:x}".rjust(64, "0"),
        identity=LegalIdentity(
            legal_name=name,
            country_code=country,
            identifier_scheme=scheme,
            registration_id=registration,
        ),
        current_status=status,
    )


def record(index: int, *reviews: DirectoryReviewEvidence, expiry=None):
    return DirectoryRecordInput(
        record_id=f"{index:024x}",
        source_record_index=index,
        registry_number=str(index),
        product_name=f"Product {index}",
        source_manufacturer_name="Registry Factory",
        record_url=f"https://example.test/{index}",
        document_expires_on=expiry,
        reviews=reviews,
    )


def directory(*records, coverage=DirectoryCoverage.COMPLETE, review_count=None):
    return build_directory(
        "00000000-0000-0000-0000-000000000099",
        records,
        response_sha256="a" * 64,
        coverage=coverage,
        review_count=(
            sum(len(item.reviews) for item in records)
            if review_count is None
            else review_count
        ),
        evaluated_at=NOW,
    )


def test_exact_key_groups_products_without_promoting_unknown_fields() -> None:
    result = directory(record(1, review(proposal=1)), record(2, review(proposal=2)))
    assert result.overall_status is ReviewStatus.PASS
    assert len(result.groups) == 1 and result.groups[0].record_ids == (f"{1:024x}", f"{2:024x}")
    assert result.groups[0].key.registration_id == "123"
    assert result.technical == result.seller == result.website == result.quote == "UNKNOWN"
    assert result.participation == "UNKNOWN"


def test_each_key_part_is_significant() -> None:
    result = directory(
        record(1, review(proposal=1, country="RU", scheme="INN", registration="1")),
        record(2, review(proposal=2, country="BY", scheme="INN", registration="1")),
        record(3, review(proposal=3, country="RU", scheme="OGRN", registration="1")),
        record(4, review(proposal=4, country="RU", scheme="INN", registration="2")),
    )
    assert len(result.groups) == 4


def test_conflicts_never_choose_one_identity_or_name() -> None:
    identity = directory(
        record(1, review(proposal=1, registration="1"), review(proposal=2, registration="2"))
    )
    assert identity.records[0].status is ReviewStatus.UNKNOWN
    assert DirectoryReason.IDENTITY_CONFLICT in identity.records[0].reason_codes
    names = directory(
        record(1, review(proposal=3, name="Factory A")),
        record(2, review(proposal=4, name="Factory B")),
    )
    assert names.groups[0].status == "UNKNOWN"
    assert all(item.status is ReviewStatus.UNKNOWN for item in names.records)
    assert all(DirectoryReason.LEGAL_NAME_CONFLICT in item.reason_codes for item in names.records)


def test_fail_precedence_source_expiry_and_unknown_review() -> None:
    result = directory(
        record(1, review(status=ReviewStatus.PASS), expiry=date(2026, 10, 5)),
        record(2, review(proposal=2, status=ReviewStatus.FAIL)),
        record(3),
    )
    assert [item.status for item in result.records] == [
        ReviewStatus.FAIL,
        ReviewStatus.FAIL,
        ReviewStatus.UNKNOWN,
    ]
    assert result.overall_status is ReviewStatus.FAIL
    assert result.unreviewed_record_ids == (f"{3:024x}",)


def test_overflow_disables_all_groups_and_passes() -> None:
    result = directory(
        record(1, review()), coverage=DirectoryCoverage.INCOMPLETE, review_count=20
    )
    assert result.overall_status is ReviewStatus.UNKNOWN and result.groups == ()
    assert result.records[0].status is ReviewStatus.UNKNOWN
    assert DirectoryReason.REVIEW_COVERAGE_INCOMPLETE in result.records[0].reason_codes


def test_empty_directory_is_unknown() -> None:
    assert directory().overall_status is ReviewStatus.UNKNOWN
