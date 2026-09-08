"""Без доказательств маркетплейс не становится разрешённым каналом закупки."""

from datetime import date

import pytest
from pydantic import ValidationError

from conftest import TZ
from procurement.domain.decisions import GateStatus
from procurement.domain.platforms import (
    DigitalPlatformCase,
    PlatformCheck,
    PlatformCondition,
    PlatformRuleSnapshot,
    PlatformUse,
)


def case() -> DigitalPlatformCase:
    # Синтетический ruleset, не нормативный справочник.
    return DigitalPlatformCase(
        case_id="case",
        company_id="tenant",
        platform_id="test-platform",
        use=PlatformUse.SHELF_SALES,
        notice_published_on=date(2026, 10, 1),
        notice_provenance=TZ,
        rules=PlatformRuleSnapshot(
            version="synthetic-v1",
            notice_valid_from=date(2026, 10, 1),
            notice_valid_through=date(2028, 9, 30),
            official_source=TZ,
            reviewed_by="test-reviewer",
            reviewed_on=date(2026, 9, 7),
        ),
        checks=tuple(
            PlatformCheck(
                condition=c, status=GateStatus.PASS, reason="synthetic evidence", evidence=(TZ,)
            )
            for c in PlatformCondition
        ),
    )


@pytest.mark.parametrize(
    ("day", "status"),
    [
        (date(2026, 9, 30), GateStatus.FAIL),
        (date(2026, 10, 1), GateStatus.PASS),
        (date(2028, 9, 30), GateStatus.PASS),
        (date(2028, 10, 1), GateStatus.FAIL),
    ],
)
def test_notice_date_controls_applicability(day: date, status: GateStatus) -> None:
    assert case().model_copy(update={"notice_published_on": day}).shelf_eligibility() is status


@pytest.mark.parametrize("condition", list(PlatformCondition))
def test_each_missing_condition_blocks_pass(condition: PlatformCondition) -> None:
    item = case()
    checks = tuple(c for c in item.checks if c.condition is not condition)
    assert item.model_copy(update={"checks": checks}).shelf_eligibility() is GateStatus.UNKNOWN


def test_no_approved_rules_means_unknown() -> None:
    assert case().model_copy(update={"rules": None}).shelf_eligibility() is GateStatus.UNKNOWN


def test_negative_operator_check_blocks_channel() -> None:
    item = case()
    checks = (item.checks[0].model_copy(update={"status": GateStatus.FAIL}), *item.checks[1:])
    assert item.model_copy(update={"checks": checks}).shelf_eligibility() is GateStatus.FAIL


def test_pass_without_evidence_is_invalid() -> None:
    with pytest.raises(ValidationError):
        PlatformCheck(condition=PlatformCondition.GOODS, status=GateStatus.PASS, reason="guess")


def test_sourcing_cannot_be_interpreted_as_shelf_sales() -> None:
    with pytest.raises(ValueError):
        case().model_copy(update={"use": PlatformUse.SUPPLIER_SOURCING}).shelf_eligibility()
