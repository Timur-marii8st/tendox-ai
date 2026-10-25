import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from procurement.domain.provenance import Extractor, Provenance
from procurement.domain.public_price_opportunity import (
    AmountFact,
    OpportunityRequest,
    PublicPrice,
    RequiredLine,
    TradeUnit,
    calculate_public_opportunity,
    rank_public_opportunities,
)

XML = "a" * 64
HTML = "b" * 64
NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)
AGE = timedelta(hours=24)


def fact(value: str, document: str = XML) -> AmountFact:
    return AmountFact(
        value=value,
        provenance=Provenance(
            document_id=document, locator="/synthetic/value", extractor=Extractor.API
        ),
    )


def unit(document: str = XML, **changes: object) -> TradeUnit:
    return TradeUnit.model_validate(
        {"code": "piece", "provenance": fact("1", document).provenance, **changes}
    )


def price(**changes: object) -> PublicPrice:
    return PublicPrice.model_validate(
        {
            "company_id": "alpha",
            "notice_xml_sha256": XML,
            "source_sha256": HTML,
            "line_id": "1",
            "source_url": "https://supplier.example/product/1",
            "observed_at": NOW,
            "price": fact("40", HTML),
            "quantity_per_price": fact("1", HTML),
            "unit": unit(HTML),
            "currency": "RUB",
            "amount_basis": "EX_VAT",
            "currency_provenance": fact("1", HTML).provenance,
            "amount_basis_provenance": fact("1", HTML).provenance,
            **changes,
        }
    )


def request(**changes: object) -> OpportunityRequest:
    return OpportunityRequest.model_validate(
        {
            "company_id": "alpha",
            "notice_xml_sha256": XML,
            "ceiling": fact("1000"),
            "deadline": NOW + timedelta(days=3),
            "deadline_provenance": fact("1").provenance,
            "blocking_sources": (fact("1").provenance,),
            "source_line_count": 1,
            "line_count_provenance": fact("1").provenance,
            "lines": (RequiredLine(line_id="1", quantity=fact("10"), unit=unit()),),
            "prices": (price(),),
            "other_expenses": fact("100", "expenses"),
            "expenses_complete": True,
            "expenses_completeness_provenance": fact("1", "cost-review").provenance,
            "vat_rate": fact("0.2", "tax-model"),
            **changes,
        }
    )


def calculate(**changes: object):
    return calculate_public_opportunity(request(**changes), now=NOW, max_price_age=AGE)


def test_automatic_cost_uses_supplier_price_for_whole_quantity_and_three_scenarios():
    result = calculate()
    assert result.status == "ESTIMATE"
    assert result.goods_net_rub == Decimal("400.00")
    assert result.estimate is not None
    assert {s.kind for s in result.estimate.scenarios} == {"base", "realistic", "conservative"}
    assert result.quote_status == result.participation == "UNKNOWN"
    assert result.selected[0].source.price.provenance.document_id == HTML


def test_price_for_ten_units_is_not_multiplied_as_price_for_one():
    result = calculate(prices=(price(quantity_per_price=fact("10", HTML)),))
    assert result.goods_net_rub == Decimal("40.00")


def test_cheapest_comparable_source_is_selected_not_cheapest_unrelated_price():
    unrelated = price(price=fact("1", HTML), unit=unit(HTML, code="box", contents="10 pieces"))
    result = calculate(prices=(unrelated, price(), price(price=fact("30", HTML))))
    assert result.goods_net_rub == Decimal("300.00")


@pytest.mark.parametrize(
    "changes",
    [
        {"amount_basis": "UNKNOWN"},
        {"amount_basis": "GROSS"},
        {"currency": "UNKNOWN"},
        {"technical_status": "FAIL"},
        {"availability": "UNAVAILABLE"},
        {"price_kind": "FROM"},
        {"price_kind": "RANGE"},
        {"observed_at": NOW - AGE - timedelta(seconds=1)},
        {"observed_at": NOW + timedelta(seconds=1)},
        {"quantity_per_price": fact("0", HTML)},
        {"price": fact("0", HTML)},
    ],
)
def test_noncomparable_observations_never_become_cost_or_profit(changes):
    result = calculate(prices=(price(**changes),))
    assert result.status == "UNKNOWN"
    assert result.goods_net_rub is None and result.estimate is None
    assert "COMPARABLE_PUBLIC_PRICE:1" in result.missing


@pytest.mark.parametrize("contents", [None, "100 sheets", "5/100"])
def test_packaging_is_not_guessed_from_same_unit_label_or_ambiguous_contents(contents):
    line = RequiredLine(
        line_id="1", quantity=fact("10"), unit=unit(code="pack", contents="500 sheets")
    )
    result = calculate(
        lines=(line,), prices=(price(unit=unit(HTML, code="pack", contents=contents)),)
    )
    assert result.status == "UNKNOWN" and result.goods_net_rub is None


def test_explicit_equal_pack_contents_allow_preliminary_linear_cost():
    line = RequiredLine(
        line_id="1", quantity=fact("10"), unit=unit(code="pack", contents="500 sheets")
    )
    result = calculate(
        lines=(line,), prices=(price(unit=unit(HTML, code="pack", contents="500 sheets")),)
    )
    assert result.goods_net_rub == Decimal("400.00")
    assert any("MOQ" in assumption for assumption in result.assumptions)


def test_unpriced_second_position_blocks_full_lot_profit():
    extra = RequiredLine(line_id="2", quantity=fact("5"), unit=unit())
    result = calculate(lines=(*request().lines, extra))
    assert result.status == "UNKNOWN" and result.goods_net_rub is None
    assert result.estimate is None
    assert "COMPARABLE_PUBLIC_PRICE:2" in result.missing


@pytest.mark.parametrize(
    "field,missing",
    [("other_expenses", "OTHER_EXPENSES_UNKNOWN"), ("vat_rate", "TAX_MODEL_UNKNOWN")],
)
def test_missing_expenses_or_tax_never_become_zero(field, missing):
    result = calculate(**{field: None})
    assert result.goods_net_rub == Decimal("400.00")
    assert result.status == "UNKNOWN" and result.estimate is None
    assert missing in result.missing


@pytest.mark.parametrize(
    "changes", [{"company_id": "beta"}, {"notice_xml_sha256": "c" * 64}, {"line_id": "2"}]
)
def test_foreign_prices_are_rejected(changes):
    with pytest.raises(ValueError, match="PRICE_SCOPE_MISMATCH"):
        calculate(prices=(price(**changes),))


@pytest.mark.parametrize("changes", [{"blocked": True}, {"deadline": NOW}])
def test_source_fail_or_expired_deadline_blocks_even_extremely_profitable_price(changes):
    result = calculate(**changes)
    assert result.status == "BLOCKED" and result.estimate is None
    assert rank_public_opportunities("alpha", (("blocked", result),)) == ()


def test_ranking_uses_profit_not_contract_ceiling_and_excludes_unknown_or_losses():
    profitable = calculate()
    large_unprofitable = calculate(ceiling=fact("10000"), prices=(price(price=fact("999", HTML)),))
    unknown = calculate(other_expenses=None)
    assert rank_public_opportunities(
        "alpha", (("unknown", unknown), ("large", large_unprofitable), ("profitable", profitable))
    ) == (("profitable", profitable),)


def test_shortlist_has_at_most_five_and_uses_stable_ties():
    result = calculate()
    candidates = []
    for i in range(8, 0, -1):
        source = hashlib.sha256(str(i).encode()).hexdigest()
        item = OpportunityRequest.model_validate_json(
            request().model_dump_json().replace(XML, source)
        )
        candidates.append((str(i), calculate_public_opportunity(item, now=NOW, max_price_age=AGE)))
    ranked = rank_public_opportunities("alpha", tuple(candidates))
    assert [key for key, _ in ranked] == ["1", "2", "3", "4", "5"]
    with pytest.raises(ValueError, match="TENANT_MISMATCH"):
        rank_public_opportunities("beta", (("1", result),))


@pytest.mark.parametrize("value", [True, 1.2, "NaN", "Infinity", "1e-100000", "1e10000"])
def test_exact_bounded_numbers_only(value):
    with pytest.raises(ValidationError):
        AmountFact(value=value, provenance=fact("1").provenance)


def test_all_price_fields_must_belong_to_same_saved_source():
    with pytest.raises(ValidationError, match="PUBLIC_PRICE_SOURCE_MISMATCH"):
        price(price=fact("1", "different-document"))


def test_rounding_never_understates_goods_cost():
    result = calculate(prices=(price(price=fact("1", HTML), quantity_per_price=fact("3", HTML)),))
    assert result.goods_net_rub == Decimal("3.34")


def test_an_expense_total_alone_does_not_acknowledge_cost_completeness():
    result = calculate(expenses_complete=False, expenses_completeness_provenance=None)
    assert result.status == "UNKNOWN" and result.estimate is None
    assert "OTHER_EXPENSES_COMPLETENESS_UNKNOWN" in result.missing


def test_priced_subset_does_not_become_complete_lot_profit():
    result = calculate(source_line_count=2)
    assert result.status == "UNKNOWN" and result.estimate is None
    assert "LOT_COMPOSITION_INCOMPLETE" in result.missing


def test_scientific_source_numbers_have_plain_exact_json_for_the_client():
    assert fact("1e2").model_dump(mode="json")["value"] == "100"
    assert fact("1e-6").model_dump(mode="json")["value"] == "0.000001"


def test_the_same_procurement_source_cannot_fill_several_shortlist_places():
    result = calculate()
    assert rank_public_opportunities("alpha", (("b", result), ("a", result))) == (("a", result),)
