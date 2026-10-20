import assert from "node:assert/strict";
import test from "node:test";
import fixture from "./fixtures/eis-supplier-catalog.json";
import { validSupplierCatalogRequest, supplierCatalogMatches, supplierCatalogRequestKey, type SavedSupplierCatalog, type SupplierCatalogRequest } from "../src/lib/eis-supplier-catalog";
import { searchFixture } from "./supplier-catalog-fixture";
const rawRequest: unknown = fixture.report.request;
assert.ok(validSupplierCatalogRequest(rawRequest));
const request: SupplierCatalogRequest = rawRequest;
const baseline: unknown = fixture;
assert.ok(supplierCatalogMatches(baseline, request));
test("saved search binds confirmed form, exact public name and filtered product ordinal", () => {
  const v = searchFixture(); assert.ok(supplierCatalogMatches(v, v.report.request));
  assert.ok(supplierCatalogMatches({ ...v, created: true, source_requests: 1 }, v.report.request, true));
  assert.equal(supplierCatalogMatches(v, request), false);
  assert.notEqual(supplierCatalogRequestKey(v.report.request), supplierCatalogRequestKey(request));
});
test("caller cannot inject URL/query/tenant or half a parent selection", () => {
  for (const v of [{ ...request, url: "https://evil.ru" }, { ...request, query: "other" }, { ...request, company_id: "other" },
    { ...request, search_run_id: null }, { ...request, product_index: null }, { ...request, product_index: true }, { ...request, product_index: 11 }]) assert.ok(!validSupplierCatalogRequest(v));
});
test("product replay requires exact saved selected link and source count", () => {
  const v: unknown = fixture; assert.ok(supplierCatalogMatches(v, request, false, baseline.report.selected_link!));
  assert.ok(!supplierCatalogMatches(v, request, false, { ...baseline.report.selected_link!, title: "Changed" }));
  assert.ok(!supplierCatalogMatches({ ...fixture, created: true, source_requests: 1 }, request));
  assert.ok(!supplierCatalogMatches({ ...fixture, source_requests: 1 }, request));
});
test("observed relative product href and fragment normalize against actual search URL", () => {
  const v = searchFixture(); v.report.links!.links[0].raw_href = "../товар/paper#details";
  assert.ok(supplierCatalogMatches(v, v.report.request));
  v.report.links!.links[0].raw_href = "товар/paper";
  assert.equal(supplierCatalogMatches(v, v.report.request), false);
});
test("SEARCH failure with retained CAPTCHA body has no navigable product links", () => {
  const v = searchFixture(); v.report.observation!.status = "BLOCKED"; v.report.observation!.reason_code = "ACCESS_BLOCKED";
  v.report.observation!.extraction_status = "NOT_ATTEMPTED";
  assert.equal(supplierCatalogMatches(v, v.report.request), false);
  v.report.links = null; assert.ok(supplierCatalogMatches(v, v.report.request));
});
test("unsafe link or foreign evidence cannot be accepted as a catalog candidate", () => {
  const mutations: Array<(v: SavedSupplierCatalog) => void> = [
    v => { v.report.links!.links[0].url = "https://other.ru/товар/paper"; },
    v => { v.report.links!.links[0].raw_href = "http://127.0.0.1/"; },
    v => { v.report.links!.links[0].html_sha256 = "a".repeat(64); },
    v => { v.report.links!.links[0].index = 2; },
    v => { v.report.links!.source_url = "https://bumaga-s.ru/other"; },
    v => { v.report.search_spec!.search_url += "&secret=x"; },
    v => { v.report.search_spec!.query = "other"; },
  ];
  for (const mutate of mutations) { const v = searchFixture(); mutate(v); assert.equal(supplierCatalogMatches(v, v.report.request), false); }
});
test("price remains exact declaration with UNKNOWN commercial eligibility", () => {
  for (const field of ["quote", "technical", "participation", "price_comparability"] as const) {
    const v = structuredClone(fixture); v.report[field] = "PASS"; assert.equal(supplierCatalogMatches(v, request), false);
  }
  const v = structuredClone(fixture); v.report.observation.products[0].prices[0].raw_amount = "299.7";
  assert.equal(supplierCatalogMatches(v, request), false);
});
test("durable STARTED replay keeps form evidence and no invented result", () => {
  const v = searchFixture(); Object.assign(v.report, { status: "STARTED", reason_code: "SOURCE_OUTCOME_UNKNOWN", observation: null, links: null,
    attempted_source_requests: null, source_body_sha256: null, source_body_byte_count: null });
  assert.ok(supplierCatalogMatches(v, v.report.request));
});
