"""Inspect two explicit public 223 families with verified local XSDs; no index writes."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, NotRequired, Protocol, TypedDict
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from lxml import etree as E  # type: ignore[import-untyped]

from procurement.sources.eis_223_archive import PURCHASE_NS, notice223_request
from procurement.sources.eis_feed import (
    EisArchiveReference,
    EisFeedResponse,
    parse_get_docs_ip_response,
    validate_eis_archive_url,
)
from procurement.sources.eis_feed_sync import _request, eis_browser_transport

FAMILIES = ("purchaseNotice", "purchaseNoticeZKESMBO")
ROOT = Path("/var/lib/eis-browser/research/223-families")
MAX_ZIP = 16 * 1024**2
MAX_XML = 4 * 1024**2
MAX_EXPANDED = 32 * 1024**2


class Schema(Protocol):
    def validate(self, root: Any) -> bool: ...


class Inspection(TypedDict):
    archive_sha256: str
    bytes: int
    record_count: int
    records: list[dict[str, object]]
    coverage: Literal["UNKNOWN"]
    rejection: NotRequired[str]
    validation: NotRequired[list[dict[str, object]]]


def ready_refs(
    initial: EisFeedResponse, prepared: EisFeedResponse, uid: str
) -> tuple[EisArchiveReference, ...]:
    if (
        initial.service != "IP"
        or initial.kind != "BY_REGION"
        or initial.source_mode != "PROD"
        or initial.request_id != uid
        or initial.state != "LINKS_PENDING"
        or prepared.service != "IP"
        or prepared.kind != "PREPARED"
        or prepared.source_mode != "PROD"
        or prepared.doc_request_uid != uid
        or prepared.state != "READY"
    ):
        raise ValueError("SOURCE_BINDING_INVALID")
    expected = set()
    for url in initial.archive_urls:
        validate_eis_archive_url(url, doc_request_uid=uid)
        expected.add(UUID(parse_qs(urlsplit(url).query)["compoundUid"][0]).hex)
    refs = prepared.prepared_archives
    if (
        not 1 <= len(refs) <= 2
        or len(expected) != len(initial.archive_urls)
        or len({r.archive_uid for r in refs}) != len(refs)
        or expected != {r.archive_uid for r in refs}
    ):
        raise ValueError("ARCHIVE_SET_MISMATCH")
    for ref in refs:
        validate_eis_archive_url(ref.url, doc_request_uid=uid)
        if UUID(parse_qs(urlsplit(ref.url).query)["compoundUid"][0]).hex != ref.archive_uid:
            raise ValueError("ARCHIVE_UID_MISMATCH")
    return refs


def request(token: str, uid: str, family: str, day: date) -> bytes:
    if family not in FAMILIES:
        raise ValueError("FAMILY_NOT_ADMITTED_FOR_PROBE")
    root = ET.fromstring(notice223_request(token, uid, "50", day))
    field = root.find(".//documentType223")
    assert field is not None
    field.text = family
    serialized = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    assert isinstance(serialized, bytes)
    return serialized


def safe_members(raw: bytes, token: str) -> list[tuple[str, bytes]]:
    if not raw or len(raw) > MAX_ZIP:
        raise ValueError("ARCHIVE_BYTES_LIMIT")
    seen = set()
    result = []
    with ZipFile(BytesIO(raw)) as archive:
        members = archive.infolist()
        if not 1 <= len(members) <= 200 or sum(m.file_size for m in members) > MAX_EXPANDED:
            raise ValueError("ARCHIVE_EXPANSION_LIMIT")
        for member in members:
            name = member.orig_filename
            if (
                name != member.filename
                or not re.fullmatch(r"[^/\\:\x00]+\.xml", name)
                or name in seen
                or member.file_size > MAX_XML
                or member.flag_bits & 1
                or member.compress_type not in {ZIP_DEFLATED, ZIP_STORED}
                or member.external_attr >> 16 & 0o170000 == 0o120000
            ):
                raise ValueError("ARCHIVE_MEMBER_INVALID")
            seen.add(name)
            xml = archive.read(member)
            if (
                token.encode() in xml
                or b"\x00" in xml
                or re.search(rb"<!\s*(DOCTYPE|ENTITY)\b", xml, re.I)
            ):
                raise ValueError("XML_CONTENT_REJECTED")
            E.fromstring(xml, E.XMLParser(resolve_entities=False, no_network=True))
            result.append((name, xml))
    return result


def inspect(raw: bytes, family: str, schemas: tuple[Schema, ...], token: str) -> Inspection:
    if family not in FAMILIES:
        raise ValueError("ARCHIVE_OR_FAMILY_INVALID")
    records: list[dict[str, object]] = []
    identities = set()
    for name, xml in safe_members(raw, token):
        root = E.fromstring(xml, E.XMLParser(resolve_entities=False, no_network=True))
        if root.tag != f"{{{PURCHASE_NS}}}{family}":
            raise ValueError("SOURCE_FAMILY_MISMATCH")
        if not schemas or any(not schema.validate(root) for schema in schemas):
            raise ValueError("XSD_VALIDATION_FAILED")
        data = root.find(
            f"{{{PURCHASE_NS}}}body/{{{PURCHASE_NS}}}item/{{{PURCHASE_NS}}}{family}Data"
        )
        if data is None:
            raise ValueError("DIRECT_DATA_SHAPE_UNKNOWN")
        number = data.findtext(f"{{{PURCHASE_NS}}}registrationNumber")
        version = data.findtext(f"{{{PURCHASE_NS}}}version")
        if not re.fullmatch(r"[0-9]{11}", number or "") or not re.fullmatch(
            r"[1-9][0-9]*", version or ""
        ):
            raise ValueError("IDENTITY_SHAPE_UNKNOWN")
        key = (number, version)
        if key in identities:
            raise ValueError("NOTICE_VERSION_DUPLICATE")
        identities.add(key)
        records.append(
            {
                "purchase_number": number,
                "version_number": int(version or "0"),
                "xml_sha256": hashlib.sha256(xml).hexdigest(),
                "source_member": name,
                "data_locator": f"{family}/p:body/p:item/p:{family}Data",
                "title_raw": data.findtext(f"{{{PURCHASE_NS}}}name"),
                "deadline_raw": data.findtext(f"{{{PURCHASE_NS}}}submissionCloseDateTime"),
                "direct_fields": [str(e.tag) for e in data],
                "xsd_valid": True,
                "admission": "UNKNOWN",
                "economics": "UNKNOWN",
            }
        )
    return {
        "archive_sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "record_count": len(records),
        "records": records,
        "coverage": "UNKNOWN",
    }


def write(path: Path, raw: bytes) -> None:
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("LOCAL_REPLAY_CONFLICT")
        return
    with path.open("xb") as stream:
        stream.write(raw)
    path.chmod(0o600)


async def run(company: str, family: str, day: date, cached: str | None = None) -> dict[str, object]:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", company):
        raise ValueError("COMPANY_INVALID")
    token = os.environ["EIS_GETDOCS_IP_TOKEN"]
    uid = str(UUID(cached)) if cached else str(uuid4())
    outbound = request(token, uid, family, day)
    root = ROOT / company / family
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    schemas = []
    schema_proofs = []
    for version in ("16.2", "16.3"):
        schema_dir = Path("/var/lib/eis-browser/research/223") / company / f"schemas-{version}"
        xsd = schema_dir / "purchase.xsd"
        schemas.append(
            E.XMLSchema(E.parse(str(xsd), E.XMLParser(resolve_entities=False, no_network=True)))
        )
        schema_proofs.append(
            {
                "version": version,
                "purchase_xsd_sha256": hashlib.sha256(xsd.read_bytes()).hexdigest(),
            }
        )
    selection = {
        "company_id": company,
        "family": family,
        "day": day.isoformat(),
        "region": "50",
        "offset": "+03:00",
        "request_id": uid,
    }
    selection_path = root / f"{uid}-selection.json"
    if cached and (
        not selection_path.exists() or json.loads(selection_path.read_bytes()) != selection
    ):
        raise ValueError("CACHED_SELECTION_MISMATCH")
    write(selection_path, json.dumps(selection).encode())
    started = perf_counter()
    async with eis_browser_transport() as transport:

        async def post(raw: bytes, suffix: str) -> EisFeedResponse:
            path = root / f"{uid}-{suffix}.xml"
            if cached:
                status, response = 200, path.read_bytes()
            else:
                status, response = await transport.post(raw)
            if status != 200 or len(response) > 2 * 1024**2 or token.encode() in response:
                raise ValueError("SOURCE_RESPONSE_REJECTED")
            parsed = parse_get_docs_ip_response(response)
            write(path, response)
            return parsed

        initial = await post(outbound, "initial")
        if (
            initial.service != "IP"
            or initial.kind != "BY_REGION"
            or initial.request_id != uid
            or initial.source_mode != "PROD"
        ):
            raise ValueError("INITIAL_REQUEST_MISMATCH")
        proof: dict[str, object] = {
            "company_id": company,
            "family": family,
            "region": "50",
            "day": day.isoformat(),
            "request_id": uid,
            "response_sha256": initial.source_sha256,
            "state": initial.state,
            "coverage": "UNKNOWN",
            "schemas": schema_proofs,
        }
        archives: list[Inspection] = []
        if initial.state == "LINKS_PENDING":
            for poll in range(4):
                if not cached:
                    await asyncio.sleep(10)
                poll_uid = str(uuid4())
                prepared = await post(
                    _request(token, poll_uid, original_request_id=uid), f"prepared-{poll}"
                )
                if cached:
                    poll_uid = prepared.request_id
                if (
                    prepared.service != "IP"
                    or prepared.kind != "PREPARED"
                    or prepared.source_mode != "PROD"
                    or prepared.doc_request_uid != uid
                    or prepared.request_id != poll_uid
                ):
                    raise ValueError("PREPARED_REQUEST_MISMATCH")
                if prepared.state != "PREPARING":
                    break
            proof["state"] = prepared.state
            proof["prepared_sha256"] = prepared.source_sha256
            if prepared.state == "READY":
                refs = ready_refs(initial, prepared, uid)
                for index, ref in enumerate(refs, 1):
                    archive_path = root / f"{uid}-{index}.zip"
                    if cached and archive_path.exists():
                        status, raw = 200, archive_path.read_bytes()
                    else:
                        status, raw = await transport.download(ref.url, token)
                    if status != 200 or token.encode() in raw:
                        raise ValueError("ARCHIVE_DOWNLOAD_REJECTED")
                    members = safe_members(raw, token)
                    write(archive_path, raw)
                    try:
                        inspected = inspect(raw, family, tuple(schemas), token)
                    except ValueError as error:
                        validation: list[dict[str, object]] = []
                        for name, xml in members:
                            source = E.fromstring(
                                xml, E.XMLParser(resolve_entities=False, no_network=True)
                            )
                            checks = []
                            errors = []
                            for schema in schemas:
                                checks.append(schema.validate(source))
                                errors.append([str(e)[:300] for e in schema.error_log][:4])
                            validation.append(
                                {
                                    "member": name,
                                    "xml_sha256": hashlib.sha256(xml).hexdigest(),
                                    "valid": checks,
                                    "errors": errors,
                                }
                            )
                        inspected = {
                            "archive_sha256": hashlib.sha256(raw).hexdigest(),
                            "bytes": len(raw),
                            "record_count": 0,
                            "records": [],
                            "coverage": "UNKNOWN",
                            "rejection": str(error),
                            "validation": validation,
                        }
                    archives.append(inspected)
                proof["archives"] = archives
                proof["state"] = (
                    "SOURCE_REJECTED"
                    if any("rejection" in a for a in archives)
                    else "XSD_VALIDATED"
                )
    proof["seconds"] = perf_counter() - started
    suffix = "-replay-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") if cached else ""
    path = root / f"{uid}{suffix}-proof.json"
    write(path, json.dumps(proof, ensure_ascii=False).encode())
    return {
        "proof_path": str(path),
        "proof_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "family": family,
        "state": proof["state"],
        "seconds": proof["seconds"],
        "records": sum(a["record_count"] for a in archives),
        "coverage": "UNKNOWN",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", required=True)
    parser.add_argument("--family", choices=FAMILIES, required=True)
    parser.add_argument("--day", type=date.fromisoformat, required=True)
    parser.add_argument("--cached-request")
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(run(args.company, args.family, args.day, args.cached_request)),
            ensure_ascii=False,
        )
    )
