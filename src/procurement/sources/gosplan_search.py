"""Read bounded Gosplan search data without promoting provider hints to EIS facts."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal
from urllib.parse import parse_qs, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict

from procurement.sources.gosplan_discovery import MAX_OFFSET

Law = Literal["44", "223"]
_MAX_BYTES = 2 * 1024 * 1024
_PLATFORM_HOSTS = frozenset(
    {
        "roseltorg.ru",
        "sberbank-ast.ru",
        "rts-tender.ru",
        "etp.gpb.ru",
        "etp-ets.ru",
        "tektorg.ru",
        "zakazrf.ru",
        "astgoz.ru",
    }
)


class GosplanSearchError(ValueError):
    """A bounded safe provider error without credentials or response bytes."""


class SourceModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SearchItem(SourceModel):
    law: Law
    number: str
    title: str
    purchase_type: str
    price: str | None
    currency: str | None
    deadline_raw: str | None
    deadline_status: Literal["UNKNOWN"] = "UNKNOWN"
    submission_status: Literal["UNKNOWN"] = "UNKNOWN"
    source_sha256: str


class SearchPage(SourceModel):
    law: Law
    query: str
    observed_at: datetime
    response_sha256: str
    items: tuple[SearchItem, ...]
    may_have_more: bool
    coverage: Literal["UNKNOWN"] = "UNKNOWN"


class DocumentLink(SourceModel):
    name: str
    url: str
    source_sha256: str


class Detail(SourceModel):
    law: Law
    number: str
    observed_at: datetime
    response_sha256: str
    eis_url: str | None
    eis_url_origin: Literal["PROVIDER", "NUMBER_DERIVED"] | None = None
    platform_url: str | None
    documents: tuple[DocumentLink, ...]
    documents_truncated: bool = False
    submission_status: Literal["UNKNOWN"] = "UNKNOWN"


def _request(client: httpx.Client, key: str, url: str, params: dict[str, object]) -> bytes:
    if not key or "\n" in key or "\r" in key or len(key) > 1024:
        raise GosplanSearchError("KEY_INVALID")
    try:
        with client.stream(
            "GET",
            url,
            params=params,
            headers={"apikey": key, "Accept": "application/json"},
            follow_redirects=False,
        ) as response:
            if response.status_code != 200:
                raise GosplanSearchError(f"HTTP_{response.status_code}")
            raw = bytearray()
            for chunk in response.iter_bytes():
                raw.extend(chunk)
                if len(raw) > _MAX_BYTES:
                    raise GosplanSearchError("RESPONSE_SIZE_INVALID")
    except httpx.HTTPError as exc:
        raise GosplanSearchError("TRANSPORT_ERROR") from exc
    if not raw:
        raise GosplanSearchError("RESPONSE_SIZE_INVALID")
    if key.encode() in raw:
        raise GosplanSearchError("TOKEN_REFLECTION_REJECTED")
    return bytes(raw)


def _json(raw: bytes) -> object:
    def reject(_: str) -> None:
        raise ValueError("non-finite")

    try:
        return json.loads(raw, parse_float=Decimal, parse_constant=reject)
    except (ValueError, UnicodeDecodeError) as exc:
        raise GosplanSearchError("RESPONSE_JSON_INVALID") from exc


def _scope(law: Law, now: datetime) -> None:
    if law not in ("44", "223") or now.tzinfo is None or now.utcoffset() is None:
        raise GosplanSearchError("SCOPE_INVALID")


def _number(value: object, law: Law) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{19}" if law == "44" else r"\d{11}", value
    ):
        raise GosplanSearchError("NUMBER_INVALID")
    return value


def _text(value: object, limit: int) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value) > limit
        or any(ord(c) < 32 and c not in "\n\r\t" for c in value)
    ):
        raise GosplanSearchError("FIELD_INVALID")
    return " ".join(value.split()) or None


def _money(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, Decimal, str)):
        raise GosplanSearchError("PRICE_INVALID")
    if len(str(value)) > 100:
        raise GosplanSearchError("PRICE_INVALID")
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise GosplanSearchError("PRICE_INVALID") from exc
    if (
        not number.is_finite()
        or number < 0
        or number.adjusted() > 18
        or number.as_tuple().exponent < -8
    ):
        raise GosplanSearchError("PRICE_INVALID")
    return format(number, "f")


def search_page(
    client: httpx.Client,
    key: str,
    law: Law,
    *,
    query: str,
    offset: int,
    now: datetime,
    limit: int = 20,
) -> SearchPage:
    _scope(law, now)
    if (
        not isinstance(query, str)
        or not query.strip()
        or len(query) > 120
        or not 0 <= offset <= MAX_OFFSET
        or not 1 <= limit <= 20
    ):
        raise GosplanSearchError("SCOPE_INVALID")
    normalized = query.strip()
    exact = bool(re.fullmatch(r"\d{19}" if law == "44" else r"\d{11}", normalized))
    if exact and offset:
        raise GosplanSearchError("SCOPE_INVALID")
    base = f"https://v2.gosplan.info/fz{law}/purchases"
    raw = _request(
        client,
        key,
        f"{base}/{normalized}" if exact else base,
        {} if exact else {"object_info": normalized, "stage": 1, "limit": limit, "skip": offset},
    )
    data = _json(raw)
    if exact:
        if not isinstance(data, dict) or data.get("purchase_number") != normalized:
            raise GosplanSearchError("DETAIL_IDENTITY_MISMATCH")
        data = [data]
    if not isinstance(data, list) or len(data) > limit:
        raise GosplanSearchError("RESPONSE_SHAPE_INVALID")
    digest = hashlib.sha256(raw).hexdigest()
    rows = []
    seen = set()
    for item in data:
        if not isinstance(item, dict):
            raise GosplanSearchError("ROW_INVALID")
        number = _number(item.get("purchase_number"), law)
        if number in seen:
            raise GosplanSearchError("DUPLICATE_NUMBER")
        seen.add(number)
        title = _text(item.get("object_info"), 4000) or "Наименование не подтверждено"
        kind = _text(item.get("purchase_type"), 100)
        if not kind or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,99}", kind):
            raise GosplanSearchError("TYPE_INVALID")
        rows.append(
            SearchItem(
                law=law,
                number=number,
                title=title,
                purchase_type=kind,
                price=_money(item.get("max_price")),
                currency=_text(item.get("currency_code"), 12),
                deadline_raw=_text(
                    item.get("collecting_finished_at" if law == "44" else "submission_close_at"), 80
                ),
                source_sha256=digest,
            )
        )
    return SearchPage(
        law=law,
        query=query.strip(),
        observed_at=now,
        response_sha256=digest,
        items=tuple(rows),
        may_have_more=len(rows) == limit,
    )


def _safe_url(value: object, kind: str, number: str | None = None) -> str | None:
    if (
        not isinstance(value, str)
        or len(value) > 2048
        or "\\" in value
        or any(ord(c) < 33 for c in value)
    ):
        return None
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port is not None
        ):
            return None
    except ValueError:
        return None
    if kind == "file":
        if host != "zakupki.gov.ru" or not re.fullmatch(
            r"/(44fz|223)/filestore/public/1\.0/download/(priz|fz223)/file\.html", parsed.path
        ):
            return None
    elif kind == "eis":
        if host != "zakupki.gov.ru" or not parsed.path.startswith(
            ("/epz/", "/223/purchase/public/")
        ):
            return None
        if not number or parse_qs(parsed.query).get("regNumber") != [number]:
            return None
    elif not any(host == x or host.endswith("." + x) for x in _PLATFORM_HOSTS):
        return None
    return value


def _objects(value: object) -> list[dict]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list) and len(value) <= 100 and all(isinstance(x, dict) for x in value):
        return value
    if value is not None:
        raise GosplanSearchError("DETAIL_SHAPE_INVALID")
    return []


def read_detail(client: httpx.Client, key: str, law: Law, number: str, *, now: datetime) -> Detail:
    _scope(law, now)
    _number(number, law)
    raw = _request(client, key, f"https://v2.gosplan.info/fz{law}/purchases/{number}", {})
    data = _json(raw)
    if not isinstance(data, dict) or data.get("purchase_number") != number:
        raise GosplanSearchError("DETAIL_IDENTITY_MISMATCH")
    docs = data.get("docs", [])
    if not isinstance(docs, list) or len(docs) > 100 or not all(isinstance(x, dict) for x in docs):
        raise GosplanSearchError("DETAIL_SHAPE_INVALID")
    digest = hashlib.sha256(raw).hexdigest()
    links: list[DocumentLink] = []
    seen = set()
    eis = platform = None
    truncated = False
    may_derive_eis = False
    hidden_or_ambiguous = False
    for doc in docs:
        source = doc.get("source")
        if not isinstance(source, dict):
            continue
        common = source.get("commonInfo") if isinstance(source.get("commonInfo"), dict) else {}
        hidden = source.get("hidePurchase")
        accredited = source.get("hidePurchaseCustomerAccredited")
        if law == "223" and (
            hidden not in (None, "false", "0", False)
            or accredited not in (None, "false", "0", False)
        ):
            hidden_or_ambiguous = True
        if (
            law == "223"
            and hidden in ("false", "0", False)
            and accredited in (None, "false", "0", False)
        ):
            may_derive_eis = True
        for candidate in (source.get("urlEIS"), source.get("href"), common.get("href")):
            eis = eis or _safe_url(candidate, "eis", number)
        platform = platform or _safe_url(source.get("urlVSRZ"), "platform")
        for outer, inner in (
            ("attachments", "document"),
            ("attachments", "attachment"),
            ("attachmentsInfo", "attachmentInfo"),
        ):
            group = source.get(outer)
            if not isinstance(group, dict):
                continue
            for entry in _objects(group.get(inner)):
                url = _safe_url(entry.get("url"), "file")
                if url and url not in seen:
                    seen.add(url)
                    if len(links) >= 50:
                        truncated = True
                    else:
                        name = _text(entry.get("fileName"), 500) or "Документ закупки"
                        links.append(DocumentLink(name=name, url=url, source_sha256=digest))
    if hidden_or_ambiguous:
        raise GosplanSearchError("NOTICE_RESTRICTED")
    origin = "PROVIDER" if eis else None
    if not eis and may_derive_eis and not hidden_or_ambiguous:
        eis = f"https://zakupki.gov.ru/223/purchase/public/purchase/info/common-info.html?regNumber={number}"
        origin = "NUMBER_DERIVED"
    return Detail(
        law=law,
        number=number,
        observed_at=now,
        response_sha256=digest,
        eis_url=eis,
        eis_url_origin=origin,
        platform_url=platform,
        documents=tuple(links),
        documents_truncated=truncated,
    )
