"""Bounded operator NSI probe; run on VPS under the global eis-import.lock."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Literal
from uuid import UUID, uuid4

from procurement.sources.eis_catalog import (
    MAX_ARCHIVE_BYTES,
    MAX_RESPONSE_BYTES,
    EisCatalogError,
    EisCatalogInspection,
    catalog_request,
    inspect_catalog_archive,
    parse_catalog_response,
)
from procurement.sources.eis_feed_archive import SUPPORTED_NOTICE_TYPES
from procurement.sources.eis_feed_sync import EisSyncError, eis_browser_transport

ROOT = Path("/var/lib/eis-browser/research/catalog")


def _write(path: Path, raw: bytes) -> None:
    if path.exists():
        if path.read_bytes() != raw:
            raise EisCatalogError("CATALOG_LOCAL_REPLAY_CONFLICT")
        path.chmod(0o600)
        return
    with path.open("xb") as stream:
        stream.write(raw)
    path.chmod(0o600)


async def run(company: str, cached_ids: tuple[str, str] | None) -> dict[str, object]:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", company):
        raise EisCatalogError("CATALOG_COMPANY_INVALID")
    token = os.environ.get("EIS_GETDOCS_IP_TOKEN", "")
    if not re.fullmatch(r"[A-Za-z0-9-]{16,128}", token):
        raise EisCatalogError("CATALOG_TOKEN_CONFIG_INVALID")
    target = ROOT / company
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    target.chmod(0o700)
    started = datetime.now(UTC)
    timer = perf_counter()
    reports: list[dict[str, object]] = []
    async with eis_browser_transport() as transport:
        laws: tuple[Literal["44", "223"], ...] = ("44", "223")
        for offset, law in enumerate(laws):
            request_id = str(UUID(cached_ids[offset])) if cached_ids else str(uuid4())
            # Only request metadata (no token or outgoing SOAP) is persisted.
            response_path = target / f"contract-{law}-{request_id}.xml"
            if cached_ids:
                raw = response_path.read_bytes()
            else:
                status, raw = await transport.post(catalog_request(token, request_id, law))
                if status != 200:
                    raise EisCatalogError("CATALOG_SOURCE_HTTP_REJECTED")
            if len(raw) > MAX_RESPONSE_BYTES or token.encode() in raw:
                raise EisCatalogError("CATALOG_SOURCE_CONTENT_REJECTED")
            response = parse_catalog_response(raw, request_id=request_id)
            _write(response_path, raw)
            inspections: list[EisCatalogInspection] = []
            for part, reference in enumerate(response.archives, 1):
                archive_path = target / f"contract-{law}-{request_id}-{part}.zip"
                if cached_ids:
                    if len(response.archives) == 1 and not archive_path.exists():
                        archive_path = target / f"contract-{law}-{request_id}.zip"
                    content = archive_path.read_bytes()
                else:
                    status, content = await transport.download(reference.url, token)
                    if status != 200:
                        raise EisCatalogError("CATALOG_DOWNLOAD_HTTP_REJECTED")
                if not 0 < len(content) <= MAX_ARCHIVE_BYTES or token.encode() in content:
                    raise EisCatalogError("CATALOG_DOWNLOAD_CONTENT_REJECTED")
                inspection = inspect_catalog_archive(
                    content,
                    law=law,
                    response=response,
                    reference=reference,
                    forbidden_bytes=token.encode(),
                )
                inspections.append(inspection)
                _write(archive_path, content)
            entries = [entry for inspection in inspections for entry in inspection.entries]
            if len({e.document_type for e in entries}) != len(entries):
                raise EisCatalogError("CATALOG_MULTI_ARCHIVE_DUPLICATE")
            permitted = [
                e for e in entries if e.distributed_publicly == "PASS" and e.actual == "PASS"
            ]
            snapshot_path = target / f"snapshot-{law}-{request_id}.json"
            snapshot = {
                "company_id": company,
                "catalog_code": "nsiDocumentTypes" if law == "44" else "nsiDocumentTypes223",
                "nsi_kind": "all",
                "response": response.model_dump(mode="json"),
                "inspections": [i.model_dump(mode="json") for i in inspections],
                "requested_at": None if cached_ids else started.isoformat(),
                "checked_at": started.isoformat(),
                "adapter_policy_changed": False,
                "coverage": "UNKNOWN",
            }
            # Each proof is append-only, including cached reads at a new checked_at.
            snapshot_path = snapshot_path.with_name(
                snapshot_path.stem + "-" + started.strftime("%Y%m%dT%H%M%S%fZ") + ".json"
            )
            _write(snapshot_path, json.dumps(snapshot, ensure_ascii=False).encode())
            reports.append(
                {
                    "law": law,
                    "state": response.state,
                    "response_sha256": response.source_sha256,
                    "response_path": str(response_path),
                    "archive_bytes": [
                        (target / f"contract-{law}-{request_id}-{p}.zip").stat().st_size
                        if (target / f"contract-{law}-{request_id}-{p}.zip").exists()
                        else (target / f"contract-{law}-{request_id}.zip").stat().st_size
                        for p in range(1, len(inspections) + 1)
                    ],
                    "archives": [
                        {
                            "archive_sha256": i.archive_sha256,
                            "xml_sha256": sorted({e.source_xml_sha256 for e in i.entries}),
                        }
                        for i in inspections
                    ],
                    "entries_total": len(entries),
                    "public_actual": len(permitted),
                    "public_actual_by_subsystem": dict(Counter(e.subsystem for e in permitted)),
                    "unknown_flags": sum(
                        "UNKNOWN" in {e.actual, e.distributed_publicly} for e in entries
                    ),
                    "next_notice_candidates": [
                        {
                            "type": e.document_type,
                            "subsystem": e.subsystem,
                            "name": e.document_name,
                            "xml_sha256": e.source_xml_sha256,
                            "locator": e.fields[0].provenance.locator,
                        }
                        for e in permitted
                        if (
                            law == "44"
                            and e.subsystem == "PRIZ"
                            and e.document_type.startswith("epNotification")
                            and e.document_type not in SUPPORTED_NOTICE_TYPES
                        )
                        or (
                            law == "223"
                            and e.subsystem == "RI223"
                            and e.document_type.startswith("purchaseNotice")
                        )
                    ],
                    "proof_path": str(snapshot_path),
                    "proof_sha256": hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
                    "coverage": "UNKNOWN",
                }
            )
    return {
        "company_id": company,
        "mode": "CACHED_CONTRACT" if cached_ids else "OFFICIAL_LIVE",
        "elapsed_seconds": perf_counter() - timer,
        "catalogs": reports,
        "adapter_policy_changed": False,
        "coverage": "UNKNOWN",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--cached-request-44")
    parser.add_argument("--cached-request-223")
    args = parser.parse_args()
    if bool(args.cached_request_44) != bool(args.cached_request_223):
        parser.error("Both cached request ids are required together")
    cached = (args.cached_request_44, args.cached_request_223) if args.cached_request_44 else None
    try:
        result = asyncio.run(run(args.company_id, cached))
    except (EisCatalogError, EisSyncError) as error:
        print(json.dumps({"status": "REJECTED", "reason": str(error), "coverage": "UNKNOWN"}))
        return 1
    except Exception:
        # Never emit arbitrary transport exceptions or local paths containing credentials.
        print(
            json.dumps(
                {"status": "REJECTED", "reason": "CATALOG_PROBE_FAILED", "coverage": "UNKNOWN"}
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
