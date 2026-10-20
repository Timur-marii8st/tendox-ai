import assert from "node:assert/strict";
import test from "node:test";
import fixture from "./fixtures/eis-supplier-serp.json";
import { historicalExpandedSerpEngines, serpEngines, supplierSerpMatches, supplierSerpQuery, serpSourceUrl, safeSerpLink, type SavedSupplierSerp, type SearchEngine } from "../src/lib/eis-supplier-serp";
const request = fixture.report.request;
export function v2Fixture(): SavedSupplierSerp {
  const value = structuredClone(fixture) as unknown as SavedSupplierSerp;
  value.report.policy_version = "eis-position-supplier-serp-v2";
  const query = value.report.query!;
  const attempt = (engine: SearchEngine) => ({ engine, query, source_url: serpSourceUrl(engine, query), observed_at: value.report.created_at, status: "BLOCKED" as const, reason_code: "ACCESS_BLOCKED", dom_sha256: null, byte_count: null, links: [], scanned_count: 0, returned_count: 0, truncated: false, elapsed_ms: 1, browser_navigation_count: 1 as const });
  value.report.batch!.attempts = [value.report.batch!.attempts[0], attempt("BRAVE"), attempt("DUCKDUCKGO"), attempt("MOJEEK"), value.report.batch!.attempts[1], value.report.batch!.attempts[2]];
  value.report.attempted_source_requests = 6;
  return value;
}
test("cached and newly captured multi-engine report bind exact position", () => {
  assert.ok(supplierSerpMatches(fixture, request));
  const fresh = { ...fixture, created: true, source_requests: 3 };
  assert.ok(supplierSerpMatches(fresh, request, true)); assert.ok(!supplierSerpMatches(fresh, request));
});
test("full DOM byte count above two MiB is accepted only up to eight MiB", () => {
  const value = structuredClone(fixture);
  value.report.batch.attempts[0].byte_count = 2_404_084;
  assert.ok(supplierSerpMatches(value, request));
  value.report.batch.attempts[0].byte_count = 8_388_608;
  assert.ok(supplierSerpMatches(value, request));
  value.report.batch.attempts[0].byte_count++;
  assert.ok(!supplierSerpMatches(value, request));
});
test("Google and Yandex organic evidence require their own locator prefix", () => {
  for (const [index, prefix] of [[1, 'locator("li.serp-item").nth(0)'], [2, 'locator("#search a:has(h3)").nth(0)']] as const) {
    const value = structuredClone(fixture);
    const old = value.report.batch.attempts[index];
    const completed = structuredClone(value.report.batch.attempts[0]);
    Object.assign(completed, { engine: old.engine, source_url: old.source_url, byte_count: 2_404_084 });
    completed.links[0].locator = prefix;
    value.report.batch.attempts[index] = completed;
    assert.ok(supplierSerpMatches(value, request));
    if (old.engine === "YANDEX") {
      completed.links[0].locator = 'locator("ul[aria-label=\'Результаты поиска\'] > li").nth(0).locator(":scope>div.Organic>div.OrganicTitle[data-initer=OrganicHeader]>a.OrganicTitle-Link").first()';
      assert.ok(supplierSerpMatches(value, request));
      completed.links[0].locator += "x".repeat(257 - completed.links[0].locator.length);
      assert.ok(!supplierSerpMatches(value, request));
    }
    completed.links[0].locator = 'locator("li.b_algo").nth(0)';
    assert.ok(!supplierSerpMatches(value, request));
  }
});
test("foreign position, query and unverified business upgrades rejected", () => {
  const mutations: Array<(v: typeof fixture) => void> = [
    v => { v.report.request.selection.source_index++; }, v => { v.report.query += " private"; },
    v => { v.report.position_name.provenance.document_id = "f".repeat(64); },
    v => { v.report.position_name.provenance.confidence = NaN; },
    v => { v.report.price = "PASS"; }, v => { v.report.participation = "PARTICIPATE"; },
    v => { v.report.batch.attempts[0].links[0].price_status = "PASS"; },
    v => { v.source_requests = 3; }, v => { v.jobs_created = 1; },
  ];
  for (const mutate of mutations) { const v = structuredClone(fixture); mutate(v); assert.ok(!supplierSerpMatches(v, request)); }
});
test("attempt counts, DOM evidence, strict states and engine order rejected on mismatch", () => {
  const mutations: Array<(v: typeof fixture) => void> = [
    v => { v.report.batch.attempts.reverse(); }, v => { v.report.batch.status = "COMPLETED"; },
    v => { v.report.attempted_source_requests = 0; },
    v => { v.report.batch.attempts[0].links[0].dom_sha256 = "f".repeat(64); },
    v => { v.report.batch.attempts[0].returned_count = true as unknown as number; },
    v => { v.report.batch.attempts[0].browser_navigation_count = 0; },
    v => { v.report.batch.attempts[0].source_url += "&q=other"; },
    v => { v.report.source_bundle_byte_count = 0; },
    v => { v.report.batch.attempts[0].links[0].url = "http://127.0.0.1/private"; },
  ];
  for (const mutate of mutations) { const v = structuredClone(fixture); mutate(v); assert.ok(!supplierSerpMatches(v, request)); }
});
test("Python urlencode parity for allowed special characters", () => {
  const query = supplierSerpQuery("Бумага ~ * ' (A4)!"); assert.ok(query);
  assert.equal(serpSourceUrl("BING", query), "https://www.bing.com/search?q=%D0%91%D1%83%D0%BC%D0%B0%D0%B3%D0%B0+~+%2A+%27+%28A4%29%21+%D0%BF%D1%80%D0%BE%D0%B8%D0%B7%D0%B2%D0%BE%D0%B4%D0%B8%D1%82%D0%B5%D0%BB%D1%8C+%D0%BF%D0%BE%D1%81%D1%82%D0%B0%D0%B2%D1%89%D0%B8%D0%BA+%D0%BA%D1%83%D0%BF%D0%B8%D1%82%D1%8C+%D0%BE%D0%BF%D1%82%D0%BE%D0%BC");
  const v = structuredClone(fixture); v.report.position_name.value = "Бумага ~ * ' (A4)!";
  v.report.query = query; v.report.batch.query = query;
  for (const a of v.report.batch.attempts) { a.query = query; a.source_url = serpSourceUrl(a.engine as "BING" | "YANDEX" | "GOOGLE", query); }
  assert.ok(supplierSerpMatches(v, request));
});
test("public query rejects absent, control and overlong names", () => {
  for (const v of [null, undefined, "", "UNKNOWN", "неизвестно", "a\nb", "x".repeat(151)]) assert.equal(supplierSerpQuery(v), null);
  assert.equal(supplierSerpQuery(" Бумага  A4 "), "Бумага A4 производитель поставщик купить оптом");
});
test("v2 binds exact six-engine order, endpoints and policy-specific bounds", () => {
  const value = v2Fixture();
  assert.ok(supplierSerpMatches(value, request));
  assert.deepEqual(value.report.batch!.attempts.map(item => item.engine), ["BING", "BRAVE", "DUCKDUCKGO", "MOJEEK", "YANDEX", "GOOGLE"]);
  assert.equal(value.report.batch!.attempts[1].source_url, serpSourceUrl("BRAVE", value.report.query!));
  assert.equal(value.report.batch!.attempts[2].source_url, serpSourceUrl("DUCKDUCKGO", value.report.query!));
  assert.equal(value.report.batch!.attempts[3].source_url, serpSourceUrl("MOJEEK", value.report.query!));
  value.report.source_bundle_byte_count = 13_631_488; assert.ok(supplierSerpMatches(value, request));
  value.report.source_bundle_byte_count++; assert.ok(!supplierSerpMatches(value, request));
  const legacy = structuredClone(fixture); legacy.report.source_bundle_byte_count = 8_388_609; assert.ok(!supplierSerpMatches(legacy, request));
});
test("active engine policy remains the original three while historical v2 stays readable", () => {
  assert.deepEqual(serpEngines, ["BING", "YANDEX", "GOOGLE"]);
  assert.deepEqual(historicalExpandedSerpEngines, ["BING", "BRAVE", "DUCKDUCKGO", "MOJEEK", "YANDEX", "GOOGLE"]);
  assert.ok(supplierSerpMatches(v2Fixture(), request));
});
test("versions reject mixed engine counts, order, locators and search self-links", () => {
  const v2 = v2Fixture(); v2.report.batch!.attempts.splice(1, 1); assert.ok(!supplierSerpMatches(v2, request));
  const legacy = structuredClone(fixture) as unknown as SavedSupplierSerp; legacy.report.batch!.attempts.splice(1, 0, v2Fixture().report.batch!.attempts[1]); assert.ok(!supplierSerpMatches(legacy, request));
  const locators = [
    [1, 'locator("#results .snippet[data-type=web]").nth(0).locator("a.heading-serpresult")'],
    [2, 'locator(".result.results_links.web-result:not(.result--ad)").nth(0).locator("a.result__a")'],
    [3, 'locator("ul.results-standard > li:not(.ad):not(.sponsored)").nth(0).locator("h2 a")'],
  ] as const;
  for (const [index, locator] of locators) {
    const completed = v2Fixture(), attempt = completed.report.batch!.attempts[index], digest = `${index}`.repeat(64);
    Object.assign(attempt, { status: "COMPLETED", reason_code: "ORGANIC_LINKS_FOUND", dom_sha256: digest, byte_count: 20, scanned_count: 1, returned_count: 1, links: [{ rank: 1, title: "Result", snippet: "", url: `https://supplier${index}.ru/item`, dom_sha256: digest, locator: 'locator("li.b_algo").nth(0)', role_status: "UNKNOWN", price_status: "UNKNOWN", technical_status: "UNKNOWN" }] });
    assert.ok(!supplierSerpMatches(completed, request));
    attempt.links[0].locator = locator; assert.ok(supplierSerpMatches(completed, request));
  }
  const self = v2Fixture(), brave = self.report.batch!.attempts[1], digest = "d".repeat(64);
  Object.assign(brave, { status: "COMPLETED", reason_code: "ORGANIC_LINKS_FOUND", dom_sha256: digest, byte_count: 20, scanned_count: 1, returned_count: 1, links: [{ rank: 1, title: "Result", snippet: "", url: "https://search.brave.com/item", dom_sha256: digest, locator: locators[0][1], role_status: "UNKNOWN", price_status: "UNKNOWN", technical_status: "UNKNOWN" }] });
  assert.ok(!supplierSerpMatches(self, request));
});
test("URLs reject internal, tracking and credentials and preserve public domains", () => {
  for (const v of ["http://127.0.0.1/", "http://2130706433/", "http://[::1]/", "https://a.internal/", "https://a.onion/", "https://a.lan/item", "https://a.example/", "https://yandex.com/", "https://www.bing.com/ck/a", "https://search.brave.com/item", "https://html.duckduckgo.com/item", "https://www.mojeek.com/item", "https://user:pw@supplier.ru/", "https://supplier.ru:8443/", "javascript:alert(1)"]) assert.ok(!safeSerpLink(v), v);
  for (const v of ["https://supplier.ru/item", "https://example.com/", "https://supplier.ru/бумага?тип=офисная"]) assert.ok(safeSerpLink(v), v);
});
