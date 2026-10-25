"""Import one already captured, complete AESMBO window. No network requests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import date
from pathlib import Path
from time import perf_counter
from uuid import UUID

from sqlalchemy import create_engine

from procurement.sources.eis_223_archive import (
    DOCUMENT_TYPE,
    SUPPORTED_DOCUMENT_TYPES,
    TARGETED_DOCUMENT_TYPE,
)
from procurement.sources.eis_feed import parse_get_docs_ip_response
from procurement.storage.eis_223_index import (
    bind_notice223_window,
    ingest_notice223_window,
    preflight_notice223_window,
)
from procurement.storage.repository import PostgresStorage

ROOT = Path("/var/lib/eis-browser/research/223")
TARGETED_ROOT = Path("/var/lib/eis-browser/research/active-census-m0-20261012-v1/223-by-number")


def run_number(company: str, number: str, request: str) -> dict[str, object]:
    """Import one preserved complete number response; no fabricated date/region checkpoint."""
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", company):
        raise ValueError("COMPANY_INVALID")
    if not re.fullmatch(r"[0-9]{11}", number):
        raise ValueError("PURCHASE_NUMBER_INVALID")
    uid = str(UUID(request))
    root = TARGETED_ROOT / company / TARGETED_DOCUMENT_TYPE
    selection = json.loads((root / f"{uid}-selection.json").read_bytes())
    # Old diagnostic day/offset are bookkeeping only. BY_NUMBER has neither filter.
    expected = {
        "company_id": company,
        "family": TARGETED_DOCUMENT_TYPE,
        "purchase_number": number,
        "request_id": uid,
        "day": selection.get("day"),
        "offset": "+03:00",
    }
    if selection != expected:
        raise ValueError("CACHED_SELECTION_MISMATCH")
    date.fromisoformat(selection["day"])
    proof = json.loads((root / f"{uid}-proof.json").read_bytes())
    initial = parse_get_docs_ip_response((root / f"{uid}-initial.xml").read_bytes())
    paths = [root / f"{uid}-prepared-{i}.xml" for i in range(4)]
    prepared_path = next((p for p in reversed(paths) if p.exists()), None)
    if prepared_path is None:
        raise ValueError("SOURCE_XSD_PROOF_MISSING")
    prepared = parse_get_docs_ip_response(prepared_path.read_bytes())
    if initial.request_id != uid:
        raise ValueError("CACHED_REQUEST_MISMATCH")
    downloaded = {
        ref.url: (root / f"{uid}-{i}.zip").read_bytes()
        for i, ref in enumerate(prepared.prepared_archives, 1)
    }
    key = f"getDocsIP/RI223/by-number/{number}/{TARGETED_DOCUMENT_TYPE}"
    ready = bind_notice223_window(key, initial, prepared, downloaded)
    inspections, _ = preflight_notice223_window(company, ready)
    if (
        proof.get("state") != "XSD_VALIDATED"
        or proof.get("company_id") != company
        or proof.get("family") != TARGETED_DOCUMENT_TYPE
        or proof.get("purchase_number") != number
        or proof.get("request_id") != uid
        or proof.get("response_sha256") != ready.response_sha256
        or proof.get("prepared_sha256") != ready.prepared_sha256
        or {s.get("version"): s.get("purchase_xsd_sha256") for s in proof.get("schemas", [])}
        != {
            "16.2": "712e818f74bf3d38a03a3516533d0d4bf1df343f5a6e2056ae38a35f9ee7975b",
            "16.3": "c5ad9bec7a1d1ba393f818e48a6f066db0428ce939cf9f4066acfc23ac0f7411",
        }
        or [a["archive_sha256"] for a in proof.get("archives", [])]
        != [a.archive_sha256 for a in inspections]
    ):
        raise ValueError("SOURCE_XSD_PROOF_BINDING_INVALID")
    for source, inspected in zip(proof["archives"], inspections, strict=True):
        expected_records = [
            (n.purchase_number, n.version_number, n.xml_sha256, n.source_member)
            for n in inspected.records
        ]
        source_records = [
            (r["purchase_number"], r["version_number"], r["xml_sha256"], r["source_member"])
            for r in source["records"]
        ]
        if source_records != expected_records or any(
            r.get("xsd_valid") is not True for r in source["records"]
        ):
            raise ValueError("SOURCE_XSD_PROOF_BINDING_INVALID")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    started = perf_counter()
    try:
        result = ingest_notice223_window(
            PostgresStorage(engine), company, ready, actor_id="223-targeted-operator"
        )
    finally:
        engine.dispose()
    return {
        **result.model_dump(mode="json"),
        "seconds": perf_counter() - started,
        "response_sha256": ready.response_sha256,
        "prepared_sha256": ready.prepared_sha256,
        "archive_sha256": [a.archive_sha256 for a in inspections],
        "source_calls": 0,
        "scheduled_daily_coverage": "UNKNOWN",
    }


def run(
    company: str, region: str, day: date, request: str, family: str = DOCUMENT_TYPE
) -> dict[str, object]:
    if family not in SUPPORTED_DOCUMENT_TYPES:
        raise ValueError("FAMILY_NOT_ADMITTED")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", company):
        raise ValueError("COMPANY_INVALID")
    if not re.fullmatch(r"[0-9]{2}", region):
        raise ValueError("REGION_INVALID")
    uid = str(UUID(request))
    root = ROOT / company
    if family != DOCUMENT_TYPE:
        root = Path("/var/lib/eis-browser/research/223-families") / company / family
    selection = json.loads((root / f"{uid}-selection.json").read_text(encoding="utf-8"))
    expected = {
        "company_id": company,
        "request_id": uid,
        "region": region,
        "day": day.isoformat(),
        "offset": "+03:00",
        "document_type": family,
        "subsystem": "RI223",
    }
    if family != DOCUMENT_TYPE:
        expected.pop("subsystem")
        expected["family"] = expected.pop("document_type")
    if selection != expected:
        raise ValueError("CACHED_SELECTION_MISMATCH")
    initial = parse_get_docs_ip_response((root / f"{uid}-initial.xml").read_bytes())
    prepared_path = root / f"{uid}-prepared.xml"
    if family != DOCUMENT_TYPE:
        # Only the previously XSD-validated probe can be admitted; no error proof fallback.
        proof = json.loads((root / f"{uid}-proof.json").read_bytes())
        if (
            proof.get("state") != "XSD_VALIDATED"
            or proof.get("family") != family
            or proof.get("request_id") != uid
        ):
            raise ValueError("SOURCE_XSD_PROOF_MISSING")
        paths = [root / f"{uid}-prepared-{i}.xml" for i in range(4)]
        prepared_path = next((p for p in reversed(paths) if p.exists()), prepared_path)
    prepared = parse_get_docs_ip_response(prepared_path.read_bytes())
    if initial.request_id != uid:
        raise ValueError("CACHED_REQUEST_MISMATCH")
    downloaded = {
        ref.url: (root / f"{uid}-{i}.zip").read_bytes()
        for i, ref in enumerate(prepared.prepared_archives, 1)
    }
    key = f"getDocsIP/RI223/{region}/{day.isoformat()}+03:00/{family}"
    ready = bind_notice223_window(key, initial, prepared, downloaded)
    if family != DOCUMENT_TYPE and (
        proof.get("company_id") != company
        or proof.get("region") != region
        or proof.get("day") != day.isoformat()
        or proof.get("response_sha256") != initial.source_sha256
        or proof.get("prepared_sha256") != prepared.source_sha256
        or [a["archive_sha256"] for a in proof.get("archives", [])]
        != [hashlib.sha256(raw).hexdigest() for raw in ready.archives]
    ):
        raise ValueError("SOURCE_XSD_PROOF_BINDING_INVALID")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    timer = perf_counter()
    try:
        result = ingest_notice223_window(
            PostgresStorage(engine), company, ready, actor_id="223-operator"
        )
    finally:
        engine.dispose()
    return {
        **result.model_dump(mode="json"),
        "seconds": perf_counter() - timer,
        "response_sha256": ready.response_sha256,
        "prepared_sha256": ready.prepared_sha256,
        "archive_sha256": [hashlib.sha256(raw).hexdigest() for raw in ready.archives],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", required=True)
    parser.add_argument("--region")
    parser.add_argument("--day", type=date.fromisoformat)
    parser.add_argument("--number")
    parser.add_argument("--request", required=True)
    parser.add_argument("--family", choices=SUPPORTED_DOCUMENT_TYPES, default=DOCUMENT_TYPE)
    args = parser.parse_args()
    if args.number:
        if args.region or args.day or args.family != DOCUMENT_TYPE:
            parser.error("--number cannot be combined with --region, --day or --family")
        print(json.dumps(run_number(args.company, args.number, args.request), ensure_ascii=False))
        raise SystemExit(0)
    if args.region is None or args.day is None:
        parser.error("regional import requires --region and --day")
    print(
        json.dumps(
            run(args.company, args.region, args.day, args.request, args.family), ensure_ascii=False
        )
    )
