import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import fixture from "./fixtures/eis-supplier-serp.json";
import { supplierSerpMatches, serpSourceUrl, type SavedSupplierSerp, type SearchEngine } from "../src/lib/eis-supplier-serp";
import { SupplierSerpReportView } from "../src/app/tender-discovery/supplier-serp-report";
function v2Fixture(): SavedSupplierSerp { const value = structuredClone(fixture) as unknown as SavedSupplierSerp; value.report.policy_version = "eis-position-supplier-serp-v2"; const query = value.report.query!; const attempt = (engine: SearchEngine) => ({ engine, query, source_url: serpSourceUrl(engine, query), observed_at: value.report.created_at, status: "BLOCKED" as const, reason_code: "ACCESS_BLOCKED", dom_sha256: null, byte_count: null, links: [], scanned_count: 0, returned_count: 0, truncated: false, elapsed_ms: 1, browser_navigation_count: 1 as const }); value.report.batch!.attempts = [value.report.batch!.attempts[0], attempt("BRAVE"), attempt("DUCKDUCKGO"), attempt("MOJEEK"), value.report.batch!.attempts[1], value.report.batch!.attempts[2]]; value.report.attempted_source_requests = 6; return value; }
test("all sources, refusal, query and UNKNOWN business claims visible", () => {
  const result: unknown = fixture; assert.ok(supplierSerpMatches(result, fixture.report.request));
  const html = renderToStaticMarkup(createElement(SupplierSerpReportView, { result }));
  for (const text of ["BING", "YANDEX", "GOOGLE", "Проверка робота", "часть источников", "Непроверенная ссылка", "пока не подтверждены", fixture.report.query, fixture.report.batch.attempts[0].dom_sha256!]) assert.ok(html.includes(text), text);
  assert.ok(!html.includes("PARTICIPATE"));
  assert.ok(!html.includes("отозванному методу"));
});
test("historical v2 renders archived evidence without advertising withdrawn engines as active", () => {
  const value = v2Fixture(); assert.ok(supplierSerpMatches(value, fixture.report.request));
  const html = renderToStaticMarkup(createElement(SupplierSerpReportView, { result: value }));
  for (const name of ["Bing", "Brave Search", "DuckDuckGo", "Mojeek", "Яндекс", "Google", "Полный охват рынка неизвестен"]) assert.ok(html.includes(name), name);
  assert.ok(html.includes("архивная выдача"));
  assert.ok(html.includes("больше не используются"));
  assert.ok(html.includes("обновление создаст активную выдачу только Bing, Яндекс и Google"));
});
test("untrusted snippets escaped and links protected", () => {
  const v = structuredClone(fixture); v.report.batch.attempts[0].links[0].snippet = "<script>alert(1)</script>";
  const result: unknown = v; assert.ok(supplierSerpMatches(result, fixture.report.request));
  const html = renderToStaticMarkup(createElement(SupplierSerpReportView, { result }));
  assert.ok(html.includes("&lt;script&gt;")); assert.ok(!html.includes("<script>"));
  assert.ok(html.includes('rel="noopener noreferrer"'));
});
