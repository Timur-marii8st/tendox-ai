"""Check the private server's indexed EIS search without exposing credentials."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _secret(name: str) -> str:
    for line in (Path(__file__).resolve().parents[1] / ".env").read_text().splitlines():
        if line.startswith(f"{name}="):
            return line.partition("=")[2]
    raise RuntimeError(f"Missing {name}")


def main() -> None:
    base = "http://127.0.0.1:18000/v1/tender-discovery/eis-index"
    try:
        urlopen(base + "?" + urlencode({"query": "бумага"}), timeout=10)
    except HTTPError as error:
        assert error.code == 401, f"Unauthenticated request: {error.code}"
    else:
        raise AssertionError("Unauthenticated search unexpectedly succeeded")

    token = _secret("EIS_PILOT_TOKEN")
    quotation_seen = False
    for query in ("серверное оборудование", "бумага"):
        request = Request(
            base + "?" + urlencode({"query": query}),
            headers={"Authorization": f"Bearer {token}"},
        )
        with urlopen(request, timeout=60) as response:
            result = json.load(response)
            assert response.headers.get("Cache-Control") == "no-store"
        assert result["inspected_current_notices"] >= 1462, result
        assert result["indexed_windows"] >= 9, result
        assert result["corpus_coverage"] == "UNKNOWN", result
        assert result["source_freshness"] == "UNKNOWN", result
        assert result["unindexed_versions"] == 0, result
        assert result["matched_count"] == result["evaluated_candidate_notices"], result
        assert 0 <= result["pending_windows"] <= result["planned_windows"]
        assert result["planned_windows"] - result["pending_windows"] <= result["indexed_windows"]
        for lead in result["matched"]:
            assert lead["economic_status"] == "UNKNOWN"
            assert lead["application_status"] in ("FAIL", "UNKNOWN")
            if lead["document_type"] == "epNotificationEZK2020":
                quotation_seen = True
                assert "/zk20/" in lead["notice_url"]
                assert "epNotificationEZK2020" in lead["match_locator"]
            else:
                assert lead["document_type"] == "epNotificationEF2020"
                assert "/ea20/" in lead["notice_url"]
        print(
            json.dumps(
                {
                    "query": query,
                    "inspected_current_notices": result["inspected_current_notices"],
                    "indexed_windows": result["indexed_windows"],
                    "matched_count": result["matched_count"],
                    "corpus_coverage": result["corpus_coverage"],
                    "planned_windows": result["planned_windows"],
                    "pending_windows": result["pending_windows"],
                    "requested_region_codes": result["requested_region_codes"],
                    "evaluated_candidate_notices": result["evaluated_candidate_notices"],
                    "search_elapsed_ms": result["search_elapsed_ms"],
                    "latest_source_publication": result["latest_source_publication"],
                    "source_freshness": result["source_freshness"],
                },
                ensure_ascii=False,
            )
        )
    assert quotation_seen, "Quotation type missing from both pilot searches"


if __name__ == "__main__":
    main()
