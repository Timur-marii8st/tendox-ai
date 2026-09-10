"""Сквозная связка золотого набора tz_001 с движком compliance.evaluate.

Золотой эталон data/goldenset/v1/tz_001.expected.json фиксирует два факта:
гарантия warranty >= 24 мес и число портов ethernet_ports >= 24.
Здесь проверяется, что эти факты дают корректные вердикты движка.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from conftest import DATASHEET, attr, candidate, line_item, req
from procurement.domain.compliance import CandidateVerdict, Verdict, check_requirement, evaluate
from procurement.domain.offers import Certificate
from procurement.domain.requirements import LineItem, Operator


def _tz001_item(
    *, equivalent_allowed: bool, delivery_deadline: date | None = None
) -> LineItem:
    """Позиция ТЗ по фактам эталона tz_001.

    Аргумент equivalent_allowed обязателен и задаётся явно на каждом вызове:
    дефолт хелпера line_item() (True) отличается от доменного дефолта (False).
    """
    return line_item(
        req("warranty", Operator.GE, Decimal(24), unit="мес"),
        req("ethernet_ports", Operator.GE, Decimal(24), unit="шт"),
        equivalent_allowed=equivalent_allowed,
        delivery_deadline=delivery_deadline,
    )


def test_tz001_compliant() -> None:
    """Полный кандидат (гарантия 36 мес, 24 порта) проходит оба факта эталона."""
    item = _tz001_item(equivalent_allowed=False)
    cand = candidate(
        attr("warranty", Decimal(36), unit="мес"),
        attr("ethernet_ports", Decimal(24), unit="шт"),
    )
    result = evaluate(item, cand)
    assert result.verdict is CandidateVerdict.COMPLIANT


def test_tz001_warranty_fail() -> None:
    """Гарантия 12 мес при требовании >= 24 мес — FAIL без процентов в сводке."""
    item = _tz001_item(equivalent_allowed=False)
    cand = candidate(
        attr("warranty", Decimal(12), unit="мес"),
        attr("ethernet_ports", Decimal(24), unit="шт"),
    )
    result = evaluate(item, cand)
    assert result.verdict is CandidateVerdict.FAIL
    assert "warranty" in [c.requirement.property for c in result.blocking]
    assert result.soft_score is None
    assert "%" not in result.summary()


def test_tz001_missing_ports_needs_clarification() -> None:
    """Нет данных о портах — NEEDS_CLARIFICATION с открытым вопросом, а не FAIL."""
    item = _tz001_item(equivalent_allowed=False)
    cand = candidate(attr("warranty", Decimal(36), unit="мес"))
    result = evaluate(item, cand)
    assert result.verdict is CandidateVerdict.NEEDS_CLARIFICATION
    assert "ethernet_ports" in [c.requirement.property for c in result.open_questions]


def test_tz001_low_confidence_unknown() -> None:
    """Уверенность извлечения ниже порога 0.75 даёт UNKNOWN, а не COMPLIANT."""
    item = _tz001_item(equivalent_allowed=False)
    cand = candidate(
        attr("warranty", Decimal(36), unit="мес", confidence=0.5),
        attr("ethernet_ports", Decimal(24), unit="шт"),
    )
    warranty_req = item.requirements[0]
    assert check_requirement(warranty_req, cand).verdict is Verdict.UNKNOWN
    result = evaluate(item, cand)
    assert result.verdict is CandidateVerdict.NEEDS_CLARIFICATION
    assert result.verdict is not CandidateVerdict.COMPLIANT


def test_tz001_expired_certificate_fail() -> None:
    """Просроченный на дату поставки документ — FAIL; без дедлайна не проверяется."""
    item = _tz001_item(equivalent_allowed=False, delivery_deadline=date(2026, 12, 1))
    cert = Certificate(
        kind="Декларация соответствия ТР ТС",
        number="ЕАЭС N RU Д-RU.XX.00.001",
        valid_until=date(2026, 6, 30),
        provenance=DATASHEET,
    )
    cand = candidate(
        attr("warranty", Decimal(36), unit="мес"),
        attr("ethernet_ports", Decimal(24), unit="шт"),
        certificates=(cert,),
    )
    result = evaluate(item, cand)
    assert result.verdict is CandidateVerdict.FAIL
    assert any(
        c.requirement.property.startswith("certificate:") for c in result.blocking
    ), "ожидается блокирующий признак сертификата"

    # Контрольный sub-тест: дедлайна нет — тот же сертификат не даёт FAIL по документу.
    item_no_deadline = _tz001_item(equivalent_allowed=False, delivery_deadline=None)
    control = evaluate(item_no_deadline, cand)
    assert not any(
        c.requirement.property.startswith("certificate:") for c in control.blocking
    )
    assert control.verdict is CandidateVerdict.COMPLIANT


def test_tz001_equivalent_trap() -> None:
    """Запрет эквивалента ловит аналог: FAIL по признаку equivalent."""
    item = _tz001_item(equivalent_allowed=False)
    cand = candidate(
        attr("warranty", Decimal(36), unit="мес"),
        attr("ethernet_ports", Decimal(24), unit="шт"),
        is_equivalent=True,
    )
    result = evaluate(item, cand)
    assert result.verdict is CandidateVerdict.FAIL
    assert "equivalent" in [c.requirement.property for c in result.blocking]
