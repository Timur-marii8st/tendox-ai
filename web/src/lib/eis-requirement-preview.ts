import { validSupplierProductRequest, supplierProductMatches, supplierProductRequestKey, type SupplierProductRequest, type SupplierProductReport } from "./eis-supplier-product";
import { validReviewRequest, reviewRequestKey, type ReviewRequest } from "./eis-document-review";
import { sameProtocolRef } from "./eis-protocols";
import type { SourceProvenance } from "./eis-characteristics";
export type RequirementPreviewRequest = { product: SupplierProductRequest; document: ReviewRequest; table_index: number };
export type RequirementTableCell = { source_row: number; column: number; text: string; block_index: number; source_char_count: number; provenance: SourceProvenance };
export type NumericHint = { operator: ">=" | "<=" | ">" | "<" | "=="; value: string };
export type RequirementTableRow = { source_row: number; kind: "CONTEXT_ONLY" | "CHARACTERISTIC" | "MANUAL_REVIEW_REQUIRED"; cells: RequirementTableCell[]; absent_columns: number[]; absent_columns_status: "NO_RETAINED_TEXT"; numeric_hints: NumericHint[]; unit_raw: string | null; mandatory_status: "UNKNOWN"; approved_status: "UNKNOWN" };
export type EISRequirementTable = { revision: "eis-native-requirement-table-v1"; document_sha256: string; table_index: number; header: RequirementTableCell[]; rows: RequirementTableRow[]; row_count: number; cell_count: number; total_characters: number; table_structure_status: "UNKNOWN"; native_text_completeness: "UNKNOWN"; approved_requirements: "UNKNOWN"; mandatory_status: "UNKNOWN" };
export type RequirementPreview = { policy_version: "eis-requirement-preview-v1"; scope: "SELECTED_RETAINED_DOCX_TABLE"; request: RequirementPreviewRequest; product: SupplierProductReport; product_report_sha256: string; analysis_sha256: string; document_observation_id: string; observed_at: string; analyzed_at: string; filename: string; table: EISRequirementTable; preview_sha256: string; approved_requirement_status: "UNKNOWN"; document_role: "UNKNOWN"; position_association: "UNKNOWN"; full_tspec_completeness: "UNKNOWN"; technical: "UNKNOWN"; participation: "UNKNOWN"; source_requests: 0; jobs_created: 0; database_writes: 0 };
export type RequirementPreviewState = { result?: RequirementPreview; error?: string };
const rec = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const keys = (v: Record<string, unknown>, names: string) => { const a = names.split(" "); return Object.keys(v).length === a.length && a.every(k => Object.hasOwn(v, k)); };
const text = (v: unknown, max: number): v is string => typeof v === "string" && v.length > 0 && [...v].length <= max;
const int = (v: unknown, min: number, max: number): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max;
const sha = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
const time = (v: unknown) => typeof v === "string" && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
const clean = (v: string) => v.trim().replace(/\s+/g, " ");
const headers = ["Наименование характеристики", "Тип характеристики (количественная/качественная)", "Значение характеристики", "Единица измерения характеристики", "Инструкция по заполнению характеристик"].map(clean);
export function validRequirementPreviewRequest(v: unknown): v is RequirementPreviewRequest {
  return rec(v) && keys(v, "product document table_index") && validSupplierProductRequest(v.product) && validReviewRequest(v.document) && int(v.table_index, 1, 100) && sameProtocolRef(v.document.notice, v.product.catalog.page.position.selection.notice);
}
export function requirementPreviewRequestKey(v: RequirementPreviewRequest): string { return `${supplierProductRequestKey(v.product)}:${reviewRequestKey(v.document)}:${v.table_index}`; }
function numericHints(value: string | undefined): NumericHint[] {
  if (!value) return [];
  const expression = /^\s*(>=|<=|==|≥|≤|>|<|=)\s*([+-]?\d{1,18}(?:[.,]\d{1,8})?)(?:\s+и\s+(>=|<=|==|≥|≤|>|<|=)\s*([+-]?\d{1,18}(?:[.,]\d{1,8})?))?\s*$/.exec(value);
  if (!expression) return [];
  const op = (s: string) => ({ "≥": ">=", "≤": "<=", "=": "==" }[s] ?? s) as NumericHint["operator"];
  const decimal = (s: string) => { const negative = s.startsWith("-"); const [whole,fraction] = s.replace(/^[+-]/, "").replace(",", ".").split("."); return `${negative ? "-" : ""}${whole.replace(/^0+(?=\d)/, "")}${fraction === undefined ? "" : "." + fraction}`; };
  return [{ operator: op(expression[1]), value: decimal(expression[2]) }, ...(expression[3] ? [{ operator: op(expression[3]), value: decimal(expression[4]) }] : [])];
}
function cell(v: unknown, digest: string, table: number, row: number): v is RequirementTableCell {
  return rec(v) && keys(v, "source_row column text block_index source_char_count provenance") && v.source_row === row && int(v.column, 1, 5) && text(v.text, 2000) && int(v.block_index, 0, 999) && v.source_char_count === [...v.text].length && rec(v.provenance) && keys(v.provenance, "document_id locator extractor confidence") && v.provenance.document_id === digest && v.provenance.locator === `table ${table} row ${row} cell ${v.column}` && v.provenance.extractor === "native_docx" && typeof v.provenance.confidence === "number" && Number.isFinite(v.provenance.confidence) && v.provenance.confidence >= 0 && v.provenance.confidence <= 1;
}
function selectedTable(v: unknown, request: RequirementPreviewRequest): v is EISRequirementTable {
  if (!rec(v) || !keys(v, "revision document_sha256 table_index header rows row_count cell_count total_characters table_structure_status native_text_completeness approved_requirements mandatory_status") || v.revision !== "eis-native-requirement-table-v1" || v.document_sha256 !== request.document.expected_document_sha256 || v.table_index !== request.table_index || [v.table_structure_status,v.native_text_completeness,v.approved_requirements,v.mandatory_status].some(x => x !== "UNKNOWN") || !Array.isArray(v.header) || v.header.length !== 5 || !Array.isArray(v.rows) || v.rows.length < 1 || v.rows.length > 24 || v.row_count !== v.rows.length) return false;
  if (!v.header.every((c, i) => cell(c, v.document_sha256 as string, request.table_index, 1) && c.column === i + 1 && clean(c.text) === headers[i])) return false;
  const all: RequirementTableCell[] = [...v.header];
  for (const [i, row] of v.rows.entries()) {
    if (!rec(row) || !keys(row, "source_row kind cells absent_columns absent_columns_status numeric_hints unit_raw mandatory_status approved_status") || row.source_row !== i + 2 || !Array.isArray(row.cells) || row.cells.length < 1 || row.cells.length > 5 || !row.cells.every(c => cell(c, v.document_sha256 as string, request.table_index, i + 2)) || row.absent_columns_status !== "NO_RETAINED_TEXT" || row.mandatory_status !== "UNKNOWN" || row.approved_status !== "UNKNOWN") return false;
    const cells = row.cells as RequirementTableCell[];
    if (!cells.every((c, j) => j === 0 || c.column > cells[j - 1].column)) return false;
    const raw = (column: number) => cells.find(c => c.column === column)?.text;
    const kind = cells.length === 1 && cells[0].column === 1 ? "CONTEXT_ONLY" : raw(1) && raw(3) ? "CHARACTERISTIC" : "MANUAL_REVIEW_REQUIRED";
    const absent = [1,2,3,4,5].filter(c => !cells.some(x => x.column === c));
    if (row.kind !== kind || row.unit_raw !== (raw(4) ?? null) || JSON.stringify(row.absent_columns) !== JSON.stringify(absent) || !Array.isArray(row.numeric_hints) || JSON.stringify(row.numeric_hints) !== JSON.stringify(kind === "CHARACTERISTIC" ? numericHints(raw(3)) : [])) return false;
    all.push(...cells);
  }
  const names = v.rows.filter(r => r.kind === "CHARACTERISTIC").map(r => clean(r.cells.find((c: RequirementTableCell) => c.column === 1)!.text).toLowerCase());
  return new Set(names).size === names.length && v.cell_count === all.length && v.total_characters === all.reduce((sum,c) => sum + [...c.text].length, 0) && int(v.total_characters, 1, 16000) && all.every((c,i) => i === 0 || c.block_index > all[i - 1].block_index);
}
export function requirementPreviewMatches(v: unknown, request: RequirementPreviewRequest, expected?: { run_id: string; source_url: string; html_sha256: string }): v is RequirementPreview {
  if (!validRequirementPreviewRequest(request) || !rec(v) || !keys(v, "policy_version scope request product product_report_sha256 analysis_sha256 document_observation_id observed_at analyzed_at filename table preview_sha256 approved_requirement_status document_role position_association full_tspec_completeness technical participation source_requests jobs_created database_writes") || v.policy_version !== "eis-requirement-preview-v1" || v.scope !== "SELECTED_RETAINED_DOCX_TABLE" || !validRequirementPreviewRequest(v.request) || requirementPreviewRequestKey(v.request) !== requirementPreviewRequestKey(request) || !sha(v.product_report_sha256) || !sha(v.analysis_sha256) || !sha(v.preview_sha256) || !text(v.document_observation_id,200) || !time(v.observed_at) || !time(v.analyzed_at) || !text(v.filename,1024) || [v.approved_requirement_status,v.document_role,v.position_association,v.full_tspec_completeness,v.technical,v.participation].some(x => x !== "UNKNOWN") || v.source_requests !== 0 || v.jobs_created !== 0 || v.database_writes !== 0 || !supplierProductMatches({report:v.product,created:false,source_requests:0,jobs_created:0},request.product,false,expected) || !selectedTable(v.table,request)) return false;
  return !expected || rec(v.product) && v.product.run_id === expected.run_id;
}
const groups = [["формат","формат бумаги"],["марка бумаги","класс бумаги","класс"],["количество листов в пачке","количество листов","листов в пачке","листов"],["масса бумаги площадью 1м2","масса бумаги площадью 1м грамм","плотность бумаги","плотность"]];
export function supplierFieldsForTableRow(row: RequirementTableRow, product: SupplierProductReport): number[] {
  const raw = row.cells.find(c => c.column === 1)?.text;
  if (row.kind !== "CHARACTERISTIC" || !raw) return [];
  const normalized = (s: string) => s.toLowerCase().replace(/[^0-9a-zа-яё]+/g," ").trim();
  const group = groups.findIndex(a => a.includes(normalized(raw)));
  return product.details.characteristics.flatMap((c,i) => group >= 0 && groups[group].includes(normalized(c.label_raw)) ? [i] : []);
}
