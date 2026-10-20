import assert from "node:assert/strict";
import test from "node:test";
import fixture from "./fixtures/eis-supplier-page.json";
import { supplierPageMatches, validSupplierPageRequest, supplierPageRequestKey } from "../src/lib/eis-supplier-page";

const request = fixture.report.request;
assert.ok(validSupplierPageRequest(request));
const baseline: unknown = fixture;
assert.ok(supplierPageMatches(baseline, request));
test("saved priced product binds exact parent and public SERP evidence", () => {
  assert.ok(supplierPageMatches(fixture, request, false, baseline.report.link));
  const fresh = { ...fixture, created: true, source_requests: fixture.report.observation.dispatch_count };
  assert.ok(supplierPageMatches(fresh, request, true)); assert.ok(!supplierPageMatches(fresh, request));
  assert.ok(!supplierPageMatches(fixture, { ...request, rank: request.rank + 1 }));
  assert.notEqual(supplierPageRequestKey(request), supplierPageRequestKey({ ...request, engine: "GOOGLE" }));
});
test("caller URL, tenant, boolean rank and foreign parent are rejected", () => {
  for (const v of [{ ...request, url: "https://supplier.ru/" }, { ...request, company_id: "foreign" },
    { ...request, rank: true }, { ...request, rank: 0 }, { ...request, serp_run_id: "bad" }]) assert.ok(!validSupplierPageRequest(v));
  const foreign = structuredClone(fixture); foreign.report.request.serp_run_id = "00000000-0000-0000-0000-000000000000";
  assert.ok(!supplierPageMatches(foreign, request));
  assert.ok(!supplierPageMatches(fixture, request, false, { ...baseline.report.link, title: "Changed evidence" }));
});
test("supplier-page request preserves historical v2 parent engines", () => {
  for (const engine of ["BING", "BRAVE", "DUCKDUCKGO", "MOJEEK", "YANDEX", "GOOGLE"] as const) assert.ok(validSupplierPageRequest({ ...request, engine }), engine);
});
test("money and raw numeric spelling agree exactly without floating conversion", () => {
  const v = structuredClone(fixture), p = v.report.observation.products[0].prices[0];
  p.amount = "1000.00"; p.raw_amount = "1E+3"; assert.ok(supplierPageMatches(v, request));
  p.amount = "9999999999999999.99"; p.raw_amount = "9999999999999999.99"; assert.ok(supplierPageMatches(v, request));
  p.raw_amount = "9999999999999999.98"; assert.ok(!supplierPageMatches(v, request));
  for (const raw of ["NaN", "Infinity", "1,000", "1000 RUB", "-1000", "0", "1e99999999999999999999"]) {
    p.amount = "1000.00"; p.raw_amount = raw; assert.ok(!supplierPageMatches(v, request), raw);
  }
  for (const amount of ["1000.001", "10000000000000000", "0", "NaN", "1e3"]) {
    p.amount = amount; p.raw_amount = amount; assert.ok(!supplierPageMatches(v, request), amount);
  }
});
test("price evidence and UNKNOWN commercial claims cannot be upgraded", () => {
  const mutations: Array<(v: typeof fixture) => void> = [
    v => { v.report.observation.products[0].prices[0].html_sha256 = "f".repeat(64); },
    v => { v.report.observation.products[0].name!.html_sha256 = "f".repeat(64); },
    v => { v.report.observation.products[0].prices[0].currency = "₽"; },
    v => { v.report.price_comparability = "PASS"; }, v => { v.report.quote = "PASS"; },
    v => { v.report.participation = "PARTICIPATE"; }, v => { v.report.observation.identity_status = "PASS"; },
    v => { v.report.source_body_sha256 = "f".repeat(64); }, v => { v.source_requests = 1; }, v => { v.jobs_created = 1; },
  ];
  for (const mutate of mutations) { const v = structuredClone(fixture); mutate(v); assert.ok(!supplierPageMatches(v, request)); }
});
test("transport hop count, final status and source evidence must agree", () => {
  const mutations: Array<(v: typeof fixture) => void> = [
    v => { v.report.observation.final_url = "https://127.0.0.1/"; },
    v => { v.report.observation.hops[0].url = "https://supplier.lan/"; },
    v => { v.report.observation.final_url = "https://other.ru/"; },
    v => { v.report.observation.dispatch_count = 2; }, v => { v.report.observation.redirect_count = 1; },
    v => { v.report.observation.http_status = 302; }, v => { v.report.observation.reason_code = "TRANSPORT_FAILED"; },
    v => { v.report.observation.products = []; }, v => { v.report.observation.extraction_status = "EMPTY"; },
    v => { v.report.observation.extraction_status = "LIMIT_EXCEEDED"; },
    v => { v.report.observation.byte_count = 2097153; },
  ];
  for (const mutate of mutations) { const v = structuredClone(fixture); mutate(v); assert.ok(!supplierPageMatches(v, request)); }
});
test("durable STARTED is replayable UNKNOWN and never a fresh success", () => {
  const v = { ...fixture, report: { ...fixture.report, status: "STARTED", reason_code: "SOURCE_OUTCOME_UNKNOWN",
    observation: null, attempted_source_requests: null, source_body_sha256: null, source_body_byte_count: null } };
  assert.ok(supplierPageMatches(v, request)); assert.ok(!supplierPageMatches({ ...v, created: true }, request, true));
});
test("unsafe redirect target is retained only as untrusted header text", () => {
  const v = structuredClone(fixture), o = v.report.observation;
  o.status = "UNSAFE_URL"; o.reason_code = "URL_UNSAFE"; o.http_status = 302;
  o.hops[0].http_status = 302; o.hops[0].location = "http://127.0.0.1/private" as unknown as null;
  o.html_sha256 = null as unknown as string; o.byte_count = null as unknown as number;
  o.products = []; o.extraction_status = "NOT_ATTEMPTED"; o.page_kind = "UNKNOWN";
  v.report.source_body_sha256 = null as unknown as string; v.report.source_body_byte_count = null as unknown as number;
  assert.ok(supplierPageMatches(v, request));
});
