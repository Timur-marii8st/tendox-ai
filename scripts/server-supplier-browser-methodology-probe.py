"""One controlled headed Chrome/CDP probe; no production DB or personal profile."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from playwright.async_api import async_playwright

QUERY = "Бумага A4 производитель поставщик купить оптом"
URLS = {
    "bing": "https://www.bing.com/search?" + urlencode({"q": QUERY}),
    "google": "https://www.google.com/search?" + urlencode({"q": QUERY}),
    "yandex": "https://yandex.ru/search/?" + urlencode({"text": QUERY}),
    "market": "https://market.yandex.ru/search?"
    + urlencode({"text": "Бумага A4 80 г/м2 500 листов"}),
}


async def probe(engine: str, root: Path, filtered: bool) -> None:
    profile = root / "profiles" / engine
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_path = profile / "probe-state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    if state.get("blocked_until", 0) > time.time():
        print(json.dumps({"engine": engine, "status": "COOLDOWN"}), flush=True)
        return
    run = root / "reports" / (engine + "-" + uuid4().hex)
    run.mkdir(parents=True, mode=0o700)
    chrome = display = None
    report = {"engine": engine, "requested_url": URLS[engine], "filtered": filtered}
    with (profile / "probe.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            async with asyncio.timeout(50), async_playwright() as p:
                display = subprocess.Popen(
                    ["Xvfb", "-displayfd", "1", "-screen", "0", "1365x900x24", "-nolisten", "tcp"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                number = await asyncio.to_thread(display.stdout.readline)
                if not number.strip().isdigit():
                    raise RuntimeError("DISPLAY_UNAVAILABLE")
                env = dict(os.environ, DISPLAY=":" + number.strip())
                port_file = profile / "DevToolsActivePort"
                port_file.unlink(missing_ok=True)
                # Same container sandbox setting as its existing Playwright launch.
                chrome = subprocess.Popen(
                    [
                        p.chromium.executable_path,
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--user-data-dir=" + str(profile),
                        "--remote-debugging-address=127.0.0.1",
                        "--remote-debugging-port=0",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--window-size=1365,900",
                        "about:blank",
                    ],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                for _ in range(100):
                    if port_file.exists() and chrome.poll() is None:
                        lines = port_file.read_text().splitlines()
                        if lines and lines[0].isdigit():
                            break
                    if chrome.poll() is not None:
                        raise RuntimeError("CHROME_EXITED")
                    await asyncio.sleep(0.1)
                else:
                    raise RuntimeError("CDP_UNAVAILABLE")
                browser = await p.chromium.connect_over_cdp("http://127.0.0.1:" + lines[0])
                context = browser.contexts[0]
                page = context.pages[0]
                if filtered:
                    from procurement.sources.supplier_serp import SearchEngine, request_allowed

                    selected = SearchEngine(engine.upper())

                    async def route_request(route):
                        request = route.request
                        allowed = request_allowed(
                            selected,
                            QUERY,
                            request.url,
                            request.resource_type,
                            navigation=request.is_navigation_request(),
                            main_frame=request.frame == page.main_frame,
                        )
                        await (route.continue_() if allowed else route.abort())

                    await context.route("**/*", route_request)
                remaining = 15 - (time.time() - state.get("last_request_at", 0))
                if remaining > 0:
                    await asyncio.sleep(remaining)
                state["last_request_at"] = time.time()
                state_path.write_text(json.dumps(state))
                response = await page.goto(
                    URLS[engine], wait_until="domcontentloaded", timeout=25000
                )
                await page.wait_for_timeout(2500)
                body = await page.locator("body").inner_text(timeout=3000)
                content = (await page.content()).encode()
                http_status = response.status if response else None
                blocked = (
                    http_status in {403, 429}
                    or any(
                        marker in body.lower()
                        for marker in (
                            "unusual traffic",
                            "подтвердите, что вы не робот",
                            "докажите, что вы не робот",
                        )
                    )
                    or "/sorry" in page.url
                    or "showcaptcha" in page.url
                )
                if blocked:
                    state["blocked_until"] = time.time() + 1800
                    state_path.write_text(json.dumps(state))
                report.update(
                    observed_at=datetime.now(UTC).isoformat(),
                    browser_version=browser.version,
                    mode="ordinary headed Chrome/Xvfb + CDP attachment, persistent task profile",
                    final_url=page.url,
                    title=await page.title(),
                    http_status=http_status,
                    status="BLOCKED" if blocked else "OBSERVED",
                    dom_sha256=hashlib.sha256(content).hexdigest(),
                    dom_bytes=len(content),
                    result_headings=await page.locator("h3").all_text_contents(),
                    market_snippets=await page.locator('[data-zone-name="productSnippet"]').count(),
                )
                if engine != "market":
                    from procurement.sources.supplier_serp import SearchEngine, parse_supplier_serp

                    attempt = parse_supplier_serp(
                        SearchEngine(engine.upper()),
                        QUERY,
                        content,
                        final_url=page.url,
                        observed_at=datetime.now(UTC),
                        http_status=http_status or 0,
                    )
                    report["parsed_attempt"] = attempt.model_dump(mode="json")
                if len(content) <= 2 * 1024**2:
                    (run / "capture.html").write_bytes(content)
                await page.screenshot(path=str(run / "capture.png"))
                await browser.close()
        except Exception as error:
            report.update(status="PROBE_ERROR", error_type=type(error).__name__)
        finally:
            for process in (chrome, display):
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
            (run / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(
                json.dumps({**report, "report_path": str(run / "report.json")}, ensure_ascii=True),
                flush=True,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("engine", choices=tuple(URLS))
    parser.add_argument("--root", type=Path, default=Path("/tmp/supplier-methodology-20261006"))
    parser.add_argument("--filtered", action="store_true")
    args = parser.parse_args()
    if args.filtered and args.engine == "market":
        parser.error("filtered proof applies to SERP only")
    asyncio.run(probe(args.engine, args.root.resolve(), args.filtered))
