import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import fixture from "./fixtures/eis-supplier-product.json";
import { supplierProductMatches, validSupplierProductRequest } from "../src/lib/eis-supplier-product";
import { SupplierProductReportView } from "../src/app/tender-discovery/supplier-product-report";
const raw: unknown = fixture.report.request; assert.ok(validSupplierProductRequest(raw)); const request = raw;
test("public position and product declarations render side by side with gaps", () => {
  const v: unknown = fixture; assert.ok(supplierProductMatches(v, request));
  const html = renderToStaticMarkup(createElement(SupplierProductReportView, { result: v }));
  for (const label of ["Записано заказчиком", "Опубликовано у товара", "UNKNOWN", "Плотность", "За какую единицу", "Новых обращений к сайту: 0", "Минимальный заказ", "стоимость партии", "XML SHA256", "HTML SHA256"]) assert.ok(html.includes(label), label);
  assert.ok(!html.includes("PARTICIPATE")); assert.ok(!html.includes("соответствует"));
});
test("packaging and form control never become inferred price denominator or MOQ", () => {
  const rawResult: unknown = structuredClone(fixture); assert.ok(supplierProductMatches(rawResult, request));
  const v = rawResult; const evidence = { html_sha256: v.report.source_body_sha256, locator: "div.nth(1)" };
  v.report.details.packaging_raw = { ...evidence, value: "5/100" };
  v.report.details.contents_raw = { ...evidence, value: "500 листов" };
  v.report.details.order_controls = [{ ...evidence, attribute: "data-package", raw_value: "5" }];
  assert.ok(supplierProductMatches(v, request));
  const html = renderToStaticMarkup(createElement(SupplierProductReportView, { result: v }));
  for (const label of ["5/100", "500 листов", "data-package", "смысл для заказа не подтверждён", "не определяют единицу цены"]) assert.ok(html.includes(label), label);
});
test("untrusted labels and values render as text", () => {
  const rawResult: unknown = structuredClone(fixture); assert.ok(supplierProductMatches(rawResult, request));
  rawResult.report.details.characteristics[0].value_raw = "<script>alert(1)</script>";
  const html = renderToStaticMarkup(createElement(SupplierProductReportView, { result: rawResult }));
  assert.ok(html.includes("&lt;script&gt;")); assert.ok(!html.includes("<script>"));
});
