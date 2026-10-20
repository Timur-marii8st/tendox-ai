import { validSupplierCatalogRequest, supplierCatalogRequestKey, type SupplierCatalogRequest } from "./eis-supplier-catalog";
import { savedPositionMatches, type SavedPosition } from "./eis-characteristics";
import type { DeclaredFact } from "./eis-supplier-page";
export type SupplierProductRequest = { catalog: SupplierCatalogRequest; product_run_id: string };
export type SupplierCharacteristic = { label_raw: string; value_raw: string; label_locator: string; value_locator: string; html_sha256: string };
export type SupplierOrderControl = { attribute: string; raw_value: string; locator: string; html_sha256: string };
export type SupplierProductDetails = { revision: "bumaga-s-details-v1"; source_url: string; html_sha256: string;
  status: "EXTRACTED" | "EMPTY" | "UNSUPPORTED" | "AMBIGUOUS" | "LIMIT_EXCEEDED";
  product_name: DeclaredFact | null; characteristics: SupplierCharacteristic[];
  packaging_raw: DeclaredFact | null; contents_raw: DeclaredFact | null; price_basis_raw: DeclaredFact | null;
  order_controls: SupplierOrderControl[]; price_basis_status: "UNKNOWN"; MOQ_status: "UNKNOWN"; order_step_status: "UNKNOWN"; technical_status: "UNKNOWN" };
export type SupplierProductRow = { characteristic_index: number; name: string; supplier_indices: number[]; observation: "UNKNOWN"; reason: string };
export type SupplierProductReport = { policy_version: "eis-position-supplier-product-v1"; scope: "PUBLIC_POSITION_AND_SAVED_PRODUCT";
  run_id: string; request: SupplierProductRequest; parent_product_report_sha256: string; position_sha256: string; source_body_sha256: string;
  created_at: string; position: SavedPosition; details: SupplierProductDetails; rows: SupplierProductRow[]; row_count: number;
  technical: "UNKNOWN"; price_comparability: "UNKNOWN"; unit_cost: "UNKNOWN"; party_total: "UNKNOWN"; quote: "UNKNOWN";
  profit: "UNKNOWN"; participation: "UNKNOWN"; specification_completeness: "UNKNOWN"; source_requests: 0; jobs_created: 0 };
export type SavedSupplierProduct = { report: SupplierProductReport; created: boolean; source_requests: 0; jobs_created: 0 };
export type SupplierProductState = { result?: SavedSupplierProduct; error?: string };
const rec = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const keys = (v: Record<string, unknown>, s: string) => { const list = s.split(" "); return Object.keys(v).length === list.length && list.every(k => Object.hasOwn(v, k)); };
const text = (v: unknown, max: number): v is string => typeof v === "string" && v.length > 0 && [...v].length <= max;
const sha = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const uuid = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(v);
const int = (v: unknown, min: number, max: number): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max;
const time = (v: unknown) => typeof v === "string" && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
export function validSupplierProductRequest(v: unknown): v is SupplierProductRequest {
  return rec(v) && keys(v, "catalog product_run_id") && validSupplierCatalogRequest(v.catalog) && v.catalog.search_run_id !== null && uuid(v.product_run_id);
}
export function supplierProductRequestKey(v: SupplierProductRequest) { return `${supplierCatalogRequestKey(v.catalog)}:${v.product_run_id}`; }
function fact(v: unknown, digest: string): v is DeclaredFact | null {
  return v === null || rec(v) && keys(v, "value html_sha256 locator") && text(v.value, 500) && v.html_sha256 === digest && text(v.locator, 200);
}
function details(v: unknown, digest: string): v is SupplierProductDetails {
  if (!rec(v) || !keys(v, "revision source_url html_sha256 status product_name characteristics packaging_raw contents_raw price_basis_raw order_controls price_basis_status MOQ_status order_step_status technical_status") ||
    v.revision !== "bumaga-s-details-v1" || v.html_sha256 !== digest || !text(v.source_url, 2048) ||
    !["EXTRACTED", "EMPTY", "UNSUPPORTED", "AMBIGUOUS", "LIMIT_EXCEEDED"].includes(String(v.status)) ||
    [v.price_basis_status, v.MOQ_status, v.order_step_status, v.technical_status].some(x => x !== "UNKNOWN") ||
    ![v.product_name, v.packaging_raw, v.contents_raw, v.price_basis_raw].every(x => fact(x, digest)) ||
    !Array.isArray(v.characteristics) || v.characteristics.length > 16 || !Array.isArray(v.order_controls) || v.order_controls.length > 8) return false;
  try { const u = new URL(v.source_url); if (u.protocol !== "https:" || u.hostname !== "bumaga-s.ru" || u.username || u.password || u.port || u.hash || !decodeURIComponent(u.pathname).startsWith("/товар/")) return false; } catch { return false; }
  if (!v.characteristics.every(c => rec(c) && keys(c, "label_raw value_raw label_locator value_locator html_sha256") && text(c.label_raw, 150) && text(c.value_raw, 500) && text(c.label_locator, 200) && text(c.value_locator, 200) && c.html_sha256 === digest) ||
    !v.order_controls.every(c => rec(c) && keys(c, "attribute raw_value locator html_sha256") && text(c.attribute, 80) && typeof c.raw_value === "string" && [...c.raw_value].length <= 150 && text(c.locator, 200) && c.html_sha256 === digest)) return false;
  if (v.status === "EXTRACTED") return v.product_name !== null;
  return [v.product_name, v.packaging_raw, v.contents_raw, v.price_basis_raw].every(x => x === null) &&
    (v.status === "AMBIGUOUS" || v.characteristics.length === 0 && v.order_controls.length === 0);
}
const reasons = new Set(["POSITION_CHARACTERISTIC_NAME_MISSING", "POSITION_CHARACTERISTIC_VALUES_INCOMPLETE", "SUPPLIER_DETAILS_NOT_EXTRACTED", "SUPPLIER_CHARACTERISTIC_MISSING", "SUPPLIER_CHARACTERISTIC_AMBIGUOUS", "PUBLIC_LABEL_MATCH_RECORDED"]);
const labelGroups = [
  ["формат", "формат бумаги"],
  ["плотность", "плотность бумаги", "плотность г м2", "масса бумаги площадью 1м грамм"],
  ["белизна", "белизна cie", "cie"], ["яркость", "яркость iso", "iso яркость"],
  ["непрозрачность"], ["количество листов", "количество листов в пачке", "листов в пачке", "листов"],
  ["цвет"], ["класс бумаги", "марка бумаги", "класс"],
];
const labelGroup = (s: string) => labelGroups.findIndex(g => g.includes(s.toLowerCase().replace(/[^0-9a-zа-яё]+/g, " ").trim()));
export function supplierProductMatches(v: unknown, request: SupplierProductRequest, prepare = false, expected?: { source_url: string; html_sha256: string }): v is SavedSupplierProduct {
  if (!validSupplierProductRequest(request) || !rec(v) || !keys(v, "report created source_requests jobs_created") || typeof v.created !== "boolean" || !prepare && v.created || v.source_requests !== 0 || v.jobs_created !== 0 || !rec(v.report)) return false;
  const r = v.report;
  if (!keys(r, "policy_version scope run_id request parent_product_report_sha256 position_sha256 source_body_sha256 created_at position details rows row_count technical price_comparability unit_cost party_total quote profit participation specification_completeness source_requests jobs_created") ||
    r.policy_version !== "eis-position-supplier-product-v1" || r.scope !== "PUBLIC_POSITION_AND_SAVED_PRODUCT" || !uuid(r.run_id) || !validSupplierProductRequest(r.request) || supplierProductRequestKey(r.request) !== supplierProductRequestKey(request) ||
    !sha(r.parent_product_report_sha256) || !sha(r.position_sha256) || !sha(r.source_body_sha256) || !time(r.created_at) ||
    !savedPositionMatches(r.position, request.catalog.page.position.selection) || !details(r.details, r.source_body_sha256) ||
    [r.technical, r.price_comparability, r.unit_cost, r.party_total, r.quote, r.profit, r.participation, r.specification_completeness].some(x => x !== "UNKNOWN") || r.source_requests !== 0 || r.jobs_created !== 0 ||
    !Array.isArray(r.rows) || r.rows.length > 24 || r.row_count !== r.rows.length || r.rows.length !== r.position.position.characteristics.length) return false;
  if (expected && (r.details.source_url !== expected.source_url || r.details.html_sha256 !== expected.html_sha256)) return false;
  const chars = r.details.characteristics;
  const position = r.position;
  return r.rows.every((row, i) => {
    if (!rec(row) || !keys(row, "characteristic_index name supplier_indices observation reason") || row.characteristic_index !== i + 1 || !text(row.name, 300) || row.observation !== "UNKNOWN" || !reasons.has(String(row.reason)) ||
      !Array.isArray(row.supplier_indices) || !row.supplier_indices.every(j => int(j, 1, chars.length)) || new Set(row.supplier_indices).size !== row.supplier_indices.length) return false;
    const name = position.position.characteristics[i].name.value;
    if (row.name !== (name?.trim() ? name : "(без названия)")) return false;
    const group = name ? labelGroup(name) : -1;
    const expectedIndices = chars.flatMap((c,j) => group >= 0 && labelGroup(c.label_raw) === group ? [j + 1] : []);
    return JSON.stringify(row.supplier_indices) === JSON.stringify(expectedIndices);
  });
}
