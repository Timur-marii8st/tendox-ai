import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { runInNewContext } from "node:vm";
import ts from "typescript";
import { rowsFromResult } from "../src/lib/tender-workspace";

// Исполняется настоящий server action; подменяется только граница существующего API.
function harness(overrides: Record<string, (...args: unknown[]) => unknown> = {}) {
  const navigationCalls: unknown[] = [];
  const calls: Array<{ name: string; args: unknown[] }> = [];
  const actions = Object.fromEntries([
    "searchIndexed", "searchIndexed223", "loadIndexedSearchPage", "loadIndexed223SearchPage",
  ].map(name => [name, async (...args: unknown[]) => {
    calls.push({ name, args });
    if (overrides[name]) return overrides[name](...args);
    return { result: { query: "бумага", matched: [], matched_count: 0 } };
  }]));
  const source = readFileSync("src/app/tender-discovery/workspace-actions.ts", "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const exported: Record<string, (...args: unknown[]) => Promise<Record<string, unknown>>> = {};
  runInNewContext(compiled.outputText, {
    exports: exported, FormData,
    require: (name: string) => {
      if (name === "@/lib/tender-workspace") return { rowsFromResult };
      if (name === "@/lib/procurement-api") return { ApiError: class extends Error {}, searchGlobalPrice: async (...args: unknown[]) => { calls.push({ name: "searchGlobalPrice", args }); return overrides.searchGlobalPrice?.(...args); }, readTenderNavigation: async (ref: unknown) => { navigationCalls.push(ref); if (overrides.readTenderNavigation) return overrides.readTenderNavigation(ref); throw new Error("no synthetic navigation"); } };
      assert.equal(name, "./actions"); return actions;
    },
  });
  return { calls, navigationCalls, api: exported };
}

test("unified search preserves the successful law when the other fails", async () => {
  const { calls, api } = harness({ searchIndexed223: () => { throw new Error("private transport detail"); } });
  const result = await api.searchWorkspace(" бумага ", "all");
  assert.equal(result.query, "бумага");
  assert.ok(result.result44);
  assert.equal(result.result223, undefined);
  assert.match(String(result.error223), /223-ФЗ/);
  assert.ok(!JSON.stringify(result).includes("private transport detail"));
  assert.equal(calls.length, 2);
  for (const call of calls) {
    const form = call.args[1] as FormData;
    assert.equal(form.get("query"), "бумага");
    assert.equal(form.get("refresh"), null);
    assert.equal(form.get("regions"), null);
  }
});

test("selected law makes only one search and retains explicit API errors", async () => {
  const { calls, api } = harness({ searchIndexed223: () => ({ error: "Индекс недоступен" }) });
  const result = await api.searchWorkspace("бумага", "223");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].name, "searchIndexed223");
  assert.equal(result.error223, "Индекс недоступен");
  assert.equal(result.result44, undefined);
});

test("invalid wire input never reaches the search adapter", async () => {
  const { calls, api } = harness();
  for (const [query, law] of [[null, "44"], [" ", "all"], ["x".repeat(121), "44"], ["бумага", "foreign"]]) {
    const result = await api.searchWorkspace(query, law);
    assert.ok(result.error);
  }
  for (const args of [["бумага", "all", "abc"], ["бумага", "44", "../../secret"], [null, "44", "abc"]]) {
    assert.equal((await api.loadWorkspacePage(...args)).restartRequired, true);
  }
  assert.equal(calls.length, 0);
});

test("continuation preserves law, scope, cursor and expiry refusal", async () => {
  const { calls, api } = harness({ loadIndexedSearchPage: () => ({ error: "Снимок истёк", restartRequired: true }) });
  const result = await api.loadWorkspacePage(" бумага ", "44", "cursor_44");
  assert.equal(result.restartRequired, true);
  assert.equal(result.error44, "Снимок истёк");
  assert.equal(JSON.stringify(calls[0].args), JSON.stringify(["бумага", "NOT_EXPIRED_OR_UNKNOWN", "cursor_44"]));
  await api.loadWorkspacePage("бумага", "223", "cursor_223");
  assert.equal(calls[1].name, "loadIndexed223SearchPage");
  assert.equal(JSON.stringify(calls[1].args), JSON.stringify(["бумага", "cursor_223"]));
});

test("transient page failure stays retryable and does not erase existing rows", async () => {
  const { api } = harness({ loadIndexed223SearchPage: () => { throw new Error("secret"); } });
  const result = await api.loadWorkspacePage("бумага", "223", "cursor");
  assert.ok(result.error223);
  assert.equal(result.restartRequired, undefined);
  assert.equal(result.result223, undefined);
  assert.ok(!JSON.stringify(result).includes("secret"));
});


test("region evidence covers the complete two-law page and remains bounded", async () => {
  const matched = Array.from({ length: 201 }, (_, index) => ({
    purchase_number: String(index + 1).padStart(19, "0"), version_number: 1,
    xml_sha256: "a".repeat(64), deadline: null, application_status: "UNKNOWN",
    reasons: [], lot_items: [], attachments: [], notice_url: "https://example.invalid/notice",
    title: "Synthetic paper", nmck_rub: "100", source_window: "synthetic", source_member: "notice.xml",
  }));
  const { api, navigationCalls } = harness({
    searchIndexed: () => ({ result: { matched } }),
    readTenderNavigation: ref => ({ ...(ref as object), delivery_regions: [] }),
  });
  const result = await api.searchWorkspace("бумага", "44");
  assert.equal(navigationCalls.length, 200);
  assert.equal(Object.keys(result.navigation as object).length, 200);
  assert.equal((navigationCalls[199] as { purchase_number: string }).purchase_number, String(200).padStart(19, "0"));
});


test("global price search sends region before selection and preserves a single mixed-law cursor", async () => {
  const { calls, api } = harness({ searchGlobalPrice: (query, law, region, unknown, cursor) => {
    assert.equal(cursor, "opaque");
    return { query, law, delivery_region: region, include_unknown_region: unknown, result44: { matched: [] }, result223: { matched: [] }, navigation: {}, next_cursor: "next", page_snapshot_sha256: "a".repeat(64), snapshot_at: "2026-10-22T00:00:00Z", matched_count: 410, unknown_region_count: 3 };
  } });
  const result = await api.searchGlobalWorkspace(" бумага ", "all", " Москва ", false, "opaque");
  assert.ok(result.globalPrice); assert.equal(result.error, undefined);
  assert.deepEqual(calls[0].args, ["бумага", "all", "Москва", false, "opaque"]);
});

test("global price response cannot cross region or query and invalid input never calls API", async () => {
  const { calls, api } = harness({ searchGlobalPrice: () => ({ query: "бумага", law: "all", delivery_region: "другой регион", include_unknown_region: false }) });
  assert.equal((await api.searchGlobalWorkspace("бумага", "all", "Москва", false)).restartRequired, true);
  assert.ok((await api.searchGlobalWorkspace("бумага", "all", "x".repeat(201), false)).error);
  assert.ok((await api.searchGlobalWorkspace("бумага", "all", "Москва", false, "bad cursor")).error);
  assert.equal(calls.length, 1);
});
