from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from procurement.domain.beta_quote import BetaQuoteInput, calculate_quote
from procurement.domain.economics import COST_FIELD_NAMES
from procurement.domain.provenance import Extractor, Provenance

NOW = datetime(2026, 10, 21, tzinfo=UTC)
SOURCE = Provenance(document_id="manual:test", locator="/quote", extractor=Extractor.MANUAL)


def quote(**updates):
    data = dict(
        supplier="Synthetic supplier",
        document="offer.pdf",
        locator="page 1",
        amount_ex_vat="50000",
        quote_vat_rate="0.20",
        issued_at=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=10),
        covers_full_scope=True,
        availability_terms="100 units in stock",
        delivery_terms="to destination",
        payment_terms="postpay",
        expenses={key: "0" for key in COST_FIELD_NAMES if key != "goods"},
        expense_basis="operator expense worksheet",
        tax_model="Explicit test tax model",
        output_vat_rate="0.20",
        realistic_discount="0.05",
        conservative_discount="0.10",
        conservative_cost_growth="0.10",
    )
    return BetaQuoteInput(**(data | updates))


def calculate(data=None, **updates):
    args = dict(
        company="tenant-a",
        tender_id="44:123:0",
        quote_id="quote-1",
        quote_source=SOURCE,
        expense_source=SOURCE,
        nmck_gross=Decimal("120000"),
        deadline=NOW + timedelta(days=2),
        blocked=False,
        now=NOW,
    )
    return calculate_quote(data or quote(), **(args | updates))


def test_three_scenarios_are_net_and_do_not_authorize_participation():
    result = calculate()
    assert result.status == "CALCULATED"
    assert result.costs.is_complete and result.quote.is_complete
    assert [s.profit for s in result.scenarios] == [
        Decimal("50000.00"),
        Decimal("45000.00"),
        Decimal("35000.00"),
    ]
    assert result.participation == "UNKNOWN"


@pytest.mark.parametrize(
    "change",
    [
        dict(expenses={}),
        dict(covers_full_scope=False),
        dict(valid_until=NOW),
        dict(issued_at=NOW + timedelta(days=1)),
    ],
)
def test_incomplete_or_invalid_quote_never_becomes_calculated(change):
    result = calculate(quote(**change))
    assert result.status == "UNKNOWN" and not result.scenarios


@pytest.mark.parametrize("change", [dict(deadline=None), dict(nmck_gross=None)])
def test_source_unknown_remains_unknown(change):
    assert calculate(**change).status == "UNKNOWN"


@pytest.mark.parametrize("change", [dict(blocked=True), dict(deadline=NOW)])
def test_blocker_overrides_profitable_quote(change):
    result = calculate(**change)
    assert result.status == "BLOCKED" and not result.scenarios


@pytest.mark.parametrize("value", [0.1, True, "NaN", "Infinity"])
def test_money_rejects_inexact_and_nonfinite_inputs(value):
    with pytest.raises(ValidationError):
        quote(amount_ex_vat=value)


def test_expenses_are_not_silently_defaulted_or_allowed_negative():
    assert not calculate(quote(expenses={"logistics": "10"})).costs.is_complete
    with pytest.raises(ValidationError):
        quote(expenses={"taxes": "-1"})
    with pytest.raises(ValidationError):
        quote(expenses={"profit": "1000"})


def test_quote_requires_aware_dates():
    with pytest.raises(ValidationError):
        quote(issued_at=NOW.replace(tzinfo=None))
