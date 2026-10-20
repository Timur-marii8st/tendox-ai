import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import fixture from "./fixtures/eis-document-review.json";
import { firstReviewCursor, reviewPageMatches } from "../src/lib/eis-document-review";
import { DocumentReviewReport } from "../src/app/tender-discovery/document-review-report";

test("body scope, unknown conclusions and source locators remain visible", () => {
  const report: unknown = fixture;
  assert.ok(reviewPageMatches(report, fixture.request, firstReviewCursor));
  const html = renderToStaticMarkup(createElement(DocumentReviewReport, { report }));
  for (const s of ["Колонтитулы", "Полнота документа и ТЗ: UNKNOWN", "Роль, требования и участие: UNKNOWN", "100000", "16000", "XML SHA-256", "SHA-256", "Длинный блок", "Сохранён весь извлечённый текст тела документа"]) assert.ok(html.includes(s), s);
  assert.ok(!html.includes("PARTICIPATE"));
});
test("untrusted text is escaped and does not become a command or HTML", () => {
  const changed = structuredClone(fixture);
  const unsafe = "<script>alert(1)</script>";
  changed.page.blocks[0].text = unsafe + "x".repeat(16000 - [...unsafe].length);
  const report: unknown = changed;
  assert.ok(reviewPageMatches(report, fixture.request, firstReviewCursor));
  const html = renderToStaticMarkup(createElement(DocumentReviewReport, { report }));
  assert.ok(html.includes("&lt;script&gt;")); assert.ok(!html.includes("<script>"));
});
