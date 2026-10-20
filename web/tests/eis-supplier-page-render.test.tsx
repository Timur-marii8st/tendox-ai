import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import fixture from "./fixtures/eis-supplier-page.json";
import { supplierPageMatches, validSupplierPageRequest } from "../src/lib/eis-supplier-page";
import { SupplierPageReportView } from "../src/app/tender-discovery/supplier-page-report";
const request = fixture.report.request;
assert.ok(validSupplierPageRequest(request));

test("exact price and range stay separate with provenance and commercial gaps", () => {
  const result: unknown = fixture; assert.ok(supplierPageMatches(result, request));
  const html = renderToStaticMarkup(createElement(SupplierPageReportView, { result }));
  for (const label of ["Опубликованная цена", "Нижняя граница цены", "Верхняя граница цены", "562957.00", "540000.00", "610000.00", "RUB", "НДС", "пока не подтверждены", "полная стоимость закупки неизвестны", fixture.report.observation.html_sha256]) assert.ok(html.includes(label), label);
  assert.ok(!html.includes("PARTICIPATE"));
});
test("untrusted declarations and redirect headers are escaped, not navigable", () => {
  const v = structuredClone(fixture); v.report.observation.products[0].name!.value = "<script>alert(1)</script>";
  v.report.observation.hops[0].location = "http://127.0.0.1/private" as unknown as null;
  const result: unknown = v; assert.ok(supplierPageMatches(result, request));
  const html = renderToStaticMarkup(createElement(SupplierPageReportView, { result }));
  assert.ok(html.includes("&lt;script&gt;")); assert.ok(!html.includes("<script>"));
  assert.ok(html.includes("http://127.0.0.1/private")); assert.ok(!html.includes('href="http://127.0.0.1/private"'));
});
test("unfinished attempt renders uncertainty without product prices", () => {
  const v = { ...fixture, report: { ...fixture.report, status: "STARTED", reason_code: "SOURCE_OUTCOME_UNKNOWN",
    observation: null, attempted_source_requests: null, source_body_sha256: null, source_body_byte_count: null } };
  const result: unknown = v; assert.ok(supplierPageMatches(result, request));
  const html = renderToStaticMarkup(createElement(SupplierPageReportView, { result }));
  assert.ok(html.includes("итог ещё не сохранён")); assert.ok(!html.includes("562957.00"));
});
