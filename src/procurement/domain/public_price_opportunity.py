"""Предварительная выгодность по источникам цен, без повышения до полного КП."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal, localcontext
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_serializer,
    field_validator,
    model_validator,
)

from procurement.domain.discovery_economics import (
    DiscoveryCostInput,
    DiscoveryEstimate,
    calculate_discovery_economics,
)
from procurement.domain.provenance import Provenance


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AmountFact(Frozen):
    value: Decimal = Field(ge=0, le=Decimal("1000000000000000000"))
    provenance: Provenance

    @field_serializer("value")
    def plain_decimal(self, value: Decimal) -> str:
        return format(value, "f")

    @field_validator("value", mode="before")
    @classmethod
    def exact(cls, value: object) -> object:
        if isinstance(value, (float, bool)) or not isinstance(value, (Decimal, str, int)):
            raise ValueError("EXACT_DECIMAL_REQUIRED")
        return value

    @field_validator("value")
    @classmethod
    def bounded_precision(cls, value: Decimal) -> Decimal:
        exponent = value.as_tuple().exponent
        if not isinstance(exponent, int) or exponent < -6:
            raise ValueError("DECIMAL_PRECISION_LIMIT")
        return value


class TradeUnit(Frozen):
    """Упаковки сравнимы только при явно записанном одинаковом содержимом."""

    code: Literal["piece", "pack", "box", "g", "kg", "m"]
    contents: str | None = Field(default=None, min_length=1, max_length=200)
    provenance: Provenance


class RequiredLine(Frozen):
    line_id: str = Field(min_length=1, max_length=200)
    quantity: AmountFact
    unit: TradeUnit


class PublicPrice(Frozen):
    company_id: str = Field(min_length=1)
    notice_xml_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    line_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_url: str = Field(min_length=1, max_length=2048)
    observed_at: AwareDatetime
    price: AmountFact
    quantity_per_price: AmountFact
    unit: TradeUnit
    currency: Literal["RUB", "UNKNOWN"]
    amount_basis: Literal["EX_VAT", "GROSS", "UNKNOWN"]
    currency_provenance: Provenance
    amount_basis_provenance: Provenance
    technical_status: Literal["PASS", "FAIL", "UNKNOWN"] = "UNKNOWN"
    availability: Literal["IN_STOCK", "UNAVAILABLE", "UNKNOWN"] = "UNKNOWN"
    price_kind: Literal["EXACT", "FROM", "RANGE"] = "EXACT"

    @model_validator(mode="after")
    def source_binding(self) -> PublicPrice:
        if any(
            fact.provenance.document_id != self.source_sha256
            for fact in (self.price, self.quantity_per_price, self.unit)
        ):
            raise ValueError("PUBLIC_PRICE_SOURCE_MISMATCH")
        if any(
            source.document_id != self.source_sha256
            for source in (self.currency_provenance, self.amount_basis_provenance)
        ):
            raise ValueError("PUBLIC_PRICE_SOURCE_MISMATCH")
        return self


class OpportunityRequest(Frozen):
    company_id: str = Field(min_length=1)
    notice_xml_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    ceiling: AmountFact
    deadline: AwareDatetime
    deadline_provenance: Provenance
    blocked: StrictBool = False
    blocking_sources: tuple[Provenance, ...] = ()
    source_line_count: StrictInt = Field(ge=1, le=200)
    line_count_provenance: Provenance
    lines: tuple[RequiredLine, ...] = Field(min_length=1, max_length=200)
    prices: tuple[PublicPrice, ...] = Field(max_length=1000)
    # Полные прочие расходы без НДС и выходной НДС — только из явных источников.
    other_expenses: AmountFact | None = None
    expenses_complete: StrictBool = False
    expenses_completeness_provenance: Provenance | None = None
    vat_rate: AmountFact | None = None


class SelectedPrice(Frozen):
    line_id: str
    source: PublicPrice
    goods_net_rub: Decimal


class PublicOpportunity(Frozen):
    request: OpportunityRequest
    checked_at: AwareDatetime
    max_price_age: timedelta
    company_id: str
    notice_xml_sha256: str
    status: Literal["ESTIMATE", "UNKNOWN", "BLOCKED"]
    selected: tuple[SelectedPrice, ...]
    goods_net_rub: Decimal | None
    estimate: DiscoveryEstimate | None
    missing: tuple[str, ...]
    assumptions: tuple[str, ...]
    quote_status: Literal["UNKNOWN"] = "UNKNOWN"
    participation: Literal["UNKNOWN"] = "UNKNOWN"
    policy: Literal["public-price-opportunity-v1"] = "public-price-opportunity-v1"


def _same_unit(left: TradeUnit, right: TradeUnit) -> bool:
    if left.code != right.code:
        return False
    if left.code in {"pack", "box"}:
        return left.contents is not None and left.contents == right.contents
    return left.contents == right.contents


def calculate_public_opportunity(
    request: OpportunityRequest, *, now: datetime, max_price_age: timedelta
) -> PublicOpportunity:
    """Выбирает минимальную сопоставимую цену каждой позиции полного лота.

    Возраст цен задаёт вызывающая policy. Нельзя ранжировать UNKNOWN как прибыль.
    Сетевых запросов и сохранения здесь нет; публичная цена не становится КП.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_REQUIRED")
    if max_price_age <= timedelta(0):
        raise ValueError("PRICE_AGE_POLICY_REQUIRED")
    ids = [line.line_id for line in request.lines]
    if len(set(ids)) != len(ids) or any(line.quantity.value <= 0 for line in request.lines):
        raise ValueError("EXACT_POSITIVE_LINE_QUANTITIES_REQUIRED")
    if any(
        price.company_id != request.company_id
        or price.notice_xml_sha256 != request.notice_xml_sha256
        or price.line_id not in ids
        for price in request.prices
    ):
        raise ValueError("PRICE_SCOPE_MISMATCH")
    if request.deadline_provenance.document_id != request.notice_xml_sha256:
        raise ValueError("DEADLINE_SOURCE_MISMATCH")
    if request.blocked and not request.blocking_sources:
        raise ValueError("BLOCKER_SOURCE_REQUIRED")
    if request.line_count_provenance.document_id != request.notice_xml_sha256:
        raise ValueError("LOT_COMPOSITION_SOURCE_MISMATCH")
    if request.ceiling.provenance.document_id != request.notice_xml_sha256:
        raise ValueError("CEILING_SOURCE_MISMATCH")
    if any(
        line.quantity.provenance.document_id != request.notice_xml_sha256
        or line.unit.provenance.document_id != request.notice_xml_sha256
        for line in request.lines
    ):
        raise ValueError("QUANTITY_SOURCE_MISMATCH")
    if request.vat_rate is not None and request.vat_rate.value > 1:
        raise ValueError("VAT_RATE_INVALID")
    if request.blocked or request.deadline <= now:
        return PublicOpportunity(
            request=request,
            checked_at=now,
            max_price_age=max_price_age,
            company_id=request.company_id,
            notice_xml_sha256=request.notice_xml_sha256,
            status="BLOCKED",
            selected=(),
            goods_net_rub=None,
            estimate=None,
            missing=("SOURCE_OR_DEADLINE_BLOCKER",),
            assumptions=(),
        )
    selected: list[SelectedPrice] = []
    missing = (
        [] if request.source_line_count == len(request.lines) else ["LOT_COMPOSITION_INCOMPLETE"]
    )
    for line in request.lines:
        options = []
        for price in request.prices:
            if (
                price.line_id != line.line_id
                or price.technical_status == "FAIL"
                or price.availability == "UNAVAILABLE"
                or price.price_kind != "EXACT"
                or price.currency != "RUB"
                or price.amount_basis != "EX_VAT"
                or not timedelta(0) <= now - price.observed_at <= max_price_age
                or price.price.value <= 0
                or price.quantity_per_price.value <= 0
                or not _same_unit(line.unit, price.unit)
            ):
                continue
            with localcontext() as context:
                context.prec = 80
                amount = (
                    price.price.value * line.quantity.value / price.quantity_per_price.value
                ).quantize(Decimal("0.01"), rounding=ROUND_CEILING)
            if amount > Decimal("1000000000000000000"):
                continue
            options.append(SelectedPrice(line_id=line.line_id, source=price, goods_net_rub=amount))
        if not options:
            missing.append(f"COMPARABLE_PUBLIC_PRICE:{line.line_id}")
        else:
            selected.append(
                min(
                    options,
                    key=lambda item: (
                        item.goods_net_rub,
                        item.source.source_url,
                        item.source.price.provenance.locator,
                    ),
                )
            )
    assumptions = (
        "Публичные цены не являются действующим КП; наличие, объём и условия уточняются.",
        "Сопоставимость единицы цены не подтверждает соответствие полному ТЗ.",
        "Линейная цена на объём — предварительное допущение; MOQ и шаг заказа не проверены.",
        "Сценарии beta v1: снижение 0%/5%/10%, рост затрат в conservative 10%.",
    )
    goods = None
    if not missing:
        with localcontext() as context:
            context.prec = 80
            goods = sum((item.goods_net_rub for item in selected), Decimal(0))
        if goods > Decimal("1000000000000000000"):
            goods = None
            missing.append("LOT_COST_LIMIT")
    if request.other_expenses is None:
        missing.append("OTHER_EXPENSES_UNKNOWN")
    if not request.expenses_complete or request.expenses_completeness_provenance is None:
        missing.append("OTHER_EXPENSES_COMPLETENESS_UNKNOWN")
    if request.vat_rate is None:
        missing.append("TAX_MODEL_UNKNOWN")
    if request.ceiling.value <= 0:
        missing.append("CEILING_UNKNOWN")
    if missing or goods is None:
        return PublicOpportunity(
            request=request,
            checked_at=now,
            max_price_age=max_price_age,
            company_id=request.company_id,
            notice_xml_sha256=request.notice_xml_sha256,
            status="UNKNOWN",
            selected=tuple(selected),
            goods_net_rub=goods,
            estimate=None,
            missing=tuple(missing),
            assumptions=assumptions,
        )
    assert request.other_expenses is not None and request.vat_rate is not None
    costs = DiscoveryCostInput(
        goods=goods,
        expenses=request.other_expenses.value,
        vat_rate=request.vat_rate.value,
        basis="Автоматический предварительный расчёт по привязанным публичным источникам.",
        costs_complete_ack=True,
    )
    estimate = calculate_discovery_economics(request.ceiling.value, costs)
    return PublicOpportunity(
        request=request,
        checked_at=now,
        max_price_age=max_price_age,
        company_id=request.company_id,
        notice_xml_sha256=request.notice_xml_sha256,
        status=estimate.status,
        selected=tuple(selected),
        goods_net_rub=goods,
        estimate=estimate,
        missing=(),
        assumptions=assumptions,
    )


def rank_public_opportunities(
    company_id: str, candidates: tuple[tuple[str, PublicOpportunity], ...]
) -> tuple[tuple[str, PublicOpportunity], ...]:
    """До пяти положительных оценок по conservative прибыли, затем марже.

    UNKNOWN не получает место или балл прибыли; это предварительный shortlist,
    а не допуск и не утверждение, что найден весь рынок.
    """
    if not company_id.strip() or any(row.company_id != company_id for _, row in candidates):
        raise ValueError("TENANT_MISMATCH")
    if len({key for key, _ in candidates}) != len(candidates):
        raise ValueError("DUPLICATE_CANDIDATE")
    scored = []
    for key, row in candidates:
        if row.status != "ESTIMATE" or row.estimate is None:
            continue
        conservative = next((s for s in row.estimate.scenarios if s.kind == "conservative"), None)
        if conservative is not None and conservative.profit > 0:
            scored.append((conservative.profit, conservative.margin, key, row))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    seen: set[str] = set()
    ranked: list[tuple[str, PublicOpportunity]] = []
    for _, _, key, row in scored:
        if row.notice_xml_sha256 in seen:
            continue
        seen.add(row.notice_xml_sha256)
        ranked.append((key, row))
        if len(ranked) == 5:
            break
    return tuple(ranked)
