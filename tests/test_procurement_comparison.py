"""Ноль ложных PASS и изоляция выбранных точных входов сравнения."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from procurement.access import AccessRole
from procurement.api.comparison_demo import ContractExamplesAdapter, create_comparison_app
from procurement.api.contracts import Principal
from procurement.comparison.profile_adapter import digest, validate_example_snapshot
from procurement.comparison.service import CaseRef, CompareCommand, ProfileRef, compare_selected
from procurement.domain.cases import ProcurementCase, case_input_digest
from procurement.domain.decisions import GateStatus


@pytest.fixture
def adapter() -> ContractExamplesAdapter:
    return ContractExamplesAdapter()


def inputs(adapter: ContractExamplesAdapter, version: int = 1, count: int = 5):
    catalog = adapter.catalog("demo-company")
    snapshot = adapter.profile(
        "demo-company",
        ProfileRef.model_validate(
            next(
                profile["ref"]
                for profile in catalog["profiles"]
                if profile["ref"]["version"] == version
            )
        ),
    )
    cases = tuple(
        adapter.case("demo-company", CaseRef.model_validate(row["ref"]))
        for row in catalog["cases"][:count]
    )
    return snapshot, cases


def check(row, key):
    return next(check for check in row.checks if check.check_id == key)


def rehash(snapshot):
    snapshot["snapshot_sha256"] = digest(
        {k: v for k, v in snapshot.items() if k != "snapshot_sha256"}
    )
    return snapshot


def test_complete_user_comparison_keeps_partial_pass_unknown_and_hard_fail(adapter):
    snapshot, cases = inputs(adapter)
    report = compare_selected("demo-company", snapshot, cases, at=adapter.at)
    assert [row.overall_status for row in report.rows] == [GateStatus.UNKNOWN] + [
        GateStatus.FAIL
    ] * 4
    assert check(report.rows[0], "geography").status == GateStatus.PASS
    assert check(report.rows[0], "execution").status == GateStatus.UNKNOWN
    assert check(report.rows[1], "amount").status == GateStatus.FAIL
    assert check(report.rows[2], "geography").status == GateStatus.FAIL
    assert check(report.rows[3], "submission").status == GateStatus.FAIL
    assert check(report.rows[4], "mandatory_technical").status == GateStatus.FAIL
    assert "rating" not in report.model_dump_json()
    assert "PARTICIPATE" not in report.model_dump_json()
    assert len(report.rows[0].economics) == 3
    for row in report.rows[1:]:
        assert row.economics == ()  # НМЦК, чужой ledger или отсутствующее КП не дают прибыль.
    for row in report.rows:
        for item in row.checks:
            assert item.reason and item.reason_code
            if item.status == GateStatus.UNKNOWN:
                assert item.missing
            else:
                assert item.profile_sources or item.case_sources


@pytest.mark.parametrize("count", [2, 3, 4, 5])
def test_fixed_versions_and_time_are_reproducible_without_mutation(adapter, count):
    snapshot, cases = inputs(adapter, count=count)
    before = deepcopy(snapshot)
    original = [case.case.model_dump_json() for case in cases]
    first = compare_selected("demo-company", snapshot, cases, at=adapter.at)
    second = compare_selected("demo-company", snapshot, cases, at=adapter.at)
    assert first.model_dump_json() == second.model_dump_json()
    assert snapshot == before
    assert [case.case.model_dump_json() for case in cases] == original
    changed_time = compare_selected(
        "demo-company", snapshot, cases, at=adapter.at + timedelta(seconds=1)
    )
    assert changed_time.input_sha256 != first.input_sha256


def test_expiry_boundary_and_naive_time(adapter):
    snapshot, cases = inputs(adapter, count=2)
    at = cases[0].case.tender.submission.closes_at
    result = compare_selected("demo-company", snapshot, cases, at=at)
    assert check(result.rows[0], "submission").status == GateStatus.FAIL
    assert result.rows[0].economics == ()
    with pytest.raises(ValueError, match="timezone"):
        compare_selected("demo-company", snapshot, cases, at=at.replace(tzinfo=None))


def test_same_instant_in_different_timezone_has_identical_report(adapter):
    snapshot, cases = inputs(adapter, count=2)
    first = compare_selected("demo-company", snapshot, cases, at=adapter.at)
    second = compare_selected("demo-company", snapshot, cases, at=adapter.at.astimezone(UTC))
    assert first.model_dump_json() == second.model_dump_json()
    assert digest(Decimal("123456789012345678901234567890.0001")) != digest(
        Decimal("123456789012345678901234567890.0002")
    )


def test_realistic_revenue_must_also_fit_selected_company_amount_limits(adapter):
    snapshot, cases = inputs(adapter, count=2)
    for field in ("min_margin", "min_expected_profit", "price_floor_margin"):
        snapshot["facts"]["finance"][field]["value"] = "0"
    payload = cases[0].case.model_dump(mode="python")
    payload["selected_quote"]["amount_ex_vat"] = "300000"
    for scenario in payload["scenarios"]["scenarios"]:
        scenario["economics"]["contract_revenue"] = "400000"
        costs = scenario["economics"]["costs"]
        for field in costs["specified_cost_fields"]:
            costs[field] = "300000" if field == "goods" else "0"
    case = ProcurementCase.model_validate(payload)
    selected = replace(cases[0], case=case, economics_input_sha256=case_input_digest(case))
    report = compare_selected("demo-company", rehash(snapshot), (selected, cases[1]), at=adapter.at)
    assert check(report.rows[0], "amount").status == GateStatus.PASS
    assert check(report.rows[0], "economics").status == GateStatus.FAIL
    assert report.rows[0].overall_status == GateStatus.FAIL


def test_profile_version_change_cannot_reuse_old_manual_pass_or_change_old_result(adapter):
    snapshot, cases = inputs(adapter, count=2)
    original = compare_selected("demo-company", snapshot, cases, at=adapter.at)
    serialized = original.model_dump_json()
    v2, _ = inputs(adapter, version=2, count=2)
    updated = compare_selected("demo-company", v2, cases, at=adapter.at)
    assert updated.profile_ref.version == 2 and updated.input_sha256 != original.input_sha256
    assert check(updated.rows[0], "amount").status == GateStatus.FAIL
    assert check(updated.rows[0], "mandatory_legal").status == GateStatus.UNKNOWN
    assert original.model_dump_json() == serialized
    assert cases[0].case.profile.version == 1


def test_unknown_limits_and_scope_do_not_become_zero_false_or_empty_pass(adapter):
    snapshot, cases = inputs(adapter, version=3, count=2)
    result = compare_selected("demo-company", snapshot, cases, at=adapter.at)
    assert check(result.rows[0], "amount").status == GateStatus.UNKNOWN
    assert check(result.rows[0], "geography").status == GateStatus.UNKNOWN
    assert result.rows[0].overall_status == GateStatus.UNKNOWN


def test_explicit_empty_methods_is_fail_not_unknown(adapter):
    snapshot, cases = inputs(adapter, count=2)
    snapshot["facts"]["allowed_procedure_methods"]["value"] = []
    result = compare_selected("demo-company", rehash(snapshot), cases, at=adapter.at)
    assert check(result.rows[0], "method").status == GateStatus.FAIL


@pytest.mark.parametrize(
    "path, value",
    [
        ("finance.max_contract_amount", 10000000),
        ("finance.max_contract_amount", 1.5),
        ("finance.max_contract_amount", True),
        ("finance.max_contract_amount", "NaN"),
        ("finance.max_contract_amount", "Infinity"),
        ("finance.min_margin", "1.01"),
        ("geography.all_russia", "false"),
    ],
)
def test_invalid_profile_values_rejected_by_existing_constraints(adapter, path, value):
    snapshot, _ = inputs(adapter, count=2)
    group, name = path.split(".")
    snapshot["facts"][group][name]["value"] = value
    with pytest.raises(ValueError):
        validate_example_snapshot(rehash(snapshot), "demo-company")


def test_missing_source_tampering_and_conflicting_known_limits_rejected(adapter):
    snapshot, _ = inputs(adapter, count=2)
    snapshot["facts"]["finance"]["max_contract_amount"]["value"] = "499999"
    with pytest.raises(ValueError, match="contradictory"):
        validate_example_snapshot(rehash(snapshot), "demo-company")
    snapshot, _ = inputs(adapter, count=2)
    snapshot["facts"]["finance"]["min_contract_amount"]["sources"] = []
    with pytest.raises(ValueError, match="requires source"):
        validate_example_snapshot(rehash(snapshot), "demo-company")
    snapshot, _ = inputs(adapter, count=2)
    snapshot["facts"]["finance"]["max_contract_amount"]["value"] = "1"
    with pytest.raises(ValueError, match="digest"):
        validate_example_snapshot(snapshot, "demo-company")


@pytest.mark.parametrize("missing", ["quote", "ledger", "vat", "taxes"])
def test_incomplete_economics_never_outputs_profit(adapter, missing):
    snapshot, cases = inputs(adapter, count=2)
    selected = cases[0]
    payload = selected.case.model_dump(mode="python")
    if missing == "quote":
        payload["selected_quote"] = None
    elif missing == "vat":
        payload["scenarios"]["scenarios"][0]["economics"]["nds_rate"] = None
    elif missing == "taxes":
        costs = payload["scenarios"]["scenarios"][0]["economics"]["costs"]
        costs["specified_cost_fields"] = tuple(
            field for field in costs["specified_cost_fields"] if field != "taxes"
        )
    case = ProcurementCase.model_validate(payload)
    selected = replace(
        selected,
        case=case,
        economics_input_sha256=case_input_digest(case),
        economics_sources=() if missing == "ledger" else selected.economics_sources,
    )
    result = compare_selected("demo-company", snapshot, (selected, cases[1]), at=adapter.at)
    assert result.rows[0].economics == ()
    assert check(result.rows[0], "economics").status == GateStatus.UNKNOWN


def test_assessment_changes_participate_in_report_hash_even_with_same_case_input(adapter):
    snapshot, cases = inputs(adapter, count=2)
    first = compare_selected("demo-company", snapshot, cases, at=adapter.at)
    changed = replace(cases[0], case=cases[0].case.model_copy(update={"assessment": None}))
    second = compare_selected("demo-company", snapshot, (changed, cases[1]), at=adapter.at)
    assert first.rows[0].case_ref == second.rows[0].case_ref
    assert first.input_sha256 != second.input_sha256
    assert first.rows[0].case_snapshot_sha256 != second.rows[0].case_snapshot_sha256
    assert check(second.rows[0], "mandatory_legal").status == GateStatus.UNKNOWN


def test_missing_ledger_does_not_claim_existing_quote_or_scenarios_are_absent(adapter):
    snapshot, cases = inputs(adapter, count=2)
    selected = replace(cases[0], economics_sources=())
    report = compare_selected("demo-company", snapshot, (selected, cases[1]), at=adapter.at)
    assert check(report.rows[0], "economics").missing == (
        "источники выручки и всех статей расходов",
    )


def test_service_tenant_guard(adapter):
    snapshot, cases = inputs(adapter, count=2)
    with pytest.raises(LookupError):
        compare_selected("other-company", snapshot, cases, at=adapter.at)
    forged = replace(
        cases[0], case=cases[0].case.model_copy(update={"company_id": "other-company"})
    )
    with pytest.raises(LookupError):
        compare_selected("demo-company", snapshot, (forged, cases[1]), at=adapter.at)


class TestAuthenticator:
    __test__ = False

    async def authenticate(self, credential):
        return {
            "a": Principal(company_id="demo-company", actor_id="a"),
            "b": Principal(company_id="other-company", actor_id="b"),
            "auditor": Principal(
                company_id="demo-company", actor_id="auditor", access_role=AccessRole.AUDITOR
            ),
        }.get(credential)


def test_http_exact_refs_tenant_isolation_and_replay(adapter):
    client = TestClient(create_comparison_app(adapter, TestAuthenticator()))
    auth = {"Authorization": "Bearer a"}
    foreign = {"Authorization": "Bearer b"}
    assert client.get("/v1/local-comparison/catalog").status_code == 401
    catalog = client.get("/v1/local-comparison/catalog", headers=auth).json()
    command = {
        "profile_ref": catalog["profiles"][0]["ref"],
        "case_refs": [row["ref"] for row in catalog["cases"]],
    }
    result = client.post("/v1/local-comparison", headers=auth, json=command)
    assert result.status_code == 200
    assert result.json() == client.post("/v1/local-comparison", headers=auth, json=command).json()
    assert result.json()["company_id"] == "demo-company"
    other = client.get("/v1/local-comparison/catalog", headers=foreign).json()
    assert other["profiles"] == other["cases"] == []
    assert client.post("/v1/local-comparison", headers=foreign, json=command).status_code == 404
    assert (
        client.post(
            "/v1/local-comparison", headers=auth, json={**command, "company_id": "other-company"}
        ).status_code
        == 422
    )
    for key in ("profile_ref", "case_refs"):
        changed = deepcopy(command)
        ref = changed[key] if key == "profile_ref" else changed[key][0]
        ref["snapshot_sha256" if key == "profile_ref" else "input_sha256"] = "0" * 64
        assert client.post("/v1/local-comparison", headers=auth, json=changed).status_code == 409
    changed = deepcopy(command)
    changed["case_refs"][0]["version"] = 999
    assert client.post("/v1/local-comparison", headers=auth, json=changed).status_code == 404


def test_auditor_can_read_catalog_but_cannot_run_comparison(adapter):
    client = TestClient(create_comparison_app(adapter, TestAuthenticator()))
    auth = {"Authorization": "Bearer auditor"}
    response = client.get("/v1/local-comparison/catalog", headers=auth)
    assert response.status_code == 200
    catalog = response.json()
    command = {
        "profile_ref": catalog["profiles"][0]["ref"],
        "case_refs": [row["ref"] for row in catalog["cases"][:2]],
    }
    assert client.post("/v1/local-comparison", headers=auth, json=command).status_code == 403


@pytest.mark.parametrize("count", [0, 1, 6])
def test_selection_bounds_and_duplicate_refs(adapter, count):
    catalog = adapter.catalog("demo-company")
    ref = catalog["cases"][0]["ref"]
    with pytest.raises(ValidationError):
        CompareCommand.model_validate(
            {"profile_ref": catalog["profiles"][0]["ref"], "case_refs": [ref] * count}
        )
    with pytest.raises(ValidationError):
        CompareCommand.model_validate(
            {"profile_ref": catalog["profiles"][0]["ref"], "case_refs": [ref, ref]}
        )
