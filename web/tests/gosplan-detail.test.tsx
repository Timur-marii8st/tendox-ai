import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { GosplanDetailContent } from "../src/app/tender-discovery/gosplan-detail";
import type { GosplanDetail } from "../src/lib/procurement-api";

test("provider links and bounded document list are visible without asserting status", () => {
  const detail: GosplanDetail = { law: "223", number: "32616316174", observed_at: "2026-10-29T10:00:00Z", response_sha256: "a".repeat(64), eis_url: "https://zakupki.gov.ru/223/purchase/public/purchase/info/common-info.html?regNumber=32616316174", eis_url_origin: "NUMBER_DERIVED", platform_url: "https://corp.roseltorg.ru/#notice/822105", documents: [{ name: "ТЗ <проект>.pdf", url: "https://zakupki.gov.ru/223/filestore/public/1.0/download/fz223/file.html?uid=ABCD", source_sha256: "a".repeat(64) }], documents_truncated: true, submission_status: "UNKNOWN" };
  const html = renderToStaticMarkup(createElement(GosplanDetailContent, { detail }));
  for (const phrase of ["ГосПлан", "Найти карточку ЕИС по номеру", "Открыть на площадке", "ТЗ &lt;проект&gt;.pdf", "Показаны первые 50", "noopener noreferrer"]) assert.ok(html.includes(phrase), phrase);
  assert.ok(!html.includes("PARTICIPATE"));
});
