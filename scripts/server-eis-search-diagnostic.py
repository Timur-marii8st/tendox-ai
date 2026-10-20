"""Inspect one browser search response while honoring the shared EIS cooldown."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sys
import time
from datetime import UTC, datetime
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

from procurement.sources.eis_public import (
    EisPublicError,
    _host_lease,
    _parse_html,
    _public_browser_proxy,
    parse_public_search,
    public_search_url,
)


async def inspect(query: str, page_number: int, page_size: int) -> None:
    if not 10 <= page_size <= 5000:
        raise ValueError("page_size must be between 10 and 5000")
    if page_number == 21:
        url = public_search_url(query, 20).replace("pageNumber=20", "pageNumber=21")
    else:
        url = public_search_url(query, page_number)
    url = re.sub(r"recordsPerPage=_\d+", f"recordsPerPage=_{page_size}", url)
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
                start = time.perf_counter()
                response = await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
                content = await page.content()
                duration = round(time.perf_counter() - start, 2)
                root = _parse_html(content.encode())
                raw_cards = sum(
                    "search-registry-entry-block" in node.classes()
                    for node in root.walk()
                )
                page_size_controls = [
                    {
                        "attrs": node.attrs,
                        "options": [
                            {"value": option.attrs.get("value"), "text": option.text()[:40]}
                            for option in node.walk()
                            if option.tag == "option"
                        ][:20],
                    }
                    for node in root.walk()
                    if node.tag == "select"
                    and "recordsPerPage" in str(node.attrs)
                ][:3]
                final = urlsplit(page.url)
                try:
                    parsed = parse_public_search(content.encode(), query, url, datetime.now(UTC))
                    parse_status = "COMPLETED"
                    card_count = parsed.scanned_count
                    match_count = len(parsed.leads)
                except EisPublicError as error:
                    parse_status = str(error)
                    card_count = None
                    match_count = None
                print(json.dumps({
                    "observed_at": datetime.now(UTC).isoformat(),
                    "requested_page_size": page_size,
                    "duration_seconds": duration,
                    "response_status": response.status if response is not None else None,
                    "same_url": page.url == url,
                    "final_host": final.hostname,
                    "final_path": final.path,
                    "content_bytes": len(content.encode()),
                    "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
                    "title": (await page.title())[:120],
                    "blocked_marker": any(word in content.casefold() for word in (
                        "подтвердите, что вы не робот", "verify you are human",
                        "доступ временно ограничен",
                    )),
                    "parse_status": parse_status,
                    "scanned_cards": card_count,
                    "title_matches": match_count,
                    "raw_card_blocks": raw_cards,
                    "page_size_controls": page_size_controls,
                }, ensure_ascii=False))
            finally:
                await browser.close()


if __name__ == "__main__":
    asyncio.run(inspect(
        sys.argv[1] if len(sys.argv) > 1 else "бумага",
        int(sys.argv[2]) if len(sys.argv) > 2 else 1,
        int(sys.argv[3]) if len(sys.argv) > 3 else 50,
    ))
