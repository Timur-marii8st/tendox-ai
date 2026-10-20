import assert from "node:assert/strict";
import test from "node:test";
import fixture from "./fixtures/eis-requirement-preview.json";
import { requirementPreviewMatches, validRequirementPreviewRequest } from "../src/lib/eis-requirement-preview";
const raw: unknown = fixture.request; assert.ok(validRequirementPreviewRequest(raw)); const request = raw;
function copy() { const v: unknown = structuredClone(fixture); assert.ok(requirementPreviewMatches(v,request)); return v; }
test("exact saved DOCX table and product preview accepts source0/write0", () => {
  assert.ok(requirementPreviewMatches(fixture,request,{run_id:fixture.product.run_id,source_url:fixture.product.details.source_url,html_sha256:fixture.product.details.html_sha256}));
});
test("caller URL/tenant/raw rows and mismatched notice or boolean table rejected", () => {
  for (const extra of [{url:"http://localhost"},{company_id:"other"},{rows:[]},{mandatory:true},{table_index:true}]) assert.equal(validRequirementPreviewRequest({...request,...extra}),false);
  assert.equal(validRequirementPreviewRequest({...request,document:{...request.document,notice:{...request.document.notice,version_number:2}}}),false);
});
test("product identity and source bindings reject substitutions", () => {
  const v = copy(); v.product.request.product_run_id="00000000-0000-0000-0000-000000000000"; assert.equal(requirementPreviewMatches(v,request),false);
  const w = copy(); w.table.document_sha256="a".repeat(64); assert.equal(requirementPreviewMatches(w,request),false);
  assert.equal(requirementPreviewMatches(fixture,request,{run_id:"00000000-0000-0000-0000-000000000000",source_url:fixture.product.details.source_url,html_sha256:fixture.product.details.html_sha256}),false);
});
test("review/mandatory/technical and preview cannot become approved or write", () => {
  for (const field of ["technical","participation","approved_requirement_status","document_role","full_tspec_completeness"]) assert.equal(requirementPreviewMatches({...fixture,[field]:"PASS"},request),false);
  for (const field of ["source_requests","jobs_created","database_writes"]) assert.equal(requirementPreviewMatches({...fixture,[field]:1},request),false);
  const v=copy(); v.table.rows[0].mandatory_status="PASS" as "UNKNOWN"; assert.equal(requirementPreviewMatches(v,request),false);
});
test("missing cells and instructions remain absence, cannot be invented", () => {
  const v=copy(); v.table.rows[0].absent_columns=[]; assert.equal(requirementPreviewMatches(v,request),false);
  const w=copy(); w.table.rows[0].absent_columns_status="EMPTY" as "NO_RETAINED_TEXT"; assert.equal(requirementPreviewMatches(w,request),false);
});
test("cell coordinate/digest/count/header and nested topology cannot be changed", () => {
  for (const mutation of [(v:ReturnType<typeof copy>) => {v.table.rows[0].cells[0].provenance.locator="table 1 row 2 cell 1 nested table 1";},(v:ReturnType<typeof copy>) => {v.table.total_characters++;},(v:ReturnType<typeof copy>) => {v.table.header[0].text="Тип товара";},(v:ReturnType<typeof copy>) => {v.table.rows[0].cells[0].block_index=0;}]) { const v=copy();mutation(v);assert.equal(requirementPreviewMatches(v,request),false); }
});
test("open upper bound remains < and never becomes inclusive BETWEEN", () => {
  const v=copy(), cell=v.table.rows[0].cells.find(c=>c.column===3)!;
  v.table.total_characters-=cell.source_char_count;cell.text="≥ 80 и < 90";cell.source_char_count=[...cell.text].length;v.table.total_characters+=cell.source_char_count;
  v.table.rows[0].numeric_hints=[{operator:">=",value:"80"},{operator:"<",value:"90"}];assert.ok(requirementPreviewMatches(v,request));
  v.table.rows[0].numeric_hints[1].operator="<=";assert.equal(requirementPreviewMatches(v,request),false);
});
test("text grade and tolerance do not become numeric hints", () => {
  for (const value of ["не ниже С","Сэ","C","80±3",">=80 И <90",">=80и<90",">=80 кроме случаев"]){const v=copy(),c=v.table.rows[0].cells.find(c=>c.column===3)!;v.table.total_characters-=c.source_char_count;c.text=value;c.source_char_count=[...value].length;v.table.total_characters+=c.source_char_count;v.table.rows[0].numeric_hints=[];assert.ok(requirementPreviewMatches(v,request),value);}
});
test("Decimal string normalization retains precision and signed zero", () => {
  for(const [raw,value] of [[">=+000.50","0.50"],["<=-0,00","-0.00"]]){const v=copy(),c=v.table.rows[0].cells.find(c=>c.column===3)!;v.table.total_characters-=c.source_char_count;c.text=raw;c.source_char_count=raw.length;v.table.total_characters+=c.source_char_count;v.table.rows[0].numeric_hints=[{operator:raw.startsWith(">=")?">=":"<=",value}];assert.ok(requirementPreviewMatches(v,request));}
});
