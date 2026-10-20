import assert from "node:assert/strict";
import test from "node:test";
import fixture from "./fixtures/eis-supplier-product.json";
import { validSupplierProductRequest, supplierProductMatches, supplierProductRequestKey } from "../src/lib/eis-supplier-product";
const rawRequest: unknown = fixture.report.request; assert.ok(validSupplierProductRequest(rawRequest));
const request = rawRequest;
test("exact retained product can be derived and replayed without HTTP", () => {
  assert.ok(supplierProductMatches(fixture, request));
  assert.ok(supplierProductMatches({ ...fixture, created: true }, request, true));
  assert.equal(supplierProductMatches({ ...fixture, created: true }, request), false);
  assert.notEqual(supplierProductRequestKey(request), supplierProductRequestKey({ ...request, product_run_id: "66666666-6666-4666-8666-666666666666" }));
});
test("caller URL/HTML/tenant, SEARCH parent and boolean index are rejected", () => {
  for (const v of [{ ...request, url: "https://other.ru/" }, { ...request, html: "unsafe" }, { ...request, company_id: "other" },
    { ...request, catalog: { ...request.catalog, search_run_id: null, product_index: null } },
    { ...request, catalog: { ...request.catalog, product_index: true } }]) assert.equal(validSupplierProductRequest(v), false);
});
test("parent HTML and position provenance cannot be substituted", () => {
  for (const mutate of [
    (v: typeof fixture) => { v.report.details.characteristics[0].html_sha256 = "f".repeat(64); },
    (v: typeof fixture) => { v.report.position.position.quantity.provenance.document_id = "f".repeat(64); },
    (v: typeof fixture) => { v.report.details.source_url = "http://127.0.0.1/"; },
    (v: typeof fixture) => { v.report.source_body_sha256 = "f".repeat(64); },
  ]) { const v = structuredClone(fixture); mutate(v); assert.equal(supplierProductMatches(v, request), false); }
  assert.equal(supplierProductMatches(fixture, request, false, { source_url: fixture.report.details.source_url, html_sha256: "f".repeat(64) }), false);
});
test("UNKNOWN cannot turn into match, unit cost, party total or participation", () => {
  for (const key of ["technical", "price_comparability", "unit_cost", "party_total", "quote", "profit", "participation", "specification_completeness"] as const) {
    const v = structuredClone(fixture); v.report[key] = "PASS"; assert.equal(supplierProductMatches(v, request), false);
  }
  const v = structuredClone(fixture); v.report.rows[0].observation = "PASS";
  assert.equal(supplierProductMatches(v, request), false);
});
test("row references must cover the exact public characteristics and valid supplier indices", () => {
  for (const mutate of [
    (v: typeof fixture) => { v.report.rows[0].supplier_indices = [2]; },
    (v: typeof fixture) => { v.report.rows[0].supplier_indices = [1, 1]; },
    (v: typeof fixture) => { v.report.rows[0].characteristic_index = 2; },
    (v: typeof fixture) => { v.report.rows = []; v.report.row_count = 0; },
  ]) { const v = structuredClone(fixture); mutate(v); assert.equal(supplierProductMatches(v, request), false); }
});
test("ambiguous supplier data clears summaries while retaining bounded conflict evidence", () => {
  const v = structuredClone(fixture); v.report.details.status = "AMBIGUOUS";
  assert.equal(supplierProductMatches(v, request), false);
  v.report.details.product_name = null as unknown as typeof v.report.details.product_name;
  assert.ok(supplierProductMatches(v, request));
});
test("field associations cannot point to an unrelated supplier field or omit a duplicate", () => {
  const v = structuredClone(fixture);
  v.report.details.characteristics.push({ ...v.report.details.characteristics[0], label_raw: "Формат", value_raw: "А4" });
  v.report.rows[0].supplier_indices = [2];
  assert.equal(supplierProductMatches(v, request), false);
  v.report.details.characteristics[1].label_raw = "Плотность бумаги";
  v.report.rows[0].supplier_indices = [1];
  assert.equal(supplierProductMatches(v, request), false);
});
