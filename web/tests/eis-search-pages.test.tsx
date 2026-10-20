import assert from "node:assert/strict";
import test from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { mergeSearchPage, PagedResults } from "../src/app/tender-discovery/paged-results";

const row = (id: string) => ({ id, price: "9007199254740993.01", application_status: "FAIL" });
const first = {
  query: "бумага", matched_count: 3, matched: [row("1")], next_cursor: "next-1",
  page_snapshot_sha256: "a".repeat(64), snapshot_at: "2026-10-07T05:00:00Z",
};
const second = { ...first, matched: [row("2"), row("3")], next_cursor: null as string | null };
const identity = (item: typeof first.matched[number]) => item.id;

test("continuation appends ordered rows without losing exact money or FAIL", () => {
  const result = mergeSearchPage(first, second, identity);
  assert.deepEqual(result.matched.map(identity), ["1", "2", "3"]);
  assert.equal(result.matched[2].price, "9007199254740993.01");
  assert.equal(result.matched[2].application_status, "FAIL");
  assert.equal(result.next_cursor, null);
  assert.equal(first.matched.length, 1);
});

test("changed provenance, query, clock, counts, duplicates and stalled pages cannot mix", () => {
  for (const changed of [
    { ...second, page_snapshot_sha256: "b".repeat(64) },
    { ...second, snapshot_at: "2026-10-07T05:00:01Z" },
    { ...second, query: "картон" }, { ...second, matched_count: 4 },
    { ...second, matched: [row("1")] }, { ...second, matched: [] },
    { ...second, matched: [row("2"), row("3"), row("4")] },
    { ...second, next_cursor: "next-1" },
  ]) assert.throws(() => mergeSearchPage(first, changed, identity), /SEARCH_PAGE_CHANGED/);
});

test("a continuation button states loaded subset and frozen clock, then disappears on exhaustion", () => {
  const render = (initial: typeof second) => renderToStaticMarkup(<PagedResults
    initial={initial} loadPage={async () => ({ result: second })} identity={identity}>
    {(result, canLoad) => <p>{result.matched.length} / {String(canLoad)}</p>}
  </PagedResults>);
  const partial = render(first);
  assert.ok(partial.includes("Получено 1 из 3"));
  assert.ok(partial.includes("Загрузить следующие совпадения"));
  assert.ok(partial.includes("Продолжение доступно 15 минут"));
  const complete = render(mergeSearchPage(first, second, identity));
  assert.ok(complete.includes("3 / false"));
  assert.ok(!complete.includes("Загрузить следующие совпадения"));
});
