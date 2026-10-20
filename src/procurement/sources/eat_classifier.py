"""Bounded read-only probe of the public EAT category classifier.

This feed lists categories, not procurement sessions, suppliers or offers.
The source URL is fixed so a caller cannot turn the probe into an arbitrary fetch.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from io import BytesIO
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

import httpx
from pydantic import BaseModel, ConfigDict, Field

from procurement.sources.http_transport import public_source_client

EAT_CATEGORY_SET_URL = "https://agregatoreat.ru/integration/ecom/classifier/eatCategorySet.zip"
_ROOT_TAG = "{http://agregatoreat.ru/eat/object-types/}eatCategorySet"
_CATEGORY_TAG = "{http://agregatoreat.ru/eat/}category"
_FIELD_NS = "{http://agregatoreat.ru/eat/}"
_MEMBER_NAME = "eatCategorySet.xml"
_MAX_ARCHIVE_BYTES = 2 * 1024 * 1024
_MAX_XML_BYTES = 12 * 1024 * 1024
_MAX_CATEGORIES = 20_000


class FeedStatus(StrEnum):
    """The probe describes access to one exact feed, not source coverage."""

    PASS = "PASS"
    UNKNOWN = "UNKNOWN"


class EatClassifierError(ValueError):
    """The published archive cannot be used as a valid classifier snapshot."""


class EatCategory(BaseModel):
    """A category from the exact XML snapshot."""

    model_config = ConfigDict(frozen=True)

    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=200)
    parent_code: str | None = Field(default=None, max_length=30)
    deleted: bool


class EatClassifierSnapshot(BaseModel):
    """Immutable in-memory observation of the public category feed."""

    model_config = ConfigDict(frozen=True)

    source_url: str
    source_sha256: str
    fetched_at: datetime
    categories: tuple[EatCategory, ...]

    @property
    def active_count(self) -> int:
        """Count non-deleted entries without treating them as verified offers."""
        return sum(not category.deleted for category in self.categories)


def parse_eat_classifier_archive(archive: bytes, *, fetched_at: datetime) -> EatClassifierSnapshot:
    """Parse one bounded EAT classifier ZIP and retain exact-byte provenance."""
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise EatClassifierError("fetched_at must have a timezone")
    if not archive or len(archive) > _MAX_ARCHIVE_BYTES:
        raise EatClassifierError("archive size is outside the allowed range")
    try:
        with ZipFile(BytesIO(archive)) as zipped:
            members = zipped.infolist()
            if (
                len(members) != 1
                or members[0].filename != _MEMBER_NAME
                or members[0].is_dir()
                or members[0].flag_bits & 1
                or members[0].file_size > _MAX_XML_BYTES
            ):
                raise EatClassifierError("archive has an unsupported member layout")
            with zipped.open(members[0]) as member:
                xml = member.read(_MAX_XML_BYTES + 1)
            if len(xml) > _MAX_XML_BYTES or len(xml) != members[0].file_size:
                raise EatClassifierError("classifier XML exceeds its declared size")
    except (BadZipFile, OSError, RuntimeError) as error:
        raise EatClassifierError("invalid classifier archive") from error
    if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
        raise EatClassifierError("XML declarations with entities are unsupported")
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as error:
        raise EatClassifierError("invalid classifier XML") from error
    if root.tag != _ROOT_TAG or len(root) > _MAX_CATEGORIES:
        raise EatClassifierError("unexpected classifier root or category count")

    categories: list[EatCategory] = []
    codes: set[str] = set()
    for element in root:
        if element.tag != _CATEGORY_TAG:
            raise EatClassifierError("unexpected classifier entry")
        code = (element.findtext(f"{_FIELD_NS}code") or "").strip()
        name = (element.findtext(f"{_FIELD_NS}shortName") or "").strip()
        parent = (element.findtext(f"{_FIELD_NS}parentCode") or "").strip() or None
        deleted_text = element.findtext(f"{_FIELD_NS}deleted")
        if not code or code in codes or deleted_text not in (None, "true", "false"):
            raise EatClassifierError("duplicate or invalid classifier entry")
        try:
            categories.append(
                EatCategory(
                    code=code,
                    name=name,
                    parent_code=parent,
                    deleted=deleted_text == "true",
                )
            )
        except ValueError as error:
            raise EatClassifierError("invalid classifier category") from error
        codes.add(code)
    if not categories or any(
        category.parent_code is not None and category.parent_code not in codes
        for category in categories
    ):
        raise EatClassifierError("empty classifier or missing parent category")
    return EatClassifierSnapshot(
        source_url=EAT_CATEGORY_SET_URL,
        source_sha256=hashlib.sha256(archive).hexdigest(),
        fetched_at=fetched_at,
        categories=tuple(categories),
    )


def fetch_eat_classifier() -> EatClassifierSnapshot:
    """Fetch the fixed public ZIP once, with no redirects, proxy or credentials."""
    try:
        with (
            public_source_client() as client,
            client.stream("GET", EAT_CATEGORY_SET_URL) as response,
        ):
            if response.status_code != 200:
                raise EatClassifierError("classifier feed did not return HTTP 200")
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > _MAX_ARCHIVE_BYTES:
                    raise EatClassifierError("classifier download exceeds size limit")
                chunks.append(chunk)
    except httpx.HTTPError as error:
        raise EatClassifierError("classifier feed is unavailable") from error
    return parse_eat_classifier_archive(b"".join(chunks), fetched_at=datetime.now(UTC))


def main() -> int:
    """Print only aggregate evidence; a failed probe remains UNKNOWN."""
    try:
        snapshot = fetch_eat_classifier()
    except EatClassifierError as error:
        print(json.dumps({"status": FeedStatus.UNKNOWN, "reason": str(error)}))
        return 3
    print(
        json.dumps(
            {
                "status": FeedStatus.PASS,
                "source_url": snapshot.source_url,
                "source_sha256": snapshot.source_sha256,
                "fetched_at": snapshot.fetched_at.isoformat(),
                "categories_total": len(snapshot.categories),
                "categories_active": snapshot.active_count,
                "categories_deleted": len(snapshot.categories) - snapshot.active_count,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
