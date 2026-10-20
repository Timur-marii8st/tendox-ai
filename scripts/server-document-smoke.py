"""Verify real indexed manifests and durable planning, without claiming a download."""

import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def main() -> None:
    base = "http://127.0.0.1:18000/v1/tender-discovery"
    env = (Path(__file__).resolve().parents[1] / ".env").read_text()
    token = next(
        line.partition("=")[2] for line in env.splitlines() if line.startswith("EIS_PILOT_TOKEN=")
    )
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    with urlopen(
        Request(base + "/eis-index?" + urlencode({"query": "бумага"}), headers=headers), timeout=60
    ) as response:
        leads = json.load(response)["matched"]
    lead = next(item for item in leads if item["attachments"])
    ref = {
        "purchase_number": lead["purchase_number"],
        "version_number": lead["version_number"],
        "notice_xml_sha256": lead["xml_sha256"],
    }
    results = []
    for _ in range(2):
        with urlopen(
            Request(base + "/eis-document-jobs", json.dumps(ref).encode(), headers), timeout=30
        ) as response:
            results.append(json.load(response))
            assert response.headers.get("Cache-Control") == "no-store"
    assert results[0] == results[1]
    params = urlencode({key: value for key, value in ref.items() if key != "purchase_number"})
    with urlopen(
        Request(base + f"/eis-document-jobs/{ref['purchase_number']}?{params}", headers=headers),
        timeout=30,
    ) as response:
        result = json.load(response)
    assert result == results[0] and result["requested"]
    assert result["source_manifest_coverage"] == result["review_status"] == "UNKNOWN"
    assert result["listed_count"] == len(lead["attachments"])
    print(
        json.dumps(
            {
                "purchase_number": ref["purchase_number"],
                "listed": result["listed_count"],
                "received": result["received_count"],
                "download_status": result["download_status"],
                "review_status": result["review_status"],
                "source_manifest_coverage": result["source_manifest_coverage"],
            }
        )
    )
    selections = []
    for _ in range(2):
        with urlopen(
            Request(
                base + "/eis-document-selection",
                json.dumps({"query": "бумага", "max_candidates": 3}).encode(),
                headers,
            ),
            timeout=30,
        ) as response:
            selections.append(json.load(response))
    assert selections[0]["jobs"] == selections[1]["jobs"]
    result = selections[0]
    assert len(result["jobs"]) + len(result["rejected"]) <= 3
    assert result["selection_kind"] == "PRELIMINARY"
    print(
        json.dumps(
            {
                "selected_jobs": len(result["jobs"]),
                "eligible": result["eligible_count"],
                "rejected": len(result["rejected"]),
            }
        )
    )


if __name__ == "__main__":
    main()
