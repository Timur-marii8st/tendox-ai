import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import fixture from "./fixtures/eis-position-association.json";
import type { SavedAssociation, AssociationListResult } from "../src/lib/eis-position-association";
import { PositionAssociationReportView } from "../src/app/tender-discovery/position-association-report";
import { PositionAssociationListView } from "../src/app/tender-discovery/position-association-list";
test("operator link displays exact source context and preserves admission UNKNOWN", () => {
  const result = fixture as SavedAssociation;
  const html = renderToStaticMarkup(createElement(PositionAssociationReportView, { result }));
  for (const label of ["Фрагменты связаны оператором", "Требования ещё не нормализованы", "участие: UNKNOWN",
    result.report.analysis_sha256, result.report.document_sha256, ...result.report.fragments.map(f => f.text)]) assert.ok(html.includes(label));
  assert.ok(!html.includes("PARTICIPATE"));
});

test("saved metadata offers explicit individual choice without selecting latest or claiming requirements", () => {
  const r = (fixture as SavedAssociation).report;
  const result: AssociationListResult = { request: { scope: { position: r.request.position, document: r.request.document,
    analyzer_version: r.request.analyzer_version }, cursor: null, limit: 1 }, items: [{ association_id: r.association_id,
    created_at: r.created_at, linked_by: "<img src=x>", fragment_count: r.fragments.length, selected_characters: r.selected_characters }],
    next_cursor: { created_at: r.created_at, association_id: r.association_id }, source_requests: 0, jobs_created: 0, writes: 0 };
  const html = renderToStaticMarkup(createElement(PositionAssociationListView, { result, onOpen: () => {}, onNext: () => {} }));
  for (const label of ["Повторное выделение строк не требуется", "Открыть эту связь", "Следующая страница", r.association_id,
    "UNKNOWN", "0 записей", "&lt;img src=x&gt;"]) assert.ok(html.includes(label));
  assert.ok(!html.includes("<img src=x>")); assert.ok(!html.includes(r.fragments[0].text)); assert.ok(!html.includes("PARTICIPATE"));
  const empty = renderToStaticMarkup(createElement(PositionAssociationListView, { result: { ...result, items: [], next_cursor: null }, onOpen: () => {}, onNext: () => {} }));
  assert.ok(empty.includes("сохранённых связей на этой странице нет")); assert.ok(!empty.includes("Открыть эту связь"));
});
test("source text and actor HTML are escaped", () => {
  const result = structuredClone(fixture) as SavedAssociation;
  result.report.fragments[0].text = "<script>alert(1)</script>"; result.report.linked_by = "<img src=x>";
  const html = renderToStaticMarkup(createElement(PositionAssociationReportView, { result }));
  assert.ok(html.includes("&lt;script&gt;")); assert.ok(!html.includes("<script>")); assert.ok(!html.includes("<img src=x>"));
});
