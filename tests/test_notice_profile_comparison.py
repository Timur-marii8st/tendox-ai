"""Cached source facts never become an invented saved case or false admission."""

import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from procurement.comparison.notices import NoticeCompareCommand, _declarations, compare_notices
from procurement.sources.eis_223_events import resolve_purchase_rejection_state
from procurement.storage.eis_mixed_comparison import Mixed223Row, MixedComparisonResult
from test_eis_223_events import parse
from test_eis_mixed_comparison import NOW, result, row223


def snapshot():
    return json.loads(
        (Path(__file__).parent / "fixtures/company_profile/unknown.json").read_text(
            encoding="utf-8"
        )
    )["profile_snapshot"]


def inputs(count=2):
    profile = snapshot()
    rows = []
    refs = []
    for index in range(count):
        row = row223()
        notice = row.notice.model_copy(update={"purchase_number": f"326{index:08d}"})
        rows.append(Mixed223Row(**row.model_copy(update={"notice": notice}).model_dump()))
        refs.append(
            {
                "law": "223",
                "purchase_number": notice.purchase_number,
                "version_number": notice.version_number,
                "notice_xml_sha256": notice.xml_sha256,
            }
        )
    command = NoticeCompareCommand(
        selection_id=uuid4(),
        profile_ref={"version": profile["version"], "snapshot_sha256": profile["snapshot_sha256"]},
        notices=refs,
    )
    return profile, command, MixedComparisonResult(checked_at=NOW, rows=tuple(rows))


@pytest.mark.parametrize("count", [2, 5])
def test_bound_exact_inputs_keep_all_economics_unknown(count):
    profile, command, source = inputs(count)
    report = compare_notices(profile["company_id"], profile, command, source)
    assert len(report.rows) == count and report.source == source
    assert report.profile_ref == command.profile_ref
    assert report.persistence == "EPHEMERAL" and report.comparison_kind == "PRELIMINARY"
    assert all(c.status == "UNKNOWN" for r in report.rows for c in r.checks)
    assert compare_notices(profile["company_id"], profile, command, source) == report


@pytest.mark.parametrize("change", ["one", "six", "duplicate", "tenant"])
def test_bad_bounds_or_client_tenant_rejected(change):
    _, command, _ = inputs()
    raw = command.model_dump(mode="json")
    if change == "one":
        raw["notices"] = raw["notices"][:1]
    elif change == "six":
        raw["notices"] *= 3
    elif change == "duplicate":
        raw["notices"][1] = {**raw["notices"][0], "version_number": 9}
    else:
        raw["company_id"] = "foreign"
    with pytest.raises(ValidationError):
        NoticeCompareCommand.model_validate(raw)


def test_deadline_fail_preserves_unknown_money_and_source_provenance():
    profile, command, source = inputs()
    first = source.rows[0]
    deadline = first.notice.deadline.model_copy(
        update={"value": NOW - timedelta(seconds=1), "status": "AWARE"}
    )
    first = first.model_copy(
        update={"notice": first.notice.model_copy(update={"deadline": deadline})}
    )
    source = source.model_copy(update={"rows": (first, source.rows[1])})
    report = compare_notices(profile["company_id"], profile, command, source)
    checks = {c.check_id: c for c in report.rows[0].checks}
    assert checks["submission"].status == "FAIL" and checks["submission"].case_sources
    assert checks["amount"].status == checks["economics"].status == "UNKNOWN"
    assert report.rows[0].overall_status == "FAIL"


@pytest.mark.parametrize("change", ["profile", "tenant", "notice", "order"])
def test_identity_mismatches_fail_closed(change):
    profile, command, source = inputs()
    company = profile["company_id"]
    if change == "profile":
        command = command.model_copy(
            update={
                "profile_ref": command.profile_ref.model_copy(update={"snapshot_sha256": "f" * 64})
            }
        )
    elif change == "tenant":
        company = "foreign"
    elif change == "notice":
        command = command.model_copy(
            update={
                "notices": (
                    command.notices[0].model_copy(update={"notice_xml_sha256": "f" * 64}),
                    command.notices[1],
                )
            }
        )
    else:
        source = source.model_copy(update={"rows": tuple(reversed(source.rows))})
    with pytest.raises(ValueError):
        compare_notices(company, profile, command, source)


def test_mixed_order_and_source_hold_are_explicit_not_supplier_pass():
    profile = snapshot()
    source = result()
    refs = [
        {"law": "44", **source.rows[0].evidence.notice.model_dump()},
        {
            "law": "223",
            "purchase_number": source.rows[1].notice.purchase_number,
            "version_number": source.rows[1].notice.version_number,
            "notice_xml_sha256": source.rows[1].notice.xml_sha256,
        },
    ]
    command = NoticeCompareCommand(
        selection_id=uuid4(),
        profile_ref={"version": profile["version"], "snapshot_sha256": profile["snapshot_sha256"]},
        notices=refs,
    )
    report = compare_notices(profile["company_id"], profile, command, source)
    assert [r.notice_ref.law for r in report.rows] == ["44", "223"]
    assert not any(c.status == "PASS" for r in report.rows for c in r.checks)


@pytest.mark.parametrize("verified", [False, True])
def test_cancellation_requires_qualified_evidence_and_retains_event_sources(verified):
    profile, command, source = inputs()
    row = source.rows[0]
    event = parse(number=row.notice.purchase_number)
    checks = (
        tuple(
            SimpleNamespace(
                event_guid=event.event_guid.value,
                purchase_number=event.purchase_number,
                xml_sha256=event.xml_sha256,
                schema_release=release,
                status="PASS",
            )
            for release in ("16.2", "16.3")
        )
        if verified
        else ()
    )
    state = resolve_purchase_rejection_state(event.purchase_number, [event], checks, now=NOW)
    row = row.model_copy(update={"cancellation_state": state})
    source = source.model_copy(update={"rows": (row, source.rows[1])})
    report = compare_notices(profile["company_id"], profile, command, source)
    submission = next(c for c in report.rows[0].checks if c.check_id == "submission")
    assert submission.status == ("FAIL" if verified else "UNKNOWN")
    assert event.purchase_number_provenance in submission.case_sources


def test_declared_values_are_human_labels_without_python_repr_or_false_defaults():
    profile = snapshot()
    profile["facts"]["supplied_goods"].update(knowledge="KNOWN", value=["Краны", "Насосы"])
    profile["facts"]["geography.all_russia"].update(knowledge="KNOWN", value=False)
    text = _declarations(profile, ("supplied_goods", "geography.all_russia", "geography.cities"))
    assert text == "Товары: Краны, Насосы; Вся Россия: Нет; Города: не указано"
