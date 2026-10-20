"""Measure one public EIS search page through the production parser."""

from __future__ import annotations

import json
import re
import sys
import time
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

from procurement.sources.eis_public import _NUMBER, _official_url, _parse_html, search_public_eis


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hidden = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else "бумага"
    page_number = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    raw: list[bytes] = []
    start = time.perf_counter()
    result = search_public_eis(query, page_number=page_number, raw_observer=raw.append)
    payload: dict[str, object] = {
        "query": query,
        "status": result.status,
        "reason": result.reason,
        "duration_seconds": round(time.perf_counter() - start, 2),
        "page_number": result.page_number,
        "scanned_cards": result.scanned_count,
        "unparsed_cards": result.unparsed_count,
        "title_matches": len(result.leads),
        "source_result_count_floor": result.source_result_count_floor,
        "source_result_count_exact": result.source_result_count_exact,
        "query_exceeds_page_limit": result.query_exceeds_page_limit,
        "has_more_pages": result.has_more_pages,
        "observed_at": result.observed_at.isoformat(),
        "source_sha256": result.source_sha256,
    }
    if raw:
        html = raw[0].decode("utf-8", errors="replace")
        visible = _VisibleText()
        visible.feed(html)
        text = " ".join(unescape(" ".join(visible.parts)).split())
        payload["pagination_targets"] = sorted({
            int(value) for value in re.findall(r"(?:goToPage\(|pageNumber=)(\d{1,5})", html)
        })[-10:]
        counts = re.findall(r"Результаты поиска\s+(?:более\s+)?[\d\s]+\s+записей", text, re.I)
        payload["result_count_labels"] = [" ".join(label.split()) for label in counts[:3]]
        if result.status == "SOURCE_CHANGED":
            root = _parse_html(raw[0])
            cards = [
                node for node in root.walk()
                if "search-registry-entry-block" in node.classes()
            ]
            payload["raw_card_blocks"] = len(cards)
            payload["missing_card_fields"] = [
                {
                    "index": index,
                    "number_box": node.first("registry-entry__header-mid__number") is not None,
                    "subject_box": node.first("registry-entry__body-value") is not None,
                    "text_start": node.text()[:800],
                    "body_classes": sorted({
                        class_name
                        for child in node.walk()
                        for class_name in child.classes()
                        if "body" in class_name or "purchase" in class_name
                    })[:35],
                }
                for index, node in enumerate(cards, 1)
                if node.first("registry-entry__header-mid__number") is None
                or node.first("registry-entry__body-value") is None
            ][:5]
            payload["first_cards"] = [
                {
                    "number_text": (
                        node.first("registry-entry__header-mid__number") or node
                    ).text()[:90],
                    "method": (node.first("registry-entry__header-top__title") or node).text()[:90],
                    "link_path": next((
                        link.attrs.get("href", "").split("?")[0]
                        for link in node.walk() if link.tag == "a"
                    ), "")[:120],
                    "number_links": [
                        {
                            "text": link.text()[:50],
                            "path": link.attrs.get("href", "").split("?")[0][:120],
                            "number_valid": bool(_NUMBER.fullmatch(re.sub(r"\D", "", link.text()))),
                            "url_allowed": _official_url(link.attrs.get("href", ""), (
                                "/epz/order/notice/", "/223/purchase/public/purchase/info/",
                            )) is not None,
                            "reg_number": parse_qs(urlsplit(link.attrs.get("href", "")).query)
                            .get("regNumber", [None])[0],
                        }
                        for link in (
                            node.first("registry-entry__header-mid__number") or node
                        ).walk()
                        if link.tag == "a"
                    ][:4],
                }
                for node in cards[:3]
            ]
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
