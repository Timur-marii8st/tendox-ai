"""Retain one bounded failed official window; credentials never enter artifacts."""

import argparse
import asyncio
import hashlib
import json
import os
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from sqlalchemy import create_engine

from procurement.sources import eis_feed_sync
from procurement.sources.eis_corpus import resource_gate
from procurement.sources.eis_feed_archive import EisFeedArchiveError
from procurement.storage.eis_notice_index import EisIndexConflict
from procurement.storage.repository import PostgresStorage


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", required=True)
    parser.add_argument("--day", required=True)
    parser.add_argument("--document-type", default="epNotificationEF2020")
    args = parser.parse_args()
    selection = eis_feed_sync.EisDateSelection(
        args.region, date.fromisoformat(args.day), 3, args.document_type
    )
    company = "local-eis-supplier"
    now = datetime.now(UTC)
    root = (
        Path("/var/lib/eis-browser/research/freshness-diagnostic")
        / company
        / now.strftime("%Y%m%dT%H%M%S%fZ")
    )
    root.mkdir(parents=True, exist_ok=False)
    token = os.environ["EIS_GETDOCS_IP_TOKEN"]
    original_post = eis_feed_sync._BrowserTransport.post
    original_download = eis_feed_sync._BrowserTransport.download
    files: list[dict[str, object]] = []
    archive_bytes = 0

    def retain(raw: bytes, suffix: str) -> None:
        if token.encode() in raw:
            raise ValueError("TOKEN_IN_RESPONSE_REJECTED")
        filename = f"{len(files):02d}.{suffix}"
        (root / filename).write_bytes(raw)
        files.append(
            {"file": filename, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        )

    async def post(transport, xml):
        status, raw = await original_post(transport, xml)
        if status == 200 and len(raw) <= eis_feed_sync.MAX_RESPONSE_BYTES:
            retain(raw, "xml")
        return status, raw

    async def download(transport, url, credential):
        nonlocal archive_bytes
        status, raw = await original_download(transport, url, credential)
        if status == 200 and raw.startswith(b"PK\x03\x04"):
            archive_bytes += len(raw)
            if archive_bytes <= eis_feed_sync.MAX_WINDOW_COMPRESSED_BYTES:
                retain(raw, "zip")
        return status, raw

    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    try:
        storage = PostgresStorage(engine)
        reason = resource_gate(
            storage, company, max_database_bytes=100 * 1024**3, min_free_bytes=40 * 1024**3
        )
        if reason:
            print(json.dumps({"status": "BLOCKED", "reason": reason}))
            return 2
        eis_feed_sync._BrowserTransport.post = post
        eis_feed_sync._BrowserTransport.download = download
        try:
            result = await eis_feed_sync.sync_eis_window_via_browser(
                storage, company, "server-freshness-diagnostic", selection, token, refresh=True
            )
            reason = result.status
        except (EisFeedArchiveError, EisIndexConflict, eis_feed_sync.EisSyncError) as error:
            reason = str(error)
        groups: dict[tuple[str, str], list[dict[str, object]]] = {}
        for item in files:
            if not str(item["file"]).endswith(".zip"):
                continue
            with ZipFile(BytesIO((root / str(item["file"])).read_bytes())) as archive:
                for info in archive.infolist():
                    raw = archive.read(info)
                    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
                        continue
                    document = ET.fromstring(raw)
                    key = (
                        document.findtext(".//{*}purchaseNumber") or "",
                        document.findtext(".//{*}versionNumber") or "",
                    )
                    groups.setdefault(key, []).append(
                        {
                            "archive": item["file"],
                            "member": info.filename,
                            "xml_sha256": hashlib.sha256(raw).hexdigest(),
                            "bytes": len(raw),
                        }
                    )
        duplicates = [
            {
                "number": key[0],
                "version": key[1],
                "members": values,
                "identical_bytes": len({str(value["xml_sha256"]) for value in values}) == 1,
            }
            for key, values in groups.items()
            if len(values) > 1
        ]
        report = {
            "company_id": company,
            "window_key": selection.window_key,
            "reason": reason,
            "started_at": now,
            "finished_at": datetime.now(UTC),
            "files": files,
            "duplicate_groups": duplicates,
            "coverage": "UNKNOWN",
        }
        content = json.dumps(report, default=str, ensure_ascii=False, indent=2).encode()
        (root / "diagnostic.json").write_bytes(content)
        print(
            json.dumps(
                {
                    "report": str(root / "diagnostic.json"),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "reason": reason,
                    "duplicate_groups": len(duplicates),
                    "conflicting_groups": sum(not row["identical_bytes"] for row in duplicates),
                }
            )
        )
        return 0
    finally:
        eis_feed_sync._BrowserTransport.post = original_post
        eis_feed_sync._BrowserTransport.download = original_download
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
