"""Verify the live read-only bridge against saved official XML and native analysis."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _read(url: str, token: str) -> dict:
    with urlopen(
        Request(url, headers={"Authorization": f"Bearer {token}"}), timeout=45
    ) as response:
        assert response.headers.get("Cache-Control") == "no-store"
        return json.load(response)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    token = next(
        line.partition("=")[2]
        for line in (root / ".env").read_text().splitlines()
        if line.startswith("EIS_PILOT_TOKEN=")
    )
    base = "http://127.0.0.1:18000/v1/tender-discovery"
    search = _read(base + "/eis-index?" + urlencode({"query": "бумага"}), token)
    lead = next(row for row in search["matched"] if row["purchase_number"] == "0148300000626001036")
    ref = {"version_number": lead["version_number"], "notice_xml_sha256": lead["xml_sha256"]}
    path = base + f"/eis-document-jobs/{lead['purchase_number']}"
    bridge = _read(path + "/evidence?" + urlencode(ref), token)
    assert bridge["notice"]["notice_xml_sha256"] == lead["xml_sha256"]
    assert bridge["collection"]["notice"] == bridge["notice"]
    assert bridge["collection"]["received_count"] == bridge["collection"]["listed_count"]
    assert bridge["collection"]["review_status"] == "UNKNOWN"
    assert bridge["requirement_status"] == bridge["completeness_status"] == "UNKNOWN"
    assert bridge["economic_status"] in {"UNKNOWN", "BLOCKED"}
    assert "SUPPLIER_QUOTE_MISSING" in bridge["economic_missing"]
    if bridge["nmck_rub"] is not None:
        assert bridge["nmck_provenance"]["document_id"] == lead["xml_sha256"]
        assert bridge["nmck_rub"] == lead["nmck_rub"]
    files = {item["content_uid"]: item for item in bridge["collection"]["documents"]}
    linked = 0
    for document in bridge["documents"]:
        assert document["role_status"] == "UNKNOWN"
        uid = document["content_uid"]
        if not document["conditions"]:
            continue
        assert files[uid]["fetch_status"] == "RECEIVED"
        analysis = _read(path + f"/{uid}/analysis?" + urlencode(ref), token)
        for condition in document["conditions"]:
            assert any(
                snippet["kind"] == condition["kind"]
                and snippet["provenance"] == condition["provenance"]
                and snippet["text"].startswith(condition["excerpt"])
                for snippet in analysis["snippets"]
            )
            linked += 1
    assert linked > 0
    replay = _read(path + "/evidence?" + urlencode(ref), token)
    assert bridge["documents"] == replay["documents"]
    print(
        json.dumps(
            {
                "purchase_number": lead["purchase_number"],
                "listed": bridge["collection"]["listed_count"],
                "received": bridge["collection"]["received_count"],
                "linked_conditions": linked,
                "application_status": bridge["application_status"],
                "economic_status": bridge["economic_status"],
                "requirement_status": bridge["requirement_status"],
                "completeness_status": bridge["completeness_status"],
            }
        )
    )


if __name__ == "__main__":
    main()
