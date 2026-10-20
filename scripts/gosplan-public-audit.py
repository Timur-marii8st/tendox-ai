"""Ограниченный read-only аудит публичных документов и test API ГосПлана."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import httpx

DOC_URLS = {
    "home": "https://gosplan.info/",
    "docs": "https://gosplan.info/docs/",
    "purchases": "https://gosplan.info/docs/guides/purchases/",
    "schemas": "https://gosplan.info/docs/guides/howto-xsd/",
    "contracts": "https://gosplan.info/docs/guides/contracts/",
    "planning": "https://gosplan.info/docs/guides/planning/",
    "periods": "https://gosplan.info/docs/guides/data-periods/",
    "history": "https://gosplan.info/docs/guides/history-data/",
    "nsi": "https://gosplan.info/docs/dictionaries/nsi/",
    "regions": "https://gosplan.info/docs/dictionaries/regions-kladr/",
    "errors": "https://gosplan.info/docs/errors/troubleshooting/",
    "api-key": "https://gosplan.info/docs/getting-started/api-key/",
    "pricing": "https://gosplan.info/pricing/",
    "faq": "https://gosplan.info/docs/faq/",
    "legal": "https://gosplan.info/legal/api-usage/",
    "roadmap": "https://gosplan.info/roadmap/",
    "swagger-ui": "https://swagger.gosplan.info/",
    "spec44": "https://swagger.gosplan.info/fz44/swagger.yaml",
    "spec223": "https://swagger.gosplan.info/fz223/swagger.yaml",
}


class PublicText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.skip += 1
        elif tag in {"p", "h1", "h2", "h3", "li", "tr", "pre"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def fetch(
    client: httpx.Client, output: Path, name: str, url: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        response = client.get(url, params=params)
    except httpx.HTTPError as error:
        record = {
            "name": name,
            "observed_at": datetime.now(UTC).isoformat(),
            "requested_url": str(httpx.Request("GET", url, params=params).url),
            "status": None,
            "seconds": round(time.perf_counter() - start, 3),
            "error_type": type(error).__name__,
        }
        with (output / "manifest.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(json.dumps(record, ensure_ascii=False), flush=True)
        return record
    raw = response.content
    if len(raw) > 5 * 1024 * 1024:
        raise ValueError("PUBLIC_AUDIT_RESPONSE_TOO_LARGE")
    suffix = ".json" if "json" in response.headers.get("content-type", "") else ".txt"
    (output / f"{name}.raw{suffix}").write_bytes(raw)
    if "html" in response.headers.get("content-type", ""):
        parser = PublicText()
        parser.feed(response.text)
        lines = [" ".join(line.split()) for line in " ".join(parser.parts).splitlines()]
        (output / f"{name}.text.txt").write_text("\n".join(lines), encoding="utf-8")
    record = {
        "name": name,
        "observed_at": datetime.now(UTC).isoformat(),
        "requested_url": str(response.request.url),
        "final_url": str(response.url),
        "status": response.status_code,
        "seconds": round(time.perf_counter() - start, 3),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "headers": {
            key: value
            for key, value in response.headers.items()
            if key
            in {"content-type", "cache-control", "etag", "last-modified", "retry-after", "server"}
        },
    }
    with (output / "manifest.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps(record, ensure_ascii=False), flush=True)
    return record


def run(mode: str, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        if mode == "docs":
            for name, url in DOC_URLS.items():
                record = fetch(client, output, name, url)
                if record["status"] in {None, 401, 403, 429}:
                    break
                time.sleep(2)
            return
        now = datetime.now(UTC)
        scope = {"published_after": "2024-10-01T00:00:00+03:00"}
        if mode == "timeline":
            last_file = output / "last-api-request.txt"
            previous = float(last_file.read_text()) if last_file.exists() else 0
            time.sleep(max(0, previous + 15 - time.time()))
            last_file.write_text(str(time.time()))
            record = fetch(
                client,
                output,
                "completed-list",
                "https://v2test.gosplan.info/fz44/purchases",
                {**scope, "stage": 3, "limit": 1, "sort": "updated_at_desc"},
            )
            if record["status"] != 200:
                return
            rows = json.loads((output / "completed-list.raw.json").read_text(encoding="utf-8"))
            if not rows:
                return
            number = str(rows[0]["purchase_number"])
            if not number.isdecimal() or len(number) != 19:
                raise ValueError("PUBLIC_AUDIT_NUMBER_INVALID")
            time.sleep(max(0, float(last_file.read_text()) + 15 - time.time()))
            last_file.write_text(str(time.time()))
            fetch(
                client,
                output,
                "completed44",
                f"https://v2test.gosplan.info/fz44/purchases/{number}",
            )
            return
        cases: list[tuple[str, str, dict[str, Any]]] = [
            (
                "active44",
                "/fz44/purchases",
                {
                    **scope,
                    "object_info": "бумага",
                    "stage": 1,
                    "limit": 3,
                    "collecting_finished_after": now.isoformat(),
                },
            ),
            ("known44", "/fz44/purchases/0848300054826000154", {}),
            ("notice44", "/fz44/purchases/0848300054826000154/notification", {}),
            (
                "expired_stage1",
                "/fz44/purchases",
                {
                    **scope,
                    "stage": 1,
                    "limit": 3,
                    "collecting_finished_before": now.isoformat(),
                },
            ),
            ("known223", "/fz223/purchases/32616426034", {}),
            (
                "updated44",
                "/fz44/purchases",
                {**scope, "updated_after": (now - timedelta(days=1)).isoformat(), "limit": 3},
            ),
        ]
        last_file = output / "last-api-request.txt"
        for name, path, params in cases:
            previous = float(last_file.read_text()) if last_file.exists() else 0
            time.sleep(max(0, previous + 15 - time.time()))
            last_file.write_text(str(time.time()))
            record = fetch(client, output, name, "https://v2test.gosplan.info" + path, params)
            if record["status"] in {None, 401, 403, 429}:
                print("PUBLIC_AUDIT_STOPPED_ON_ACCESS_OR_RATE_LIMIT", flush=True)
                break


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("docs", "api", "timeline"))
    parser.add_argument("--output", type=Path, default=Path("data/research/gosplan-2026-10-01"))
    args = parser.parse_args()
    run(args.mode, args.output)
