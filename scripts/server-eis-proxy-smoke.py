"""Одна живая загрузка вложения через API; токен и текст не печатаются."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def main() -> None:
    env = (Path(__file__).resolve().parents[1] / ".env").read_text().splitlines()
    token = next(line.partition("=")[2] for line in env if line.startswith("EIS_PILOT_TOKEN="))
    headers = {"Authorization": f"Bearer {token}"}
    base = "http://127.0.0.1:18000/v1/tender-discovery"
    request = Request(
        base + "/eis-index?" + urlencode({"query": "офисная бумага"}), headers=headers
    )
    with urlopen(request, timeout=60) as response:
        search = json.load(response)
    attachment = next(
        item
        for lead in search["matched"]
        for item in lead["attachments"]
        if item["filename"].casefold().endswith(".docx")
    )
    request = Request(
        base + "/eis-attachment",
        data=json.dumps({"url": attachment["url"], "filename": attachment["filename"]}).encode(),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=60) as response:
        result = json.load(response)
    assert result["byte_count"] > 0 and len(result["sha256"]) == 64
    print(json.dumps({key: result[key] for key in ("byte_count", "sha256", "extraction_status")}))


if __name__ == "__main__":
    main()
