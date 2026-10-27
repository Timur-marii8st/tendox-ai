"""Strict official 44-FZ declared/signed nominal totals; no VAT or execution inference."""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any, Literal

from pydantic import AwareDatetime, Field

from procurement.domain.provenance import Provenance
from procurement.domain.regional_discount import HistoryFact, HistoryModel, HistoryMoney
from procurement.sources.eis_contract_characteristics import SpecProfile, parse_spec

EXPORT = "http://zakupki.gov.ru/oos/export/1"
TYPES = "http://zakupki.gov.ru/oos/types/1"
EP = "http://zakupki.gov.ru/oos/EPtypes/1"
COMMON = "http://zakupki.gov.ru/oos/common/1"
BASE = "http://zakupki.gov.ru/oos/base/1"
MAX_XML = 4 * 1024**2
MAX_ITEMS = 25
MAX_PARTITION_ITEMS = 1000
MAX_CUSTOMERS = 200
MAX_ALLOCATIONS = 2000
ITEM_PATH = "notificationInfo/purchaseObjectsInfo/notDrugPurchaseObjectsInfo/c:purchaseObject"
CUSTOMER_PATH = "notificationInfo/customerRequirementsInfo/customerRequirementInfo"
PRICE_PATH = "notificationInfo/contractConditionsInfo/maxPriceInfo/maxPrice"


class MarketItem(HistoryModel):
    sid: HistoryFact[str]
    product_key: HistoryFact[str]
    quantity: HistoryMoney
    unit: HistoryFact[str]
    line_sum: HistoryMoney
    specification: SpecProfile


class MarketNotice(HistoryModel):
    purchase_number: str
    version: int
    xml_sha256: str
    kind: str
    published_at: HistoryFact[AwareDatetime]
    initial: HistoryMoney
    notice_initial: HistoryMoney
    scope_kind: Literal["WHOLE_NOTICE", "WHOLE_CUSTOMER_CONTRACT"] = "WHOLE_NOTICE"
    customer: HistoryFact[str] | None = None
    currency: HistoryFact[str]
    items: tuple[MarketItem, ...] = Field(max_length=MAX_ITEMS)
    delivery_addresses: tuple[HistoryFact[str], ...] = Field(max_length=100)
    reasons: tuple[str, ...]


class ContractResult(HistoryModel):
    registry_number: str
    kind: str
    xml_sha256: str
    version: int | None
    purchase_number: HistoryFact[str]
    customer: HistoryFact[str]
    signed_on: HistoryFact[date]
    published_at: HistoryFact[AwareDatetime]
    price: HistoryMoney
    currency: HistoryFact[str]
    price_type: HistoryFact[str]
    items: tuple[MarketItem, ...] = Field(max_length=MAX_ITEMS)
    delivery_addresses: tuple[HistoryFact[str], ...] = Field(max_length=100)
    foundation_signature: str
    commercial_fingerprint: str
    reasons: tuple[str, ...]


class _XML:
    def __init__(self, raw: bytes, member: str, kinds: set[str], namespace: str) -> None:
        if (
            not raw
            or len(raw) > MAX_XML
            or b"\0" in raw
            or re.search(rb"<!\s*(?:DOCTYPE|ENTITY)\b", raw, re.I)
            or len(member.encode()) > 255
        ):
            raise ValueError("CONTRACT_XML_UNSAFE")
        try:
            raw.decode("utf-8-sig")
            root = ET.fromstring(raw)
        except (UnicodeError, ET.ParseError) as error:
            raise ValueError("CONTRACT_XML_INVALID") from error
        if root.tag != f"{{{EXPORT}}}export" or len(root) != 1:
            raise ValueError("CONTRACT_EXPORT_INVALID")
        self.node = root[0]
        self.kind = self.node.tag.removeprefix(f"{{{EXPORT}}}")
        if self.kind not in kinds or self.node.tag != f"{{{EXPORT}}}{self.kind}":
            raise ValueError("CONTRACT_DOCUMENT_UNSUPPORTED")
        self.ns = namespace
        self.sha = hashlib.sha256(raw).hexdigest()
        self.member = member

    def nodes(self, path: str) -> list[ET.Element]:
        def qualified(part: str) -> str:
            if ":" in part:
                prefix, name = part.split(":", 1)
                namespace = {"b": BASE, "c": COMMON, "e": EP, "t": TYPES}[prefix]
                return f"{{{namespace}}}{name}"
            return f"{{{self.ns}}}{part}"

        return self.node.findall("/".join(qualified(part) for part in path.split("/")))

    def text(self, path: str) -> str | None:
        nodes = self.nodes(path)
        if len(nodes) > 1:
            raise ValueError("CONTRACT_DUPLICATE_SCALAR")
        if not nodes or len(nodes[0]):
            return None
        value = (nodes[0].text or "").strip()
        return value if value and len(value) <= 2000 else None

    def source(self, path: str) -> Provenance:
        return Provenance(
            document_id=self.sha, locator=f"{self.member} :: {self.kind}/{path}", extractor="api"
        )

    def fact(self, path: str) -> HistoryFact[Any]:
        return HistoryFact(value=self.text(path), source=self.source(path))

    def money(self, path: str) -> HistoryMoney:
        raw = self.text(path)
        value = (
            Decimal(raw) if raw and re.fullmatch(r"[0-9]{1,20}(?:\.[0-9]{1,11})?", raw) else None
        )
        return HistoryMoney(value=value, source=self.source(path))

    def time(self, path: str) -> HistoryFact[Any]:
        from datetime import datetime

        raw = self.text(path)
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00")) if raw else None
        except ValueError:
            value = None
        if value is not None and value.utcoffset() is None:
            value = None
        return HistoryFact(value=value, source=self.source(path))

    def child(self, node: ET.Element, path: str, namespace: str) -> _XML:
        child = object.__new__(_XML)
        child.node, child.ns = node, namespace
        child.kind, child.sha, child.member = f"{self.kind}/{path}", self.sha, self.member
        return child

    def items(
        self,
        path: str,
        *,
        notice: bool,
        limit: int = MAX_ITEMS,
    ) -> tuple[tuple[MarketItem, ...], list[str]]:
        nodes = self.nodes(path)
        if not 1 <= len(nodes) <= limit:
            return (), ["WHOLE_SCOPE_ITEMS_UNAVAILABLE_OR_LIMIT"]
        items = []
        reasons = []
        for index, node in enumerate(nodes, 1):
            # Rebase strict paths on one selected item, retaining exact indexed locators.
            original, kind, namespace = self.node, self.kind, self.ns
            self.node = node
            if notice:
                self.ns = COMMON
            self.kind = kind + "/" + path + f"[{index}]"
            try:
                name = self.text("name")
                ktru_path = "KTRU/b:code" if notice else "KTRU/code"
                unit_path = "OKEI/b:code" if notice else "OKEI/code"
                okpd_path = "OKPD2/b:OKPDCode" if notice else "OKPD2/code"
                ktru = self.text(ktru_path)
                okpd = self.text(okpd_path) or self.text(
                    "KTRU/OKPD2/b:OKPDCode" if notice else "KTRU/OKPD2/OKPDCode"
                )
                key = (
                    f"KTRU:{ktru}"
                    if ktru
                    else (
                        f"OKPD2:{okpd};NAME:{' '.join(name.casefold().split())}"
                        if okpd and name
                        else None
                    )
                )
                key_source = self.source(ktru_path if ktru else okpd_path)
                supporting = () if ktru else (self.source("name"),)
                specification = parse_spec(self.node, notice=notice)
                if specification.reasons or specification.signature is None:
                    reasons.append("SOURCE_PRODUCT_CHARACTERISTICS_UNSUPPORTED")
                if specification.present:
                    supporting += (self.source("KTRU/characteristics"),)
                if key is not None and len(key) > 500:
                    key = None
                    reasons.append("SOURCE_PRODUCT_KEY_LIMIT")
                if self.nodes("drugPurchaseObjectInfo"):
                    reasons.append("DRUG_SCOPE_NOT_SUPPORTED")
                if self.nodes("improvedProductReplacement") and self.text(
                    "improvedProductReplacement"
                ) not in {"false", "0"}:
                    reasons.append("REPLACED_SOURCE_PRODUCT")
                quantity = self.money("quantity/value" if notice else "quantity")
                # CommonTypes16.3 purchaseObjects2020Type: the method applies to
                # WORK/SERVICE. PRODUCT may explicitly declare a numeric quantity
                # without this optional method; never synthesize a QF source fact.
                numeric_goods = (
                    notice
                    and not self.nodes("volumeSpecifyingMethod")
                    and self.text("type") == "PRODUCT"
                    and quantity.value is not None
                    and quantity.value > 0
                    and not self.nodes("quantity/undefined")
                    and not self.nodes("volumeTextForm")
                    and not self.nodes("quantity/volumeTextForm")
                )
                if self.text("volumeSpecifyingMethod") != "QF" and not numeric_goods:
                    reasons.append("FIXED_PRODUCT_VOLUME_NOT_CONFIRMED")
                item = MarketItem(
                    sid=self.fact("sid" if notice else "purchaseObjectSid"),
                    product_key=HistoryFact(
                        value=key, source=key_source, supporting_sources=supporting
                    ),
                    quantity=quantity,
                    unit=self.fact(unit_path),
                    line_sum=self.money("sum"),
                    specification=specification,
                )
                items.append(item)
            finally:
                self.node, self.kind, self.ns = original, kind, namespace
        return tuple(items), reasons


def _unique_source_child(node: ET.Element, name: str, namespace: str) -> ET.Element | None:
    matches = [child for child in node if child.tag.rsplit("}", 1)[-1] == name]
    return matches[0] if len(matches) == 1 and matches[0].tag == f"{{{namespace}}}{name}" else None


def _sole_customer_number(x: _XML) -> str | None:
    """Only one exact source path can identify the sole buyer; aliases stay ambiguous."""
    node = x.node
    for name in (
        "notificationInfo",
        "customerRequirementsInfo",
        "customerRequirementInfo",
        "customer",
        "regNum",
    ):
        namespace = BASE if name == "regNum" else EP
        child = _unique_source_child(node, name, namespace)
        if child is None:
            return None
        node = child
    value = (node.text or "").strip()
    return value if not len(node) and re.fullmatch(r"[0-9]{11}", value) else None


def _automatic_partition_unambiguous(x: _XML) -> bool:
    """Do not silently omit namespace aliases from an automatically selected scope."""
    for parent in x.node.iter():
        qualified: dict[str, str] = {}
        for child in parent:
            name = child.tag.rsplit("}", 1)[-1]
            if name in qualified and qualified[name] != child.tag:
                return False
            qualified[name] = child.tag
    parent = x.node
    for name in ("notificationInfo", "purchaseObjectsInfo", "notDrugPurchaseObjectsInfo"):
        child = _unique_source_child(parent, name, EP)
        if child is None:
            return False
        parent = child
    goods = [child for child in parent if child.tag.rsplit("}", 1)[-1] == "purchaseObject"]
    if not 1 <= len(goods) <= MAX_PARTITION_ITEMS:
        return False
    count = 0
    for item in goods:
        if item.tag != f"{{{COMMON}}}purchaseObject":
            return False
        allocations = _unique_source_child(item, "customerQuantities", COMMON)
        if allocations is None or not len(allocations):
            return False
        count += len(allocations)
        if count > MAX_ALLOCATIONS:
            return False
        for allocation in allocations:
            if allocation.tag != f"{{{COMMON}}}customerQuantity":
                return False
            customer = _unique_source_child(allocation, "customer", COMMON)
            quantity = _unique_source_child(allocation, "quantity", COMMON)
            if customer is None or quantity is None or len(quantity):
                return False
            number = _unique_source_child(customer, "regNum", BASE)
            if number is None or len(number):
                return False
    return True


def notice_market(raw: bytes, member: str, *, customer_number: str | None = None) -> MarketNotice:
    """Re-extract exact source IDs and whole fixed scope; never guess a missing quantity."""
    x = _XML(
        raw, member, {"epNotificationEF2020", "epNotificationEZK2020", "epNotificationEOK2020"}, EP
    )
    number = x.text("commonInfo/purchaseNumber")
    version = x.text("versionNumber")
    if number is None or not re.fullmatch(r"[0-9]{19,23}", number) or not (version or "").isdigit():
        raise ValueError("CONTRACT_NOTICE_IDENTITY_INVALID")
    if customer_number is not None and (
        not isinstance(customer_number, str) or not re.fullmatch(r"[0-9]{11}", customer_number)
    ):
        raise ValueError("CUSTOMER_NUMBER_INVALID")
    requirements = x.nodes(CUSTOMER_PATH)
    joint = len(requirements) > 1 or bool(x.nodes(ITEM_PATH + "/c:customerQuantities"))
    automatic_partition_ambiguous = False
    if joint and customer_number is None and len(requirements) == 1:
        # A sole source buyer is unambiguous, but its entire allocation must still
        # pass _customer_partition. Never choose among multiple requirements.
        sole = _sole_customer_number(x)
        if sole is not None:
            if _automatic_partition_unambiguous(x):
                customer_number = sole
            else:
                automatic_partition_ambiguous = True
    items, reasons = x.items(ITEM_PATH, notice=True) if not joint else ((), [])
    notice_initial = x.money(PRICE_PATH)
    initial = notice_initial
    customer = None
    scope_kind: Literal["WHOLE_NOTICE", "WHOLE_CUSTOMER_CONTRACT"] = "WHOLE_NOTICE"
    currency = x.fact("notificationInfo/contractConditionsInfo/maxPriceInfo/currency/b:code")
    if currency.value not in {"RUB", "RUR", "643"}:
        reasons.append("NOTICE_NATIVE_RUB_NOT_CONFIRMED")
    formula = x.text("notificationInfo/contractConditionsInfo/maxPriceInfo/isContractPriceFormula")
    if x.nodes(
        "notificationInfo/contractConditionsInfo/maxPriceInfo/isContractPriceFormula"
    ) and formula not in {"false", "0"}:
        reasons.append("NOTICE_FORMULA_PRICE_NOT_SUPPORTED")
    if x.text(
        "notificationInfo/purchaseObjectsInfo/notDrugPurchaseObjectsInfo/quantityUndefined"
    ) not in {"false", "0"}:
        reasons.append("NOTICE_QUANTITY_DEFINITION_UNKNOWN")
    delivery_path = (
        "notificationInfo/customerRequirementsInfo/customerRequirementInfo/"
        "contractConditionsInfo/deliveryPlacesInfo"
    )
    addresses, delivery_reasons = _delivery(x, delivery_path, EP) if not joint else ((), [])
    reasons.extend(delivery_reasons)
    if joint:
        scope_kind = "WHOLE_CUSTOMER_CONTRACT"
        # A joint notice's global price is never an individual buyer's baseline.
        initial = HistoryMoney(value=None, source=notice_initial.source)
        items, addresses = (), ()
        if customer_number is None:
            reasons.append("CUSTOMER_IDENTITY_REQUIRED")
            if automatic_partition_ambiguous:
                reasons.append("CUSTOMER_PARTITION_SOURCE_AMBIGUOUS")
        else:
            initial, currency, items, addresses, customer, customer_reasons = _customer_partition(
                x,
                customer_number,
                notice_initial,
                currency,
            )
            reasons.extend(customer_reasons)
    elif customer_number is not None:
        if len(requirements) == 1:
            buyer = x.child(requirements[0], CUSTOMER_PATH + "[1]", EP)
            customer = buyer.fact("customer/b:regNum")
        if customer is None or customer.value != customer_number:
            reasons.append("CUSTOMER_IDENTITY_UNCONFIRMED")
            initial = HistoryMoney(value=None, source=notice_initial.source)
    return MarketNotice(
        purchase_number=number,
        version=int(version or "0"),
        xml_sha256=x.sha,
        kind=x.kind,
        published_at=x.time("commonInfo/publishDTInEIS"),
        initial=initial,
        notice_initial=notice_initial,
        scope_kind=scope_kind,
        customer=customer,
        currency=currency,
        items=items,
        delivery_addresses=addresses,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def _customer_partition(
    x: _XML,
    customer_number: str,
    global_initial: HistoryMoney,
    currency: HistoryFact[str],
) -> tuple[
    HistoryMoney,
    HistoryFact[str],
    tuple[MarketItem, ...],
    tuple[HistoryFact[str], ...],
    HistoryFact[str] | None,
    list[str],
]:
    """Validate the entire source partition before exposing one buyer's scope."""
    empty = HistoryMoney(value=None, source=global_initial.source)
    customer: HistoryFact[str] | None = None
    requirements, goods = x.nodes(CUSTOMER_PATH), x.nodes(ITEM_PATH)
    if not (1 <= len(requirements) <= MAX_CUSTOMERS and 1 <= len(goods) <= MAX_PARTITION_ITEMS):
        return empty, currency, (), (), customer, ["CUSTOMER_PARTITION_LIMIT"]
    reasons: list[str] = []
    buyers: dict[str, tuple[_XML, HistoryMoney, HistoryFact[str]]] = {}
    for index, node in enumerate(requirements, 1):
        buyer = x.child(node, CUSTOMER_PATH + f"[{index}]", EP)
        fact = buyer.fact("customer/b:regNum")
        if fact.value is None or not re.fullmatch(r"[0-9]{11}", fact.value):
            reasons.append("CUSTOMER_PARTITION_IDENTITY_INVALID")
            continue
        if fact.value in buyers:
            reasons.append("CUSTOMER_PARTITION_DUPLICATE_BUYER")
            continue
        maximum = buyer.money("contractConditionsInfo/maxPriceInfo/maxPrice")
        if maximum.value is None or maximum.value <= 0:
            reasons.append("CUSTOMER_INITIAL_UNCONFIRMED")
        # EP maxPriceInfoType declares RUB maxPrice, with no own currency.
        # maxPriceCurrency is not the baseline and is never converted here.
        if buyer.nodes("contractConditionsInfo/maxPriceInfo/currency"):
            reasons.append("CUSTOMER_CURRENCY_SCOPE_UNSUPPORTED")
        for path in (
            "contractConditionsInfo/maxPriceInfo/isContractPriceFormula",
            "contractConditionsInfo/isContractPriceFormula",
        ):
            if buyer.nodes(path) and buyer.text(path) not in {"false", "0"}:
                reasons.append("CUSTOMER_FORMULA_PRICE_NOT_SUPPORTED")
        buyers[fact.value] = buyer, maximum, fact
    selected = buyers.get(customer_number)
    if selected is None:
        reasons.append("CUSTOMER_IDENTITY_UNCONFIRMED")
    else:
        customer = selected[2]
    source_items, item_reasons = x.items(ITEM_PATH, notice=True, limit=MAX_PARTITION_ITEMS)
    reasons.extend(item_reasons)
    if global_initial.value is None or global_initial.value <= 0:
        reasons.append("CUSTOMER_GLOBAL_INITIAL_UNCONFIRMED")
    if currency.value not in {"RUB", "RUR", "643"}:
        reasons.append("CUSTOMER_NATIVE_RUB_NOT_CONFIRMED")
    selected_items: list[MarketItem] = []
    seen_sids: set[str] = set()
    allocation_count = 0
    totals = dict.fromkeys(buyers, Decimal(0))
    global_lines = Decimal(0)
    with localcontext() as context:
        context.prec = 80
        for index, (node, item) in enumerate(zip(goods, source_items, strict=True), 1):
            source = x.child(node, ITEM_PATH + f"[{index}]", COMMON)
            sid = item.sid.value
            if not sid or sid in seen_sids:
                reasons.append("CUSTOMER_PARTITION_SID_INVALID_OR_DUPLICATE")
            if sid:
                seen_sids.add(sid)
            if source.text("type") != "PRODUCT":
                reasons.append("CUSTOMER_PARTITION_NON_PRODUCT")
            if any(
                source.nodes(path)
                for path in (
                    "quantity/undefined",
                    "quantity/volumeTextForm",
                    "volumeTextForm",
                )
            ):
                reasons.append("CUSTOMER_PARTITION_QUANTITY_UNCONFIRMED")
            quantity, price, declared = item.quantity, source.money("price"), item.line_sum
            if any(fact.value is None or fact.value <= 0 for fact in (quantity, price, declared)):
                reasons.append("CUSTOMER_PARTITION_ITEM_NUMERIC_UNCONFIRMED")
            if declared.value is not None:
                global_lines += declared.value
            if (
                quantity.value is not None
                and price.value is not None
                and declared.value is not None
            ):
                computed = (quantity.value * price.value).quantize(Decimal(".01"), ROUND_HALF_UP)
                if abs(computed - declared.value) > Decimal(".01"):
                    reasons.append("CUSTOMER_PARTITION_ITEM_TOTAL_CONFLICT")
            allocations = source.nodes("customerQuantities/customerQuantity")
            allocation_count += len(allocations)
            if allocation_count > MAX_ALLOCATIONS:
                return empty, currency, (), (), customer, ["CUSTOMER_PARTITION_LIMIT"]
            if not allocations:
                reasons.append("CUSTOMER_PARTITION_ALLOCATION_MISSING")
            seen_buyers: set[str] = set()
            allocated = Decimal(0)
            for ordinal, allocation_node in enumerate(allocations, 1):
                allocation = source.child(
                    allocation_node,
                    f"customerQuantities/customerQuantity[{ordinal}]",
                    COMMON,
                )
                buyer_fact = allocation.fact("customer/b:regNum")
                number = buyer_fact.value
                if number not in buyers or number in seen_buyers:
                    reasons.append("CUSTOMER_PARTITION_ALLOCATION_BUYER_INVALID")
                if number:
                    seen_buyers.add(number)
                own_quantity = allocation.money("quantity")
                if own_quantity.value is None or own_quantity.value <= 0:
                    reasons.append("CUSTOMER_PARTITION_QUANTITY_UNCONFIRMED")
                    continue
                allocated += own_quantity.value
                if price.value is None:
                    continue
                amount = (price.value * own_quantity.value).quantize(Decimal(".01"), ROUND_HALF_UP)
                if number in totals:
                    totals[number] += amount
                if number == customer_number:
                    selected_items.append(
                        item.model_copy(
                            update={
                                "quantity": HistoryMoney(
                                    value=own_quantity.value,
                                    source=own_quantity.source,
                                    supporting_sources=(quantity.source, buyer_fact.source),
                                ),
                                "line_sum": HistoryMoney(
                                    value=amount,
                                    source=price.source,
                                    supporting_sources=(
                                        own_quantity.source,
                                        buyer_fact.source,
                                        declared.source,
                                    ),
                                ),
                            }
                        )
                    )
            if quantity.value is None or allocated != quantity.value:
                reasons.append("CUSTOMER_PARTITION_QUANTITY_CONFLICT")
        maximums = [entry[1].value for entry in buyers.values()]
        if any(value is None for value in maximums) or (
            global_initial.value is None
            or sum((value for value in maximums if value is not None), Decimal(0))
            != global_initial.value
        ):
            reasons.append("CUSTOMER_PARTITION_GLOBAL_TOTAL_CONFLICT")
        if global_initial.value is None or abs(global_lines - global_initial.value) > Decimal(
            ".01"
        ):
            reasons.append("CUSTOMER_PARTITION_GLOBAL_TOTAL_CONFLICT")
        for number, (_, maximum, _) in buyers.items():
            if maximum.value is None or abs(totals[number] - maximum.value) > Decimal(".01"):
                reasons.append("CUSTOMER_PARTITION_BUYER_TOTAL_CONFLICT")
    addresses: tuple[HistoryFact[str], ...] = ()
    if selected is not None:
        addresses, delivery_reasons = _delivery(
            selected[0], "contractConditionsInfo/deliveryPlacesInfo", EP
        )
        reasons.extend(delivery_reasons)
    if not 1 <= len(selected_items) <= MAX_ITEMS:
        reasons.append("CUSTOMER_SELECTED_ITEMS_UNAVAILABLE_OR_LIMIT")
    if reasons:
        return empty, currency, (), (), customer, list(dict.fromkeys(reasons))
    assert selected is not None  # Proven by the absence of CUSTOMER_IDENTITY_UNCONFIRMED.
    return selected[1], currency, tuple(selected_items), addresses, customer, []


def contract_result(raw: bytes, member: str) -> ContractResult:
    """Read RGK registration and nominal price; signing date retains DATE precision."""
    x = _XML(raw, member, {"contract", "contractCancel", "contractProcedure"}, TYPES)
    registry = x.text("regNum") or x.text("contractRegNum")
    if registry is None or not re.fullmatch(r"[0-9]{19,23}", registry):
        raise ValueError("CONTRACT_REGISTRY_IDENTITY_INVALID")
    version_raw = x.text("versionNumber")
    version = int(version_raw) if (version_raw or "").isdigit() else None
    signed = x.text("signDate")
    try:
        signed_on = date.fromisoformat(signed) if signed else None
    except ValueError:
        signed_on = None
    items, reasons = x.items("products/product", notice=False) if x.kind == "contract" else ((), [])
    if x.kind == "contract":
        for path, reason in [
            ("isInvalid", "CONTRACT_INVALID_IN_SOURCE"),
            ("products/quantityUndefined", "CONTRACT_UNDEFINED_VOLUME_NOT_SUPPORTED"),
        ]:
            value = x.text(path)
            if x.nodes(path) and value not in {"false", "0"}:
                reasons.append(reason)
        if x.text("priceInfo/priceType") != "P":
            reasons.append("FIXED_CONTRACT_PRICE_NOT_CONFIRMED")
        if x.text("priceInfo/currency/code") not in {"RUB", "RUR", "643"}:
            reasons.append("CONTRACT_NATIVE_RUB_NOT_CONFIRMED")
        if (
            x.nodes("priceInfo/rightToConcludeContractPriceInfo")
            or x.nodes("priceInfo/priceFormula")
            or (
                x.nodes("priceInfo/maxPriceAndPriceFormulaSpecified")
                and x.text("priceInfo/maxPriceAndPriceFormulaSpecified") not in {"false", "0"}
            )
        ):
            reasons.append("FORMULA_OR_RIGHT_TO_CONCLUDE_PRICE")
        if x.nodes("conclusionContractSt95Ch17.1") and x.text(
            "conclusionContractSt95Ch17.1"
        ) not in {"false", "0"}:
            reasons.append("REPLACEMENT_CONTRACT_NOT_ORIGINAL_AWARD")
    addresses, delivery_reasons = _delivery(x, "deliveryPlaceInfo", COMMON)
    if x.kind == "contract":
        reasons.extend(delivery_reasons)
    foundation = x.nodes("foundation")
    # Compare the full foundation on revisions, not merely notificationNumber.
    signature = (
        hashlib.sha256(ET.tostring(foundation[0])).hexdigest() if len(foundation) == 1 else ""
    )
    scope = []
    for path in (
        "foundation",
        "customer",
        "priceInfo",
        "products",
        "deliveryPlaceInfo",
        "signDate",
        "contractSubject",
        "executionPeriod",
    ):
        for node in x.nodes(path):
            scope.append(
                ET.canonicalize(
                    ET.tostring(node, encoding="unicode"), strip_text=True, rewrite_prefixes=True
                )
            )
    commercial_fingerprint = hashlib.sha256("\n".join(scope).encode()).hexdigest()
    return ContractResult(
        registry_number=registry,
        kind=x.kind,
        xml_sha256=x.sha,
        version=version,
        purchase_number=x.fact("foundation/fcsOrder/order/notificationNumber"),
        customer=x.fact("customer/regNum"),
        signed_on=HistoryFact(value=signed_on, source=x.source("signDate")),
        published_at=x.time("publishDate"),
        price=x.money("priceInfo/price"),
        currency=x.fact("priceInfo/currency/code"),
        price_type=x.fact("priceInfo/priceType"),
        items=items,
        delivery_addresses=tuple(addresses),
        foundation_signature=signature,
        commercial_fingerprint=commercial_fingerprint,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def _delivery(
    x: _XML, path: str, gar_namespace: str
) -> tuple[tuple[HistoryFact[str], ...], list[str]]:
    addresses: list[HistoryFact[str]] = []
    reasons = []
    blocks = x.nodes(path)
    if not blocks:
        return (), ["DELIVERY_SCOPE_NOT_EXTRACTED"]
    seen_addresses: set[str] = set()
    references = 0
    for ordinal, block in enumerate(blocks, 1):
        for index, node in enumerate(block, 1):
            references += 1
            if references > 2000:
                raise ValueError("CONTRACT_DELIVERY_REFERENCE_LIMIT")
            if node.tag != f"{{{gar_namespace}}}byGARInfo":
                reasons.append("DELIVERY_SCOPE_UNSUPPORTED")
                continue
            values = node.findall(f"{{{COMMON}}}GARInfo/{{{COMMON}}}GARAddress")
            value = (
                (values[0].text or "").strip() if len(values) == 1 and not len(values[0]) else None
            )
            if not value or len(value) > 2000:
                reasons.append("DELIVERY_ADDRESS_UNKNOWN")
                continue
            if value in seen_addresses:
                continue  # Repeated identical delivery declarations add no region evidence.
            seen_addresses.add(value)
            addresses.append(
                HistoryFact(
                    value=value,
                    source=x.source(f"{path}[{ordinal}]/byGARInfo[{index}]/GARInfo/GARAddress"),
                )
            )
            if len(addresses) > 100:
                raise ValueError("CONTRACT_DELIVERY_LIMIT")
    return tuple(addresses), list(dict.fromkeys(reasons))
