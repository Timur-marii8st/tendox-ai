"""Source-bound read of an existing supplier HTML; no caller prices or HTTP."""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal, localcontext
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from procurement.domain.provenance import Provenance
from procurement.domain.public_price_opportunity import AmountFact, PublicPrice
from procurement.sources.eis_supplier_product import SupplierProductRequest
from procurement.sources.public_unit_price import extract_public_unit_price
from procurement.storage.eis_supplier_product import _product_parent
from procurement.storage.repository import PostgresStorage


class PublicUnitPriceReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    policy: Literal["saved-public-unit-price-v1"] = "saved-public-unit-price-v1"
    company_id: str = Field(min_length=1)
    request: SupplierProductRequest
    checked_at: AwareDatetime
    position_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    price: PublicPrice | None
    required_quantity: AmountFact | None
    required_unit: str | None
    required_unit_provenance: Provenance
    quantity_cost_rub: Decimal | None
    status: Literal["CALCULATED", "UNKNOWN"]
    missing: tuple[str, ...]
    profit: Literal["UNKNOWN"] = "UNKNOWN"
    technical: Literal["UNKNOWN"] = "UNKNOWN"
    quote: Literal["UNKNOWN"] = "UNKNOWN"
    source_requests: Literal[0] = 0

    @model_validator(mode="after")
    def exact_scope(self) -> PublicUnitPriceReport:
        ref = self.request.catalog.page.position.selection
        if self.required_unit_provenance.document_id != ref.notice.notice_xml_sha256:
            raise ValueError("PUBLIC_QUANTITY_SOURCE_MISMATCH")
        if self.required_quantity is not None and (
            self.required_quantity.provenance.document_id != ref.notice.notice_xml_sha256
        ):
            raise ValueError("PUBLIC_QUANTITY_SOURCE_MISMATCH")
        if self.price is not None and (
            self.price.company_id != self.company_id
            or self.price.source_sha256 != self.source_sha256
            or self.price.notice_xml_sha256 != ref.notice.notice_xml_sha256
            or self.price.line_id != str(ref.source_index)
        ):
            raise ValueError("PUBLIC_PRICE_SCOPE_MISMATCH")
        if self.status == "CALCULATED":
            if (
                self.quantity_cost_rub is None
                or not self.quantity_cost_rub.is_finite()
                or self.quantity_cost_rub <= 0
                or self.missing
                or self.price is None
                or self.required_quantity is None
            ):
                raise ValueError("PUBLIC_PRICE_CALCULATION_INCOMPLETE")
        elif self.quantity_cost_rub is not None or not self.missing:
            raise ValueError("PUBLIC_PRICE_UNKNOWN_HAS_COST")
        return self


def read_public_unit_price(
    storage: PostgresStorage,
    company: str,
    request: SupplierProductRequest,
    *,
    now: datetime | None = None,
) -> PublicUnitPriceReport:
    """Read current/tenant/parent-bound source; a partial position is never lot profit."""
    at = now or datetime.now(UTC)
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_REQUIRED")
    with storage.transaction(company, consistent_read=True) as connection:
        parent, _, content, position, position_sha = _product_parent(
            connection, company, request, body=True
        )
    assert parent.observation is not None and content is not None
    selection = request.catalog.page.position.selection
    price = extract_public_unit_price(
        content,
        parent.observation,
        company_id=company,
        notice_xml_sha256=selection.notice.notice_xml_sha256,
        line_id=str(selection.source_index),
        now=at,
    )
    quantity = None
    raw_quantity = position.position.quantity
    if raw_quantity.value is not None:
        with suppress(ValidationError):
            quantity = AmountFact(value=raw_quantity.value, provenance=raw_quantity.provenance)
    unit = position.position.unit
    cost = None
    missing = []
    names = {
        "шт": "piece",
        "шт.": "piece",
        "штука": "piece",
        "штук": "piece",
        "кг": "kg",
        "г": "g",
        "м": "m",
    }
    if price is None:
        missing.append("EXPLICIT_PRICE_BASIS_UNAVAILABLE")
    elif not timedelta(0) <= at - price.observed_at <= timedelta(hours=24):
        missing.append("PUBLIC_PRICE_STALE")
    elif price.availability == "UNAVAILABLE":
        missing.append("PUBLIC_PRODUCT_UNAVAILABLE")
    if quantity is None or quantity.value <= 0:
        missing.append("REQUIRED_QUANTITY_UNKNOWN")
    if price is not None and names.get((unit.value or "").strip().lower()) != price.unit.code:
        missing.append("UNIT_COMPARABILITY_UNKNOWN")
    if not missing and price is not None and quantity is not None:
        with localcontext() as context:
            context.prec = 80
            cost = (price.price.value * quantity.value / price.quantity_per_price.value).quantize(
                Decimal("0.01"), rounding=ROUND_CEILING
            )
        if cost > Decimal("1000000000000000000"):
            cost = None
            missing.append("POSITION_COST_LIMIT")
    return PublicUnitPriceReport(
        company_id=company,
        request=request,
        checked_at=at,
        position_sha256=position_sha,
        source_sha256=parent.source_body_sha256 or "",
        price=price,
        required_quantity=quantity,
        required_unit=unit.value,
        required_unit_provenance=unit.provenance,
        quantity_cost_rub=cost,
        status="CALCULATED" if cost is not None else "UNKNOWN",
        missing=tuple(missing),
    )
