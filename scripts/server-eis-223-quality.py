"""Offline bounded audit of saved 223 XML; no source HTTP requests."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from sqlalchemy import create_engine, select

from procurement.sources.eis_223_archive import Eis223NoticeSnapshot, inspect_notice223_archive
from procurement.sources.eis_223_schema import load_schema_tree, validate_notice223_schema
from procurement.storage.eis_223_quality import record_schema_check
from procurement.storage.models import eis_223_blobs, eis_223_notice_versions
from procurement.storage.repository import PostgresStorage

COMPANY = "local-eis-supplier"
MAX_VERSIONS = 200
MAX_COMPRESSED = 32 * 1024**2


def run() -> dict[str, object]:
    engine = create_engine(os.environ["DATABASE_URL"])
    storage = PostgresStorage(engine)
    root = Path("/var/lib/eis-browser/research/223") / COMPANY
    try:
        trees = tuple(
            load_schema_tree(root / f"schemas-{release}", release) for release in ("16.2", "16.3")
        )
        with storage.transaction(COMPANY, consistent_read=True) as conn:
            rows = list(
                conn.execute(
                    select(eis_223_notice_versions)
                    .where(eis_223_notice_versions.c.company_id == COMPANY)
                    .order_by(
                        eis_223_notice_versions.c.purchase_number,
                        eis_223_notice_versions.c.version_number,
                    )
                    .limit(MAX_VERSIONS + 1)
                ).mappings()
            )
            if len(rows) > MAX_VERSIONS:
                raise ValueError("AUDIT_VERSION_BUDGET_REACHED")
            hashes = {row["archive_sha256"] for row in rows}
            archives = {
                row["archive_sha256"]: row["content"]
                for row in conn.execute(
                    select(eis_223_blobs).where(
                        eis_223_blobs.c.company_id == COMPANY,
                        eis_223_blobs.c.archive_sha256.in_(hashes),
                    )
                ).mappings()
            }
        if sum(len(raw) for raw in archives.values()) > MAX_COMPRESSED:
            raise ValueError("AUDIT_BYTE_BUDGET_REACHED")
        now = datetime.now(UTC)
        reports = []
        new = 0
        # Recheck bounded archive safety and the exact family before expanding saved bytes.
        for digest, raw in archives.items():
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("AUDIT_ARCHIVE_SHA_MISMATCH")
            family = Eis223NoticeSnapshot.model_validate(
                next(r["snapshot"] for r in rows if r["archive_sha256"] == digest)
            ).document_type
            inspect_notice223_archive(
                raw,
                company_id=COMPANY,
                source_response_sha256="0" * 64,
                source_locator="saved-immutable-archive",
                document_type=family,
            )
            with ZipFile(BytesIO(raw)) as archive:
                for row in (r for r in rows if r["archive_sha256"] == digest):
                    notice = Eis223NoticeSnapshot.model_validate(row["snapshot"])
                    content = archive.read(notice.source_member)
                    for tree in trees:
                        check = validate_notice223_schema(notice, content, tree, now=now)
                        new += record_schema_check(
                            storage, COMPANY, check, actor_id="223-offline-quality"
                        )
                        reports.append(check.model_dump(mode="json"))
        path = root / ("s155-schema-proof-" + now.strftime("%Y%m%dT%H%M%S%fZ") + ".json")
        proof = {
            "company_id": COMPANY,
            "checked_at": now.isoformat(),
            "versions": len(rows),
            "checks": reports,
            "new_checks": new,
            "source_requests": 0,
            "eligibility": "UNKNOWN",
        }
        with path.open("x", encoding="utf-8") as stream:
            json.dump(proof, stream, ensure_ascii=False)
        path.chmod(0o600)
        counts = Counter(check["status"] for check in reports)
        invalid = [
            {
                "purchase_number": c["purchase_number"],
                "version_number": c["version_number"],
                "xml_sha256": c["xml_sha256"],
                "schema_release": c["schema_release"],
                "diagnostics": c["diagnostics"],
            }
            for c in reports
            if c["status"] == "FAIL"
        ]
        return {
            "versions": len(rows),
            "checks": len(reports),
            "new_checks": new,
            "statuses": dict(counts),
            "invalid": invalid,
            "source_requests": 0,
            "proof_path": str(path),
            "proof_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        print(json.dumps(run(), ensure_ascii=False))
    except Exception:
        print('{"reason":"QUALITY_AUDIT_FAILED","source_requests":0}')
        raise SystemExit(1) from None
