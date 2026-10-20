"""Bounded live pagination evidence via the production parser and shared cooldown."""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from procurement.sources.eis_public import search_public_eis
from procurement.sources.eis_workflow import DiscoveryRequest, DiscoveryRun, _record_search_page


def main() -> None:
    output = (
        Path(os.environ.get("EIS_BROWSER_STATE_DIR", "data/eis-public-browser"))
        / "research"
        / "s133"
        / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    )
    output.mkdir(parents=True, exist_ok=True)
    print(json.dumps({"evidence_directory": str(output)}), flush=True)
    manifest: list[dict[str, object]] = []
    sizes: tuple[Literal[50, 100], ...] = (100, 50)
    for size in sizes:
        run = DiscoveryRun(
            id=f"smoke-{size}",
            company_id="smoke-memory-only",
            request=DiscoveryRequest(query="бумага", search_page_size=size, max_pages=20),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        for page in (1, 2, 20) if size == 100 else (1, 2):
            raw_path = output / f"paper-{size}-{page}.html"

            def save_raw(content: bytes, path: Path = raw_path) -> None:
                path.write_bytes(content)

            for _attempt in range(6):
                started = time.perf_counter()
                result = search_public_eis(
                    "бумага",
                    page_number=page,
                    page_size=size,
                    raw_observer=save_raw,
                )
                if result.status != "COOLDOWN":
                    break
                delay = (
                    max(1.0, (result.retry_at - datetime.now(UTC)).total_seconds())
                    if result.retry_at
                    else 60.0
                )
                print(
                    json.dumps({"status": "COOLDOWN", "wait_seconds": round(delay, 1)}), flush=True
                )
                # Short waits keep operational progress observable.
                remaining = min(delay + 0.2, 61.0)
                while remaining > 0:
                    interval = min(15.0, remaining)
                    time.sleep(interval)
                    remaining -= interval
            item: dict[str, object] = {
                "result": result.model_dump(mode="json", exclude={"leads"}),
                "title_matches": len(result.leads),
                "request_seconds": round(time.perf_counter() - started, 3),
            }
            if result.status == "COMPLETED":
                prior_ids = {
                    number for evidence in run.search_pages for number in evidence.purchase_numbers
                }
                _record_search_page(run, result)
                item.update(
                    {
                        "new_identifiers": len(set(result.purchase_numbers or ()) - prior_ids),
                        "unique_across_checked_pages": run.unique_scanned_count,
                        "duplicate_count": run.duplicate_count,
                        "guard_reason": run.search_stop_reason,
                        "fingerprint": run.search_pages[-1].fingerprint,
                        "saved_raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                    }
                )
            manifest.append(item)
            (output / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                json.dumps(
                    {key: value for key, value in item.items() if key != "result"}
                    | {
                        "size": size,
                        "page": page,
                        "status": result.status,
                        "rows": result.scanned_count,
                        "unparsed": result.unparsed_count,
                        "unidentified": result.unidentified_count,
                        "source_sha256": result.source_sha256,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if result.status != "COMPLETED" or run.search_stop_reason is not None:
                break


if __name__ == "__main__":
    main()
