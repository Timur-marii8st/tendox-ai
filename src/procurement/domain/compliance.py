"""Движок соответствия — ядро продукта.

Инвариант домена №4: LLM извлекает, правила решают. Этот модуль детерминирован и
не имеет доступа к языковой модели. Методика — docs/architecture/03-compliance-engine.md,
обоснование — docs/adr/0002-llm-extracts-rules-decide.md.

Три правила, которые здесь закодированы и не подлежат «оптимизации»:

1. Отсутствие данных даёт UNKNOWN, никогда PASS.
2. Провал обязательного требования даёт FAIL кандидату целиком.
3. При FAIL процент соответствия не считается и не показывается — карточка
   «96% соответствует» с проваленной гарантией дезинформирует пользователя.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from procurement.domain.offers import Attribute, Candidate
from procurement.domain.requirements import LineItem, Operator, Requirement
from procurement.domain.units import Quantity

DEFAULT_MIN_CONFIDENCE = 0.75
"""Порог уверенности извлечения. Ниже — UNKNOWN. Калибруется на золотом наборе."""


class Verdict(str, Enum):
    """Результат проверки одного требования."""

    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class CandidateVerdict(str, Enum):
    """Итог по кандидату целиком."""

    COMPLIANT = "COMPLIANT"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    FAIL = "FAIL"


class RequirementCheck(BaseModel):
    """Проверка одного требования с обоими источниками — ТЗ и товара."""

    model_config = ConfigDict(frozen=True)

    requirement: Requirement
    verdict: Verdict
    actual: str = Field(description="Факт по товару в человекочитаемом виде")
    reason: str = Field(description="Почему такой вердикт")
    evidence: str | None = Field(default=None, description="Источник факта по товару")

    @property
    def is_blocking(self) -> bool:
        """FAIL по обязательному требованию убивает кандидата."""
        return self.verdict is Verdict.FAIL and self.requirement.mandatory

    @property
    def needs_clarification(self) -> bool:
        """UNKNOWN по обязательному требованию — вопрос производителю, не отказ."""
        return self.verdict is Verdict.UNKNOWN and self.requirement.mandatory

    def explain(self) -> str:
        """Формат вывода из docs/architecture/03-compliance-engine.md — обе ссылки обязательны."""
        icon = {Verdict.PASS: "OK", Verdict.FAIL: "FAIL", Verdict.UNKNOWN: "?"}[self.verdict]
        return "\n".join(
            (
                f"[{icon}] {self.requirement.property}",
                f"    Требование ТЗ:  {self.requirement.label()}"
                f"   источник: {self.requirement.provenance}",
                f"    Факт по товару: {self.actual}   источник: {self.evidence or 'нет данных'}",
                f"    {self.reason}",
            )
        )


class ComplianceResult(BaseModel):
    """Результат проверки кандидата по позиции ТЗ."""

    model_config = ConfigDict(frozen=True)

    candidate_id: str
    line_item_number: int
    verdict: CandidateVerdict
    checks: tuple[RequirementCheck, ...]
    soft_score: float | None = Field(
        default=None,
        description="Оценка по желательным требованиям. None при любом вердикте кроме COMPLIANT",
    )

    @property
    def blocking(self) -> tuple[RequirementCheck, ...]:
        """Обязательные требования, которые товар провалил."""
        return tuple(c for c in self.checks if c.is_blocking)

    @property
    def open_questions(self) -> tuple[RequirementCheck, ...]:
        """Обязательные требования без данных. Из них RFQ Agent строит вопросы."""
        return tuple(c for c in self.checks if c.needs_clarification)

    def summary(self) -> str:
        """Итог для пользователя. При FAIL процент соответствия не упоминается."""
        if self.verdict is CandidateVerdict.FAIL:
            props = "; ".join(c.requirement.property for c in self.blocking)
            return f"FAIL — товар не проходит ТЗ. Обязательные требования: {props}"
        if self.verdict is CandidateVerdict.NEEDS_CLARIFICATION:
            props = "; ".join(c.requirement.property for c in self.open_questions)
            return f"Нужно уточнить у производителя: {props}"
        if self.soft_score is None:
            return "Соответствует ТЗ"
        return f"Соответствует ТЗ, желательные требования {self.soft_score:.0%}"

    def report(self) -> str:
        """Полный разбор для интерфейса и для приложения к заявке."""
        header = f"Позиция №{self.line_item_number} · кандидат {self.candidate_id}"
        body = "\n".join(c.explain() for c in self.checks)
        return f"{header}\n{self.summary()}\n{body}" if body else f"{header}\n{self.summary()}"


def _canonical_numbers(
    req: Requirement, attr: Attribute
) -> tuple[Decimal, tuple[Decimal, ...]] | str:
    """Привести факт и границы требования к каноническим единицам.

    Возвращает либо пару (факт, границы), либо строку-причину, по которой
    сравнение невозможно — она станет UNKNOWN. Догадки не допускаются.
    """
    raw_bounds = req.value if isinstance(req.value, tuple) else (req.value,)
    bounds: list[Decimal] = []
    for item in raw_bounds:
        if not isinstance(item, Decimal):
            return "значение требования не числовое"
        bounds.append(item)

    if not isinstance(attr.value, Decimal):
        return "значение по товару не числовое — сравнение невозможно"

    if req.unit is None:
        # Безразмерное требование, например число портов.
        if attr.unit is not None:
            return (
                f"единица измерения «{attr.unit}» указана только у факта — "
                "размерность требования не подтверждена"
            )
        return attr.value, tuple(bounds)

    if attr.unit is None:
        return f"единица измерения по товару не указана, ТЗ требует {req.unit}"

    fact = Quantity.parse(attr.value, attr.unit)
    if fact is None:
        return f"единица измерения «{attr.unit}» не распознана"

    canonical_bounds: list[Decimal] = []
    for bound in bounds:
        quantity = Quantity.parse(bound, req.unit)
        if quantity is None:
            return f"единица измерения «{req.unit}» не распознана"
        if not fact.comparable_with(quantity):
            return f"единицы несопоставимы: {req.unit} и {attr.unit} — разные величины"
        canonical_bounds.append(quantity.canonical)

    return fact.canonical, tuple(canonical_bounds)


def _compare_numeric(req: Requirement, attr: Attribute) -> tuple[Verdict, str]:
    """Числовое сравнение с приведением единиц измерения."""
    prepared = _canonical_numbers(req, attr)
    if isinstance(prepared, str):
        return Verdict.UNKNOWN, prepared

    fact, bounds = prepared

    if req.operator is Operator.BETWEEN:
        low, high = bounds
        passed = low <= fact <= high
        reason = (
            "значение в допустимом диапазоне"
            if passed
            else f"требуется {req.label()}, фактически {attr.display()}"
        )
        return (Verdict.PASS if passed else Verdict.FAIL), reason

    limit = bounds[0]
    passed = {
        Operator.GE: fact >= limit,
        Operator.LE: fact <= limit,
        Operator.GT: fact > limit,
        Operator.LT: fact < limit,
        Operator.EQ: fact == limit,
        Operator.NE: fact != limit,
    }[req.operator]
    reason = (
        "значение удовлетворяет требованию"
        if passed
        else f"требуется {req.label()}, фактически {attr.display()}"
    )
    return (Verdict.PASS if passed else Verdict.FAIL), reason


def _norm(value: object) -> str:
    return str(value).strip().casefold()


def _compare_non_numeric(req: Requirement, attr: Attribute) -> tuple[Verdict, str]:
    """Сравнение перечислений и строк: EQ, NE, IN, CONTAINS."""
    if req.operator in (Operator.EQ, Operator.NE):
        if isinstance(req.value, Decimal) and isinstance(attr.value, Decimal):
            same = req.value == attr.value
        else:
            same = _norm(attr.value) == _norm(req.value)
        passed = same if req.operator is Operator.EQ else not same
        reason = (
            "значение совпадает с требуемым"
            if passed
            else f"требуется {req.label()}, фактически {attr.display()}"
        )
        return (Verdict.PASS if passed else Verdict.FAIL), reason

    if req.operator is Operator.IN:
        allowed = {_norm(v) for v in req.value} if isinstance(req.value, list) else set()
        passed = _norm(attr.value) in allowed
        reason = (
            "значение входит в допустимый перечень"
            if passed
            else f"значение {attr.display()} не входит в допустимый перечень"
        )
        return (Verdict.PASS if passed else Verdict.FAIL), reason

    if req.operator is Operator.CONTAINS:
        needle = _norm(req.value)
        haystack = (
            {_norm(v) for v in attr.value} if isinstance(attr.value, list) else {_norm(attr.value)}
        )
        passed = any(needle == item or needle in item for item in haystack)
        reason = (
            "требуемое значение присутствует"
            if passed
            else f"требуемое «{req.value}» не найдено в {attr.display()}"
        )
        return (Verdict.PASS if passed else Verdict.FAIL), reason

    return Verdict.UNKNOWN, f"оператор {req.operator.value} не поддержан движком"


def check_requirement(
    req: Requirement,
    candidate: Candidate,
    *,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    delivery_deadline: date | None = None,
) -> RequirementCheck:
    """Проверить одно требование. Отсутствие данных даёт UNKNOWN, никогда PASS."""
    if req.property.startswith("certificate:") and req.operator is Operator.EXISTS:
        return _check_certificate_requirement(
            req,
            candidate,
            delivery_deadline=delivery_deadline,
            min_confidence=min_confidence,
        )

    attr = candidate.attribute(req.property)

    if attr is None:
        return RequirementCheck(
            requirement=req,
            verdict=Verdict.UNKNOWN,
            actual="не указан",
            reason="характеристика отсутствует в данных о товаре — нужно уточнить у производителя",
        )

    if attr.confidence < min_confidence:
        return RequirementCheck(
            requirement=req,
            verdict=Verdict.UNKNOWN,
            actual=attr.display(),
            reason=(
                f"уверенность извлечения {attr.confidence:.2f} ниже порога "
                f"{min_confidence:.2f} — значение не принимается как доказательство"
            ),
            evidence=str(attr.provenance),
        )

    if req.operator is Operator.EXISTS:
        return RequirementCheck(
            requirement=req,
            verdict=Verdict.PASS,
            actual=attr.display(),
            reason="характеристика присутствует",
            evidence=str(attr.provenance),
        )

    numeric_equality = (
        req.operator in (Operator.EQ, Operator.NE) and isinstance(req.value, Decimal)
    )
    verdict, reason = (
        _compare_numeric(req, attr)
        if req.operator.is_numeric or numeric_equality
        else _compare_non_numeric(req, attr)
    )
    if verdict is Verdict.FAIL and req.mandatory:
        reason = f"{reason}. Требование обязательное — товар не проходит ТЗ"

    return RequirementCheck(
        requirement=req,
        verdict=verdict,
        actual=attr.display(),
        reason=reason,
        evidence=str(attr.provenance),
    )


def _equivalent_gate(item: LineItem, candidate: Candidate) -> RequirementCheck | None:
    """ТЗ может запрещать эквивалент. Аналог при запрете — безусловный FAIL."""
    if not candidate.is_equivalent or item.equivalent_allowed:
        return None
    gate = Requirement(
        property="equivalent",
        operator=Operator.EXISTS,
        mandatory=True,
        raw_text="Поставка эквивалента не допускается",
        provenance=item.provenance,
    )
    return RequirementCheck(
        requirement=gate,
        verdict=Verdict.FAIL,
        actual="предложен эквивалент",
        reason="ТЗ не допускает поставку эквивалента. Требование обязательное",
        evidence=f"кандидат {candidate.candidate_id}",
    )


def _normalized_certificate_kind(value: str) -> str:
    """Нормализовать только регистр и пробелы, не угадывая вид документа."""
    return " ".join(value.split()).casefold()


def _check_certificate_requirement(
    req: Requirement,
    candidate: Candidate,
    *,
    delivery_deadline: date | None,
    min_confidence: float,
) -> RequirementCheck:
    """Проверить явно требуемый вид документа на дату поставки."""
    required_kind = req.property.removeprefix("certificate:")
    matching = tuple(
        certificate
        for certificate in candidate.certificates
        if _normalized_certificate_kind(certificate.kind)
        == _normalized_certificate_kind(required_kind)
    )
    if not matching:
        return RequirementCheck(
            requirement=req,
            verdict=Verdict.UNKNOWN,
            actual="документ не представлен",
            reason=f"нет подтверждённого документа вида «{required_kind}»",
        )
    if delivery_deadline is None:
        return RequirementCheck(
            requirement=req,
            verdict=Verdict.UNKNOWN,
            actual=f"представлен документ {matching[0].number}",
            reason="дата поставки не указана — действительность документа проверить нельзя",
            evidence=str(matching[0].provenance),
        )

    trusted = tuple(
        certificate
        for certificate in matching
        if certificate.provenance.confidence >= min_confidence
    )
    if not trusted:
        return RequirementCheck(
            requirement=req,
            verdict=Verdict.UNKNOWN,
            actual=f"представлен документ {matching[0].number}",
            reason=(
                f"уверенность источника {matching[0].provenance.confidence:.2f} ниже порога "
                f"{min_confidence:.2f}"
            ),
            evidence=str(matching[0].provenance),
        )

    validity = tuple(certificate.is_valid_on(delivery_deadline) for certificate in trusted)
    if any(state is True for state in validity):
        certificate = trusted[validity.index(True)]
        return RequirementCheck(
            requirement=req,
            verdict=Verdict.PASS,
            actual=(
                f"{certificate.kind} {certificate.number} действует на "
                f"{delivery_deadline.isoformat()}"
            ),
            reason="требуемый документ действует на дату поставки",
            evidence=str(certificate.provenance),
        )
    if any(state is None for state in validity):
        certificate = trusted[validity.index(None)]
        return RequirementCheck(
            requirement=req,
            verdict=Verdict.UNKNOWN,
            actual=f"срок действия документа {certificate.number} не указан",
            reason="действительность документа на дату поставки не подтверждена",
            evidence=str(certificate.provenance),
        )

    certificate = trusted[0]
    reason = "документ не действует на дату поставки"
    if req.mandatory:
        reason = f"{reason}. Требование обязательное — товар не проходит ТЗ"
    return RequirementCheck(
        requirement=req,
        verdict=Verdict.FAIL,
        actual=(
            f"{certificate.kind} {certificate.number} недействителен на "
            f"{delivery_deadline.isoformat()}"
        ),
        reason=reason,
        evidence=str(certificate.provenance),
    )


def _soft_score(checks: tuple[RequirementCheck, ...]) -> float | None:
    """Взвешенная оценка по желательным требованиям. UNKNOWN даёт 0 баллов."""
    desirable = [c for c in checks if not c.requirement.mandatory]
    if not desirable:
        return None
    total = sum(c.requirement.weight for c in desirable)
    earned = sum(c.requirement.weight for c in desirable if c.verdict is Verdict.PASS)
    return earned / total


def evaluate(
    item: LineItem,
    candidate: Candidate,
    *,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> ComplianceResult:
    """Проверить кандидата по позиции ТЗ.

    Порядок вердикта неизменяем:

    * есть FAIL по обязательному    -> FAIL, soft_score не считается;
    * есть UNKNOWN по обязательному -> NEEDS_CLARIFICATION, soft_score не считается;
    * все обязательные PASS         -> COMPLIANT + soft_score по желательным.
    """
    checks: list[RequirementCheck] = []

    for gate in (_equivalent_gate(item, candidate),):
        if gate is not None:
            checks.append(gate)

    checks.extend(
        check_requirement(
            req,
            candidate,
            min_confidence=min_confidence,
            delivery_deadline=item.delivery_deadline,
        )
        for req in item.requirements
    )

    result_checks = tuple(checks)

    if any(c.is_blocking for c in result_checks):
        verdict, soft = CandidateVerdict.FAIL, None
    elif any(c.needs_clarification for c in result_checks):
        verdict, soft = CandidateVerdict.NEEDS_CLARIFICATION, None
    else:
        verdict, soft = CandidateVerdict.COMPLIANT, _soft_score(result_checks)

    return ComplianceResult(
        candidate_id=candidate.candidate_id,
        line_item_number=item.number,
        verdict=verdict,
        checks=result_checks,
        soft_score=soft,
    )
