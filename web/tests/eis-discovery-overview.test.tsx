import assert from "node:assert/strict";
import test from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { filterResults, ResultExplorer, ResultRow, type ResultEntry } from "../src/app/tender-discovery/result-explorer";

const entries: ResultEntry[] = Array.from({ length: 12 }, (_, i) => ({
  id: String(i), quality: i % 2 ? "PARTIAL" : "STRONG",
  application: i === 0 ? "FAIL" : "UNKNOWN", method: i < 5 ? "Аукцион" : "Котировки",
}));

test("strong word matches retain blocked candidates and never imply admission", () => {
  assert.ok(filterResults(entries, "STRONG", null).some(entry => entry.application === "FAIL"));
  assert.equal(filterResults(entries, "FAIL", null).length, 1);
  assert.equal(filterResults(entries, "UNKNOWN", null).length, 11);
  assert.equal(filterResults(entries, "FAIL", "Котировки").length, 0);
  assert.equal(filterResults(entries, "ALL", null).length, 12);
});

test("overview distinguishes all matches from bounded returned records and paginates only those records", () => {
  const html = renderToStaticMarkup(<ResultExplorer entries={entries} total={790}>
    {visible => <div>{[...visible].map(id => <p key={id}>row-{id}</p>)}</div>}
  </ResultExplorer>);
  for (const text of ["только 12 из 790", "Ещё 778", "полученные записи", "Не подтверждена", "страница 1 из 2", "Аукцион", "Котировки"]) {
    assert.ok(html.includes(text), text);
  }
  assert.ok(html.includes("row-9"));
  assert.ok(!html.includes("row-10"));
  assert.ok(!html.includes("PARTICIPATE"));
});

test("a blocked candidate exposes FAIL in its closed summary with source details still available", () => {
  const html = renderToStaticMarkup(<ResultRow
    title="<script>чужой текст</script>" number="synthetic-1" quality="STRONG" application="FAIL"
    price="1.000000000001 ₽ · НМЦК" deadline={null}>Источник: exact XML locator</ResultRow>);
  const summary = html.split("</summary>")[0];
  for (const text of ["FAIL", "Подача заблокирована", "1.000000000001", "не подтверждён"]) assert.ok(summary.includes(text));
  assert.ok(!html.includes("<script>"));
  assert.ok(html.includes("&lt;script&gt;"));
  assert.ok(html.includes("Источник: exact XML locator"));
  assert.ok(!html.includes(" open="));
});

test("empty returned results do not imply absence in EIS or show a phantom page", () => {
  const html = renderToStaticMarkup(<ResultExplorer entries={[]} total={0}>{() => null}</ResultExplorer>);
  assert.ok(html.includes("не означает отсутствие закупок в ЕИС"));
  assert.ok(!html.includes("Строки 1"));
  assert.ok(!html.includes("NaN"));
});
