import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import fixture from "./fixtures/procurement-comparison.json";
import { commandValid, reportMatches, rub } from "../src/lib/procurement-comparison";
import { ComparisonReportView } from "../src/app/procurement-comparison/report";

const command = { profile_ref: fixture.profile_ref, case_refs: fixture.rows.map(row => row.case_ref) };
const companyId = fixture.company_id;
const matches = (value: unknown, input = command, tenant = companyId): boolean => reportMatches(value, input, tenant);

test("report renders confirmed conditions, missing facts, sources and explicit forecast basis", () => {
  const report: unknown = fixture;
  assert.ok(reportMatches(report, command, fixture.company_id));
  const html = renderToStaticMarkup(createElement(ComparisonReportView, { report }));
  for (const phrase of ["Сравнительная таблица", "FAIL · несоответствие", "UNKNOWN · нужны сведения",
    "PASS · проверенное условие", "Нужно уточнить:", "НМЦК без НДС", "RUB", "Прибыль не рассчитана",
    "Частичная проверка не означает полный допуск", "Обязательный FAIL блокирует", "SHA-256",
    "Прочие налоги в расходах", "Допущения", "Источники", "Синтетическая ручная проверка",
    "Реальный API профиля", "audit отсутствует"]) assert.ok(html.includes(phrase), phrase);
  assert.ok(!html.includes("PARTICIPATE") && !html.includes("Наиболее прибыльн") && !html.includes("соответствие: 100%"));
});

test("fixed profile, tenant and case hashes must match selection", () => {
  assert.ok(matches(fixture));
  assert.ok(!matches(fixture, command, "other-company"));
  assert.ok(!matches(fixture, { ...command, profile_ref: { ...command.profile_ref, version: 2 } }));
  const refs = structuredClone(command.case_refs); refs[0].input_sha256 = "0".repeat(64);
  assert.ok(!matches(fixture, { ...command, case_refs: refs }));
});

test("hard fail cannot become a PASS report and UNKNOWN cannot hide its missing facts", () => {
  const report = structuredClone(fixture); report.rows[1].overall_status = "PASS";
  assert.ok(!reportMatches(report, command, fixture.company_id));
  const missing = structuredClone(fixture); missing.rows[0].checks[0].missing = [];
  assert.ok(!reportMatches(missing, command, fixture.company_id));
  const numeric = structuredClone(fixture) as unknown as Record<string, unknown>;
  (numeric.rows as { nmck_ex_vat: unknown }[])[0].nmck_ex_vat = 1500000;
  assert.ok(!reportMatches(numeric, command, fixture.company_id));
});

test("selection requires 2 to 5 distinct cases and Decimal formatting preserves digits", () => {
  assert.ok(commandValid(command));
  assert.ok(!commandValid({ ...command, case_refs: command.case_refs.slice(0, 1) }));
  assert.ok(!commandValid({ ...command, case_refs: [...command.case_refs, command.case_refs[0]] }));
  assert.equal(rub("12345678901234567890.00000001"), "12\u00a0345\u00a0678\u00a0901\u00a0234\u00a0567\u00a0890,00000001 ₽");
  assert.equal(rub("NaN"), "UNKNOWN");
});

test("external text is escaped in table and evidence", () => {
  const report: unknown = { ...fixture, profile_name: "<script>alert(1)</script>" };
  assert.ok(reportMatches(report, command, fixture.company_id));
  const html = renderToStaticMarkup(createElement(ComparisonReportView, { report }));
  assert.ok(!html.includes("<script>"));
  assert.ok(html.includes("&lt;script&gt;"));
});


test("saved report requires tenant-scoped profile sources and honest persistence limits", () => {
  const report = structuredClone(fixture) as unknown as import("../src/lib/procurement-comparison").ComparisonReport;
  report.persistence = "EPHEMERAL";
  assert.equal(matches(report), false);
  for (const row of report.rows) for (const check of row.checks) for (const source of check.profile_sources) source.company_id = companyId;
  assert.equal(matches(report), true);
  const html = renderToStaticMarkup(createElement(ComparisonReportView, { report }));
  assert.ok(html.includes("Прочитаны сохранённые версии профиля и кейсов"));
  assert.ok(!html.includes("Использованы статические синтетические"));
  report.rows[0].checks.find(check => check.profile_sources.length)!.profile_sources[0].company_id = "foreign";
  assert.equal(matches(report), false);
});
