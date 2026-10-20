"""Source0 проверка исторических фактов трёх S202 закупок; секреты не выводятся."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from sqlalchemy import create_engine, select

from procurement.storage.eis_document_store import NoticeDocumentRef
from procurement.storage.eis_protocols import EisHistoricalProtocolReport, read_historical_protocols
from procurement.storage.models import eis_notice_versions
from procurement.storage.repository import PostgresStorage

COMPANY = "local-eis-supplier"
NUMBERS = ("0373100075926000096", "0373100075926000095", "0573500000526000095")
ROOT = Path("/var/lib/eis-browser/research/rejected")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", action="store_true")
    args = parser.parse_args()
    engine = create_engine(os.environ["DATABASE_URL"])
    storage = PostgresStorage(engine)
    reports = []
    elapsed_ms = []
    with storage.transaction(COMPANY, consistent_read=True) as conn:
        rows = (
            conn.execute(
                select(eis_notice_versions).where(
                    eis_notice_versions.c.company_id == COMPANY,
                    eis_notice_versions.c.purchase_number.in_(NUMBERS),
                    eis_notice_versions.c.version_number == 1,
                )
            )
            .mappings()
            .all()
        )
    if len(rows) != 3:
        raise ValueError("PROTOCOL_CHECK_COHORT_MISMATCH")
    for row in rows:
        ref = NoticeDocumentRef(
            purchase_number=row["purchase_number"],
            version_number=row["version_number"],
            notice_xml_sha256=row["xml_sha256"],
        )
        started = perf_counter_ns()
        if args.api:
            request = Request(
                "http://127.0.0.1:8000/v1/tender-discovery/eis-protocols?"
                + urlencode(ref.model_dump()),
                headers={"Authorization": "Bearer " + os.environ["EIS_PILOT_TOKEN"]},
            )
            with urlopen(request, timeout=30) as response:
                if response.status != 200 or response.headers["Cache-Control"] != "no-store":
                    raise ValueError("PROTOCOL_CHECK_API_INVALID")
                content = response.read(1024**2 + 1)
            if len(content) > 1024**2:
                raise ValueError("PROTOCOL_CHECK_RESPONSE_LIMIT")
            report = EisHistoricalProtocolReport.model_validate_json(content)
        else:
            report = read_historical_protocols(storage, COMPANY, ref, now=datetime.now(UTC))
        if report.company_id != COMPANY or report.notice != ref or len(report.documents) != 3:
            raise ValueError("PROTOCOL_CHECK_IDENTITY_INVALID")
        if report.application_status != "FAIL" or "DEADLINE_EXPIRED" not in report.reasons:
            raise ValueError("PROTOCOL_CHECK_GATE_INVALID")
        reports.append(report)
        elapsed_ms.append((perf_counter_ns() - started) // 1_000_000)
    engine.dispose()
    proof = {
        "checked_at": datetime.now(UTC).isoformat(),
        "mode": "API" if args.api else "DIRECT",
        "company_id": COMPANY,
        "source_requests": 0,
        "database_writes": 0,
        "read_elapsed_ms": elapsed_ms,
        "reports": [report.model_dump(mode="json") for report in reports],
    }
    blob = json.dumps(proof, ensure_ascii=False, indent=2).encode()
    if len(blob) > 2 * 1024**2:
        raise ValueError("PROTOCOL_CHECK_PROOF_LIMIT")
    path = ROOT / f"s203-protocol-facts-{uuid4()}.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(blob)
    print(
        json.dumps(
            {
                "checked_at": proof["checked_at"],
                "mode": proof["mode"],
                "source_requests": 0,
                "database_writes": 0,
                "proof": str(path),
                "sha256": hashlib.sha256(blob).hexdigest(),
                "proof_bytes": len(blob),
                "read_elapsed_ms": elapsed_ms,
                "reports": [
                    {
                        "number": report.notice.purchase_number,
                        "application_status": report.application_status,
                        "documents": [
                            {
                                "type": doc.source.document_type,
                                "xml_sha256": doc.source.xml_sha256,
                                "observed_rows": doc.observed_rows.value,
                                "represented_applications": doc.represented_applications.value,
                                "count_status": doc.represented_applications.status,
                                "explicit_prices": sum(
                                    app.proposal.amount.value is not None
                                    for app in doc.applications
                                ),
                            }
                            for doc in report.documents
                        ],
                    }
                    for report in reports
                ],
            }
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print('{"status":"UNKNOWN","reason":"PROTOCOL_CHECK_UNAVAILABLE"}')
        raise SystemExit(65) from None
