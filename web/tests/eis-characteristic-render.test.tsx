import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import fixture from "./fixtures/eis-characteristics.json";
import ranges from "./fixtures/eis-characteristic-ranges.json";
import { characteristicReportMatches } from "../src/lib/eis-characteristics";
import { CharacteristicPairReportView } from "../src/app/tender-discovery/characteristic-pair-report";

test("raw Decimal distinctions remain visible with complete technical status UNKNOWN", () => {
  const report: unknown = fixture;
  assert.ok(characteristicReportMatches(report, fixture.request));
  const html = renderToStaticMarkup(createElement(CharacteristicPairReportView, { report }));
  for (const text of ["1.000000000001", "1.000000000002", "Записанные значения различаются",
    "Полная техническая сопоставимость: UNKNOWN", "участие: UNKNOWN", "Прибыль: UNKNOWN",
    "Прибыль", "XML SHA-256", "Инструкция заполнения", "Исходные границы диапазона"]) assert.ok(html.includes(text), text);
  assert.ok(!html.includes("PARTICIPATE"));
});

test("external names and unknown reason keys are escaped without inherited labels", () => {
  const changed = structuredClone(fixture);
  changed.rows[0].name = "<script>alert(1)</script>";
  changed.target.position.characteristics[0].name.value = changed.rows[0].name;
  changed.candidate.position.characteristics[0].name.value = changed.rows[0].name;
  changed.rows[0].reason = "constructor";
  const report: unknown = changed;
  assert.ok(characteristicReportMatches(report, changed.request));
  const html = renderToStaticMarkup(createElement(CharacteristicPairReportView, { report }));
  assert.ok(!html.includes("<script>"));
  assert.ok(html.includes("&lt;script&gt;"));
  assert.ok(html.includes("constructor") && !html.includes("function Object"));
});

test("complete source range is shown as recorded equality with raw endpoints and UNKNOWN eligibility", () => {
  const report: unknown = ranges;
  assert.ok(characteristicReportMatches(report, ranges.request));
  const html = renderToStaticMarkup(createElement(CharacteristicPairReportView, { report }));
  for (const text of ["Записанные значения совпали", "500.0", "greaterOrEqual",
    "Исходная структура границ: сохранена полностью", "Совпадение записанных диапазонов не подтверждает допуск товара",
    "Полная техническая сопоставимость: UNKNOWN", "Прибыль: UNKNOWN", "участие: UNKNOWN"]) assert.ok(html.includes(text), text);
  assert.ok(!html.includes("PARTICIPATE"));
});
