"""Synthetic contracts only: no real procurement data in test fixtures."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from procurement.domain.provenance import Provenance
from procurement.domain.regional_discount import (
    HistoryFact,
    HistoryMoney,
    RegionalCohort,
    RegionalHistory,
    RegionalObservation,
    regional_discount,
)

NOW = datetime(2026, 10, 25, tzinfo=UTC)
SOURCE = Provenance(document_id="synthetic-source", locator="/verified/contract", extractor="api")


def fact(value):
    return {"value": value, "source": SOURCE}


def observation(index=1, **updates):
    data = dict(
        company_id="tenant-a",
        law="44",
        purchase_number=f"{index:019d}",
        region=fact("Region A"),
        product_key=fact("KTRU:synthetic"),
        procedure=fact("EF"),
        unit=fact("pcs"),
        quantity=fact("100"),
        initial=fact("1000"),
        final=fact(str(1000 - index * 100)),
        concluded_at=fact(NOW - timedelta(days=10)),
        notice_lot_volume_link=fact(True),
        rub_nominal_totals=fact(True),
        concluded_contract=fact(True),
        current_result=fact(True),
    )
    return RegionalObservation(**(data | updates))


def history(observations=None, **updates):
    data = dict(
        company_id="tenant-a",
        target_id="44:9999999999999999999:0",
        law="44",
        region="Region A",
        product_key="KTRU:synthetic",
        procedure="EF",
        unit="pcs",
        quantity="100",
        period_start=NOW - timedelta(days=365),
        period_end=NOW,
        source=SOURCE,
    )
    return RegionalHistory(
        cohort=RegionalCohort(**(data | updates)),
        observations=tuple(
            observations if observations is not None else [observation(i) for i in range(1, 6)]
        ),
    )


def test_distinct_comparable_results_use_nearest_rank_median_and_p75():
    report = regional_discount(history(), now=NOW)
    assert report.status == "PASS" and report.sample_size == 5
    assert report.realistic_discount == Decimal("0.300000")
    assert report.conservative_discount == Decimal("0.400000")
    assert report.coverage == "UNKNOWN"
    assert report.evaluated[0].observation.final.source == SOURCE


def test_even_sample_median_is_lower_nearest_rank_not_interpolated():
    report = regional_discount(history([observation(i) for i in range(1, 7)]), now=NOW)
    assert report.realistic_discount == Decimal("0.300000")
    assert report.conservative_discount == Decimal("0.500000")


@pytest.mark.parametrize(
    "field",
    ["notice_lot_volume_link", "rub_nominal_totals", "concluded_contract", "current_result"],
)
@pytest.mark.parametrize("value", [None, False])
def test_unknown_or_rejected_bindings_never_count(field, value):
    report = regional_discount(
        history([observation(i, **{field: fact(value)}) for i in range(1, 6)]), now=NOW
    )
    assert report.status == "UNKNOWN" and report.sample_size == 0
    assert report.realistic_discount is report.conservative_discount is None
    assert all(f"{field.upper()}_NOT_CONFIRMED" in e.reasons for e in report.evaluated)


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"region": fact("Region B")}, "REGION_MISSING_OR_MISMATCH"),
        ({"product_key": fact("KTRU:other")}, "PRODUCT_KEY_MISSING_OR_MISMATCH"),
        ({"procedure": fact(None)}, "PROCEDURE_MISSING_OR_MISMATCH"),
        ({"unit": fact("kg")}, "UNIT_MISSING_OR_MISMATCH"),
        ({"quantity": fact("201")}, "VOLUME_OUTSIDE_HALF_TO_DOUBLE_OR_UNKNOWN"),
        ({"quantity": fact(None)}, "VOLUME_OUTSIDE_HALF_TO_DOUBLE_OR_UNKNOWN"),
        ({"final": fact("0")}, "PRICES_NOT_POSITIVE_COMPARABLE_TOTALS"),
        ({"final": fact("-1")}, "PRICES_NOT_POSITIVE_COMPARABLE_TOTALS"),
        ({"final": fact("1001")}, "PRICES_NOT_POSITIVE_COMPARABLE_TOTALS"),
        ({"initial": fact(None)}, "PRICES_NOT_POSITIVE_COMPARABLE_TOTALS"),
        ({"law": "223"}, "LAW_MISMATCH"),
        ({"concluded_at": fact(NOW)}, "CONCLUSION_OUTSIDE_PERIOD_OR_UNKNOWN"),
        ({"concluded_at": fact(NOW - timedelta(days=366))}, "CONCLUSION_OUTSIDE_PERIOD_OR_UNKNOWN"),
    ],
)
def test_bad_comparability_is_visible_and_not_in_statistics(change, reason):
    report = regional_discount(history([observation(**change)]), now=NOW)
    assert report.status == "UNKNOWN" and report.sample_size == 0
    assert reason in report.evaluated[0].reasons


def test_duplicate_revisions_do_not_multiply_sample_size():
    rows = [observation(i) for i in range(1, 6)] + [observation(1, final=fact("100"))]
    report = regional_discount(history(rows), now=NOW)
    assert report.status == "UNKNOWN" and report.sample_size == 4
    assert report.evaluated[0].discount is None
    assert report.evaluated[-1].reasons == ("DUPLICATE_PROCUREMENT",)


def test_target_itself_and_foreign_tenant_cannot_be_history():
    report = regional_discount(
        history([observation(purchase_number="9999999999999999999")]), now=NOW
    )
    assert "TARGET_IS_NOT_HISTORY" in report.evaluated[0].reasons
    with pytest.raises(ValueError, match="TENANT"):
        regional_discount(history([observation(company_id="tenant-b")]), now=NOW)


@pytest.mark.parametrize("value", [1.0, True, "NaN", "Infinity", "1e50"])
def test_no_float_bool_nonfinite_or_unbounded_money(value):
    with pytest.raises(ValidationError):
        HistoryMoney(**fact(value))


def test_zero_discount_is_an_observation_and_tiny_final_cannot_round_to_one():
    rows = [observation(i, final=fact("1000")) for i in range(1, 6)]
    assert regional_discount(history(rows), now=NOW).realistic_discount == 0
    report = regional_discount(
        history([observation(initial=fact("100000000"), final=fact("0.01"))]), now=NOW
    )
    assert "DISCOUNT_UNREPRESENTABLE" in report.evaluated[0].reasons


def test_period_must_precede_calculation_and_be_aware():
    for change in [{"period_end": NOW + timedelta(seconds=1)}, {"period_start": NOW}]:
        with pytest.raises(ValueError, match="PERIOD"):
            regional_discount(history(**change), now=NOW)
    with pytest.raises(ValueError):
        regional_discount(history(), now=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        history(period_end=NOW.replace(tzinfo=None))


def test_third_based_discount_rounds_against_optimistic_profit():
    report = regional_discount(history([observation(initial=fact("3"), final=fact("2"))]), now=NOW)
    assert report.evaluated[0].discount == Decimal("0.333334")
    assert isinstance(HistoryFact[bool](**fact(True)).value, bool)


@pytest.mark.parametrize("timeout", [0, -1, 20001, True, 5.0, "5"])
def test_invalid_protocol_timeout_fails_before_database_access(timeout):
    from procurement.storage.eis_document_store import NoticeDocumentRef
    from procurement.storage.eis_protocols import read_historical_protocols

    ref = NoticeDocumentRef(purchase_number="1" * 19, version_number=1, notice_xml_sha256="a" * 64)
    with pytest.raises(ValueError, match="PROTOCOL_TIMEOUT_INVALID"):
        read_historical_protocols(None, "tenant", ref, now=NOW, statement_timeout_ms=timeout)


@pytest.mark.parametrize("field", ["region", "product_key", "procedure", "unit", "quantity"])
def test_incomplete_target_cannot_make_history_applicable(field):
    report = regional_discount(history(**{field: None}), now=NOW)
    assert report.status == "UNKNOWN" and report.sample_size == 0
    assert "TARGET_COHORT_INCOMPLETE" in report.reasons


@pytest.mark.parametrize(
    "law,target",
    [
        ("223", "44:123:0"),
        ("44", "44:123:1"),
        ("223", "223:123:0"),
        ("44", "44:123:00"),
        ("44", "44:123"),
        ("44", "44:abc:0"),
    ],
)
def test_target_identity_has_exact_law_number_and_lot(law, target):
    with pytest.raises(ValidationError, match="TARGET_IDENTITY"):
        history(law=law, target_id=target)


def test_customer_scope_requires_identity_and_joint_contracts_do_not_multiply_independence():
    unknown = observation(price_scope="WHOLE_CUSTOMER_CONTRACT", customer=None)
    result = regional_discount(history([unknown]), now=NOW)
    assert result.sample_size == 0
    assert "CUSTOMER_SCOPE_IDENTITY_NOT_CONFIRMED" in result.evaluated[0].reasons
    joint = [
        observation(
            1,
            price_scope="WHOLE_CUSTOMER_CONTRACT",
            customer=fact(f"{index:011d}"),
        )
        for index in range(1, 6)
    ]
    result = regional_discount(history(joint), now=NOW)
    assert result.status == "UNKNOWN" and result.sample_size == 0
    assert all("DUPLICATE_PROCUREMENT" in item.reasons for item in result.evaluated)
