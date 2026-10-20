"""One bounded AESMBO window; operator runs under the server's global source lock."""

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
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4
from zipfile import ZipFile

from procurement.sources.eis_223_archive import (
    DOCUMENT_TYPE,
    MAX_ARCHIVE_BYTES,
    Eis223ContractError,
    inspect_notice223_archive,
    notice223_request,
)
from procurement.sources.eis_feed import parse_get_docs_ip_response
from procurement.sources.eis_feed_sync import _request, eis_browser_transport

ROOT = Path("/var/lib/eis-browser/research/223")


def write(path: Path, raw: bytes) -> None:
    if path.exists():
        if path.read_bytes() != raw:
            raise Eis223ContractError("LOCAL_REPLAY_CONFLICT")
    else:
        with path.open("xb") as stream:
            stream.write(raw)
    path.chmod(0o600)


async def run(company: str, region: str, day: date, cached: str | None) -> dict[str, object]:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", company):
        raise Eis223ContractError("COMPANY_INVALID")
    if not re.fullmatch(r"[0-9]{2}", region) or day > datetime.now(UTC).date():
        raise Eis223ContractError("WINDOW_INVALID")
    token = os.environ.get("EIS_GETDOCS_IP_TOKEN", "")
    if not re.fullmatch(r"[A-Za-z0-9-]{16,128}", token):
        raise Eis223ContractError("TOKEN_CONFIG_INVALID")
    uid = str(UUID(cached)) if cached else str(uuid4())
    target = ROOT / company
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    target.chmod(0o700)
    selection = {
        "company_id": company,
        "request_id": uid,
        "region": region,
        "day": day.isoformat(),
        "offset": "+03:00",
        "document_type": DOCUMENT_TYPE,
        "subsystem": "RI223",
    }
    selection_path = target / f"{uid}-selection.json"
    if cached and (
        not selection_path.exists()
        or json.loads(selection_path.read_text(encoding="utf-8")) != selection
    ):
        raise Eis223ContractError("CACHED_SELECTION_MISMATCH")
    write(selection_path, json.dumps(selection, sort_keys=True).encode())
    timer = perf_counter()
    async with eis_browser_transport() as transport:

        async def response(path: Path, request: bytes) -> bytes:
            if cached:
                raw = path.read_bytes()
            else:
                status, raw = await transport.post(request)
                if status != 200:
                    raise Eis223ContractError("SOURCE_HTTP_REJECTED")
            if len(raw) > 2 * 1024 * 1024 or token.encode() in raw:
                raise Eis223ContractError("SOURCE_CONTENT_REJECTED")
            return raw

        initial_path = target / f"{uid}-initial.xml"
        raw = await response(initial_path, notice223_request(token, uid, region, day))
        initial = parse_get_docs_ip_response(raw)
        if (
            initial.request_id != uid
            or initial.source_mode != "PROD"
            or initial.service != "IP"
            or initial.kind != "BY_REGION"
        ):
            raise Eis223ContractError("SOURCE_BINDING_REJECTED")
        write(initial_path, raw)
        report: dict[str, object] = {
            "company_id": company,
            "window_key": f"getDocsIP/RI223/{region}/{day.isoformat()}+03:00/{DOCUMENT_TYPE}",
            "request_id": uid,
            "initial_sha256": initial.source_sha256,
            "state": initial.state,
            "coverage": "UNKNOWN",
        }
        if initial.state != "LINKS_PENDING":
            return report
        prepared_path = target / f"{uid}-prepared.xml"
        for _ in range(4):
            if not cached:
                await asyncio.sleep(10)
            raw = await response(
                prepared_path, _request(token, str(uuid4()), original_request_id=uid)
            )
            prepared = parse_get_docs_ip_response(raw)
            if (
                prepared.doc_request_uid != uid
                or prepared.source_mode != "PROD"
                or prepared.service != "IP"
                or prepared.kind != "PREPARED"
            ):
                raise Eis223ContractError("PREPARED_BINDING_REJECTED")
            if prepared.state == "READY":
                break
            if prepared.state != "PREPARING":
                raise Eis223ContractError("PREPARED_STATE_REJECTED")
        if prepared.state != "READY" or not 1 <= len(prepared.prepared_archives) <= 2:
            raise Eis223ContractError("PREPARED_LIMIT_OR_INCOMPLETE")
        initial_uids = [
            parse_qs(urlsplit(url).query)["compoundUid"][0].replace("-", "").lower()
            for url in initial.archive_urls
        ]
        ready_uids = [reference.archive_uid for reference in prepared.prepared_archives]
        if (
            len(set(initial_uids)) != len(initial_uids)
            or len(set(ready_uids)) != len(ready_uids)
            or set(initial_uids) != set(ready_uids)
        ):
            raise Eis223ContractError("ARCHIVE_SET_MISMATCH")
        write(prepared_path, raw)
        archives = []
        for index, reference in enumerate(prepared.prepared_archives, 1):
            archive_path = target / f"{uid}-{index}.zip"
            if cached:
                raw = archive_path.read_bytes()
            else:
                status, raw = await transport.download(reference.url, token)
                if status != 200:
                    raise Eis223ContractError("ARCHIVE_HTTP_REJECTED")
            if len(raw) > MAX_ARCHIVE_BYTES or token.encode() in raw:
                raise Eis223ContractError("ARCHIVE_CONTENT_REJECTED")
            inspection = inspect_notice223_archive(
                raw,
                company_id=company,
                source_response_sha256=initial.source_sha256,
                source_locator=str(report["window_key"]),
            )
            with ZipFile(BytesIO(raw)) as zipfile:
                if any(token.encode() in zipfile.read(m) for m in zipfile.infolist()):
                    raise Eis223ContractError("XML_TOKEN_REFLECTION_REJECTED")
            write(archive_path, raw)
            snapshot_path = target / f"{uid}-{index}-parsed.json"
            write(snapshot_path, inspection.model_dump_json().encode())
            archives.append(
                {
                    "archive_sha256": inspection.archive_sha256,
                    "bytes": len(raw),
                    "records": len(inspection.records),
                    "lots": sum(len(n.lots) for n in inspection.records),
                    "items": sum(len(lot.items) for n in inspection.records for lot in n.lots),
                    "naive_or_missing_deadlines": sum(
                        n.deadline.status == "UNKNOWN" for n in inspection.records
                    ),
                    "attachments": sum(len(n.attachments) for n in inspection.records),
                    "invalid_urls": sum(
                        a.url.value is None for n in inspection.records for a in n.attachments
                    ),
                    "parsed_path": str(snapshot_path),
                    "parsed_sha256": hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
                }
            )
        report.update(
            state="PARSED",
            prepared_sha256=prepared.source_sha256,
            archives=archives,
            seconds=perf_counter() - timer,
            cached=bool(cached),
        )
        path = target / (
            "proof-" + uid + "-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + ".json"
        )
        write(path, json.dumps(report, ensure_ascii=False).encode())
        report.update(
            proof_path=str(path), proof_sha256=hashlib.sha256(path.read_bytes()).hexdigest()
        )
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--day", required=True, type=date.fromisoformat)
    parser.add_argument("--cached-request")
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(run(args.company, args.region, args.day, args.cached_request)),
            ensure_ascii=False,
        )
    )
