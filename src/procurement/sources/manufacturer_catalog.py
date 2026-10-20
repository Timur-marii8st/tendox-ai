"""Read-only discovery in an allowlist of official manufacturer catalog pages."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from io import BytesIO

import httpx
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from procurement.domain.sourcing import LeadSourceKind, ServerLead
from procurement.sources.http_transport import public_source_client

_MAX_HTML_BYTES = 2 * 1024 * 1024
_MAX_PDF_BYTES = 20 * 1024 * 1024
_MAX_PDF_PAGES = 200
_SPACE = re.compile(r"\s+")


class ManufacturerCatalogSourceError(ValueError):
    """An official source could not provide a validated exact snapshot."""


@dataclass(frozen=True)
class ManufacturerCatalogDefinition:
    manufacturer: str
    product_name: str
    source_url: str
    required_query_terms: tuple[str, ...]
    expected_title: str
    media_type: str = "text/html"
    max_bytes: int = _MAX_HTML_BYTES


@dataclass(frozen=True)
class ManufacturerCatalogObservation:
    source_name: str
    source_url: str
    content: bytes
    sha256: str
    observed_at: datetime
    media_type: str
    leads: tuple[ServerLead, ...]


OFFICIAL_SERVER_CATALOGS = (
    ManufacturerCatalogDefinition(
        manufacturer="HPE",
        product_name="HPE ProLiant Compute DL360 Gen12",
        source_url="https://www.hpe.com/psnow/doc/a50006984enw",
        required_query_terms=("dl360", "gen12"),
        expected_title="hpe proliant compute dl360 gen12 quickspecs",
    ),
    ManufacturerCatalogDefinition(
        manufacturer="Lenovo",
        product_name="Lenovo ThinkSystem SR630 V3",
        source_url="https://lenovopress.lenovo.com/lp1600-thinksystem-sr630-v3-server",
        required_query_terms=("sr630", "v3"),
        expected_title="lenovo thinksystem sr630 v3 server",
    ),
    ManufacturerCatalogDefinition(
        manufacturer="Dell",
        product_name="Dell PowerEdge R660",
        source_url=(
            "https://i.dell.com/sites/csdocuments/Product_Docs/en/"
            "poweredge-r660-technical-guide.pdf"
        ),
        required_query_terms=("r660",),
        expected_title="poweredge r660",
        media_type="application/pdf",
        max_bytes=_MAX_PDF_BYTES,
    ),
)


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style", "noscript"}:
            self._ignored += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._ignored:
            self._ignored -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored:
            self.parts.append(data)


def _query_terms(query: str) -> tuple[str, ...]:
    normalized = _SPACE.sub(" ", query.strip().casefold())
    terms = tuple(normalized.split())
    if not 1 <= len(terms) <= 5 or len(normalized) > 80:
        raise ManufacturerCatalogSourceError("query must contain 1 to 5 words")
    return terms


def match_official_server_catalog(query: str) -> ManufacturerCatalogDefinition | None:
    """Resolve only a distinctive, allowlisted product-family identity."""
    terms = set(_query_terms(query))
    matches = [
        item for item in OFFICIAL_SERVER_CATALOGS if set(item.required_query_terms).issubset(terms)
    ]
    if len(matches) > 1:
        raise ManufacturerCatalogSourceError("query matches more than one official catalog")
    return matches[0] if matches else None


def parse_official_manufacturer_catalog(
    definition: ManufacturerCatalogDefinition,
    content: bytes,
    *,
    observed_at: datetime,
) -> ManufacturerCatalogObservation:
    """Validate identity and create a non-quote lead from exact official content."""
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ManufacturerCatalogSourceError("observed_at must be timezone-aware")
    if not content or len(content) > definition.max_bytes:
        raise ManufacturerCatalogSourceError("official content is empty or exceeds the limit")
    if definition.media_type == "text/html":
        parser = _VisibleText()
        try:
            parser.feed(content.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise ManufacturerCatalogSourceError("official HTML is not valid UTF-8") from error
        visible = _SPACE.sub(" ", " ".join(parser.parts).casefold()).strip()
    elif definition.media_type == "application/pdf":
        try:
            reader = PdfReader(BytesIO(content), strict=True)
            if not 1 <= len(reader.pages) <= _MAX_PDF_PAGES:
                raise ManufacturerCatalogSourceError("official PDF page count is invalid")
            title = "" if reader.metadata is None else reader.metadata.title or ""
            first_pages = " ".join(
                page.extract_text() or "" for page in reader.pages[: min(8, len(reader.pages))]
            )
        except (PdfReadError, ValueError, TypeError) as error:
            raise ManufacturerCatalogSourceError("official PDF is invalid") from error
        visible = _SPACE.sub(" ", f"{title} {first_pages}".casefold()).strip()
    else:  # pragma: no cover - definitions are code-owned
        raise ManufacturerCatalogSourceError("unsupported official media type")
    if definition.expected_title not in visible:
        raise ManufacturerCatalogSourceError("official page identity did not match")
    digest = hashlib.sha256(content).hexdigest()
    source_name = f"{definition.manufacturer} official catalog"
    return ManufacturerCatalogObservation(
        source_name=source_name,
        source_url=definition.source_url,
        content=content,
        sha256=digest,
        observed_at=observed_at,
        media_type=definition.media_type,
        leads=(
            ServerLead(
                lead_id=definition.source_url,
                supplier=definition.manufacturer,
                manufacturer=definition.manufacturer,
                source_kind=LeadSourceKind.MANUFACTURER_CATALOG,
                product_name=definition.product_name,
                source_url=definition.source_url,
                product_url=definition.source_url,
                source_sha256=digest,
                observed_at=observed_at,
            ),
        ),
    )


def fetch_official_manufacturer_catalog(
    query: str,
) -> ManufacturerCatalogObservation | None:
    """Fetch one exact official page when the query names a supported family."""
    definition = match_official_server_catalog(query)
    if definition is None:
        return None
    try:
        with (
            public_source_client() as client,
            client.stream("GET", definition.source_url) as response,
        ):
            if response.status_code != 200 or definition.media_type not in response.headers.get(
                "content-type", ""
            ):
                raise ManufacturerCatalogSourceError(
                    "official catalog did not return the expected content"
                )
            parts: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > definition.max_bytes:
                    raise ManufacturerCatalogSourceError("official content exceeds the limit")
                parts.append(chunk)
    except httpx.HTTPError as error:
        raise ManufacturerCatalogSourceError("official catalog is unavailable") from error
    return parse_official_manufacturer_catalog(
        definition,
        b"".join(parts),
        observed_at=datetime.now(UTC),
    )
