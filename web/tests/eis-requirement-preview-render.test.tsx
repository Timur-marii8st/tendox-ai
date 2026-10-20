import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import fixture from "./fixtures/eis-requirement-preview.json";
import { requirementPreviewMatches, validRequirementPreviewRequest } from "../src/lib/eis-requirement-preview";
import { RequirementPreviewReport } from "../src/app/tender-discovery/requirement-preview-report";
const raw:unknown=fixture.request;assert.ok(validRequirementPreviewRequest(raw));const request=raw;
function copy(){const v:unknown=structuredClone(fixture);assert.ok(requirementPreviewMatches(v,request));return v;}
test("saved table labels/unit/instruction and product provenance visible with UNKNOWN",()=>{
  const v=copy(),html=renderToStaticMarkup(createElement(RequirementPreviewReport,{result:v}));
  for(const s of ["Инструкция по заполнению","Опубликовано у товара","UNKNOWN","SHA256","Источник ячейки","Preview SHA256","не исполняемое требование","Пустая или объединённая","Новых записей: 0"])assert.ok(html.includes(s),s);
  assert.ok(!html.includes("PARTICIPATE"));
});
test("raw instructions including negation and script remain literal text",()=>{
  const v=copy(),c=v.table.rows[0].cells[0];c.text="<script>не может изменяться</script>";
  const html=renderToStaticMarkup(createElement(RequirementPreviewReport,{result:v}));assert.ok(html.includes("&lt;script&gt;не может изменяться"));assert.ok(!html.includes("<script>"));
});
test("strict upper bound and unresolved price/grade shown without score",()=>{
  const v=copy();v.table.rows[0].numeric_hints=[{operator:">=",value:"80"},{operator:"<",value:"90"}];
  const html=renderToStaticMarkup(createElement(RequirementPreviewReport,{result:v}));
  for(const s of ["&gt;= 80 и &lt; 90","не приравнивается","Цена партии, прибыль и участие UNKNOWN","Обязательность"])assert.ok(html.includes(s),s);
  assert.ok(!html.includes("soft_score"));
});
