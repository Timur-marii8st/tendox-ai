"""Тесты движка соответствия.

Главная метрика продукта — **ноль ложных PASS**. Поэтому тесты здесь написаны не
на «счастливый путь», а на все случаи, где система могла бы соврать пользователю.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from conftest import DATASHEET, attr, candidate, line_item, req
from procurement.domain.compliance import (
    CandidateVerdict,
    Verdict,
    check_requirement,
    evaluate,
)
from procurement.domain.offers import Certificate
from procurement.domain.requirements import Operator, Requirement


class TestNoDataMeansUnknown:
    """Инвариант №2: отсутствие данных никогда не превращается в PASS."""

    def test_missing_attribute_is_unknown(self, warranty_24: Requirement) -> None:
        check = check_requirement(warranty_24, candidate())
        assert check.verdict is Verdict.UNKNOWN
        assert check.evidence is None

    def test_low_confidence_is_unknown(self, warranty_24: Requirement) -> None:
        low = candidate(attr("warranty", Decimal(36), unit="мес", confidence=0.4))
        check = check_requirement(warranty_24, low)
        assert check.verdict is Verdict.UNKNOWN
        assert "ниже порога" in check.reason

    def test_confidence_threshold_is_configurable(self, warranty_24: Requirement) -> None:
        c = candidate(attr("warranty", Decimal(36), unit="мес", confidence=0.5))
        assert check_requirement(warranty_24, c, min_confidence=0.4).verdict is Verdict.PASS
        assert check_requirement(warranty_24, c, min_confidence=0.9).verdict is Verdict.UNKNOWN

    def test_missing_unit_on_product_is_unknown(self, warranty_24: Requirement) -> None:
        """«36» без единицы при требовании в месяцах — не PASS: единицу подставлять нельзя."""
        check = check_requirement(warranty_24, candidate(attr("warranty", Decimal(36))))
        assert check.verdict is Verdict.UNKNOWN
        assert "единица измерения по товару не указана" in check.reason


class TestUnitNormalization:
    """Инвариант №5: единицы приводятся к каноническим, несопоставимые дают UNKNOWN."""

    def test_years_satisfy_requirement_in_months(self, warranty_24: Requirement) -> None:
        check = check_requirement(warranty_24, candidate(attr("warranty", Decimal(2), unit="года")))
        assert check.verdict is Verdict.PASS

    def test_two_years_equals_twenty_four_months(self) -> None:
        """2 года и 24 мес эквивалентны — сведение месяцев к 30 дням дало бы FAIL."""
        exactly = req("warranty", Operator.GE, Decimal(2), unit="года")
        check = check_requirement(exactly, candidate(attr("warranty", Decimal(24), unit="мес")))
        assert check.verdict is Verdict.PASS

    def test_days_versus_months_is_unknown_not_fail(self, warranty_24: Requirement) -> None:
        """Календарные и суточные сроки несопоставимы. UNKNOWN, а не выдуманный вердикт."""
        check = check_requirement(warranty_24, candidate(attr("warranty", Decimal(730), unit="дн")))
        assert check.verdict is Verdict.UNKNOWN
        assert "несопоставимы" in check.reason

    def test_unknown_unit_is_unknown(self, warranty_24: Requirement) -> None:
        check = check_requirement(
            warranty_24, candidate(attr("warranty", Decimal(24), unit="попугаев"))
        )
        assert check.verdict is Verdict.UNKNOWN

    def test_dimensionless_comparison(self, ports_24: Requirement) -> None:
        enough = candidate(attr("ethernet_ports", Decimal(24)))
        few = candidate(attr("ethernet_ports", Decimal(16)))
        assert check_requirement(ports_24, enough).verdict is Verdict.PASS
        assert check_requirement(ports_24, few).verdict is Verdict.FAIL

    def test_between_operator(self) -> None:
        r = req("depth", Operator.BETWEEN, (Decimal(200), Decimal(400)), unit="мм")
        inside = candidate(attr("depth", Decimal(30), unit="см"))
        outside = candidate(attr("depth", Decimal(50), unit="см"))
        assert check_requirement(r, inside).verdict is Verdict.PASS
        assert check_requirement(r, outside).verdict is Verdict.FAIL


class TestNumericEquality:
    """Числовые EQ/NE соблюдают те же правила единиц, что и сравнения диапазонов."""

    def test_equal_calendar_durations_are_normalized(self) -> None:
        r = req("warranty", Operator.EQ, Decimal(24), unit="мес")
        check = check_requirement(r, candidate(attr("warranty", Decimal(2), unit="года")))
        assert check.verdict is Verdict.PASS

    def test_different_calendar_durations_fail(self) -> None:
        r = req("warranty", Operator.EQ, Decimal(24), unit="мес")
        check = check_requirement(r, candidate(attr("warranty", Decimal(1), unit="год")))
        assert check.verdict is Verdict.FAIL

    def test_incompatible_units_are_unknown(self) -> None:
        r = req("warranty", Operator.EQ, Decimal(24), unit="мес")
        check = check_requirement(r, candidate(attr("warranty", Decimal(24), unit="дн")))
        assert check.verdict is Verdict.UNKNOWN
        assert "несопоставимы" in check.reason

    def test_missing_fact_unit_is_unknown(self) -> None:
        r = req("warranty", Operator.EQ, Decimal(24), unit="мес")
        check = check_requirement(r, candidate(attr("warranty", Decimal(24))))
        assert check.verdict is Verdict.UNKNOWN

    def test_unknown_fact_unit_is_unknown(self) -> None:
        r = req("warranty", Operator.EQ, Decimal(24), unit="мес")
        check = check_requirement(
            r,
            candidate(attr("warranty", Decimal(24), unit="попугаев")),
        )
        assert check.verdict is Verdict.UNKNOWN

    def test_dimensionless_requirement_does_not_accept_physical_unit(self) -> None:
        r = req("ethernet_ports", Operator.EQ, Decimal(24))
        check = check_requirement(
            r,
            candidate(attr("ethernet_ports", Decimal(24), unit="В")),
        )
        assert check.verdict is Verdict.UNKNOWN

    def test_power_units_are_normalized(self) -> None:
        r = req("power", Operator.EQ, Decimal(1000), unit="Вт")
        check = check_requirement(r, candidate(attr("power", Decimal(1), unit="кВт")))
        assert check.verdict is Verdict.PASS

    def test_same_number_in_different_dimensions_is_unknown(self) -> None:
        r = req("power", Operator.EQ, Decimal(1000), unit="Вт")
        check = check_requirement(r, candidate(attr("power", Decimal(1000), unit="В")))
        assert check.verdict is Verdict.UNKNOWN

    def test_not_equal_does_not_invert_unknown(self) -> None:
        r = req("warranty", Operator.NE, Decimal(24), unit="мес")
        check = check_requirement(r, candidate(attr("warranty", Decimal(24), unit="дн")))
        assert check.verdict is Verdict.UNKNOWN

    def test_not_equal_uses_normalized_values(self) -> None:
        r = req("warranty", Operator.NE, Decimal(24), unit="мес")
        same = check_requirement(r, candidate(attr("warranty", Decimal(2), unit="года")))
        different = check_requirement(r, candidate(attr("warranty", Decimal(1), unit="год")))
        assert same.verdict is Verdict.FAIL
        assert different.verdict is Verdict.PASS

    def test_numeric_requirement_with_text_fact_is_unknown(self) -> None:
        r = req("warranty", Operator.EQ, Decimal(24), unit="мес")
        check = check_requirement(r, candidate(attr("warranty", "24", unit="мес")))
        assert check.verdict is Verdict.UNKNOWN


class TestHardGate:
    """Инвариант №3: провал обязательного требования убивает кандидата целиком."""

    def test_failed_mandatory_fails_candidate(self, warranty_24: Requirement) -> None:
        result = evaluate(
            line_item(warranty_24), candidate(attr("warranty", Decimal(12), unit="мес"))
        )
        assert result.verdict is CandidateVerdict.FAIL
        assert len(result.blocking) == 1

    def test_no_percentage_on_fail(self, warranty_24: Requirement) -> None:
        """Сценарий «96% соответствует» с проваленной гарантией не должен существовать."""
        desirable = [req(f"nice_{i}", Operator.EQ, "да", mandatory=False) for i in range(24)]
        item = line_item(warranty_24, *desirable)
        good_attrs = [attr(f"nice_{i}", "да") for i in range(24)]
        result = evaluate(item, candidate(attr("warranty", Decimal(12), unit="мес"), *good_attrs))

        assert result.verdict is CandidateVerdict.FAIL
        assert result.soft_score is None, "процент соответствия при FAIL считать нельзя"
        assert "%" not in result.summary()
        assert "не проходит ТЗ" in result.summary()

    def test_unknown_mandatory_gives_clarification(self, warranty_24: Requirement) -> None:
        result = evaluate(line_item(warranty_24), candidate())
        assert result.verdict is CandidateVerdict.NEEDS_CLARIFICATION
        assert result.soft_score is None
        assert [c.requirement.property for c in result.open_questions] == ["warranty"]

    def test_fail_wins_over_unknown(self, warranty_24: Requirement, ports_24: Requirement) -> None:
        """Если есть и провал, и пробел — вердикт FAIL: кандидат уже не жив."""
        result = evaluate(
            line_item(warranty_24, ports_24), candidate(attr("ethernet_ports", Decimal(8)))
        )
        assert result.verdict is CandidateVerdict.FAIL


class TestSoftScore:
    """Желательные требования влияют на рейтинг, но не убивают кандидата."""

    def test_compliant_with_score(self, warranty_24: Requirement) -> None:
        item = line_item(
            warranty_24,
            req("poe", Operator.EQ, "да", mandatory=False, weight=3),
            req("stackable", Operator.EQ, "да", mandatory=False, weight=1),
        )
        c = candidate(
            attr("warranty", Decimal(36), unit="мес"),
            attr("poe", "да"),
            attr("stackable", "нет"),
        )
        result = evaluate(item, c)
        assert result.verdict is CandidateVerdict.COMPLIANT
        assert result.soft_score == 0.75
        assert "75%" in result.summary()

    def test_desirable_failure_does_not_kill(self) -> None:
        item = line_item(req("poe", Operator.EQ, "да", mandatory=False))
        result = evaluate(item, candidate(attr("poe", "нет")))
        assert result.verdict is CandidateVerdict.COMPLIANT
        assert result.soft_score == 0.0

    def test_unknown_desirable_scores_zero(self) -> None:
        item = line_item(req("poe", Operator.EQ, "да", mandatory=False))
        result = evaluate(item, candidate())
        assert result.verdict is CandidateVerdict.COMPLIANT
        assert result.soft_score == 0.0

    def test_no_desirable_requirements_means_no_score(self, warranty_24: Requirement) -> None:
        result = evaluate(
            line_item(warranty_24), candidate(attr("warranty", Decimal(24), unit="мес"))
        )
        assert result.verdict is CandidateVerdict.COMPLIANT
        assert result.soft_score is None
        assert result.summary() == "Соответствует ТЗ"


class TestEquivalentGate:
    """ТЗ может запрещать аналог. Тогда эквивалент — безусловный FAIL."""

    def test_equivalent_rejected_when_forbidden(self, warranty_24: Requirement) -> None:
        item = line_item(warranty_24, equivalent_allowed=False)
        c = candidate(attr("warranty", Decimal(36), unit="мес"), is_equivalent=True)
        result = evaluate(item, c)
        assert result.verdict is CandidateVerdict.FAIL
        assert [ch.requirement.property for ch in result.blocking] == ["equivalent"]

    def test_equivalent_allowed_passes(self, warranty_24: Requirement) -> None:
        item = line_item(warranty_24, equivalent_allowed=True)
        c = candidate(attr("warranty", Decimal(36), unit="мес"), is_equivalent=True)
        assert evaluate(item, c).verdict is CandidateVerdict.COMPLIANT

    def test_original_passes_even_when_equivalent_forbidden(self, warranty_24: Requirement) -> None:
        item = line_item(warranty_24, equivalent_allowed=False)
        c = candidate(attr("warranty", Decimal(36), unit="мес"), is_equivalent=False)
        assert evaluate(item, c).verdict is CandidateVerdict.COMPLIANT


def _cert(
    valid_until: date | None,
    valid_from: date | None = None,
    *,
    confidence: float = 1.0,
    kind: str = "Декларация соответствия ТР ТС",
) -> Certificate:
    return Certificate(
        kind=kind,
        number="ЕАЭС N RU Д-RU.XX.00.000",
        valid_from=valid_from,
        valid_until=valid_until,
        provenance=DATASHEET.model_copy(update={"confidence": confidence}),
    )


class TestCertificateGate:
    """Требуемые документы проверяются на дату поставки, а не на «сегодня»."""

    @staticmethod
    def _requirement() -> Requirement:
        return req(
            "certificate:Декларация соответствия ТР ТС",
            Operator.EXISTS,
        )

    def test_expired_before_delivery_fails(self, warranty_24: Requirement) -> None:
        item = line_item(
            warranty_24,
            self._requirement(),
            delivery_deadline=date(2026, 12, 1),
        )
        c = candidate(
            attr("warranty", Decimal(36), unit="мес"),
            certificates=(_cert(date(2026, 6, 30)),),
        )
        result = evaluate(item, c)
        assert result.verdict is CandidateVerdict.FAIL
        assert "недействителен на 2026-12-01" in result.blocking[0].actual

    def test_valid_on_delivery_date_passes(self, warranty_24: Requirement) -> None:
        item = line_item(
            warranty_24,
            self._requirement(),
            delivery_deadline=date(2026, 12, 1),
        )
        c = candidate(
            attr("warranty", Decimal(36), unit="мес"),
            certificates=(_cert(date(2027, 1, 1)),),
        )
        assert evaluate(item, c).verdict is CandidateVerdict.COMPLIANT

    def test_unknown_validity_needs_clarification(self, warranty_24: Requirement) -> None:
        """Срок действия неизвестен — это UNKNOWN, а не допуск или выдуманный FAIL."""
        item = line_item(
            warranty_24,
            self._requirement(),
            delivery_deadline=date(2026, 12, 1),
        )
        c = candidate(attr("warranty", Decimal(36), unit="мес"), certificates=(_cert(None),))
        result = evaluate(item, c)
        assert result.verdict is CandidateVerdict.NEEDS_CLARIFICATION
        assert result.open_questions[0].verdict is Verdict.UNKNOWN

    def test_no_deadline_needs_clarification(self, warranty_24: Requirement) -> None:
        """Без даты поставки действительность документа остаётся UNKNOWN."""
        item = line_item(warranty_24, self._requirement(), delivery_deadline=None)
        c = candidate(
            attr("warranty", Decimal(36), unit="мес"),
            certificates=(_cert(date(2020, 1, 1)),),
        )
        result = evaluate(item, c)
        assert result.verdict is CandidateVerdict.NEEDS_CLARIFICATION
        assert "дата поставки" in result.open_questions[0].reason

    def test_missing_required_certificate_needs_clarification(
        self, warranty_24: Requirement
    ) -> None:
        item = line_item(
            warranty_24,
            self._requirement(),
            delivery_deadline=date(2026, 12, 1),
        )
        result = evaluate(item, candidate(attr("warranty", Decimal(36), unit="мес")))
        assert result.verdict is CandidateVerdict.NEEDS_CLARIFICATION
        assert "certificate:" in result.open_questions[0].requirement.property

    def test_low_confidence_certificate_needs_clarification(self, warranty_24: Requirement) -> None:
        item = line_item(
            warranty_24,
            self._requirement(),
            delivery_deadline=date(2026, 12, 1),
        )
        c = candidate(
            attr("warranty", Decimal(36), unit="мес"),
            certificates=(_cert(date(2027, 1, 1), confidence=0.5),),
        )
        result = evaluate(item, c)
        assert result.verdict is CandidateVerdict.NEEDS_CLARIFICATION
        assert "ниже порога" in result.open_questions[0].reason

    def test_other_certificate_kind_does_not_satisfy_requirement(
        self, warranty_24: Requirement
    ) -> None:
        item = line_item(
            warranty_24,
            self._requirement(),
            delivery_deadline=date(2026, 12, 1),
        )
        c = candidate(
            attr("warranty", Decimal(36), unit="мес"),
            certificates=(
                _cert(
                    date(2027, 1, 1),
                    kind="Сертификат соответствия ЕАЭС",
                ),
            ),
        )
        result = evaluate(item, c)
        assert result.verdict is CandidateVerdict.NEEDS_CLARIFICATION
        assert result.open_questions[0].actual == "документ не представлен"

    def test_unrequired_expired_certificate_does_not_create_gate(
        self, warranty_24: Requirement
    ) -> None:
        """Просроченный нерелевантный документ не создаёт требование сам по себе."""
        item = line_item(warranty_24, delivery_deadline=date(2026, 12, 1))
        c = candidate(
            attr("warranty", Decimal(36), unit="мес"),
            certificates=(_cert(date(2020, 1, 1)),),
        )
        assert evaluate(item, c).verdict is CandidateVerdict.COMPLIANT


class TestNonNumericOperators:
    """Перечисления и строки: регистр и пробелы не должны менять вердикт."""

    def test_eq_is_case_insensitive(self) -> None:
        r = req("mount", Operator.EQ, 'Стойка 19"')
        c = candidate(attr("mount", ' стойка 19" '))
        assert check_requirement(r, c).verdict is Verdict.PASS

    def test_ne(self) -> None:
        r = req("country_of_origin", Operator.NE, "Китай")
        other = candidate(attr("country_of_origin", "Россия"))
        same = candidate(attr("country_of_origin", "китай"))
        assert check_requirement(r, other).verdict is Verdict.PASS
        assert check_requirement(r, same).verdict is Verdict.FAIL

    def test_in_enumeration(self) -> None:
        r = req("form_factor", Operator.IN, ["1U", "2U"])
        assert check_requirement(r, candidate(attr("form_factor", "2U"))).verdict is Verdict.PASS
        assert check_requirement(r, candidate(attr("form_factor", "4U"))).verdict is Verdict.FAIL

    def test_contains_in_list(self) -> None:
        r = req("protocols", Operator.CONTAINS, "SNMPv3")
        c = candidate(attr("protocols", ["SNMPv2c", "SNMPv3", "SSH"]))
        assert check_requirement(r, c).verdict is Verdict.PASS
        assert check_requirement(r, candidate(attr("protocols", ["SSH"]))).verdict is Verdict.FAIL

    def test_exists(self) -> None:
        r = req("rohs", Operator.EXISTS)
        assert check_requirement(r, candidate(attr("rohs", "да"))).verdict is Verdict.PASS
        assert check_requirement(r, candidate()).verdict is Verdict.UNKNOWN

    def test_numeric_operator_on_text_value_is_unknown(self, warranty_24: Requirement) -> None:
        """«по запросу» вместо числа — это пробел в данных, а не провал."""
        check = check_requirement(warranty_24, candidate(attr("warranty", "по запросу")))
        assert check.verdict is Verdict.UNKNOWN
        assert "не числовое" in check.reason


class TestExplainability:
    """Инвариант №1: у каждого факта видно источник. Без ссылок вывод бесполезен."""

    def test_explain_shows_both_sources(self, warranty_24: Requirement) -> None:
        check = check_requirement(warranty_24, candidate(attr("warranty", Decimal(36), unit="мес")))
        text = check.explain()
        assert "ТЗ.pdf, стр. 16" in text
        assert "datasheet XXX-24G, стр. 3" in text
        assert "36 мес" in text

    def test_explain_without_evidence_says_no_data(self, warranty_24: Requirement) -> None:
        check = check_requirement(warranty_24, candidate())
        assert "нет данных" in check.explain()

    def test_report_contains_verdict_and_every_check(self, warranty_24: Requirement) -> None:
        item = line_item(warranty_24, req("poe", Operator.EQ, "да", mandatory=False))
        result = evaluate(item, candidate(attr("warranty", Decimal(12), unit="мес")))
        text = result.report()
        assert "кандидат c1" in text
        assert "Позиция №1" in text
        assert "не проходит ТЗ" in text
        assert "warranty" in text
        assert "poe" in text
