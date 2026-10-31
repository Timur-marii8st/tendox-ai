import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { PositionEvidence223View } from "../src/app/tender-discovery/position-evidence-223";
import type { Eis223PositionProjection } from "../src/lib/procurement-api";

function fixture(): Eis223PositionProjection {
  const provenance = { document_id: "a".repeat(64), locator: "lot[1]/customer[1]", extractor: "api" as const, confidence: 1 };
  const fact = (value: string | null) => ({ value, raw: value, provenance });
  const item = (quantity: string) => ({ description: fact("Масло <сырьё>"), quantity: fact(quantity), unit_name: fact("Условная единица"), unit_code: fact("876"), classification_code: fact("20.30"), classification_name: fact(null), provenance });
  return { law: "223", document_type: "purchaseNoticeZPESMBO", purchase_number: "32616471357", version_number: 2, notice_xml_sha256: "a".repeat(64), source_member: "notice.xml", parser_version: "eis223-joint-positions-v1", source_item_coverage: "PASS", specification_completeness: "UNKNOWN", economics_status: "UNKNOWN", reasons: [], lots: [{ lot_index: 1, ordinal: fact("1"), provenance, customers: ["6290.8", "1140"].map((q, i) => ({ customer_index: i+1, name: fact("Заказчик"), inn: fact(null), kpp: fact(null), iko: fact(null), provenance, items: [item(q)] })) }] };
}

test("two customer scopes stay separate with raw decimal quantities and provenance", () => {
  const html = renderToStaticMarkup(createElement(PositionEvidence223View, { projection: fixture() }));
  for (const value of ["Заказчик 1:", "Заказчик 2:", "6290.8", "1140", "Условная единица", "lot[1]/customer[1]", "a".repeat(64), "Полнота ТЗ и расчёт экономики не подтверждены", "Не подтверждено", "&lt;сырьё&gt;"]) assert.ok(html.includes(value), value);
  assert.ok(!html.includes("7430.8") && !html.includes("PARTICIPATE"));
});

test("missing quantity and incomplete group remain explicit unknown", () => {
  const projection = fixture(); projection.source_item_coverage = "UNKNOWN";
  projection.lots[0].customers[0].items[0].quantity = { value: null, raw: "не определено", provenance: projection.lots[0].provenance };
  projection.lots[0].customers[1].items = [];
  const html = renderToStaticMarkup(createElement(PositionEvidence223View, { projection }));
  for (const value of ["подтверждён частично", "исходное: не определено", "Позиции заказчика не подтверждены"]) assert.ok(html.includes(value));
});

test("false joint flag never labels customer positions as a joint purchase", () => {
  const projection = fixture();
  projection.source_item_coverage = "UNKNOWN";
  projection.reasons = ["JOINT_FLAG_FALSE_WITH_CUSTOMERS"];
  const html = renderToStaticMarkup(createElement(PositionEvidence223View, { projection }));
  assert.ok(html.includes("признак совместной закупки не установлен"));
  assert.ok(html.includes("6290.8"));
  assert.ok(!html.includes("Позиции совместной закупки по заказчикам"));
});

test("large display is bounded and truncation is visible", () => {
  const projection = fixture(); const item = projection.lots[0].customers[0].items[0];
  projection.lots[0].customers[0].items = Array.from({ length: 101 }, (_, i) => ({ ...item, provenance: { ...item.provenance, locator: `item[${i}]` } }));
  const html = renderToStaticMarkup(createElement(PositionEvidence223View, { projection }));
  assert.ok(html.includes("Показаны первые 100")); assert.ok(!html.includes("item[100]"));
  assert.equal(html, renderToStaticMarkup(createElement(PositionEvidence223View, { projection })));
  projection.lots[0].customers = Array.from({ length: 101 }, (_, i) => ({ ...projection.lots[0].customers[1], customer_index: i + 1, items: [] }));
  const groups = renderToStaticMarkup(createElement(PositionEvidence223View, { projection }));
  assert.equal((groups.match(/<h5>/g) ?? []).length, 100);
  assert.ok(groups.includes("Показаны первые 100"));
});


test("ordinary items of a mixed notice remain visible beside both customer groups", () => {
  const html = renderToStaticMarkup(createElement(PositionEvidence223View, {
    projection: fixture(), ordinaryPositions: [{ name: "Обычная позиция другого лота", quantity: "17", unit: "Штука", locator: "lot[2]/lotData/lotItem[1]" }]
  }));
  for (const value of ["6290.8", "1140", "Обычная позиция другого лота", "17", "lot[2]/lotData/lotItem[1]"]) assert.ok(html.includes(value));
});

test("mirrored direct positions are not displayed twice; unrelated lots remain visible", () => {
  const projection = fixture();
  projection.source_item_coverage = "UNKNOWN";
  projection.reasons = ["JOINT_MIRRORED_DIRECT_ITEMS"];
  projection.lots[0].provenance = { ...projection.lots[0].provenance, locator: "p:lots/t:lot[1]" };
  const html = renderToStaticMarkup(createElement(PositionEvidence223View, {
    projection, ordinaryPositions: [
      { name: "Копия общей позиции", quantity: "5", unit: "шт", locator: "p:lots/t:lot[1]/t:lotData/t:lotItems/t:lotItem[1]" },
      { name: "Другой лот", quantity: "6", unit: "шт", locator: "p:lots/t:lot[2]/t:lotData/t:lotItems/t:lotItem[1]" },
    ],
  }));
  assert.ok(html.includes("Заказчик 1:"));
  assert.ok(!html.includes("Копия общей позиции"));
  assert.ok(html.includes("Другой лот"));
  assert.ok(html.includes("подтверждён частично"));
});
