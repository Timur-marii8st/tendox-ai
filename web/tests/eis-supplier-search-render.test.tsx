import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import fixture from "./fixtures/eis-supplier-search.json";
import { supplierSearchMatches } from "../src/lib/eis-supplier-search";
import { SupplierSearchReportView } from "../src/app/tender-discovery/supplier-search-report";

test("category scope, source hashes and different price scopes are visible", () => {
  const result: unknown = fixture;
  assert.ok(supplierSearchMatches(result, fixture.report.request));
  const html = renderToStaticMarkup(createElement(SupplierSearchReportView, { result }));
  for (const value of ["Цена базовой комплектации", "платёж в месяц", "Полнота рынка: UNKNOWN", "полным КП", "100000", "500", fixture.report.observation.source_sha256, "цена могла измениться"]) assert.ok(html.includes(value), value);
  assert.ok(!html.includes("PARTICIPATE"));
});
test("untrusted supplier names remain escaped text", () => {
  const changed = structuredClone(fixture); changed.report.observation.leads[0].product_name = "<script>alert(1)</script>";
  const result: unknown = changed;
  assert.ok(supplierSearchMatches(result, fixture.report.request));
  const html = renderToStaticMarkup(createElement(SupplierSearchReportView, { result }));
  assert.ok(html.includes("&lt;script&gt;")); assert.ok(!html.includes("<script>"));
});
