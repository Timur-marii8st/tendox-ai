"""Explicit 223-FZ AESMBO metadata reader; admission and global coverage unknown."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Literal, cast
from urllib.parse import parse_qs, urlsplit
from uuid import UUID
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.domain.provenance import Extractor, Provenance

PURCHASE_NS = "http://zakupki.gov.ru/223fz/purchase/1"
TYPES_NS = "http://zakupki.gov.ru/223fz/types/1"
DOCUMENT_TYPE: Literal["purchaseNoticeAESMBO"] = "purchaseNoticeAESMBO"
TARGETED_DOCUMENT_TYPE: Literal["purchaseNoticeKESMBO"] = "purchaseNoticeKESMBO"
Eis223DocumentType = Literal[
    "purchaseNoticeAESMBO", "purchaseNoticeZKESMBO", "purchaseNotice", "purchaseNoticeKESMBO"
]
SUPPORTED_DOCUMENT_TYPES: tuple[Eis223DocumentType, ...] = (
    DOCUMENT_TYPE,
    "purchaseNoticeZKESMBO",
    "purchaseNotice",
)
PARSABLE_DOCUMENT_TYPES: tuple[Eis223DocumentType, ...] = (
    *SUPPORTED_DOCUMENT_TYPES,
    TARGETED_DOCUMENT_TYPE,
)
MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_XML_BYTES = 4 * 1024 * 1024  # Shared event/lot-event contract remains unchanged.
MAX_NOTICE_XML_BYTES = 12 * 1024 * 1024
MAX_NOTICE_ITEMS = 6000
MAX_EXPANDED_BYTES = 32 * 1024 * 1024
MAX_MEMBERS = 200
BASE = f"{DOCUMENT_TYPE}/p:body/p:item/p:{DOCUMENT_TYPE}Data"


class Eis223ContractError(ValueError):
    """An exact source record cannot be safely interpreted."""


class SourceModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TextFact(SourceModel):
    value: str | None
    raw: str | None
    provenance: Provenance


class DecimalFact(SourceModel):
    value: Decimal | None
    raw: str | None
    provenance: Provenance

    @field_validator("value", mode="before")
    @classmethod
    def _no_float(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("decimal source fact cannot use float")
        return value

    @field_validator("value")
    @classmethod
    def _finite(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (not value.is_finite() or value < 0):
            raise ValueError("decimal source fact must be finite and nonnegative")
        return value


class TimeFact(SourceModel):
    value: datetime | None
    raw: str | None
    provenance: Provenance
    status: Literal["AWARE", "UNKNOWN"]

    @model_validator(mode="after")
    def _aware_only(self) -> TimeFact:
        if self.value is not None and (
            self.value.tzinfo is None or self.value.utcoffset() is None or self.status != "AWARE"
        ):
            raise ValueError("source datetime must be timezone-aware")
        if self.value is None and self.status != "UNKNOWN":
            raise ValueError("missing time remains unknown")
        return self


class Eis223Attachment(SourceModel):
    filename: TextFact
    content_uid: TextFact
    url: TextFact
    not_placement_raw: TextFact | None = None


class Eis223ManifestReference(SourceModel):
    kind: Literal["DOCUMENT_FS", "PREVIOUS_DOCUMENT"]
    guid: TextFact
    content_uid: TextFact
    provenance: Provenance


class Eis223LotItem(SourceModel):
    description: TextFact
    classification_code: TextFact
    classification_name: TextFact
    quantity: DecimalFact
    unit_code: TextFact
    unit_name: TextFact
    provenance: Provenance


class Eis223Lot(SourceModel):
    ordinal: TextFact
    subject: TextFact
    initial_sum: DecimalFact
    currency: TextFact
    currency_numeric: TextFact
    initial_sum_rub: Decimal | None
    cancelled_raw: TextFact
    items: tuple[Eis223LotItem, ...]
    provenance: Provenance
    guid: TextFact | None = None
    detail_status: Literal["PRESENT", "UNKNOWN"] | None = None
    source_price_kind: (
        Literal["INITIAL_SUM", "MAX_CONTRACT_PRICE", "TEXT_ONLY", "UNKNOWN"] | None
    ) = None
    source_amount: DecimalFact | None = None
    source_rub_equivalent: DecimalFact | None = None
    source_price_text: TextFact | None = None
    source_price_formula: TextFact | None = None
    source_price_formula_present: bool | None = None
    source_commodity_price: DecimalFact | None = None
    source_commodity_price_present: bool | None = None
    currency_letter_code: TextFact | None = None
    source_currency_status: Literal["CONSISTENT", "UNKNOWN"] | None = None
    for_small_or_middle_raw: TextFact | None = None

    @field_validator("initial_sum_rub", mode="before")
    @classmethod
    def _no_float(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("money cannot use float")
        return value

    @model_validator(mode="after")
    def _rub_has_source(self) -> Eis223Lot:
        if (
            self.source_price_formula_present is False
            and self.source_price_formula is not None
            and self.source_price_formula.raw is not None
        ) or (
            self.source_commodity_price_present is False
            and self.source_commodity_price is not None
            and self.source_commodity_price.raw is not None
        ):
            raise ValueError("source price presence flags must retain exact fields")
        if self.source_price_kind is None:
            expected = (
                self.initial_sum.value
                if self.currency.value in {"RUB", "RUR"}
                and self.currency_numeric.value in {None, "643"}
                else None
            )
        else:
            expected = (
                self.initial_sum.value
                if self.source_price_kind == "INITIAL_SUM"
                and self.source_currency_status == "CONSISTENT"
                and self.currency_letter_code is not None
                and (self.currency_letter_code.value or self.currency.value) in {"RUB", "RUR"}
                and self.currency_numeric.value in {None, "643"}
                and self.source_price_formula_present is False
                and self.source_commodity_price_present is False
                else None
            )
        if self.initial_sum_rub != expected:
            raise ValueError("rub amount requires consistent source currency")
        return self


class Eis223NoticeSnapshot(SourceModel):
    law: Literal["223"] = "223"
    document_type: Eis223DocumentType = DOCUMENT_TYPE
    purchase_number: str = Field(pattern=r"^[0-9]{11}$")
    version_number: int = Field(ge=1)
    identity_provenance: tuple[Provenance, Provenance]
    title: TextFact
    method_code: TextFact
    method_name: TextFact
    publication: TimeFact
    deadline: TimeFact
    customer_timezone_offset_raw: TextFact
    status_raw: TextFact
    xml_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_member: str
    lots: tuple[Eis223Lot, ...]
    attachments: tuple[Eis223Attachment, ...]
    manifest_status: Literal["COUNT_CONSISTENT", "UNKNOWN"]
    manifest_count: TextFact
    purchase_guid: TextFact | None = None
    hide_purchase_raw: TextFact | None = None
    hide_purchase_customer_accredited_raw: TextFact | None = None
    for_small_or_middle_raw: TextFact | None = None
    is_lot_oriented_raw: TextFact | None = None
    selected_deadline: TimeFact | None = None
    manifest_additional_count: TextFact | None = None
    manifest_references: tuple[Eis223ManifestReference, ...] = ()
    application_status: Literal["UNKNOWN"] = "UNKNOWN"
    economics_status: Literal["UNKNOWN"] = "UNKNOWN"
    lot_review_status: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def _source_bound(self) -> Eis223NoticeSnapshot:
        if self.document_type == "purchaseNotice":
            required = (
                self.purchase_guid,
                self.hide_purchase_raw,
                self.hide_purchase_customer_accredited_raw,
                self.for_small_or_middle_raw,
                self.is_lot_oriented_raw,
                self.selected_deadline,
                self.manifest_additional_count,
            )
            if any(value is None for value in required):
                raise ValueError("generic notice extensions are required")
            assert self.hide_purchase_raw is not None
            assert self.hide_purchase_customer_accredited_raw is not None
            assert self.is_lot_oriented_raw is not None
            assert self.selected_deadline is not None
            assert self.manifest_additional_count is not None
            if self.is_lot_oriented_raw.value == "false":
                if self.selected_deadline != self.deadline:
                    raise ValueError("selected deadline must retain exact notice deadline")
            elif self.selected_deadline.value is not None:
                raise ValueError("lot-oriented or unknown schedule has no selected deadline")
            hidden = self.hide_purchase_raw.value not in {
                None,
                "false",
            } or self.hide_purchase_customer_accredited_raw.value not in {None, "false"}
            for attachment in self.attachments:
                if attachment.not_placement_raw is None:
                    raise ValueError("generic attachment flags are required")
                restricted = attachment.not_placement_raw.value not in {None, "false"}
                if (hidden or restricted) and attachment.url.value is not None:
                    raise ValueError("restricted attachment URL must be suppressed")
            if self.manifest_status == "COUNT_CONSISTENT" and (
                self.manifest_count.value != str(len(self.attachments))
                or self.manifest_references
                or self.manifest_additional_count.value is not None
                or any(
                    attachment.not_placement_raw is not None
                    and attachment.not_placement_raw.value is not None
                    for attachment in self.attachments
                )
            ):
                raise ValueError("generic manifest count has unsupported references")
            for lot in self.lots:
                lot_required = (
                    lot.guid,
                    lot.detail_status,
                    lot.source_price_kind,
                    lot.source_amount,
                    lot.source_rub_equivalent,
                    lot.source_price_text,
                    lot.source_price_formula,
                    lot.source_price_formula_present,
                    lot.source_commodity_price,
                    lot.source_commodity_price_present,
                    lot.currency_letter_code,
                    lot.source_currency_status,
                    lot.for_small_or_middle_raw,
                )
                if any(value is None for value in lot_required):
                    raise ValueError("generic lot extensions are required")

        def check(value: object) -> None:
            if isinstance(value, Provenance):
                if value.document_id != self.xml_sha256:
                    raise ValueError("every fact must refer to exact XML")
                prefix = f"{self.document_type}/p:body/p:item/p:{self.document_type}Data"
                if value.locator != prefix and not value.locator.startswith(prefix + "/"):
                    raise ValueError("every fact must refer to the selected source family")
            elif isinstance(value, BaseModel):
                for name in type(value).model_fields:
                    check(getattr(value, name))
            elif isinstance(value, tuple):
                for item in value:
                    check(item)

        for name in type(self).model_fields:
            check(getattr(self, name))
        return self


class Eis223ArchiveInspection(SourceModel):
    company_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    archive_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_response_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_locator: str = Field(min_length=1, max_length=500)
    records: tuple[Eis223NoticeSnapshot, ...]
    corpus_coverage: Literal["UNKNOWN"] = "UNKNOWN"
    schema_basis: Literal["VERIFIED_SHAPE_16_2_16_3"] = "VERIFIED_SHAPE_16_2_16_3"


def notice223_request(
    token: str,
    request_id: str,
    region: str,
    day: date,
    *,
    document_type: Eis223DocumentType = DOCUMENT_TYPE,
) -> bytes:
    """One explicit public/actual RI223 family from the verified NSI catalogue."""
    if (
        document_type not in SUPPORTED_DOCUMENT_TYPES
        or not re.fullmatch(r"[A-Za-z0-9-]{16,128}", token)
        or not re.fullmatch(r"[0-9]{2}", region)
    ):
        raise Eis223ContractError("REQUEST_CONFIG_INVALID")
    try:
        identifier = str(UUID(request_id))
    except ValueError as error:
        raise Eis223ContractError("REQUEST_ID_INVALID") from error
    soap = "http://schemas.xmlsoap.org/soap/envelope/"
    service = "http://zakupki.gov.ru/fz44/get-docs-ip/ws"
    envelope = ET.Element(f"{{{soap}}}Envelope")
    ET.SubElement(
        ET.SubElement(envelope, f"{{{soap}}}Header"), "individualPerson_token"
    ).text = token
    payload = ET.SubElement(
        ET.SubElement(envelope, f"{{{soap}}}Body"), f"{{{service}}}getDocsByOrgRegionRequest"
    )
    index = ET.SubElement(payload, "index")
    for key, value in (
        ("id", identifier),
        ("createDateTime", datetime.now(UTC).isoformat()),
        ("mode", "PROD"),
    ):
        ET.SubElement(index, key).text = value
    params = ET.SubElement(payload, "selectionParams")
    for key, value in (
        ("orgRegion", region),
        ("subsystemType", "RI223"),
        ("documentType223", document_type),
    ):
        ET.SubElement(params, key).text = value
    ET.SubElement(ET.SubElement(params, "periodInfo"), "exactDate").text = (
        day.isoformat() + "+03:00"
    )
    serialized = ET.tostring(envelope, encoding="utf-8", xml_declaration=True)
    assert isinstance(serialized, bytes)
    return serialized


def _children(parent: ET.Element, namespace: str, name: str) -> list[ET.Element]:
    matches = [e for e in parent if e.tag.rsplit("}", 1)[-1] == name]
    if any(e.tag != f"{{{namespace}}}{name}" for e in matches):
        raise Eis223ContractError("FIELD_NAMESPACE_INVALID")
    return matches


def _one(parent: ET.Element, namespace: str, name: str) -> ET.Element:
    matches = _children(parent, namespace, name)
    if len(matches) != 1:
        raise Eis223ContractError("FIELD_MISSING_OR_DUPLICATE")
    return matches[0]


def _optional(parent: ET.Element | None, namespace: str, name: str) -> ET.Element | None:
    if parent is None:
        return None
    matches = _children(parent, namespace, name)
    if len(matches) > 1:
        raise Eis223ContractError("FIELD_DUPLICATE")
    return matches[0] if matches else None


def _raw(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    if len(element):
        raise Eis223ContractError("SCALAR_NESTED")
    return (element.text or "").strip() or None


def _provenance(sha: str, path: str) -> Provenance:
    return Provenance(document_id=sha, locator=path, extractor=Extractor.API)


def _text(parent: ET.Element | None, namespace: str, name: str, sha: str, path: str) -> TextFact:
    raw = _raw(_optional(parent, namespace, name))
    if raw is not None and len(raw) > 10000:
        raise Eis223ContractError("TEXT_LIMIT")
    return TextFact(value=raw, raw=raw, provenance=_provenance(sha, path))


def _decimal(parent: ET.Element, name: str, sha: str, path: str) -> DecimalFact:
    raw = _raw(_optional(parent, TYPES_NS, name))
    value = None
    if (
        raw is not None
        and len(raw) <= 100
        and re.fullmatch(r"[+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", raw)
    ):
        try:
            parsed = Decimal(raw)
            if parsed.is_finite() and parsed >= 0:
                value = parsed
        except InvalidOperation:
            pass
    return DecimalFact(value=value, raw=raw, provenance=_provenance(sha, path))


def _time(data: ET.Element, name: str, sha: str, base: str = BASE) -> TimeFact:
    raw = _raw(_optional(data, PURCHASE_NS, name))
    value = None
    if raw and len(raw) <= 100 and "T" in raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is not None and parsed.utcoffset() is not None:
                value = parsed
        except ValueError:
            pass
    return TimeFact(
        value=value,
        raw=raw,
        provenance=_provenance(sha, base + "/p:" + name),
        status="AWARE" if value else "UNKNOWN",
    )


def parse_notice223_xml(
    raw: bytes,
    *,
    source_member: str,
    document_type: str = DOCUMENT_TYPE,
) -> Eis223NoticeSnapshot:
    if document_type not in PARSABLE_DOCUMENT_TYPES:
        raise Eis223ContractError("DOCUMENT_TYPE_UNSUPPORTED")
    base = f"{document_type}/p:body/p:item/p:{document_type}Data"
    if (
        not raw
        or len(raw) > MAX_NOTICE_XML_BYTES
        or b"\x00" in raw
        or any(s in raw.upper() for s in (b"<!DOCTYPE", b"<!ENTITY"))
    ):
        raise Eis223ContractError("XML_REJECTED")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as error:
        raise Eis223ContractError("XML_INVALID") from error
    if root.tag != f"{{{PURCHASE_NS}}}{document_type}":
        raise Eis223ContractError("DOCUMENT_TYPE_UNSUPPORTED")
    data = _one(
        _one(_one(root, PURCHASE_NS, "body"), PURCHASE_NS, "item"),
        PURCHASE_NS,
        document_type + "Data",
    )
    number = _raw(_one(data, PURCHASE_NS, "registrationNumber")) or ""
    version = _raw(_one(data, PURCHASE_NS, "version")) or ""
    if not re.fullmatch(r"[0-9]{11}", number) or not re.fullmatch(r"[1-9][0-9]{0,8}", version):
        raise Eis223ContractError("NOTICE_IDENTITY_INVALID")
    sha = hashlib.sha256(raw).hexdigest()
    generic = document_type == "purchaseNotice"
    hide_purchase = _text(data, PURCHASE_NS, "hidePurchase", sha, base + "/p:hidePurchase")
    hide_accredited = _text(
        data,
        PURCHASE_NS,
        "hidePurchaseCustomerAccredited",
        sha,
        base + "/p:hidePurchaseCustomerAccredited",
    )
    lot_oriented = _text(data, PURCHASE_NS, "isLotOriented", sha, base + "/p:isLotOriented")
    lots_element = _optional(data, PURCHASE_NS, "lots")
    lots = []
    for index, lot in enumerate(
        _children(lots_element, TYPES_NS, "lot") if lots_element is not None else [], 1
    ):
        path = base + f"/p:lots/t:lot[{index}]"
        detail = _optional(lot, TYPES_NS, "lotData") if generic else _one(lot, TYPES_NS, "lotData")
        detail_path = path + "/t:lotData"
        currency = _optional(detail, TYPES_NS, "currency")
        code = _text(currency, TYPES_NS, "code", sha, detail_path + "/t:currency/t:code")
        numeric = _text(
            currency, TYPES_NS, "digitalCode", sha, detail_path + "/t:currency/t:digitalCode"
        )
        amount = (
            _decimal(detail, "initialSum", sha, detail_path + "/t:initialSum")
            if detail is not None
            else DecimalFact(
                value=None,
                raw=None,
                provenance=_provenance(sha, detail_path + "/t:initialSum"),
            )
        )
        source_fields: dict[str, object] = {}
        if generic:
            letter = _text(
                currency,
                TYPES_NS,
                "letterCode",
                sha,
                detail_path + "/t:currency/t:letterCode",
            )
            maximum = (
                _decimal(detail, "maxContractPrice", sha, detail_path + "/t:maxContractPrice")
                if detail is not None
                else DecimalFact(
                    value=None,
                    raw=None,
                    provenance=_provenance(sha, detail_path + "/t:maxContractPrice"),
                )
            )
            price_text = _text(
                detail, TYPES_NS, "initialSumInfo", sha, detail_path + "/t:initialSumInfo"
            )
            present_price_branches = sum(
                value is not None
                for value in (
                    _optional(detail, TYPES_NS, "initialSum"),
                    _optional(detail, TYPES_NS, "maxContractPrice"),
                    _optional(detail, TYPES_NS, "initialSumInfo"),
                )
            )
            if present_price_branches > 1:
                raise Eis223ContractError("PRICE_BRANCH_CONFLICT")
            if _optional(detail, TYPES_NS, "initialSum") is not None:
                price_kind = "INITIAL_SUM"
                source_amount = amount
                rub_name = "startingContractPriceRub"
            elif _optional(detail, TYPES_NS, "maxContractPrice") is not None:
                price_kind = "MAX_CONTRACT_PRICE"
                source_amount = maximum
                rub_name = "maxContractPriceRub"
            elif _optional(detail, TYPES_NS, "initialSumInfo") is not None:
                price_kind = "TEXT_ONLY"
                source_amount = DecimalFact(
                    value=None,
                    raw=None,
                    provenance=_provenance(sha, detail_path + "/t:initialSumInfo"),
                )
                rub_name = "startingContractPriceRub"
            else:
                price_kind = "UNKNOWN"
                source_amount = DecimalFact(
                    value=None,
                    raw=None,
                    provenance=_provenance(sha, detail_path),
                )
                rub_name = "startingContractPriceRub"
            rub_equivalent = (
                _decimal(detail, rub_name, sha, detail_path + "/t:" + rub_name)
                if detail is not None
                else DecimalFact(
                    value=None,
                    raw=None,
                    provenance=_provenance(sha, detail_path + "/t:" + rub_name),
                )
            )
            formula_element = _optional(detail, TYPES_NS, "priceFormula")
            formula = _text(detail, TYPES_NS, "priceFormula", sha, detail_path + "/t:priceFormula")
            commodity_element = _optional(detail, TYPES_NS, "commodityPrice")
            commodity = (
                _decimal(detail, "commodityPrice", sha, detail_path + "/t:commodityPrice")
                if detail is not None
                else DecimalFact(
                    value=None,
                    raw=None,
                    provenance=_provenance(sha, detail_path + "/t:commodityPrice"),
                )
            )
            numeric_by_code = {"RUB": "643", "RUR": "643", "USD": "840", "EUR": "978"}
            if letter.value is not None:
                currency_consistent = code.value is None and numeric.value is None
            elif code.value is not None:
                currency_consistent = (
                    code.value in numeric_by_code and numeric_by_code[code.value] == numeric.value
                )
            else:
                currency_consistent = False
            source_fields = {
                "guid": _text(lot, TYPES_NS, "guid", sha, path + "/t:guid"),
                "detail_status": "PRESENT" if detail is not None else "UNKNOWN",
                "source_price_kind": price_kind,
                "source_amount": source_amount,
                "source_rub_equivalent": rub_equivalent,
                "source_price_text": price_text,
                "source_price_formula": formula,
                "source_price_formula_present": formula_element is not None,
                "source_commodity_price": commodity,
                "source_commodity_price_present": commodity_element is not None,
                "currency_letter_code": letter,
                "source_currency_status": "CONSISTENT" if currency_consistent else "UNKNOWN",
                "for_small_or_middle_raw": _text(
                    detail,
                    TYPES_NS,
                    "forSmallOrMiddle",
                    sha,
                    detail_path + "/t:forSmallOrMiddle",
                ),
            }
        if document_type == TARGETED_DOCUMENT_TYPE:
            source_fields["guid"] = _text(lot, TYPES_NS, "guid", sha, path + "/t:guid")
        items_parent = _optional(detail, TYPES_NS, "lotItems")
        items = []
        for item_index, item in enumerate(
            _children(items_parent, TYPES_NS, "lotItem") if items_parent is not None else [], 1
        ):
            item_path = detail_path + f"/t:lotItems/t:lotItem[{item_index}]"
            classification = _optional(item, TYPES_NS, "okpd2")
            unit = _optional(item, TYPES_NS, "okei")
            items.append(
                Eis223LotItem(
                    description=_text(
                        item, TYPES_NS, "additionalInfo", sha, item_path + "/t:additionalInfo"
                    ),
                    classification_code=_text(
                        classification, TYPES_NS, "code", sha, item_path + "/t:okpd2/t:code"
                    ),
                    classification_name=_text(
                        classification, TYPES_NS, "name", sha, item_path + "/t:okpd2/t:name"
                    ),
                    quantity=_decimal(item, "qty", sha, item_path + "/t:qty"),
                    unit_code=_text(unit, TYPES_NS, "code", sha, item_path + "/t:okei/t:code"),
                    unit_name=_text(unit, TYPES_NS, "name", sha, item_path + "/t:okei/t:name"),
                    provenance=_provenance(sha, item_path),
                )
            )
        rub = code.value in {"RUB", "RUR"} and numeric.value in {None, "643"}
        if generic:
            source_price_kind = cast(str, source_fields["source_price_kind"])
            source_currency_status = cast(str, source_fields["source_currency_status"])
            source_currency_letter = cast(TextFact, source_fields["currency_letter_code"])
            rub = (
                source_price_kind == "INITIAL_SUM"
                and source_currency_status == "CONSISTENT"
                and source_fields["source_price_formula_present"] is False
                and source_fields["source_commodity_price_present"] is False
                and (source_currency_letter.value or code.value) in {"RUB", "RUR"}
            )
        lots.append(
            Eis223Lot(
                ordinal=_text(lot, TYPES_NS, "ordinalNumber", sha, path + "/t:ordinalNumber"),
                subject=_text(detail, TYPES_NS, "subject", sha, detail_path + "/t:subject"),
                initial_sum=amount,
                currency=code,
                currency_numeric=numeric,
                initial_sum_rub=amount.value if rub else None,
                cancelled_raw=_text(lot, TYPES_NS, "cancelled", sha, path + "/t:cancelled"),
                items=tuple(items),
                provenance=_provenance(sha, path),
                **source_fields,
            )
        )
    parent = _optional(data, PURCHASE_NS, "attachments")
    attachments = []
    for index, item in enumerate(
        _children(parent, TYPES_NS, "document") if parent is not None else [], 1
    ):
        path = base + f"/p:attachments/t:document[{index}]"
        uid = _text(item, TYPES_NS, "contentUid", sha, path + "/t:contentUid")
        url = _text(item, TYPES_NS, "url", sha, path + "/t:url")
        not_placement = _text(item, TYPES_NS, "notPlacement", sha, path + "/t:notPlacement")
        try:
            parts = urlsplit(url.raw or "")
            query = parse_qs(parts.query, keep_blank_values=True)
        except ValueError:
            parts = urlsplit("")
            query = {}
        valid = (
            parts.scheme == "https"
            and parts.netloc == "zakupki.gov.ru"
            and parts.path == "/223/filestore/public/1.0/download/fz223/file.html"
            and not parts.fragment
            and uid.value is not None
            and re.fullmatch(r"[0-9A-F]{32}", uid.value) is not None
            and query == {"uid": [uid.value]}
        )
        if generic and (
            hide_purchase.value not in {None, "false"}
            or hide_accredited.value not in {None, "false"}
            or not_placement.value not in {None, "false"}
        ):
            valid = False
        if not valid:
            url = url.model_copy(update={"value": None})
        attachments.append(
            Eis223Attachment(
                filename=_text(item, TYPES_NS, "fileName", sha, path + "/t:fileName"),
                content_uid=uid,
                url=url,
                **({"not_placement_raw": not_placement} if generic else {}),
            )
        )
    manifest_references: list[Eis223ManifestReference] = []
    if generic:
        for index, item in enumerate(
            _children(parent, TYPES_NS, "documentFS") if parent is not None else [], 1
        ):
            path = base + f"/p:attachments/t:documentFS[{index}]"
            manifest_references.append(
                Eis223ManifestReference(
                    kind="DOCUMENT_FS",
                    guid=_text(item, TYPES_NS, "guid", sha, path + "/t:guid"),
                    content_uid=_text(item, TYPES_NS, "contentUid", sha, path + "/t:contentUid"),
                    provenance=_provenance(sha, path),
                )
            )
        for index, item in enumerate(
            _children(parent, TYPES_NS, "prevDocument") if parent is not None else [], 1
        ):
            path = base + f"/p:attachments/t:prevDocument[{index}]"
            manifest_references.append(
                Eis223ManifestReference(
                    kind="PREVIOUS_DOCUMENT",
                    guid=_text(item, TYPES_NS, "guid", sha, path + "/t:guid"),
                    content_uid=TextFact(
                        value=None,
                        raw=None,
                        provenance=_provenance(sha, path + "/t:contentUid"),
                    ),
                    provenance=_provenance(sha, path),
                )
            )
    count = _text(
        parent, TYPES_NS, "totalDocumentsCount", sha, base + "/p:attachments/t:totalDocumentsCount"
    )
    additional_count = _text(
        parent,
        TYPES_NS,
        "additionalDocumentsCount",
        sha,
        base + "/p:attachments/t:additionalDocumentsCount",
    )
    if (
        len(lots) > 100
        or sum(len(lot.items) for lot in lots) > MAX_NOTICE_ITEMS
        or len(attachments) + len(manifest_references) > 200
    ):
        raise Eis223ContractError("NOTICE_COLLECTION_LIMIT")
    customer = _optional(data, PURCHASE_NS, "customer")
    main = _optional(customer, TYPES_NS, "mainInfo")
    zone = _optional(main, TYPES_NS, "timeZone")
    deadline = _time(data, "submissionCloseDateTime", sha, base)
    generic_fields: dict[str, object] = {}
    if generic:
        selected_deadline = deadline
        if lot_oriented.value != "false":
            selected_deadline = deadline.model_copy(update={"value": None, "status": "UNKNOWN"})
        generic_fields = {
            "purchase_guid": _text(data, PURCHASE_NS, "guid", sha, base + "/p:guid"),
            "hide_purchase_raw": hide_purchase,
            "hide_purchase_customer_accredited_raw": hide_accredited,
            "for_small_or_middle_raw": _text(
                data,
                PURCHASE_NS,
                "forSmallOrMiddle",
                sha,
                base + "/p:forSmallOrMiddle",
            ),
            "is_lot_oriented_raw": lot_oriented,
            "selected_deadline": selected_deadline,
            "manifest_additional_count": additional_count,
            "manifest_references": tuple(manifest_references),
        }
    if document_type == TARGETED_DOCUMENT_TYPE:
        generic_fields = {
            "purchase_guid": _text(data, PURCHASE_NS, "guid", sha, base + "/p:guid"),
            "for_small_or_middle_raw": _text(
                data, PURCHASE_NS, "forSmallOrMiddle", sha, base + "/p:forSmallOrMiddle"
            ),
        }
    return Eis223NoticeSnapshot(
        document_type=document_type,
        purchase_number=number,
        version_number=int(version),
        identity_provenance=(
            _provenance(sha, base + "/p:registrationNumber"),
            _provenance(sha, base + "/p:version"),
        ),
        title=_text(data, PURCHASE_NS, "name", sha, base + "/p:name"),
        method_code=_text(
            data, PURCHASE_NS, "purchaseMethodCode", sha, base + "/p:purchaseMethodCode"
        ),
        method_name=_text(data, PURCHASE_NS, "purchaseCodeName", sha, base + "/p:purchaseCodeName"),
        publication=_time(data, "publicationDateTime", sha, base),
        deadline=deadline,
        customer_timezone_offset_raw=_text(
            zone, TYPES_NS, "offset", sha, base + "/p:customer/t:mainInfo/t:timeZone/t:offset"
        ),
        status_raw=_text(data, PURCHASE_NS, "status", sha, base + "/p:status"),
        xml_sha256=sha,
        source_member=source_member,
        lots=tuple(lots),
        attachments=tuple(attachments),
        manifest_count=count,
        manifest_status=(
            "COUNT_CONSISTENT"
            if count.value == str(len(attachments))
            and not manifest_references
            and additional_count.value is None
            and all(
                item.not_placement_raw is None or item.not_placement_raw.value is None
                for item in attachments
            )
            else "UNKNOWN"
        ),
        **generic_fields,
    )


def inspect_notice223_archive(
    raw: bytes,
    *,
    company_id: str,
    source_response_sha256: str,
    source_locator: str,
    document_type: str = DOCUMENT_TYPE,
) -> Eis223ArchiveInspection:
    if not raw or len(raw) > MAX_ARCHIVE_BYTES:
        raise Eis223ContractError("ARCHIVE_BYTES_LIMIT")
    records = []
    try:
        with ZipFile(BytesIO(raw)) as archive:
            members = archive.infolist()
            if (
                not members
                or len(members) > MAX_MEMBERS
                or sum(m.file_size for m in members) > MAX_EXPANDED_BYTES
            ):
                raise Eis223ContractError("ARCHIVE_EXPANSION_LIMIT")
            seen = set()
            for member in members:
                name = member.orig_filename
                if (
                    name != member.filename
                    or name in seen
                    or not re.fullmatch(r"[^/\\:\x00]+\.xml", name)
                    or name in {".xml", "..xml"}
                    or member.flag_bits & 1
                    or member.compress_type not in {0, 8}
                    or (member.external_attr >> 16) & 0o170000 == 0o120000
                ):
                    raise Eis223ContractError("ARCHIVE_MEMBER_REJECTED")
                seen.add(name)
                if member.file_size > MAX_NOTICE_XML_BYTES:
                    raise Eis223ContractError("XML_BYTES_LIMIT")
                with archive.open(member) as stream:
                    content = stream.read(MAX_NOTICE_XML_BYTES + 1)
                if len(content) != member.file_size:
                    raise Eis223ContractError("XML_BYTES_INVALID")
                records.append(
                    parse_notice223_xml(content, source_member=name, document_type=document_type)
                )
    except (BadZipFile, RuntimeError, NotImplementedError) as error:
        raise Eis223ContractError("ARCHIVE_INVALID") from error
    identities = set()
    for record in records:
        identity = (record.purchase_number, record.version_number)
        if identity in identities:
            raise Eis223ContractError("NOTICE_VERSION_DUPLICATE")
        identities.add(identity)
    return Eis223ArchiveInspection(
        company_id=company_id,
        archive_sha256=hashlib.sha256(raw).hexdigest(),
        source_response_sha256=source_response_sha256,
        source_locator=source_locator,
        records=tuple(records),
    )
