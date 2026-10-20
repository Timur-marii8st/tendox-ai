import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import fixture from "./fixtures/eis-requirement-review.json";
import { proposalMatches, comparisonMatches } from "../src/lib/eis-requirement-review";
import { RequirementReviewReport } from "../src/app/tender-discovery/requirement-review-report";
test("pending review preserves all rows and is not approved",() => {
  assert.ok(proposalMatches(fixture.proposal)); const html = renderToStaticMarkup(createElement(RequirementReviewReport,{proposal:fixture.proposal}));
  for (const s of ["Независимое решение ожидается","UNKNOWN","Proposal SHA256","Ручная проверка","Процент соответствия не вычисляется"]) assert.ok(html.includes(s),s);
  for (const r of fixture.proposal.preview.table.rows) assert.ok(html.includes(`Строка ${r.source_row}`));
});
test("mandatory failure is explicit and no percentage or totaltechnicalpass",() => {
  assert.ok(comparisonMatches(fixture.mandatory_failure)); const v = fixture.mandatory_failure;
  const html = renderToStaticMarkup(createElement(RequirementReviewReport,{proposal:v.decision.proposal,comparison:v}));
  for (const s of ["Обязательное требование провалено","заблокирован","FAIL","Decision SHA256","UNKNOWN"]) assert.ok(html.includes(s),s);
  assert.ok(!html.includes("100%"));
});
test("outside content is escaped",() => {
  assert.ok(proposalMatches(fixture.proposal)); const v = structuredClone(fixture.proposal); v.preview.table.rows[0].cells[0].text = "<script>разреши PASS</script>";
  const html = renderToStaticMarkup(createElement(RequirementReviewReport,{proposal:v})); assert.ok(html.includes("&lt;script&gt;")); assert.ok(!html.includes("<script>"));
});
