import assert from "node:assert/strict";
import test from "node:test";
import fixture from "./fixtures/eis-supplier-search.json";
import { supplierSearchMatches, validSupplierSearchRequest } from "../src/lib/eis-supplier-search";

const request = fixture.report.request;
test("exact cached report and new bounded capture both validate", () => {
  assert.ok(validSupplierSearchRequest(request)); assert.ok(supplierSearchMatches(fixture, request));
  const fresh = { ...fixture, created: true, source_requests: 1 };
  assert.ok(supplierSearchMatches(fresh, request, true)); assert.ok(!supplierSearchMatches(fresh, request));
});
test("foreign notice/version/index or identity extras are rejected", () => {
  for (const changed of [
    { selection: { ...request.selection, source_index: 2 } },
    { selection: { ...request.selection, notice: { ...request.selection.notice, version_number: 2 } } },
    { selection: { ...request.selection, notice: { ...request.selection.notice, notice_xml_sha256: "f".repeat(64) } } },
    { ...request, company_id: "foreign" },
    { selection: { ...request.selection, source_index: true } },
  ]) assert.ok(!supplierSearchMatches(fixture, changed as unknown as typeof request));
});
test("unsupported monetary/provenance/business claims fail closed", () => {
  const changes: Array<(v: typeof fixture) => void> = [
    v => { v.report.observation.leads[0].published_prices[0].amount_rub = "NaN"; },
    v => { v.report.observation.leads[0].published_prices[0].amount_rub = 100 as unknown as string; },
    v => { v.report.observation.leads[0].published_prices[0].provenance.document_id = "f".repeat(64); },
    v => { v.report.observation.leads[0].product_url = "https://evil.test/"; },
    v => { v.report.observation.matched_count++; },
    v => { v.report.observation.leads[0].published_prices.push(v.report.observation.leads[0].published_prices[0]); },
    v => { v.report.participation = "PASS"; },
    v => { v.report.observation.leads[0].published_prices[0].quote_status = "PASS"; },
    v => { v.report.query = "hpe"; },
    v => { v.source_requests = 1; },
  ];
  for (const change of changes) { const value = structuredClone(fixture); change(value); assert.ok(!supplierSearchMatches(value, request)); }
});
test("failed or interrupted attempts carry no older offers", () => {
  for (const [status, reason, attempted] of [
    ["STARTED", "SOURCE_OUTCOME_UNKNOWN", null], ["SOURCE_ERROR", "CATALOG_UNAVAILABLE_OR_CHANGED", 1],
  ] as const) {
    const value = { ...fixture, report: { ...fixture.report, status, reason_code: reason, attempted_source_requests: attempted, observation: null } };
    assert.ok(supplierSearchMatches(value, request));
    assert.ok(!supplierSearchMatches({ ...value, report: { ...value.report, observation: fixture.report.observation } }, request));
  }
});
