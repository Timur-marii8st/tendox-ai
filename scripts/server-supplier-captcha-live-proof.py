"""Operator-owned live CAPTCHA frame proof; never solve the real challenge."""

from __future__ import annotations

import base64
import json
import math
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

from sqlalchemy import create_engine, select

from procurement.sources.supplier_captcha_recovery import pacing_paths
from procurement.sources.supplier_serp import SearchEngine
from procurement.sources.supplier_serp_browser import profile_directory
from procurement.storage.eis_supplier_serp import SupplierSerpReport
from procurement.storage.models import eis_supplier_serp_runs
from procurement.storage.repository import PostgresStorage


def post(path: str, payload: dict):
    request = Request(
        "http://127.0.0.1:8000/v1/tender-discovery/" + path,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Authorization": "Bearer " + os.environ["EIS_PILOT_TOKEN"],
            "Content-Type": "application/json",
        },
    )
    with urlopen(request, timeout=95) as response:
        return json.load(response)


def main():
    company = os.environ["EIS_PILOT_COMPANY"]
    storage = PostgresStorage(create_engine(os.environ["DATABASE_URL"]))
    with storage.transaction(company, consistent_read=True) as conn:
        payload = conn.scalar(
            select(eis_supplier_serp_runs.c.report)
            .where(
                eis_supplier_serp_runs.c.company_id == company,
                eis_supplier_serp_runs.c.report["batch"].astext.is_not(None),
            )
            .order_by(eis_supplier_serp_runs.c.created_at.desc())
            .limit(1)
        )
    report = SupplierSerpReport.model_validate(payload)
    saved = post("eis-supplier-serp/read", {"request": report.request.model_dump(mode="json")})
    report = SupplierSerpReport.model_validate(saved["report"])
    if not any(a.status == "BLOCKED" for a in report.batch.attempts):
        saved = post(
            "eis-supplier-serp/prepare",
            {"request": report.request.model_dump(mode="json"), "refresh": True},
        )
        report = SupplierSerpReport.model_validate(saved["report"])
    blocked = [a.engine for a in report.batch.attempts if a.status == "BLOCKED"]
    if not blocked:
        raise RuntimeError("NO_EXACT_BLOCKED_OBSERVATION")
    engine = SearchEngine.GOOGLE if SearchEngine.GOOGLE in blocked else blocked[0]
    root = Path(os.environ["SUPPLIER_SERP_BROWSER_STATE_DIR"])
    profile = profile_directory(root, company, engine)
    waits = []
    for path in pacing_paths(root, profile, engine):
        raw = json.loads(path.read_text())["next_allowed_at"]
        if raw:
            waits.append(datetime.fromisoformat(raw))
    delay = max(
        0, math.ceil((max(waits, default=datetime.now(UTC)) - datetime.now(UTC)).total_seconds())
    )
    if delay:
        if delay > 35:
            raise RuntimeError("PACING_WAIT_OUT_OF_BOUND")
        print(json.dumps({"status": "PACING_WAIT", "seconds": delay}), flush=True)
        time.sleep(delay + 1)
    view = post(
        "supplier-captcha/start",
        {
            "request": report.request.model_dump(mode="json"),
            "run_id": report.run_id,
            "engine": engine.value,
        },
    )
    for _ in range(100):
        if view["status"] != "STARTING":
            break
        time.sleep(0.2)
        view = post("supplier-captcha/status", {"session_id": view["session_id"]})
    if view["status"] != "WAITING":
        raise RuntimeError("MANUAL_BROWSER_NOT_WAITING:" + str(view.get("reason_code")))
    frame = post("supplier-captcha/frame", {"session_id": view["session_id"]})
    target = Path("/tmp/supplier-captcha-live-frame.jpg")
    target.write_bytes(base64.b64decode(frame["data"]))
    target.chmod(0o600)
    checked = post("supplier-captcha/verify", {"session_id": view["session_id"]})
    assert checked["status"] in {"WAITING", "VERIFIED"}
    verification = root / "manual-live-verification.json"
    verification.write_text(json.dumps(checked, indent=2))
    verification.chmod(0o600)
    resumed = None
    if checked["status"] == "VERIFIED" and checked["retry_ready"]:
        delay = checked["retry_after_seconds"]
        if delay > 35:
            raise RuntimeError("RETRY_WAIT_OUT_OF_BOUND")
        if delay:
            time.sleep(delay + 1)
        resumed = post(
            "eis-supplier-serp/prepare",
            {"request": report.request.model_dump(mode="json"), "refresh": True},
        )
        matched = next(
            a for a in resumed["report"]["batch"]["attempts"] if a["engine"] == engine.value
        )
        assert matched["browser_navigation_count"] == 1
        assert resumed["created"] and resumed["report"]["run_id"] != report.run_id
    result = {
        "status": "LIVE_BROWSER_FRAME_PASS",
        "session": checked,
        "run_id": report.run_id,
        "width": frame["width"],
        "height": frame["height"],
        "frame_bytes": target.stat().st_size,
        "source_requests": saved["source_requests"],
        "human_completion": "NOT_ATTEMPTED",
        "verified_without_human_input": checked["status"] == "VERIFIED",
        "normal_retry": None if resumed is None else {
            "source_acceptance": "PASS" if matched["status"] in {"COMPLETED", "EMPTY"} else "FAIL",
            "run_id": resumed["report"]["run_id"],
            "source_requests": resumed["source_requests"],
            "attempts": [{"engine": a["engine"], "status": a["status"],
                          "reason_code": a["reason_code"], "links": len(a["links"])}
                         for a in resumed["report"]["batch"]["attempts"]],
        },
    }
    (root / "manual-runtime-proof.json").write_text(json.dumps(result, indent=2))
    (root / "manual-runtime-proof.json").chmod(0o600)
    wire = Path("/tmp/supplier-captcha-wire-report.json")
    wire.write_text(json.dumps(resumed or saved))
    wire.chmod(0o600)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
