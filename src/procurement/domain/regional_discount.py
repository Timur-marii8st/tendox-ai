"""Evidence-gated historical discounts; a scenario assumption, never a win forecast."""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_CEILING, Decimal, localcontext
from typing import Generic, Literal, TypeVar

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

from procurement.domain.discovery_economics import _finite_decimal
from procurement.domain.provenance import Provenance

T = TypeVar("T")
MIN_SAMPLE: Literal[5] = 5  # Product threshold, not statistical significance.
POLICY: Literal["regional-discount-v2"] = "regional-discount-v2"


def source_date_bounds(day: date) -> tuple[datetime, datetime]:
    """UTC bounds for an XML DATE with no stated timezone; never invent an instant.

    Например, DATE2026-10-20 задаёт границы2026-10-19T10:00Z и2026-10-21T14:00Z.
    """
    start = datetime.combine(day, time.min, tzinfo=UTC)
    return start - timedelta(hours=14), start + timedelta(days=1, hours=14)


def _decimal(value: object) -> Decimal:
    amount = _finite_decimal(value, field_name="history_amount")
    if len(amount.as_tuple().digits) > 30 or abs(int(amount.as_tuple().exponent)) > 12:
        raise ValueError("HISTORY_DECIMAL_LIMIT")
    return amount


class HistoryModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class HistoryFact(HistoryModel, Generic[T]):
    value: T | None
    source: Provenance
    supporting_sources: tuple[Provenance, ...] = Field(default=(), max_length=16)


class HistoryMoney(HistoryFact[Decimal]):
    @field_validator("value", mode="before")
    @classmethod
    def exact(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        return _decimal(value)


class RegionalCohort(HistoryModel):
    company_id: str = Field(min_length=1, max_length=200)
    target_id: str = Field(min_length=1, max_length=200)
    law: Literal["44", "223"]
    region: str | None = Field(min_length=1, max_length=200)
    product_key: str | None = Field(min_length=1, max_length=500)
    procedure: str | None = Field(min_length=1, max_length=100)
    unit: str | None = Field(min_length=1, max_length=200)
    quantity: Decimal | None = Field(gt=0)
    period_start: AwareDatetime
    period_end: AwareDatetime
    source: Provenance

    @model_validator(mode="after")
    def target_identity(self) -> RegionalCohort:
        match = re.fullmatch(r"(44|223):([0-9]{1,23}):(0|[1-9][0-9]{0,5})", self.target_id)
        if (
            match is None
            or match[1] != self.law
            or (self.law == "44" and match[3] != "0")
            or (self.law == "223" and match[3] == "0")
        ):
            raise ValueError("HISTORY_TARGET_IDENTITY_INVALID")
        return self

    @field_validator("quantity", mode="before")
    @classmethod
    def exact(cls, value: object) -> Decimal | None:
        return None if value is None else _decimal(value)

    @field_validator("region", "product_key", "procedure", "unit", "company_id", "target_id")
    @classmethod
    def not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("HISTORY_COHORT_BLANK")
        return value


class RegionalObservation(HistoryModel):
    company_id: str = Field(min_length=1, max_length=200)
    purchase_number: str = Field(pattern=r"^[0-9]{11,23}$")
    law: Literal["44", "223"]
    region: HistoryFact[str]
    product_key: HistoryFact[str]
    procedure: HistoryFact[str]
    unit: HistoryFact[str]
    quantity: HistoryMoney
    initial: HistoryMoney
    final: HistoryMoney
    concluded_at: HistoryFact[AwareDatetime]
    concluded_date: HistoryFact[date] | None = None
    qualification_reasons: tuple[str, ...] = Field(default=(), max_length=40)
    price_basis: Literal["RUB_NOMINAL_DECLARED_SIGNED_TOTALS"] = (
        "RUB_NOMINAL_DECLARED_SIGNED_TOTALS"
    )
    price_scope: Literal["WHOLE_NOTICE", "WHOLE_CUSTOMER_CONTRACT"] = "WHOLE_NOTICE"
    customer: HistoryFact[str] | None = None
    # Each assertion needs an actual source, not a client-supplied PASS flag.
    notice_lot_volume_link: HistoryFact[StrictBool]
    rub_nominal_totals: HistoryFact[StrictBool]
    concluded_contract: HistoryFact[StrictBool]
    current_result: HistoryFact[StrictBool]


class RegionalHistory(HistoryModel):
    cohort: RegionalCohort
    observations: tuple[RegionalObservation, ...] = Field(max_length=20)
    source_reasons: tuple[str, ...] = Field(default=(), max_length=20)


class RegionalEvaluation(HistoryModel):
    observation: RegionalObservation
    status: Literal["PASS", "UNKNOWN"]
    reasons: tuple[str, ...]
    discount: Decimal | None


class RegionalDiscountReport(HistoryModel):
    policy: Literal["regional-discount-v2"] = POLICY
    checked_at: AwareDatetime
    cohort: RegionalCohort
    status: Literal["PASS", "UNKNOWN"]
    evaluated: tuple[RegionalEvaluation, ...]
    sample_size: int
    required_sample: Literal[5] = MIN_SAMPLE
    realistic_discount: Decimal | None
    conservative_discount: Decimal | None
    reasons: tuple[str, ...]
    interpretation: Literal["SCENARIO_ASSUMPTION_NOT_WIN_PROBABILITY"] = (
        "SCENARIO_ASSUMPTION_NOT_WIN_PROBABILITY"
    )
    coverage: Literal["UNKNOWN"] = "UNKNOWN"


def _key(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def regional_discount(history: RegionalHistory, *, now: datetime) -> RegionalDiscountReport:
    """Nearest-rank median/p75 of independent, comparable concluded contracts.

    Например, пять подтверждённых снижений10/20/30/40/50% дают median30% иp75=40%;
    четыре наблюдения оставляют результат UNKNOWN.
    Invalid and uncertain observations remain visible and do not enter quantiles.
    Repeated procurement IDs are all excluded: no arbitrary revision selection.
    """
    cohort = history.cohort
    if now.utcoffset() is None or not cohort.period_start < cohort.period_end <= now:
        raise ValueError("HISTORY_PERIOD_INVALID")
    duplicates = Counter((o.law, o.purchase_number) for o in history.observations)
    evaluated = []
    rates = []
    for observation in history.observations:
        reasons = list(observation.qualification_reasons)
        if observation.company_id != cohort.company_id:
            raise ValueError("HISTORY_TENANT_MISMATCH")
        if duplicates[observation.law, observation.purchase_number] > 1:
            reasons.append("DUPLICATE_PROCUREMENT")
        if f"{observation.law}:{observation.purchase_number}" == ":".join(
            cohort.target_id.split(":")[:2]
        ):
            reasons.append("TARGET_IS_NOT_HISTORY")
        if observation.law != cohort.law:
            reasons.append("LAW_MISMATCH")
        if observation.price_scope == "WHOLE_CUSTOMER_CONTRACT" and (
            observation.customer is None
            or not re.fullmatch(r"[0-9]{11}", observation.customer.value or "")
        ):
            reasons.append("CUSTOMER_SCOPE_IDENTITY_NOT_CONFIRMED")
        for name in ("region", "product_key", "procedure", "unit"):
            value = getattr(observation, name).value
            if not _key(value) or _key(value) != _key(getattr(cohort, name)):
                reasons.append(f"{name.upper()}_MISSING_OR_MISMATCH")
        for name in (
            "notice_lot_volume_link",
            "rub_nominal_totals",
            "concluded_contract",
            "current_result",
        ):
            if getattr(observation, name).value is not True:
                reasons.append(f"{name.upper()}_NOT_CONFIRMED")
        date = observation.concluded_at.value
        within_period = date is not None and cohort.period_start <= date < cohort.period_end
        if observation.concluded_date is not None:
            day = observation.concluded_date.value
            within_period = False
            if day is not None:
                lower, upper = source_date_bounds(day)
                within_period = cohort.period_start <= lower and upper <= cohort.period_end
        if not within_period:
            reasons.append("CONCLUSION_OUTSIDE_PERIOD_OR_UNKNOWN")
        quantity, initial, final = (
            observation.quantity.value,
            observation.initial.value,
            observation.final.value,
        )
        discount = None
        with localcontext() as context:
            context.prec = 80
            if (
                quantity is None
                or cohort.quantity is None
                or not cohort.quantity / 2 <= quantity <= cohort.quantity * 2
            ):
                reasons.append("VOLUME_OUTSIDE_HALF_TO_DOUBLE_OR_UNKNOWN")
            if initial is None or final is None or not 0 < final <= initial:
                reasons.append("PRICES_NOT_POSITIVE_COMPARABLE_TOTALS")
            if not reasons:
                assert initial is not None and final is not None
                # Round upwards so rate precision cannot improve estimated profit.
                discount = ((initial - final) / initial).quantize(
                    Decimal("0.000001"), rounding=ROUND_CEILING
                )
                if discount >= 1:
                    reasons.append("DISCOUNT_UNREPRESENTABLE")
                    discount = None
        if discount is not None:
            rates.append(discount)
        evaluated.append(
            RegionalEvaluation(
                observation=observation,
                status="UNKNOWN" if reasons else "PASS",
                reasons=tuple(reasons),
                discount=discount,
            )
        )
    rates.sort()
    sufficient = len(rates) >= MIN_SAMPLE
    return RegionalDiscountReport(
        checked_at=now,
        cohort=cohort,
        status="PASS" if sufficient else "UNKNOWN",
        evaluated=tuple(evaluated),
        sample_size=len(rates),
        realistic_discount=rates[(len(rates) - 1) // 2] if sufficient else None,
        conservative_discount=rates[(3 * len(rates) + 3) // 4 - 1] if sufficient else None,
        reasons=history.source_reasons
        + (() if sufficient else ("INSUFFICIENT_VERIFIED_COMPARABLE_RESULTS",))
        + (
            ("TARGET_COHORT_INCOMPLETE",)
            if any(
                getattr(cohort, key) is None
                for key in ("region", "product_key", "procedure", "unit", "quantity")
            )
            else ()
        ),
    )
