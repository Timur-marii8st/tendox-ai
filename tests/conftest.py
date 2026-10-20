"""Общие фикстуры. Только синтетические данные — реальные ТЗ в репозиторий не попадают."""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from procurement.domain.offers import Attribute, Candidate, Certificate
from procurement.domain.provenance import Extractor, Provenance
from procurement.domain.requirements import LineItem, Operator, Requirement

if TYPE_CHECKING:
    from collections.abc import Generator

_REQUIRED_DATABASE_VARIABLES = ("DATABASE_ADMIN_URL", "DATABASE_URL")


def pytest_addoption(parser: pytest.Parser) -> None:
    """Добавить fail-closed режим обязательной проверки PostgreSQL."""
    group = parser.getgroup("postgresql-gate")
    group.addoption(
        "--require-postgres",
        action="store_true",
        help=(
            "Require PostgreSQL integration-test configuration and fail if any selected "
            "integration test is skipped."
        ),
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    """Не разрешать mandatory gate без обеих строк подключения."""
    if not session.config.getoption("--require-postgres"):
        return
    missing = [name for name in _REQUIRED_DATABASE_VARIABLES if not os.environ.get(name)]
    if missing:
        raise pytest.UsageError(
            "mandatory PostgreSQL gate requires non-empty environment variables: "
            + ", ".join(missing)
        )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item,
    call: pytest.CallInfo[object],
) -> Generator[None, None, None]:
    """В mandatory gate любой skip является непроверенным результатом и ошибкой."""
    outcome = yield
    report = outcome.get_result()
    if item.config.getoption("--require-postgres") and report.skipped:
        report.outcome = "failed"
        report.longrepr = (
            str(item.path),
            report.location[1] + 1,
            f"PostgreSQL gate forbids skipped tests: {report.longrepr}",
        )

TZ = Provenance(document_id="ТЗ.pdf", locator="стр. 16", extractor=Extractor.NATIVE_PDF)
DATASHEET = Provenance(document_id="datasheet XXX-24G", locator="стр. 3", extractor=Extractor.LLM)


def req(
    prop: str,
    operator: Operator,
    value: object = None,
    *,
    unit: str | None = None,
    mandatory: bool = True,
    weight: int = 1,
) -> Requirement:
    """Требование ТЗ с минимумом церемоний."""
    return Requirement(
        property=prop,
        operator=operator,
        value=value,  # type: ignore[arg-type]
        unit=unit,
        mandatory=mandatory,
        weight=weight,
        raw_text=f"{prop} {operator.value} {value}",
        provenance=TZ,
    )


def attr(
    prop: str,
    value: object,
    *,
    unit: str | None = None,
    confidence: float = 1.0,
) -> Attribute:
    """Характеристика товара."""
    return Attribute(
        property=prop,
        value=value,  # type: ignore[arg-type]
        unit=unit,
        confidence=confidence,
        provenance=DATASHEET,
    )


def line_item(
    *requirements: Requirement,
    equivalent_allowed: bool = True,
    delivery_deadline: date | None = None,
) -> LineItem:
    """Позиция ТЗ на 50 коммутаторов."""
    return LineItem(
        number=1,
        name="Коммутатор",
        quantity=Decimal(50),
        requirements=requirements,
        equivalent_allowed=equivalent_allowed,
        delivery_deadline=delivery_deadline,
        provenance=TZ,
    )


def candidate(
    *attributes: Attribute,
    is_equivalent: bool = False,
    certificates: tuple[Certificate, ...] = (),
) -> Candidate:
    """Кандидат на поставку."""
    return Candidate(
        candidate_id="c1",
        name="XXX-24G",
        manufacturer="ООО «Х»",
        is_equivalent=is_equivalent,
        attributes=attributes,
        certificates=certificates,
    )


@pytest.fixture
def warranty_24() -> Requirement:
    """Обязательное требование: гарантия не менее 24 месяцев."""
    return req("warranty", Operator.GE, Decimal(24), unit="мес")


@pytest.fixture
def ports_24() -> Requirement:
    """Обязательное требование: не менее 24 портов (безразмерное)."""
    return req("ethernet_ports", Operator.GE, Decimal(24))
