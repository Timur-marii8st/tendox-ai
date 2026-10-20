"""Bounded live Bing transport proof or source0-only production regression."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from procurement.sources.supplier_serp import (
    SearchEngine,
    browser_transport_provenance,
    observe_supplier_serp,
)

QUERY = "Бумага A4 производитель поставщик купить оптом"


def probe() -> None:
    if os.environ.get("SUPPLIER_BROWSER_PREFLIGHT_DEBUG") == "1":
        import sys

        from procurement.sources import supplier_serp_browser as browser_module

        original = browser_module._capture_with_processes

        async def diagnostic(*args, **kwargs):
            try:
                return await original(*args, **kwargs)
            except Exception as error:
                print(type(error).__name__, str(error), file=sys.stderr)
                if error.__cause__ is not None:
                    print(type(error.__cause__).__name__, str(error.__cause__), file=sys.stderr)
                raise

        browser_module._capture_with_processes = diagnostic
    capture = observe_supplier_serp(
        QUERY,
        company_id=os.environ.get(
            "SUPPLIER_BROWSER_PREFLIGHT_COMPANY", "browser-methodology-verification"
        ),
        cooldowns=(SearchEngine.YANDEX, SearchEngine.GOOGLE),
    )
    print(
        json.dumps(
            {
                "transport": browser_transport_provenance(),
                "batch": capture.batch.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
    )
    assert capture.batch.attempts[0].status == "COMPLETED"
    assert capture.batch.attempts[0].returned_count > 0
    assert sum(a.browser_navigation_count for a in capture.batch.attempts) == 1


def cache(*, prepare: bool = False, verify_audit: bool = False) -> None:
    from sqlalchemy import create_engine, select

    from procurement.storage.eis_supplier_serp import SupplierSerpReport, read_supplier_serp
    from procurement.storage.models import eis_supplier_serp_runs
    from procurement.storage.repository import PostgresStorage

    storage = PostgresStorage(create_engine(os.environ["DATABASE_URL"]))
    company = os.environ["EIS_PILOT_COMPANY"]
    with storage.transaction(company, consistent_read=True) as connection:
        payload = connection.scalar(
            select(eis_supplier_serp_runs.c.report)
            .where(eis_supplier_serp_runs.c.company_id == company)
            .order_by(eis_supplier_serp_runs.c.created_at.desc())
            .limit(1)
        )
    if payload is None:
        raise RuntimeError("NO_PRODUCTION_SOURCE0_SAMPLE")
    report = SupplierSerpReport.model_validate(payload)
    if prepare:
        from procurement.api.eis_supplier_serp_runner import run_prepare_supplier_serp_subprocess

        result = run_prepare_supplier_serp_subprocess(
            storage, company, report.request, actor_id="server-methodology-acceptance", refresh=True
        )
        assert result.created and result.report.batch is not None
        assert result.source_requests == 1
        assert result.report.batch.attempts[0].status == "COMPLETED"
        assert result.report.batch.attempts[0].returned_count > 0
        replay = read_supplier_serp(storage, company, report.request)
        assert replay.report == result.report and replay.source_requests == 0
        print(
            json.dumps(
                {
                    "status": "PERSISTED_PREPARE_PASS",
                    "result": result.model_dump(mode="json"),
                    "replay_source_requests": 0,
                },
                ensure_ascii=False,
            )
        )
        return
    result = read_supplier_serp(storage, company, report.request)
    assert result.source_requests == 0 and not result.created
    assert result.report == report
    if verify_audit:
        from procurement.storage.models import audit_events

        with storage.transaction(company, consistent_read=True) as connection:
            basis = connection.scalar(
                select(audit_events.c.basis).where(
                    audit_events.c.company_id == company,
                    audit_events.c.event_type == "EIS_SUPPLIER_SERP_SAVED",
                    audit_events.c.basis["run_id"].astext == report.run_id,
                )
            )
        assert basis is not None
        provenance = browser_transport_provenance()
        assert all(basis.get(key) == value for key, value in provenance.items())
        print(
            json.dumps(
                {"status": "IMMUTABLE_TRANSPORT_AUDIT_PASS", "run_id": report.run_id, **provenance}
            )
        )
    print(
        json.dumps(
            {
                "status": "SOURCE0_PASS",
                "run_id": report.run_id,
                "source_requests": 0,
                "report_status": report.status,
            }
        )
    )


def cooldown() -> None:
    capture = observe_supplier_serp(
        QUERY, company_id="local-eis-supplier", cooldowns=(SearchEngine.BING,)
    )
    assert all(
        a.status == "COOLDOWN" and a.browser_navigation_count == 0 for a in capture.batch.attempts
    )
    print(json.dumps({"status": "PERSISTED_COOLDOWN_PASS", "source_requests": 0}))


def seed(directory: Path) -> None:
    from procurement.sources.supplier_serp_browser import _mark, profile_directory

    root = Path(os.environ["SUPPLIER_SERP_BROWSER_STATE_DIR"])
    evidence = []
    for name, engine in (
        ("google.json", SearchEngine.GOOGLE),
        ("yandex.json", SearchEngine.YANDEX),
    ):
        raw = (directory / name).read_bytes()
        report = json.loads(raw)
        assert report["status"] == "BLOCKED" and report["dom_sha256"]
        observed = datetime.fromisoformat(report["observed_at"])
        profile = profile_directory(root, "local-eis-supplier", engine)
        _mark(root, profile, engine, "BLOCKED", observed)
        evidence.append(
            {
                "engine": engine.value,
                "report_sha256": hashlib.sha256(raw).hexdigest(),
                "observed_at": observed.isoformat(),
            }
        )
    print(json.dumps({"status": "COOLDOWN_FROM_OBSERVED_BLOCK", "evidence": evidence}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("probe", "cache", "seed", "cooldown", "prepare", "audit"))
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    if args.mode == "probe":
        probe()
    elif args.mode == "cache":
        cache()
    elif args.mode == "cooldown":
        cooldown()
    elif args.mode == "prepare":
        cache(prepare=True)
    elif args.mode == "audit":
        cache(verify_audit=True)
    else:
        if args.evidence is None:
            parser.error("seed requires exact retained evidence directory")
        seed(args.evidence)
