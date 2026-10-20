import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import fixture from "./fixtures/eis-supplier-catalog.json";
import { supplierCatalogMatches, validSupplierCatalogRequest } from "../src/lib/eis-supplier-catalog";
import { SupplierCatalogReportView } from "../src/app/tender-discovery/supplier-catalog-report";
import { searchFixture } from "./supplier-catalog-fixture";
test("search displays bounded candidates and coverage uncertainty", () => {
  const v = searchFixture(); assert.ok(supplierCatalogMatches(v, v.report.request));
  const html = renderToStaticMarkup(createElement(SupplierCatalogReportView, { result: v }));
  for (const label of ["Бумага для офисной техники", "Бумага SvetoCopy Eco", "полный охват неизвестен", "Порядок ссылок", "HTML SHA256"]) assert.ok(html.includes(label), label);
  assert.ok(!html.includes("299.6"));
});
test("actual decimal declaration renders with commercial gaps and no eligibility", () => {
  const request = fixture.report.request; assert.ok(validSupplierCatalogRequest(request));
  const v: unknown = fixture; assert.ok(supplierCatalogMatches(v, request));
  const html = renderToStaticMarkup(createElement(SupplierCatalogReportView, { result: v }));
  for (const label of ["299.6", "RUB", "НДС", "полное КП", "полная стоимость закупки неизвестны"]) assert.ok(html.includes(label), label);
  assert.ok(!html.includes("PARTICIPATE"));
});
test("supplier label is escaped and failed source has no product controls", () => {
  const v = searchFixture(); v.report.links!.links[0].title = "<script>attack</script>";
  let html = renderToStaticMarkup(createElement(SupplierCatalogReportView, { result: v }));
  assert.ok(html.includes("&lt;script&gt;")); assert.ok(!html.includes("<script>"));
  v.report.links = null; v.report.observation!.status = "BLOCKED";
  html = renderToStaticMarkup(createElement(SupplierCatalogReportView, { result: v, renderProduct: () => createElement("button", null, "read") }));
  assert.ok(html.includes("BLOCKED")); assert.ok(!html.includes("<button"));
});
