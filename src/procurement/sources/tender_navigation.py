"""Source-bound delivery and navigation from exact saved XML, without HTTP."""

from __future__ import annotations

import hashlib
import ipaddress
import re
import xml.etree.ElementTree as ET
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field

from procurement.domain.provenance import Extractor, Provenance
from procurement.sources.eis_223_regions import RegionCatalog


class NavigationFact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    value: str = Field(min_length=1, max_length=2048)
    provenance: Provenance
    supporting_sources: tuple[Provenance, ...] = ()


class TenderNavigation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    law: Literal["44", "223"]
    purchase_number: str
    version_number: int
    xml_sha256: str
    delivery_regions: tuple[NavigationFact, ...] = ()
    delivery_addresses: tuple[NavigationFact, ...] = ()
    delivery_coverage: Literal["UNKNOWN"] = "UNKNOWN"
    eis_url: NavigationFact | None = None
    platform_url: NavigationFact | None = None
    platform_name: NavigationFact | None = None


def public_url(value: str, *, eis_number: str | None = None, allow_http: bool = False) -> bool:
    """Admit public HTTPS navigation only; never fetch these addresses."""
    if len(value) > 2048 or re.search(r"[\s\x00-\x1f\\]", value):
        return False
    try:
        url = urlsplit(value)
        host = (url.hostname or "").lower()
        if (
            url.scheme not in ({"https", "http"} if allow_http else {"https"})
            or url.username
            or url.password
            or url.port not in (None, 443 if url.scheme == "https" else 80)
        ):
            return False
        if not host or "." not in host or host.endswith((".local", ".localhost", ".internal")):
            return False
        try:
            ipaddress.ip_address(host)
            return False
        except ValueError:
            pass
        if eis_number is not None:
            return (
                host == "zakupki.gov.ru"
                and url.path == "/223/purchase/public/purchase/info/common-info.html"
                and parse_qs(url.query).get("regNumber") == [eis_number]
            )
        return True
    except ValueError:
        return False


def extract_navigation(
    raw: bytes, *, law: Literal["44", "223"], number: str, version: int, xml_sha256: str
) -> TenderNavigation:
    """Extract exact supported paths; missing/ambiguous fields stay unknown."""
    if (
        not raw
        or len(raw) > (5 if law == "223" else 32) * 1024**2
        or b"\0" in raw
        or b"<!DOCTYPE" in raw.upper()
        or b"<!ENTITY" in raw.upper()
        or hashlib.sha256(raw).hexdigest() != xml_sha256
    ):
        raise ValueError("NAVIGATION_XML_INVALID")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as error:
        raise ValueError("NAVIGATION_XML_INVALID") from error
    ns44 = "http://zakupki.gov.ru/oos/export/1"
    nsp = "http://zakupki.gov.ru/223fz/purchase/1"
    nst = "http://zakupki.gov.ru/223fz/types/1"
    if law == "223":
        kind = root.tag.removeprefix(f"{{{nsp}}}")
        if kind not in {"purchaseNotice", "purchaseNoticeAESMBO", "purchaseNoticeZKESMBO"}:
            raise ValueError("NAVIGATION_NOTICE_TYPE")
        prefix = f"{{{nsp}}}body/{{{nsp}}}item/{{{nsp}}}{kind}Data"
        nodes = root.findall(prefix)
        if len(nodes) != 1:
            raise ValueError("NAVIGATION_NOTICE_IDENTITY")
        data = nodes[0]
        path = f"{kind}/body/item/{kind}Data"
        identity = (f"{{{nsp}}}registrationNumber", f"{{{nsp}}}version")
    else:
        supported = {
            f"{{{ns44}}}{kind}"
            for kind in ("epNotificationEF2020", "epNotificationEZK2020", "epNotificationEOK2020")
        }
        nodes = [child for child in root if child.tag in supported]
        if root.tag != f"{{{ns44}}}export" or len(nodes) != 1:
            raise ValueError("NAVIGATION_NOTICE_TYPE")
        data = nodes[0]
        path = data.tag.split("}")[-1]
        # Official EP exports use EPtypes for notice fields, base for ETP leaves,
        # and common for GAR. Keep the previous export-only profile explicit;
        # never strip arbitrary namespaces or combine two identity profiles.
        common_nodes = [child for child in data if child.tag.split("}")[-1] == "commonInfo"]
        versions = [child for child in data if child.tag.split("}")[-1] == "versionNumber"]
        ep = "http://zakupki.gov.ru/oos/EPtypes/1"
        if len(common_nodes) != 1 or len(versions) != 1:
            raise ValueError("NAVIGATION_NOTICE_IDENTITY")
        if common_nodes[0].tag == f"{{{ep}}}commonInfo":
            fields44, base44, common44 = (
                ep,
                "http://zakupki.gov.ru/oos/base/1",
                "http://zakupki.gov.ru/oos/common/1",
            )
        elif common_nodes[0].tag == f"{{{ns44}}}commonInfo":
            fields44 = base44 = common44 = ns44
        else:
            raise ValueError("NAVIGATION_NOTICE_IDENTITY")
        numbers = [
            child for child in common_nodes[0] if child.tag.split("}")[-1] == "purchaseNumber"
        ]
        if (
            versions[0].tag != f"{{{fields44}}}versionNumber"
            or len(numbers) != 1
            or numbers[0].tag != f"{{{fields44}}}purchaseNumber"
        ):
            raise ValueError("NAVIGATION_NOTICE_IDENTITY")
        identity = (
            f"{{{fields44}}}commonInfo/{{{fields44}}}purchaseNumber",
            f"{{{fields44}}}versionNumber",
        )

    def one(parent: ET.Element, query: str) -> str | None:
        matches = parent.findall(query)
        if len(matches) != 1 or len(matches[0]):
            return None
        value = (matches[0].text or "").strip()
        return value if value and len(value) <= 2048 else None

    if (one(data, identity[0]), one(data, identity[1])) != (number, str(version)):
        raise ValueError("NAVIGATION_NOTICE_IDENTITY")

    def fact(value: str | None, locator: str) -> NavigationFact | None:
        return (
            NavigationFact(
                value=value,
                provenance=Provenance(
                    document_id=xml_sha256, locator=path + "/" + locator, extractor=Extractor.API
                ),
            )
            if value
            else None
        )

    regions: list[NavigationFact] = []
    addresses: list[NavigationFact] = []
    eis = platform = name = None
    if law == "223":
        lots = data.findall(f"{{{nsp}}}lots/{{{nst}}}lot")
        for index, lot in enumerate(lots, 1):
            query = f"{{{nst}}}lotData/{{{nst}}}deliveryPlace/{{{nst}}}region"
            item = fact(one(lot, query), f"lots/lot[{index}]/lotData/deliveryPlace/region")
            if item:
                regions.append(item)
        hidden = any(
            data.findall(f"{{{nsp}}}{flag}") and one(data, f"{{{nsp}}}{flag}") not in {"false", "0"}
            for flag in ("hidePurchase", "hidePurchaseCustomerAccredited")
        )
        if not hidden:
            value = one(data, f"{{{nsp}}}urlEIS")
            if value and public_url(value, eis_number=number):
                eis = fact(value, "urlEIS")
            value = one(data, f"{{{nsp}}}urlVSRZ")
            if value and public_url(value, allow_http=True):
                platform = fact(value, "urlVSRZ")
            name = fact(
                one(data, f"{{{nsp}}}electronicPlaceInfo/{{{nst}}}name"), "electronicPlaceInfo/name"
            )
    else:
        platform_value = one(data, f"{{{fields44}}}commonInfo/{{{fields44}}}ETP/{{{base44}}}url")
        if platform_value and public_url(platform_value, allow_http=True):
            platform = fact(platform_value, "commonInfo/ETP/url")
        name = fact(
            one(data, f"{{{fields44}}}commonInfo/{{{fields44}}}ETP/{{{base44}}}name"),
            "commonInfo/ETP/name",
        )
        address_query = (
            f"{{{fields44}}}notificationInfo/{{{fields44}}}customerRequirementsInfo/"
            f"{{{fields44}}}customerRequirementInfo/{{{fields44}}}contractConditionsInfo/"
            f"{{{fields44}}}deliveryPlacesInfo/{{{fields44}}}byGARInfo"
        )
        for index, block in enumerate(data.findall(address_query), 1):
            gar = one(block, f"{{{common44}}}GARInfo/{{{common44}}}GARAddress")
            address = fact(
                gar,
                "notificationInfo/customerRequirementsInfo/"
                f"customerRequirementInfo/contractConditionsInfo/deliveryPlacesInfo/"
                f"byGARInfo[{index}]/GARInfo/GARAddress",
            )
            if address:
                addresses.append(address)
        # Only structured delivery region names, never customer or publication region.
        query = (
            f"{{{fields44}}}notificationInfo/{{{fields44}}}contractConditionsInfo/"
            f"{{{fields44}}}deliveryPlaceInfo/{{{fields44}}}deliveryPlace/"
            f"{{{fields44}}}region/{{{fields44}}}name"
        )
        for index, element in enumerate(data.findall(query), 1):
            value = (element.text or "").strip() if not len(element) else None
            item = fact(
                value,
                f"notificationInfo/contractConditionsInfo/deliveryPlaceInfo/deliveryPlace[{index}]/region/name",
            )
            if item:
                regions.append(item)
    return TenderNavigation(
        law=law,
        purchase_number=number,
        version_number=version,
        xml_sha256=xml_sha256,
        delivery_regions=tuple(regions),
        delivery_addresses=tuple(addresses),
        eis_url=eis,
        platform_url=platform,
        platform_name=name,
    )


def bind_gar_regions(navigation: TenderNavigation, catalog: RegionCatalog) -> TenderNavigation:
    """Match the entire first GAR address component to an explicit saved official name.

    Only spelling abbreviations and order are normalized; cities inside a region
    are never used to infer a region. Ambiguous or missing matches stay unknown.
    """

    aliases: dict[tuple[str, ...], list[tuple[str, str]]] = {}
    for code, name in catalog.regions.items():
        aliases.setdefault(region_name_key(name), []).append((code, name))
    regions = list(navigation.delivery_regions)
    for address in navigation.delivery_addresses:
        first = address.value.split(",", 1)[0]
        matches = aliases.get(region_name_key(first), [])
        if len(matches) != 1:
            continue
        code, name = matches[0]
        regions.append(
            NavigationFact(
                value=name,
                provenance=address.provenance,
                supporting_sources=(
                    Provenance(
                        document_id=catalog.catalog_sha256,
                        locator=(
                            f"{catalog.source_url} region[{code}] "
                            f"observed {catalog.observed_at.isoformat()}"
                        ),
                        extractor=Extractor.API,
                    ),
                ),
            )
        )
    return navigation.model_copy(update={"delivery_regions": tuple(regions)})


def region_name_key(value: str) -> tuple[str, ...]:
    """Canonical spelling of a full name, without inferring territorial hierarchy."""
    replacements = {"г": "город", "обл": "область", "респ": "республика"}
    tokens = [
        replacements.get(token, token) for token in re.findall(r"[а-яёa-z0-9]+", value.casefold())
    ]
    return tuple(sorted(token for token in tokens if token != "город"))
