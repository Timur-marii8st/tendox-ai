"""Comparisons cannot turn a ceiling, stale XML or missing quote into a profit rank."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from procurement.storage.eis_evidence_bridge import build_eis_evidence_bridge
from test_eis_evidence_bridge import NOW, UID, sample


def two_bridges():
    notice, collection, analysis = sample(deadline=NOW + timedelta(days=1))
    first = build_eis_evidence_bridge(notice, collection, {UID: analysis}, (), now=NOW)
    ref = first.notice.model_copy(update={"purchase_number": "0848300054826000155"})
    second = first.model_copy(
        update={"notice": ref, "collection": collection.model_copy(update={"notice": ref})}
    )
    return first, second


def test_ceiling_and_missing_quote_never_create_profit_order():
    from procurement.storage.eis_comparison import EisComparisonRequest, build_eis_comparison

    bridges = two_bridges()
    request = EisComparisonRequest(notices=tuple(item.notice for item in bridges))
    result = build_eis_comparison(request, bridges, now=NOW)
    assert result.profit_order_status == result.coverage == "UNKNOWN"
    assert [row.evidence.notice for row in result.rows] == list(request.notices)
    assert all(row.readiness_status == "NEEDS_ANALYSIS" for row in result.rows)
    assert all(row.evidence.requirement_status == "UNKNOWN" for row in result.rows)
    assert result.rows[0].deadline_provenance.document_id == bridges[0].notice.notice_xml_sha256
    assert result.rows[0].deadline_provenance.locator.endswith("collectingInfo/endDT")


def test_stale_and_expired_are_blocked_even_with_high_ceiling():
    from procurement.storage.eis_comparison import EisComparisonRequest, build_eis_comparison

    first, second = two_bridges()
    first = first.model_copy(
        update={"collection": first.collection.model_copy(update={"version_status": "STALE"})}
    )
    second = second.model_copy(
        update={"application_status": "FAIL", "application_reasons": ("DEADLINE_EXPIRED",)}
    )
    bridges = first, second
    result = build_eis_comparison(
        EisComparisonRequest(notices=(first.notice, second.notice)), bridges, now=NOW
    )
    assert all(row.readiness_status == "BLOCKED" for row in result.rows)
    assert result.rows[0].blocking_reasons == ("NOTICE_VERSION_STALE",)
    assert "DEADLINE_EXPIRED" in result.rows[1].blocking_reasons
    assert result.profit_order_status == "UNKNOWN"


def test_duplicate_and_unbounded_or_tenant_payload_rejected():
    from procurement.storage.eis_comparison import EisComparisonRequest

    first, second = two_bridges()
    for refs in ((first.notice,), (first.notice, first.notice), (first.notice, second.notice) * 2):
        with pytest.raises(ValidationError):
            EisComparisonRequest(notices=refs)
    with pytest.raises(ValidationError):
        EisComparisonRequest.model_validate(
            {
                "notices": [first.notice.model_dump(), second.notice.model_dump()],
                "company_id": "someone-else",
            }
        )


def test_source_hold_blocks_cached_comparison_without_supplier_fail():
    from procurement.storage.eis_comparison import comparison44_row
    from procurement.storage.eis_document_store import EisDocumentReadGate

    first, _ = two_bridges()
    gate = EisDocumentReadGate(
        checked_at=NOW,
        notice=first.notice,
        blocked_reasons=("NOTICE_VARIANT_REVIEW_REQUIRED",),
        evidence=("Evidence-only ledger requires review.",),
    )
    held = first.model_copy(
        update={"collection": first.collection.model_copy(update={"read_gate": gate})}
    )
    row = comparison44_row(held)
    assert row.readiness_status == "BLOCKED"
    assert row.blocking_reasons == ("NOTICE_VARIANT_REVIEW_REQUIRED",)
    assert row.evidence.application_status == "UNKNOWN"


def test_comparison_rejects_wrong_ref_or_time_basis():
    from procurement.storage.eis_comparison import EisComparisonRequest, build_eis_comparison

    first, second = two_bridges()
    request = EisComparisonRequest(notices=(first.notice, second.notice))
    with pytest.raises(ValueError, match="EIS_COMPARISON_REFERENCE_MISMATCH"):
        build_eis_comparison(request, (second, first), now=NOW)
    with pytest.raises(ValueError, match="NOW_TIMEZONE_MISSING"):
        build_eis_comparison(request, (first, second), now=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="EIS_COMPARISON_TIME_MISMATCH"):
        build_eis_comparison(request, (first, second), now=NOW + timedelta(seconds=1))
