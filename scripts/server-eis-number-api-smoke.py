"""Check the exact-number API path without exposing server credentials or URLs."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    token = next(
        line.partition("=")[2]
        for line in (root / ".env").read_text().splitlines()
        if line.startswith("EIS_PILOT_TOKEN=")
    )
    number = "0148300000626001036"
    request = Request(
        f"http://127.0.0.1:18000/v1/tender-discovery/eis-live/{number}/verify",
        data=b"",
        headers={"Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=150) as response:
            assert response.headers.get("Cache-Control") == "no-store"
            payload = json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"API_STATUS_{error.code}: {error.read(512).decode()}") from None
    source = payload["source"]
    assert source["purchase_number"] == number
    assert source["coverage"] == "ONE_NUMBER_ONLY"
    if source["status"] == "SYNCED":
        assert source["archive_count"] > 0
        assert source["latest_version_number"] is not None
        assert len(source["latest_xml_sha256"]) == 64
    job = payload["document_job"]
    if job is not None:
        assert job["notice"]["purchase_number"] == number
        assert job["notice"]["notice_xml_sha256"] == source["latest_xml_sha256"]
    print(json.dumps({
        "status": source["status"],
        "coverage": source["coverage"],
        "archive_count": source["archive_count"],
        "new_versions": source["new_versions"],
        "latest_version_number": source["latest_version_number"],
        "document_status": job["download_status"] if job is not None else None,
        "document_queue_reason": payload["document_queue_reason"],
    }))


if __name__ == "__main__":
    main()
