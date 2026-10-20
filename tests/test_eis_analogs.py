"""Synthetic analog dimensions never invent equivalence, counts or recommendations."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from procurement.sources.eis_analogs import (
    AnalogCandidateOmission,
    AnalogReport,
    AnalogRequest,
    build_analog_report,
)
from procurement.storage.eis_analogs import _notice

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


def notice(number="0" * 19, **changes):
    item = {
        "name": "Бумага A4",
        "ktru_code": "17.12.14.110-00000001",
        "okpd2_code": "17.12.14.110",
        "quantity": "100",
        "unit": "пачка",
        "locator": "object[1]",
    }
    item.update(changes.pop("item", {}))
    row = dict(
        purchase_number=number,
        version_number=1,
        xml_sha256=("a" if number == "0" * 19 else "b") * 64,
        source_member="notice.xml",
        document_type="epNotificationEF2020",
        published_at=NOW - timedelta(days=10),
        deadline=NOW - timedelta(days=2),
        lot_parse_status="PARSED",
        lot_items=[item],
    )
    row.update(changes)
    return _notice(row)


def assess(**changes):
    target = notice()
    candidate = notice("1" * 19, published_at=NOW - timedelta(days=15), **changes)
    request = AnalogRequest(target=target.notice, source_index=1, query="бумага")
    return build_analog_report(request, target, (candidate,), now=NOW, selection_truncated=False)


def criteria(report):
    return {c.dimension: c for c in report.rows[0].criteria}


def test_matching_retrieval_dimensions_never_become_confirmed_analog_or_forecast():
    result = assess()
    checks = criteria(result)
    assert [checks[d].status for d in ("SUBJECT", "VOLUME", "PERIOD", "HISTORY")] == ["PASS"] * 4
    assert checks["TECHNICAL"].status == checks["DELIVERY_REGION"].status == "UNKNOWN"
    assert (
        result.rows[0].comparability == "UNKNOWN" and result.rows[0].disposition == "NEEDS_REVIEW"
    )
    assert result.profit == result.participation == result.competition_prediction == "UNKNOWN"
    assert result.coverage == result.lexical_recall == "UNKNOWN"
    assert {p.document_id for p in checks["SUBJECT"].evidence} == {"a" * 64, "b" * 64}


def test_conflicting_known_ktru_is_not_salvaged_by_equal_name_or_okpd():
    result = assess(item={"ktru_code": "other"})
    assert criteria(result)["SUBJECT"].reason == "KTRU_CONFLICT"
    assert result.rows[0].disposition == "EXCLUDED" and result.rows[0].comparability == "FAIL"


def test_fallback_is_whole_normalized_name_and_exact_code():
    assert (
        criteria(assess(item={"ktru_code": None, "name": "  БУМАГА   A4 "}))["SUBJECT"].status
        == "PASS"
    )
    assert (
        criteria(assess(item={"ktru_code": None, "name": "Бумага A3"}))["SUBJECT"].status == "FAIL"
    )
    assert (
        criteria(assess(item={"ktru_code": None, "okpd2_code": None}))["SUBJECT"].status
        == "UNKNOWN"
    )


@pytest.mark.parametrize(
    "quantity,status",
    [
        ("50", "PASS"),
        ("200", "PASS"),
        ("49.999999999999", "FAIL"),
        ("200.000000000001", "FAIL"),
        (None, "UNKNOWN"),
        ("0", "UNKNOWN"),
        ("NaN", "UNKNOWN"),
    ],
)
def test_decimal_volume_boundaries_are_exact(quantity, status):
    assert criteria(assess(item={"quantity": quantity}))["VOLUME"].status == status


def test_unit_names_are_retrieval_labels_and_missing_unit_stays_unknown():
    assert criteria(assess(item={"unit": "ПАЧКА"}))["VOLUME"].status == "PASS"
    assert criteria(assess(item={"unit": "лист"}))["VOLUME"].status == "FAIL"
    assert criteria(assess(item={"unit": None}))["VOLUME"].status == "UNKNOWN"
    with pytest.raises(ValueError, match="ANALOG_INEXACT_QUANTITY"):
        assess(item={"quantity": 1.2})


def test_huge_quantity_is_rejected_before_repeated_render_and_unknown_has_both_sources():
    from decimal import Decimal

    from procurement.sources.eis_analogs import AnalogFact

    with pytest.raises(ValueError, match="ANALOG_QUANTITY_LIMIT"):
        assess(item={"quantity": "1" * 200000})
    with pytest.raises(ValidationError, match="ANALOG_QUANTITY_LIMIT"):
        AnalogFact[Decimal](
            value=Decimal("1" * 1000), provenance=notice().positions[0].quantity.provenance
        )
    with pytest.raises(ValidationError, match="ANALOG_QUANTITY_LIMIT"):
        AnalogFact[Decimal](value="1" * 100, provenance=notice().positions[0].quantity.provenance)
    target = notice()
    candidate = notice("1" * 19, lot_items=[])
    req = AnalogRequest(target=target.notice, source_index=1, query="бумага")
    report = build_analog_report(req, target, (candidate,), now=NOW, selection_truncated=False)
    for check in report.rows[0].criteria:
        assert {p.document_id for p in check.evidence} == {"a" * 64, "b" * 64}


def test_missing_target_publication_never_defaults_to_now_and_future_is_rejected():
    target = notice(published_at=None)
    req = AnalogRequest(target=target.notice, source_index=1, query="бумага")
    result = build_analog_report(req, target, (), now=NOW, selection_truncated=False)
    assert (
        result.period_start is result.period_end is None
        and "TARGET_PUBLICATION_MISSING" in result.reasons
    )
    target = notice(published_at=NOW + timedelta(days=1))
    req = req.model_copy(update={"target": target.notice})
    with pytest.raises(ValueError, match="PUBLICATION_FUTURE"):
        build_analog_report(req, target, (), now=NOW, selection_truncated=False)


def test_period_and_deadline_unknown_or_failed_never_pass():
    assert criteria(assess(deadline=None))["HISTORY"].status == "UNKNOWN"
    assert criteria(assess(deadline=NOW + timedelta(seconds=1)))["HISTORY"].status == "FAIL"
    target = notice()
    req = AnalogRequest(target=target.notice, source_index=1, query="бумага", lookback_days=1)
    candidate = notice("1" * 19, published_at=NOW - timedelta(days=30))
    result = build_analog_report(req, target, (candidate,), now=NOW, selection_truncated=True)
    assert criteria(result)["PERIOD"].status == "FAIL" and result.selection_truncated


def test_counts_are_positions_not_competitors_and_uninspected_positions_are_explicit():
    target = notice()
    candidate = notice("1" * 19)
    candidate = candidate.model_copy(update={"positions_total": 30})
    req = AnalogRequest(target=target.notice, source_index=1, query="бумага")
    report = build_analog_report(req, target, (candidate,), now=NOW, selection_truncated=False)
    assert (
        report.selected_notices == report.evaluated_positions == 1
        and report.uninspected_positions == 29
    )
    assert "competitor_count" not in report.model_dump()
    with pytest.raises(ValueError, match="DUPLICATE_OR_SELF"):
        build_analog_report(req, target, (target,), now=NOW, selection_truncated=False)
    with pytest.raises(ValueError, match="TARGET_POSITION_NOT_FOUND"):
        build_analog_report(
            req.model_copy(update={"source_index": 2}),
            target,
            (),
            now=NOW,
            selection_truncated=False,
        )


def test_omissions_are_bounded_exact_refs_and_never_evaluation_rows():
    target = notice()
    admitted = notice("1" * 19)
    omitted = notice("2" * 19)
    request = AnalogRequest(target=target.notice, source_index=1, query="бумага")
    omission = AnalogCandidateOmission(
        notice=omitted.notice,
        reason="CANDIDATE_TOTAL_PAYLOAD_LIMIT",
        payload_bytes=101,
        limit_bytes=100,
    )
    report = build_analog_report(
        request,
        target,
        (admitted,),
        now=NOW,
        selection_truncated=False,
        omitted_candidates=(omission,),
    )
    assert report.policy_version == "eis-analog-retrieval-v2"
    assert report.omitted_candidates == (omission,)
    assert report.selected_notices == report.evaluated_positions == len(report.rows) == 1
    assert omitted.notice not in {row.notice for row in report.rows}

    payload = report.model_dump(mode="python")
    payload["omitted_candidates"][0]["payload_bytes"] = True
    with pytest.raises(ValidationError):
        AnalogReport.model_validate(payload)
    payload = report.model_dump(mode="python")
    payload["omitted_candidates"][0]["limit_bytes"] = 101
    with pytest.raises(ValidationError, match="OMISSION_BOUND_INVALID"):
        AnalogReport.model_validate(payload)
    payload = report.model_dump(mode="python")
    payload["omitted_candidates"][0]["notice"] = admitted.notice.model_dump()
    with pytest.raises(ValidationError, match="CANDIDATE_PARTITION_INVALID"):
        AnalogReport.model_validate(payload)


@pytest.mark.parametrize(
    "reason,payload_bytes,limit_bytes",
    [
        ("CANDIDATE_NOTICE_PAYLOAD_LIMIT", 256 * 1024 + 1, 256 * 1024),
        ("CANDIDATE_TOTAL_PAYLOAD_LIMIT", 256 * 1024, 0),
    ],
)
def test_omission_byte_boundaries_are_exact(reason, payload_bytes, limit_bytes):
    target = notice()
    omitted = notice("2" * 19)
    request = AnalogRequest(target=target.notice, source_index=1, query="бумага")
    omission = AnalogCandidateOmission(
        notice=omitted.notice,
        reason=reason,
        payload_bytes=payload_bytes,
        limit_bytes=limit_bytes,
    )
    report = build_analog_report(
        request,
        target,
        (),
        now=NOW,
        selection_truncated=False,
        omitted_candidates=(omission,),
    )
    assert report.omitted_candidates == (omission,)


@pytest.mark.parametrize(
    "reason,payload_bytes,limit_bytes",
    [
        ("CANDIDATE_NOTICE_PAYLOAD_LIMIT", 2, 0),
        ("CANDIDATE_NOTICE_PAYLOAD_LIMIT", 256 * 1024 + 2, 256 * 1024 + 1),
        ("CANDIDATE_TOTAL_PAYLOAD_LIMIT", 256 * 1024 + 1, 0),
        ("CANDIDATE_TOTAL_PAYLOAD_LIMIT", 1, 1),
        ("CANDIDATE_TOTAL_PAYLOAD_LIMIT", 2**31, 0),
    ],
)
def test_omission_rejects_invalid_reason_specific_bounds(reason, payload_bytes, limit_bytes):
    omitted = notice("2" * 19)
    with pytest.raises(ValidationError):
        build_analog_report(
            AnalogRequest(target=notice().notice, source_index=1, query="бумага"),
            notice(),
            (),
            now=NOW,
            selection_truncated=False,
            omitted_candidates=(
                AnalogCandidateOmission(
                    notice=omitted.notice,
                    reason=reason,
                    payload_bytes=payload_bytes,
                    limit_bytes=limit_bytes,
                ),
            ),
        )


def test_candidate_partition_uses_purchase_number_across_versions():
    target = notice()
    request = AnalogRequest(target=target.notice, source_index=1, query="бумага")
    self_other_version = target.notice.model_copy(
        update={"version_number": 2, "notice_xml_sha256": "c" * 64}
    )
    with pytest.raises(ValidationError, match="CANDIDATE_PARTITION_INVALID"):
        build_analog_report(
            request,
            target,
            (),
            now=NOW,
            selection_truncated=False,
            omitted_candidates=(
                AnalogCandidateOmission(
                    notice=self_other_version,
                    reason="CANDIDATE_TOTAL_PAYLOAD_LIMIT",
                    payload_bytes=1,
                    limit_bytes=0,
                ),
            ),
        )


@pytest.mark.parametrize(
    "updates",
    [{"company_id": "foreign"}, {"source_index": 26}, {"source_index": True}, {"lookback_days": 0}],
)
def test_request_rejects_tenant_and_invalid_bounds(updates):
    with pytest.raises(ValidationError):
        AnalogRequest(**(dict(target=notice().notice, source_index=1, query="бумага") | updates))
