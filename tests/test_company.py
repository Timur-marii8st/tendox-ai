"""Критические настройки профиля не должны допускать противоречия."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from procurement.domain.company import (
    CompanyIdentity,
    CompanyProfile,
    FinancialPolicy,
    GeographyPolicy,
    ProhibitionKind,
    ProhibitionRule,
)


def finance(**overrides: object) -> FinancialPolicy:
    values = {
        "min_contract_amount": Decimal("500000"),
        "max_contract_amount": Decimal("10000000"),
        "min_margin": Decimal("0.15"),
        "min_expected_profit": Decimal("150000"),
        "max_contract_without_extra_approval": Decimal("5000000"),
        "max_application_security": Decimal("300000"),
        "max_performance_security": Decimal("1000000"),
        "price_floor_margin": Decimal("0.10"),
    }
    values.update(overrides)
    return FinancialPolicy(**values)


def test_legal_prohibition_requires_legal_basis() -> None:
    with pytest.raises(ValidationError):
        ProhibitionRule(
            rule_id="license",
            kind=ProhibitionKind.LEGAL,
            condition="missing_required_license",
            rationale="нет лицензии",
        )


def test_commercial_prohibition_is_distinct() -> None:
    rule = ProhibitionRule(
        rule_id="no-prepayment",
        kind=ProhibitionKind.COMMERCIAL,
        condition="customer_advance_below_policy",
        rationale="компания не работает без аванса",
    )
    assert rule.kind is ProhibitionKind.COMMERCIAL
    assert rule.legal_basis is None


def test_financial_limits_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        finance(max_contract_without_extra_approval=Decimal("11000000"))


@pytest.mark.parametrize(
    "field",
    (
        "min_contract_amount",
        "max_contract_amount",
        "min_margin",
        "min_expected_profit",
        "max_contract_without_extra_approval",
        "max_application_security",
        "max_performance_security",
        "price_floor_margin",
    ),
)
@pytest.mark.parametrize(
    "value",
    (
        1.0,
        True,
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        "NaN",
        "Infinity",
        "-Infinity",
    ),
)
def test_financial_policy_rejects_inexact_or_nonfinite_values(
    field: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        finance(**{field: value})


def test_financial_policy_accepts_exact_positive_strings() -> None:
    policy = FinancialPolicy(
        min_contract_amount="500000",
        max_contract_amount="10000000",
        min_margin="0.15",
        min_expected_profit="150000",
        max_contract_without_extra_approval="5000000",
        max_application_security="300000",
        max_performance_security="1000000",
        price_floor_margin="0.10",
    )

    assert policy.min_contract_amount == Decimal("500000")
    assert policy.max_contract_amount == Decimal("10000000")
    assert policy.min_margin == Decimal("0.15")
    assert policy.min_expected_profit == Decimal("150000")
    assert policy.max_contract_without_extra_approval == Decimal("5000000")
    assert policy.max_application_security == Decimal("300000")
    assert policy.max_performance_security == Decimal("1000000")
    assert policy.price_floor_margin == Decimal("0.10")


def test_profile_requires_real_business_scope() -> None:
    with pytest.raises(ValidationError):
        CompanyProfile(
            company_id="tenant-1",
            version=1,
            identity=CompanyIdentity(
                name='ООО "Поставка"',
                inn="1650000000",
                kpp="165001001",
                ogrn="1161690000000",
                legal_form="ООО",
            ),
            business_description="Оптовые поставки",
            geography=GeographyPolicy(regions=frozenset({"Татарстан"})),
            finance=finance(),
        )
