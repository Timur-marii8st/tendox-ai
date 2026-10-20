"""Bounded evidence-only notice hold tests; no database or source calls."""

from contextlib import contextmanager

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from procurement.storage.eis_notice_hold import (
    EisNoticeSourceHold,
    assert_notice_source_usable,
    notice_receipt_integrity_hold_clause,
    notice_variant_hold_clause,
    read_notice_source_hold,
)


class Scalars:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return iter(self._values)


class Connection:
    def __init__(self, scalars, receipts=()):
        self.values = iter(scalars)
        self.receipts = receipts

    def scalar(self, _statement):
        return next(self.values)

    def execute(self, _statement):
        return Scalars(self.receipts)


class Storage:
    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def transaction(self, company_id, *, consistent_read=False):
        assert company_id == "tenant-a" and consistent_read is True
        yield self.connection


def test_predicate_covers_same_or_newer_variants_origins_and_incomplete_receipts():
    sql = str(
        notice_variant_hold_clause("tenant-a", "0" * 19, 7).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "eis_notice_variants.version_number >= 7" in sql
    assert "eis_notice_variant_origins.version_number >= 7" in sql
    assert "eis_notice_variant_receipts.occurrence_count" in sql
    assert "eis_notice_variant_origins.receipt_id" in sql


def test_receipt_integrity_predicate_is_separable_for_one_tenant_wide_check():
    sql = str(
        notice_receipt_integrity_hold_clause("tenant-a").compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "eis_notice_variant_receipts.company_id = 'tenant-a'" in sql
    assert "eis_notice_variant_receipts.occurrence_count" in sql
    assert "eis_notice_variants" not in sql


def test_assert_rejects_any_evidence_and_allows_no_evidence():
    assert_notice_source_usable(Connection([False]), "tenant-a", "0" * 19, 1)
    with pytest.raises(ValueError, match=r"^NOTICE_VARIANT_REVIEW_REQUIRED$"):
        assert_notice_source_usable(Connection([True]), "tenant-a", "0" * 19, 1)


def test_read_returns_singleton_hold_with_bounded_provenance():
    result = read_notice_source_hold(
        Storage(Connection([False, 1, 1, True], ["receipt-1"])),
        "tenant-a",
        "0" * 19,
        4,
    )
    assert result.status == "HOLD"
    assert result.variant_count == result.origin_count == 1
    assert result.receipt_ids == ("receipt-1",)
    assert result.evidence_scope == "EVIDENCE_ONLY" and result.resolution == "UNKNOWN"


def test_read_is_no_hold_only_for_empty_complete_ledger():
    result = read_notice_source_hold(
        Storage(Connection([False, 0, 0], [])), "tenant-a", "0" * 19, 2
    )
    assert result.status == "NO_HOLD" and not result.receipt_ids


def test_incomplete_tenant_receipt_fails_closed_without_claiming_purchase_provenance():
    result = read_notice_source_hold(Storage(Connection([True, 0, 0], [])), "tenant-a", "0" * 19, 2)
    assert result.status == "INTEGRITY_ERROR"
    assert not result.receipt_ids


def test_model_does_not_allow_no_hold_with_evidence():
    with pytest.raises(ValueError, match="NOTICE_SOURCE_HOLD_INVALID"):
        EisNoticeSourceHold(
            purchase_number="0" * 19,
            selected_version_number=1,
            status="NO_HOLD",
            variant_count=1,
            origin_count=0,
        )


def test_resolved_source_stays_unknown_for_supplier_eligibility():
    result = read_notice_source_hold(
        Storage(Connection([False, 1, 1, False], ["receipt-1"])), "tenant-a", "0" * 19, 2
    )
    assert result.status == "NO_HOLD" and result.resolution == "UNKNOWN"


def test_many_resolved_receipts_do_not_create_a_different_metadata_hold():
    result = read_notice_source_hold(
        Storage(Connection([False, 1, 21, False], [str(n) for n in range(21)])),
        "tenant-a",
        "0" * 19,
        2,
    )
    assert result.status == "NO_HOLD" and result.resolution == "UNKNOWN"


def test_discharge_requires_exact_audited_projection_and_global_singleton():
    sql = str(
        notice_variant_hold_clause("tenant-a", "0" * 19, 7).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    for binding in (
        "projection_decision.xml_sha256",
        "projected_notice.xml_sha256",
        "EIS_NOTICE_PROJECTION_RECORDED",
        "VARIANT_TRANSPORT",
        "projection_origin.member_filename",
        "projection_variant.document_type",
        "audited_batch.payload_sha256",
    ):
        assert binding in sql


def test_audit_array_is_expanded_once_for_both_hold_branches():
    sql = str(
        select(notice_variant_hold_clause("tenant-a", "0" * 19, 1)).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert sql.count("audited_projection_decisions AS MATERIALIZED") == 1
    assert sql.count("jsonb_array_elements") == 1
    assert "jsonb_typeof" in sql and "audited_projection_decisions.decision =" in sql
