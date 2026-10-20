"""Real headed Chrome synthetic UI acceptance; run with Docker --network none."""

from __future__ import annotations

import asyncio
import base64
import json
import traceback
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image

from procurement.sources import supplier_captcha_browser as manual
from procurement.sources import supplier_serp_browser as headed
from procurement.sources.supplier_serp import SearchEngine, build_supplier_query, source_url

QUERY = build_supplier_query("Синтетическая бумага")
URL = source_url(SearchEngine.GOOGLE, QUERY)
HTML = b"""<html><body><button style="position:absolute;left:100px;top:570px;
width:180px;height:40px;background:red"
onclick="document.body.innerHTML='<div id=search><div class=MjjYud>'+
'<a href=https://supplier.ru/paper/><h3>Fixture supplier</h3></a></div></div>'">
Verify you are human</button></body></html>"""


async def main():
    root = Path("/tmp/supplier-captcha-synthetic")
    profile = headed.profile_directory(root, "synthetic-tenant", SearchEngine.GOOGLE)
    headed._private_dir(profile)
    headed._mark(root, profile, SearchEngine.GOOGLE, "BLOCKED", datetime.now(UTC))
    original_prepare = manual._prepare_browser

    async def prepare(browser):
        context, page, cdp = await original_prepare(browser)

        async def fixture(route):
            if route.request.url == URL:
                await route.fulfill(status=200, content_type="text/html", body=HTML)
            else:
                await route.abort()

        # Page routes win over context routes; only synthetic fixture requests can run.
        await page.route("**/*", fixture)
        return context, page, cdp

    manual._prepare_browser = prepare
    original_open = manual._open_manual_browser

    @asynccontextmanager
    async def diagnostic_open(*args):
        try:
            async with original_open(*args) as handle:
                yield handle
        except Exception:
            # This fixture has no credentials or real network. Diagnose only its startup.
            traceback.print_exc()
            raise

    manual._open_manual_browser = diagnostic_open
    manager = manual.CaptchaBrowserManager(root)
    first = await manager.start(
        "synthetic-tenant", "synthetic-actor", SearchEngine.GOOGLE, QUERY, uuid4()
    )
    for _ in range(100):
        view = await manager.status("synthetic-tenant", "synthetic-actor", first.session_id)
        if view.status != "STARTING":
            break
        await asyncio.sleep(0.1)
    assert view.status == "WAITING", view.model_dump(mode="json")
    frame = await manager.frame("synthetic-tenant", "synthetic-actor", first.session_id)
    assert frame.width == 1280 and frame.height == 720
    with Image.open(BytesIO(base64.b64decode(frame.data))) as image:
        red, green, blue = image.getpixel((120, 580))
        assert red > 180 and green < 100 and blue < 100, "SCREEN_COORDINATE_MISMATCH"
    denied = await manager.verify("synthetic-tenant", "synthetic-actor", first.session_id)
    assert denied.status == "WAITING" and denied.reason_code == "ACCESS_BLOCKED"
    await manager.input(
        "synthetic-tenant", "synthetic-actor", first.session_id, manual.ClickInput(x=140, y=590)
    )
    verified = await manager.verify("synthetic-tenant", "synthetic-actor", first.session_id)
    assert verified.status == "VERIFIED", verified.model_dump(mode="json")
    proof = await manager.proof("synthetic-tenant", "synthetic-actor", first.session_id)
    assert proof.attempt.returned_count == 1 and proof.http_status == 200
    with headed._lease(profile / "profile.lock"):
        assert not headed._singleton_lock_present(profile)
    await manager.shutdown()
    print(
        json.dumps(
            {
                "status": "SYNTHETIC_REAL_CHROME_PASS",
                "frame": [1280, 720],
                "blocked_before_click": denied.reason_code,
                "verified_links": proof.attempt.returned_count,
                "dom_sha256": proof.dom_sha256,
                "cleanup": "PASS",
                "external_network": "DISABLED",
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
