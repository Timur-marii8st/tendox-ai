"""Извлекает явную единицу цены из exact сохранённого Product JSON-LD."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from procurement.domain.provenance import Extractor, Provenance
from procurement.domain.public_price_opportunity import AmountFact, PublicPrice, TradeUnit
from procurement.sources.supplier_page import (
    MAX_BODY_BYTES,
    MAX_NODES,
    PageObservation,
    _invalid_constant,
    _json_depth_safe,
    _kind,
    _Markup,
    _unique_pairs,
)

_UNITS = {
    "шт": "piece",
    "шт.": "piece",
    "штука": "piece",
    "штук": "piece",
    "piece": "piece",
    "pieces": "piece",
    "кг": "kg",
    "kg": "kg",
    "г": "g",
    "g": "g",
    "м": "m",
    "m": "m",
}


def extract_public_unit_price(
    content: bytes,
    observation: PageObservation,
    *,
    company_id: str,
    notice_xml_sha256: str,
    line_id: str,
    now: datetime,
) -> PublicPrice | None:
    """Нет referenceQuantity/VAT — нет догадки. Никаких HTTP или исполнения HTML."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_REQUIRED")
    if (
        len(content) > MAX_BODY_BYTES
        or observation.html_sha256 is None
        or hashlib.sha256(content).hexdigest() != observation.html_sha256
    ):
        raise ValueError("PUBLIC_PRICE_BODY_MISMATCH")
    if (
        observation.status != "COMPLETED"
        or observation.page_kind != "PRODUCT"
        or observation.extraction_status != "EXTRACTED"
        or len(observation.products) != 1
    ):
        return None
    product = observation.products[0]
    if len(product.prices) != 1 or product.prices[0].price_kind != "EXACT":
        return None
    markup = _Markup()
    markup.feed(content.decode("utf-8", errors="replace"))
    markup.close()
    if markup.limit or markup.current is not None:
        return None
    selected: dict[str, Any] | None = None
    nodes = 0
    for index, script in enumerate(markup.scripts):
        if not _json_depth_safe(script):
            return None
        try:
            root = json.loads(
                script,
                parse_float=Decimal,
                object_pairs_hook=_unique_pairs,
                parse_constant=_invalid_constant,
            )
        except (ValueError, RecursionError):
            return None
        stack = [(root, f"jsonld[{index}]$")]
        while stack:
            value, path = stack.pop()
            nodes += 1
            if nodes > MAX_NODES or len(path) > 200:
                return None
            if isinstance(value, dict):
                if path == product.locator and _kind(value.get("@type"), "Product"):
                    selected = value
                stack.extend((v, path + "." + k) for k, v in value.items() if k != "@context")
            elif isinstance(value, list):
                stack.extend((v, path + f"[{i}]") for i, v in enumerate(value))
    if selected is None:
        return None
    offer = selected.get("offers")
    if isinstance(offer, list) and len(offer) == 1:
        offer = offer[0]
    if not isinstance(offer, dict) or not _kind(offer.get("@type"), "Offer"):
        return None
    spec = offer.get("priceSpecification")
    if not isinstance(spec, dict) or not _kind(spec.get("@type"), "UnitPriceSpecification"):
        return None
    if any(
        key in spec
        for key in (
            "eligibleQuantity",
            "eligibleTransactionVolume",
            "minPrice",
            "maxPrice",
            "priceComponentType",
            "priceType",
            "billingDuration",
            "billingIncrement",
            "billingStart",
            "validForMemberTier",
        )
    ):
        return None
    if any(
        key in offer
        for key in (
            "eligibleQuantity",
            "eligibleTransactionVolume",
            "validForMemberTier",
        )
    ):
        return None
    if "valueAddedTaxIncluded" in offer and (
        type(offer["valueAddedTaxIncluded"]) is not bool
        or offer["valueAddedTaxIncluded"] != spec.get("valueAddedTaxIncluded")
    ):
        return None
    for owner in (offer, spec):
        for key, future in (
            ("validFrom", True),
            ("validThrough", False),
            ("priceValidUntil", False),
        ):
            if key not in owner:
                continue
            raw = owner[key]
            try:
                at = datetime.fromisoformat(raw) if isinstance(raw, str) else None
            except ValueError:
                return None
            if (
                at is None
                or at.tzinfo is None
                or at.utcoffset() is None
                or (future and at > now)
                or (not future and at <= now)
            ):
                return None
    reference = spec.get("referenceQuantity")
    if not isinstance(reference, dict) or not _kind(reference.get("@type"), "QuantitativeValue"):
        return None
    # Codes/pack contents require an independent, source-bound mapping policy.
    if "unitCode" in reference or "unitCode" in spec:
        return None
    raw_unit = reference.get("unitText")
    code = _UNITS.get(raw_unit.strip().lower()) if isinstance(raw_unit, str) else None
    if code is None:
        return None
    if "unitText" in spec and spec["unitText"] != raw_unit:
        return None
    displayed = product.prices[0]
    if displayed.currency != "RUB" or spec.get("priceCurrency") != "RUB":
        return None
    vat = spec.get("valueAddedTaxIncluded")
    if type(vat) is not bool:
        return None
    path = displayed.locator.removesuffix(".price") + ".priceSpecification"
    digest = observation.html_sha256

    def fact(value: object, locator: str) -> AmountFact:
        return AmountFact.model_validate(
            {
                "value": value,
                "provenance": {
                    "document_id": digest,
                    "locator": locator,
                    "extractor": Extractor.API,
                },
            }
        )

    try:
        amount = fact(spec.get("price"), path + ".price")
        quantity = fact(reference.get("value"), path + ".referenceQuantity.value")
        if amount.value != displayed.amount or amount.value <= 0 or quantity.value <= 0:
            return None
        return PublicPrice.model_validate(
            {
                "company_id": company_id,
                "notice_xml_sha256": notice_xml_sha256,
                "line_id": line_id,
                "source_sha256": digest,
                "source_url": observation.final_url,
                "observed_at": observation.observed_at,
                "price": amount,
                "quantity_per_price": quantity,
                "unit": TradeUnit.model_validate(
                    {
                        "code": code,
                        "provenance": Provenance(
                            document_id=digest,
                            locator=path + ".referenceQuantity.unitText",
                            extractor=Extractor.API,
                        ),
                    }
                ),
                "currency": "RUB",
                "amount_basis": "GROSS" if vat else "EX_VAT",
                "currency_provenance": Provenance(
                    document_id=digest, locator=path + ".priceCurrency", extractor=Extractor.API
                ),
                "amount_basis_provenance": Provenance(
                    document_id=digest,
                    locator=path + ".valueAddedTaxIncluded",
                    extractor=Extractor.API,
                ),
                "availability": "UNAVAILABLE"
                if offer.get("availability")
                in (
                    "https://schema.org/OutOfStock",
                    "https://schema.org/Discontinued",
                    "http://schema.org/OutOfStock",
                    "http://schema.org/Discontinued",
                    "OutOfStock",
                    "Discontinued",
                )
                else "UNKNOWN",
            }
        )
    except ValidationError:
        return None
