"""Syntactic source region validation; membership requires official catalog evidence."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from html.parser import HTMLParser
from io import BytesIO
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from pydantic import BaseModel, ConfigDict, Field, field_validator

from procurement.sources.eis_feed_sync import EisSyncError

REGION_SELECTOR_URL = "https://zakupki.gov.ru/epz/nsi/kladr/chooseRegion.html"


class _RegionSelector(HTMLParser):
    """Only the observed official top-level KLADR selector entries are evidence."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.regions: dict[str, str] = {}
        self.current: str | None = None
        self.parts: list[str] = []
        self.div_depth = 0
        self.modal_depth: int | None = None
        self.select_depth: int | None = None
        self.list_open = False
        self.li_open = False
        self.modal_seen = self.select_seen = self.list_seen = False
        self.modal_closed = self.select_closed = self.list_closed = False
        self.placeholder_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if self.li_open:
            raise EisSyncError("REGION_CATALOG_SHAPE_INVALID")
        if self.list_open and tag != "li":
            raise EisSyncError("REGION_CATALOG_SHAPE_INVALID")
        if (
            self.list_open
            and tag == "li"
            and not {"select-vars__item", "select-text"} <= set((values.get("class") or "").split())
        ):
            raise EisSyncError("REGION_CATALOG_SHAPE_INVALID")
        if tag == "div":
            self.div_depth += 1
            if values.get("id") == "modal-region":
                if self.modal_seen:
                    raise EisSyncError("REGION_CATALOG_SHAPE_INVALID")
                self.modal_seen = True
                self.modal_depth = self.div_depth
            if values.get("id") == "region-select":
                if self.select_seen or self.modal_depth is None or self.modal_closed:
                    raise EisSyncError("REGION_CATALOG_SHAPE_INVALID")
                self.select_seen = True
                self.select_depth = self.div_depth
        if tag == "ul" and {"select-vars", "select-overflow"} <= set(
            (values.get("class") or "").split()
        ):
            if self.list_seen or self.select_depth is None or self.select_closed:
                raise EisSyncError("REGION_CATALOG_SHAPE_INVALID")
            self.list_seen = self.list_open = True
        if tag == "li" and {"select-vars__item", "select-text"} <= set(
            (values.get("class") or "").split()
        ):
            if not self.list_open:
                raise EisSyncError("REGION_CATALOG_SHAPE_INVALID")
            self.li_open = True
            self.parts = []
            if len(attrs) != len(values):
                raise EisSyncError("REGION_CATALOG_IDENTITY_INVALID")
            identity = values.get("id")
            if identity is None:
                return
            if len(attrs) != len(values) or not re.fullmatch(
                r"(?:0[1-9]|[1-9][0-9])0{9}", identity
            ):
                raise EisSyncError("REGION_CATALOG_IDENTITY_INVALID")
            self.current = identity[:2]
            self.parts = []

    def handle_data(self, data: str) -> None:
        if self.li_open:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.list_open and tag not in {"li", "ul"}:
            raise EisSyncError("REGION_CATALOG_SHAPE_INVALID")
        if tag == "ul" and self.list_open:
            if self.li_open:
                raise EisSyncError("REGION_CATALOG_SHAPE_INVALID")
            self.list_open = False
            self.list_closed = True
        if tag == "div":
            if self.div_depth == self.select_depth:
                if not self.list_closed:
                    raise EisSyncError("REGION_CATALOG_SHAPE_INVALID")
                self.select_closed = True
            if self.div_depth == self.modal_depth:
                if not self.select_closed:
                    raise EisSyncError("REGION_CATALOG_SHAPE_INVALID")
                self.modal_closed = True
            self.div_depth -= 1
        if tag == "li" and self.li_open and self.current is None:
            if " ".join("".join(self.parts).split()) != "Не выбран" or self.placeholder_count:
                raise EisSyncError("REGION_CATALOG_IDENTITY_INVALID")
            self.placeholder_count += 1
        if tag == "li" and self.current is not None:
            name = " ".join("".join(self.parts).split())
            if not name or len(name) > 300 or self.current in self.regions:
                raise EisSyncError("REGION_CATALOG_IDENTITY_INVALID")
            self.regions[self.current] = name
            self.current = None
        if tag == "li":
            self.li_open = False


def _selector_regions(content: bytes) -> dict[str, str]:
    if not 0 < len(content) <= 512 * 1024:
        raise EisSyncError("REGION_CATALOG_BYTES_LIMIT")
    try:
        html = content.decode("utf-8", errors="strict")
        parser = _RegionSelector()
        parser.feed(html)
        parser.close()
    except UnicodeError as error:
        raise EisSyncError("REGION_CATALOG_INVALID") from error
    if (
        parser.current is not None
        or not parser.modal_closed
        or not parser.select_closed
        or not parser.list_closed
        or parser.placeholder_count != 1
        or not 1 <= len(parser.regions) <= 99
    ):
        raise EisSyncError("REGION_CATALOG_SHAPE_INVALID")
    return parser.regions


def validate_region_code(region: str) -> str:
    """Conservative ASCII KLADR code shape, never an assertion of active membership."""
    if not isinstance(region, str) or not re.fullmatch(
        r"(?:0[1-9]|[1-9][0-9])", region, flags=re.ASCII
    ):
        raise EisSyncError("REGION_INVALID")
    return region


class RegionCatalog(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_url: str
    response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_at: datetime
    regions: dict[str, str]

    @field_validator("observed_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("CATALOG_TIMEZONE_MISSING")
        return value


def inspect_region_catalog(
    content: bytes, *, source_url: str, response_sha256: str, observed_at: datetime
) -> RegionCatalog:
    """Full small official nsiSubjectRF export; require explicit two-digit KLADR mapping.

    Subject identifiers never become region identifiers by truncation or padding.
    This parser does not assert current availability of this catalog via getNsi.
    """
    if source_url == REGION_SELECTOR_URL:
        digest = hashlib.sha256(content).hexdigest()
        if response_sha256 != digest:
            raise EisSyncError("REGION_CATALOG_RESPONSE_MISMATCH")
        return RegionCatalog(
            catalog_sha256=digest,
            source_url=source_url,
            response_sha256=response_sha256,
            observed_at=observed_at,
            regions=_selector_regions(content),
        )

    from procurement.sources.eis_feed import validate_eis_archive_url

    validate_eis_archive_url(source_url)
    if not 0 < len(content) <= 8 * 1024**2:
        raise EisSyncError("REGION_CATALOG_BYTES_LIMIT")
    export = "{http://zakupki.gov.ru/oos/export/1}"
    types = "{http://zakupki.gov.ru/oos/types/1}"
    regions: dict[str, str] = {}
    try:
        with ZipFile(BytesIO(content)) as archive:
            members = archive.infolist()
            if not 1 <= len(members) <= 20 or sum(m.file_size for m in members) > 16 * 1024**2:
                raise EisSyncError("REGION_CATALOG_EXPANSION_LIMIT")
            names: set[str] = set()
            count = 0
            for member in members:
                path = PurePosixPath(member.filename)
                if (
                    member.is_dir()
                    or path.is_absolute()
                    or ".." in path.parts
                    or "\\" in member.filename
                    or member.filename in names
                    or not member.filename.endswith(".xml")
                    or member.flag_bits & 1
                ):
                    raise EisSyncError("REGION_CATALOG_MEMBER_INVALID")
                names.add(member.filename)
                xml = archive.read(member)
                if b"\x00" in xml or b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
                    raise EisSyncError("REGION_CATALOG_XML_INVALID")
                root = ET.fromstring(xml)
                if (
                    root.tag != export + "export"
                    or len(root) != 1
                    or root[0].tag != export + "nsiSubjectRFList"
                ):
                    raise EisSyncError("REGION_CATALOG_SHAPE_INVALID")
                for entry in root[0]:
                    count += 1
                    if entry.tag != export + "nsiSubjectRF" or count > 2000:
                        raise EisSyncError("REGION_CATALOG_SHAPE_INVALID")
                    tags = [child.tag for child in entry]
                    if len(tags) != len(set(tags)):
                        raise EisSyncError("REGION_CATALOG_FIELD_DUPLICATE")
                    actual = entry.findtext(types + "isActual")
                    if actual not in {"true", "1", "false", "0"}:
                        raise EisSyncError("REGION_CATALOG_ACTUAL_UNKNOWN")
                    if actual in {"false", "0"}:
                        continue
                    code = validate_region_code(entry.findtext(types + "kladrCode", ""))
                    name = entry.findtext(types + "fullName", "").strip()
                    if not name or len(name) > 300 or code in regions:
                        raise EisSyncError("REGION_CATALOG_IDENTITY_INVALID")
                    regions[code] = name
        if not 1 <= len(regions) <= 99:
            raise EisSyncError("REGION_CATALOG_EMPTY")
    except (BadZipFile, ET.ParseError, RuntimeError, OSError) as error:
        raise EisSyncError("REGION_CATALOG_INVALID") from error
    return RegionCatalog(
        catalog_sha256=hashlib.sha256(content).hexdigest(),
        source_url=source_url,
        response_sha256=response_sha256,
        observed_at=observed_at,
        regions=regions,
    )
