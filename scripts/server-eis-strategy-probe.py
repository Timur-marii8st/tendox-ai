"""Read-only source strategy checks; public metadata only, shared EIS cooldown."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import time
from collections import Counter
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlencode, urlsplit

from playwright.async_api import async_playwright

from procurement.sources.eis_public import (
    _host_lease,
    _parse_html,
    _public_browser_proxy,
    public_search_url,
)


async def inspect(mode: str, page_number: int, query: str, variant: str, page_size: int) -> None:
    url = {
        "public": public_search_url(query, page_number),
        "robots": "https://zakupki.gov.ru/robots.txt",
        "docs": "https://zakupki.gov.ru/epz/main/public/document/view.html?"
        "searchString=&sectionId=432&strictEqual=false",
    }[mode]
    if mode == "public":
        url = re.sub(r"recordsPerPage=_\d+", f"recordsPerPage=_{page_size}", url)
    if mode == "public" and variant == "full":
        params = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
        params.update(
            {
                "search-filter": "Дате обновления",
                "sortDirection": "false",
                "showLotsInfoHidden": "false",
                "savedSearchSettingsIdHidden": "",
                "placingWayList": "",
                "selectedLaws": "",
                "priceFromGeneral": "",
                "priceFromGWS": "",
                "priceFromUnitGWS": "",
                "priceToGeneral": "",
                "priceToGWS": "",
                "priceToUnitGWS": "",
                "currencyIdGeneral": "-1",
                "currencyCodeGeneral": "",
                "publishDateFrom": "",
                "publishDateTo": "",
                "applSubmissionCloseDateFrom": "",
                "applSubmissionCloseDateTo": "",
                "customerIdOrg": "",
                "customerFz94id": "",
                "customerTitle": "",
                "okpd2Ids": "",
                "okpd2IdsCodes": "",
            }
        )
        url = url.split("?", 1)[0] + "?" + urlencode(params)
    with _host_lease() as retry_at:
        if retry_at:
            print(json.dumps({"status": "COOLDOWN", "retry_at": retry_at.isoformat()}))
            return
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True, timeout=15_000, proxy=_public_browser_proxy()
            )
            try:
                page = await browser.new_page(accept_downloads=False)
                dynamic_requests: list[str] = []
                page.on(
                    "request",
                    lambda request: (
                        dynamic_requests.append(request.url)
                        if request.resource_type in {"fetch", "xhr"}
                        else None
                    ),
                )
                start = time.perf_counter()
                response = await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
                initial = await page.content()
                initial_root = _parse_html(initial.encode())
                initial_numbers = [
                    re.sub(r"\D", "", node.text())
                    for node in initial_root.walk()
                    if "registry-entry__header-mid__number" in node.classes()
                ]
                if mode == "public":
                    await page.wait_for_timeout(3000)
                raw = (
                    await response.body()
                    if mode == "robots" and response
                    else (await page.content()).encode()
                )
                payload: dict[str, object] = {
                    "checked_at": datetime.now(UTC).isoformat(),
                    "mode": mode,
                    "requested_url": url,
                    "final_url": page.url,
                    "http_status": response.status if response else None,
                    "duration_seconds": round(time.perf_counter() - start, 2),
                    "byte_count": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
                if mode == "robots":
                    payload["directives"] = raw.decode("utf-8", errors="replace")[:16000]
                else:
                    root = _parse_html(raw)
                    text = " ".join(root.text().split())
                    if mode == "docs":
                        payload["download_links"] = [
                            {"text": node.text()[:250], "href": node.attrs.get("href")}
                            for node in root.walk()
                            if node.tag == "a" and "downloadDocument" in node.attrs.get("href", "")
                        ][:35]
                        payload["version_mentions"] = re.findall(
                            r".{0,80}(?:16\.3|16\.4|машиночитаем).{0,120}", text
                        )[:15]
                    else:
                        cards = [
                            node
                            for node in root.walk()
                            if "search-registry-entry-block" in node.classes()
                        ]
                        numbers = []
                        stages: Counter[str] = Counter()
                        for card in cards:
                            number = card.first("registry-entry__header-mid__number")
                            stage = card.first("registry-entry__header-mid__title")
                            if number:
                                numbers.append(re.sub(r"\D", "", number.text()))
                            stages[stage.text() if stage else "UNKNOWN"] += 1
                        payload.update(
                            {
                                "card_count": len(cards),
                                "numbers": numbers,
                                "unique_numbers": len(set(numbers)),
                                "changed_after_three_seconds": initial_numbers != numbers,
                                "dynamic_requests": dynamic_requests[:10],
                                "subject_samples": [
                                    (card.first("registry-entry__body-value") or card).text()[:200]
                                    for card in cards[:3]
                                ],
                                "number_set_sha256": hashlib.sha256(
                                    "\n".join(sorted(set(numbers))).encode()
                                ).hexdigest(),
                                "stages": dict(stages),
                                "effective_filter_inputs": [
                                    {
                                        "name": node.attrs.get("name"),
                                        "id": node.attrs.get("id"),
                                        "value": node.attrs.get("value"),
                                        "checked": "checked" in node.attrs,
                                    }
                                    for node in root.walk()
                                    if node.tag == "input"
                                    and (node.attrs.get("name") or node.attrs.get("id"))
                                    in {
                                        "searchString",
                                        "fz44",
                                        "fz223",
                                        "af",
                                        "ca",
                                        "pc",
                                        "pa",
                                        "pageNumber",
                                        "recordsPerPage",
                                    }
                                ],
                                "pagination_markers": [
                                    {
                                        "tag": node.tag,
                                        "class": node.attrs.get("class"),
                                        "text": node.text()[:80],
                                    }
                                    for node in root.walk()
                                    if any("page" in part.casefold() for part in node.classes())
                                    and len(node.text()) < 80
                                ][:35],
                                "result_count_label": re.findall(
                                    r"Результаты поиска\s+(?:более\s+)?[\d\s]+\s+записей", text
                                )[:2],
                                "page_size_values": sorted(
                                    set(re.findall(r"recordsPerPage[=\s'\"]+(_\d+)", raw.decode()))
                                ),
                                "requested_page": parse_qs(urlsplit(url).query)["pageNumber"][0],
                                "pagination_links": [
                                    {
                                        "text": node.text()[:30],
                                        "href": node.attrs.get("href"),
                                        "onclick": node.attrs.get("onclick"),
                                    }
                                    for node in root.walk()
                                    if node.tag == "a" and "page__link" in node.classes()
                                ][:10],
                                "script_sources": [
                                    node.attrs["src"]
                                    for node in root.walk()
                                    if node.tag == "script" and "src" in node.attrs
                                ][-12:],
                                "go_to_page_code": re.findall(
                                    r"function\s+goToPage\b.{0,1500}", raw.decode(), re.S
                                )[:1],
                            }
                        )
                print(json.dumps(payload, ensure_ascii=False))
            finally:
                await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("public", "robots", "docs"))
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--query", default="бумага")
    parser.add_argument("--variant", choices=("minimal", "full"), default="minimal")
    parser.add_argument("--page-size", type=int, choices=(50, 100, 200), default=200)
    args = parser.parse_args()
    asyncio.run(inspect(args.mode, args.page, args.query, args.variant, args.page_size))
