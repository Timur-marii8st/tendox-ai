"""Read one official getDocsIP number response; print metadata only."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from playwright.async_api import async_playwright

from procurement.sources.eis_feed_sync import (
    HOST,
    IP_NS,
    SOAP_NS,
    WSDL,
    _BrowserTransport,
    _parsed_post,
    _proxy_server,
    _request,
)


async def main() -> None:
    number = "0148300000626001036"
    token = os.environ["EIS_GETDOCS_IP_TOKEN"]
    request_id = str(uuid4())
    envelope = ET.Element(f"{{{SOAP_NS}}}Envelope")
    header = ET.SubElement(envelope, f"{{{SOAP_NS}}}Header")
    ET.SubElement(header, "individualPerson_token").text = token
    body = ET.SubElement(envelope, f"{{{SOAP_NS}}}Body")
    payload = ET.SubElement(body, f"{{{IP_NS}}}getDocsByReestrNumberRequest")
    index = ET.SubElement(payload, "index")
    ET.SubElement(index, "id").text = request_id
    ET.SubElement(index, "createDateTime").text = datetime.now(UTC).isoformat()
    ET.SubElement(index, "mode").text = "PROD"
    params = ET.SubElement(payload, "selectionParams")
    ET.SubElement(params, "subsystemType").text = "PRIZ"
    ET.SubElement(params, "reestrNumber").text = number
    xml = ET.tostring(envelope, encoding="utf-8", xml_declaration=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True, proxy={"server": _proxy_server()}
        )
        try:
            page = await browser.new_page(accept_downloads=False)
            response = await page.goto(WSDL, wait_until="domcontentloaded", timeout=25_000)
            if response is None or response.status != 200 or not page.url.startswith(f"{HOST}/"):
                raise RuntimeError("SOURCE_WSDL_UNAVAILABLE")
            transport = _BrowserTransport(page)
            initial = await _parsed_post(transport, xml, token)
            if initial.kind != "BY_NUMBER" or initial.request_id != request_id:
                raise RuntimeError("SOURCE_RESPONSE_MISMATCH")
            result: dict[str, object] = {
                "state": initial.state,
                "archive_urls": len(initial.archive_urls),
                "source_response_sha256": initial.source_sha256,
            }
            if initial.state == "LINKS_PENDING":
                prepared = None
                for attempt in range(6):
                    if attempt:
                        await asyncio.sleep(10)
                    reply = await _parsed_post(
                        transport,
                        _request(token, str(uuid4()), original_request_id=request_id),
                        token,
                    )
                    if reply.state == "READY":
                        prepared = reply
                        break
                if prepared is None:
                    result["prepared"] = "NOT_READY"
                else:
                    result["prepared"] = "READY"
                    sizes = []
                    xml_members = []
                    for item in prepared.prepared_archives:
                        status, content = await transport.download(item.url, token)
                        if status != 200:
                            raise RuntimeError("ARCHIVE_DOWNLOAD_FAILED")
                        sizes.append(len(content))
                        with ZipFile(BytesIO(content)) as archive:
                            for member in archive.infolist():
                                if member.filename.lower().endswith(".xml"):
                                    root = ET.fromstring(archive.read(member))
                                    xml_members.extend(
                                        child.tag.rsplit("}", 1)[-1] for child in root
                                    )
                    result["archive_sizes"] = sizes
                    result["xml_element_types"] = sorted(set(xml_members))
                    result["xml_element_count"] = len(xml_members)
            print(json.dumps(result))
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
