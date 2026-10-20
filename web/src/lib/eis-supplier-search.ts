import { validProtocolRef, sameProtocolRef } from "./eis-protocols";
import type { PositionSelection, SourceProvenance, TextFact } from "./eis-characteristics";

export type SupplierSearchRequest = { selection: PositionSelection };
export type PublishedSupplierPrice = { kind: "BASE_PRICE_FROM" | "PRICE_FROM" | "LEASE_MONTHLY";
  amount_rub: string; raw_label: string; provenance: SourceProvenance;
  configured_unit_cost: "UNKNOWN"; quote_status: "UNKNOWN"; tax_status: "UNKNOWN" };
export type SupplierCatalogLead = { supplier: "ServerMall"; manufacturer: "HPE";
  product_name: string; product_url: string; name_provenance: SourceProvenance;
  price_status: "PUBLISHED" | "UNKNOWN"; published_prices: PublishedSupplierPrice[];
  stock: "UNKNOWN"; delivery: "UNKNOWN"; compliance: "UNKNOWN"; participation: "UNKNOWN" };
export type SupplierCatalogObservation = { policy_version: "eis-supplier-catalog-v1";
  source_url: "https://servermall.ru/sets/servery-hp-proliant-gen12/";
  observed_at: string; source_sha256: string; byte_count: number; query: string;
  leads: SupplierCatalogLead[]; scanned_count: number; matched_count: number;
  returned_count: number; truncated: boolean; scope: "ONE_CATEGORY_PAGE_ONLY";
  source_requests: 1; coverage: "UNKNOWN"; tax: "UNKNOWN"; stock: "UNKNOWN";
  delivery: "UNKNOWN"; compliance: "UNKNOWN"; participation: "UNKNOWN" };
export type SupplierSearchReport = { policy_version: "eis-position-supplier-search-v1";
  run_id: string; request: SupplierSearchRequest; position_sha256: string; position_name: TextFact;
  query: "сервер" | "hpe" | "dl360" | "dl380" | null;
  query_scope: "FIXED_CATEGORY_ROUTE_FROM_POSITION_NAME";
  status: "STARTED" | "COMPLETED" | "QUERY_NOT_COVERED" | "SOURCE_ERROR";
  reason_code: "SOURCE_OUTCOME_UNKNOWN" | "FIXED_CATEGORY_SNAPSHOT" | "CATEGORY_NOT_SUPPORTED" | "CATALOG_UNAVAILABLE_OR_CHANGED";
  created_at: string; observation: SupplierCatalogObservation | null;
  attempted_source_requests: 0 | 1 | null;
  specification_completeness: "UNKNOWN"; position_document_association: "UNKNOWN";
  quote: "UNKNOWN"; technical: "UNKNOWN"; profit: "UNKNOWN"; participation: "UNKNOWN" };
export type SavedSupplierSearch = { report: SupplierSearchReport; created: boolean;
  source_requests: 0 | 1; jobs_created: 0 };
export type SupplierSearchState = { result?: SavedSupplierSearch; error?: string };

const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const keys = (v: Record<string, unknown>, names: string) => {
  const expected = names.split(" ");
  return Object.keys(v).length === expected.length && expected.every(k => Object.hasOwn(v, k));
};
const text = (v: unknown, max = 4096): v is string => typeof v === "string" && v.length > 0 && [...v].length <= max;
const nullableText = (v: unknown) => v === null || text(v);
const sha = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
const integer = (v: unknown, min: number, max: number): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max;
const time = (v: unknown) => typeof v === "string" && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
function provenance(v: unknown, digest: string, supplier = false): v is SourceProvenance {
  return record(v) && keys(v, "document_id locator extractor confidence") && v.document_id === digest &&
    text(v.locator) && (supplier ? v.extractor === "api" : typeof v.extractor === "string" &&
      ["api", "native_docx", "manual", "native_pdf", "native_xlsx", "native_xls", "legacy_doc_text", "ocr", "llm"].includes(v.extractor)) &&
    typeof v.confidence === "number" && Number.isFinite(v.confidence) && v.confidence >= 0 && v.confidence <= 1;
}
function productUrl(v: unknown): v is string {
  if (!text(v, 2000)) return false;
  try { const url = new URL(v); return url.protocol === "https:" && url.host === "servermall.ru" &&
    !url.username && !url.password && url.pathname.startsWith("/catalog/servers/") && url.pathname.endsWith("/") && !url.search && !url.hash;
  } catch { return false; }
}
function price(v: unknown, digest: string): v is PublishedSupplierPrice {
  if (!record(v) || !keys(v, "kind amount_rub raw_label provenance configured_unit_cost quote_status tax_status")) return false;
  return ["BASE_PRICE_FROM", "PRICE_FROM", "LEASE_MONTHLY"].includes(String(v.kind)) && typeof v.amount_rub === "string" &&
    /^\d{1,18}(?:\.\d{1,2})?$/.test(v.amount_rub) && v.amount_rub.replace(".", "").length <= 18 && /[1-9]/.test(v.amount_rub) &&
    text(v.raw_label, 300) && provenance(v.provenance, digest, true) &&
    [v.configured_unit_cost, v.quote_status, v.tax_status].every(x => x === "UNKNOWN");
}
function observation(v: unknown, query: string): v is SupplierCatalogObservation {
  if (!record(v) || !keys(v, "policy_version source_url observed_at source_sha256 byte_count query leads scanned_count matched_count returned_count truncated scope source_requests coverage tax stock delivery compliance participation") ||
    v.policy_version !== "eis-supplier-catalog-v1" || v.source_url !== "https://servermall.ru/sets/servery-hp-proliant-gen12/" ||
    !time(v.observed_at) || !sha(v.source_sha256) || !integer(v.byte_count, 1, 2097152) || v.query !== query ||
    !Array.isArray(v.leads) || v.leads.length > 10 || !integer(v.scanned_count, 1, 50) ||
    !integer(v.matched_count, 0, v.scanned_count) || !integer(v.returned_count, 0, 10) || v.returned_count !== v.leads.length ||
    v.returned_count !== Math.min(10, v.matched_count) || v.truncated !== (v.matched_count > v.returned_count) ||
    v.scope !== "ONE_CATEGORY_PAGE_ONLY" || v.source_requests !== 1 ||
    [v.coverage, v.tax, v.stock, v.delivery, v.compliance, v.participation].some(x => x !== "UNKNOWN")) return false;
  const seen = new Set<string>();
  for (const lead of v.leads) {
    if (!record(lead) || !keys(lead, "supplier manufacturer product_name product_url name_provenance price_status published_prices stock delivery compliance participation") ||
      lead.supplier !== "ServerMall" || lead.manufacturer !== "HPE" || !text(lead.product_name, 500) || !productUrl(lead.product_url) ||
      seen.has(lead.product_url) || !provenance(lead.name_provenance, v.source_sha256, true) ||
      !Array.isArray(lead.published_prices) || lead.published_prices.length > 3 ||
      !lead.published_prices.every(p => price(p, v.source_sha256 as string)) ||
      new Set(lead.published_prices.map(p => p.kind)).size !== lead.published_prices.length ||
      lead.price_status !== (lead.published_prices.length ? "PUBLISHED" : "UNKNOWN") ||
      [lead.stock, lead.delivery, lead.compliance, lead.participation].some(x => x !== "UNKNOWN")) return false;
    seen.add(lead.product_url);
  }
  return true;
}
export function validSupplierSearchRequest(v: unknown): v is SupplierSearchRequest {
  return record(v) && keys(v, "selection") && record(v.selection) && keys(v.selection, "notice source_index") &&
    validProtocolRef(v.selection.notice) && integer(v.selection.source_index, 1, 25);
}
export function supplierSearchRequestKey(v: SupplierSearchRequest): string {
  const s = v.selection;
  return `${s.notice.purchase_number}:${s.notice.version_number}:${s.notice.notice_xml_sha256}:${s.source_index}`;
}
export function supplierSearchMatches(v: unknown, request: SupplierSearchRequest, prepare = false): v is SavedSupplierSearch {
  if (!validSupplierSearchRequest(request) || !record(v) || !keys(v, "report created source_requests jobs_created") ||
    typeof v.created !== "boolean" || (!prepare && v.created) || !integer(v.source_requests, 0, 1) || v.jobs_created !== 0 || !record(v.report)) return false;
  const r = v.report;
  if (!keys(r, "policy_version run_id request position_sha256 position_name query query_scope status reason_code created_at observation attempted_source_requests specification_completeness position_document_association quote technical profit participation") ||
    r.policy_version !== "eis-position-supplier-search-v1" || typeof r.run_id !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(r.run_id) ||
    !validSupplierSearchRequest(r.request) || !sameProtocolRef(r.request.selection.notice, request.selection.notice) ||
    r.request.selection.source_index !== request.selection.source_index || !sha(r.position_sha256) ||
    !record(r.position_name) || !keys(r.position_name, "value raw provenance") || !nullableText(r.position_name.value) || !nullableText(r.position_name.raw) ||
    !provenance(r.position_name.provenance, request.selection.notice.notice_xml_sha256) ||
    !(r.query === null || ["сервер", "hpe", "dl360", "dl380"].includes(String(r.query))) ||
    r.query_scope !== "FIXED_CATEGORY_ROUTE_FROM_POSITION_NAME" || !time(r.created_at) ||
    [r.specification_completeness, r.position_document_association, r.quote, r.technical, r.profit, r.participation].some(x => x !== "UNKNOWN")) return false;
  if (r.status === "COMPLETED") {
    if (typeof r.query !== "string" || r.attempted_source_requests !== 1 || r.reason_code !== "FIXED_CATEGORY_SNAPSHOT" || !observation(r.observation, r.query)) return false;
  } else {
    if (r.observation !== null) return false;
    if (r.status === "QUERY_NOT_COVERED") {
      if (r.query !== null || r.attempted_source_requests !== 0 || r.reason_code !== "CATEGORY_NOT_SUPPORTED") return false;
    } else if (r.status === "SOURCE_ERROR") {
      if (r.query === null || r.attempted_source_requests !== 1 || r.reason_code !== "CATALOG_UNAVAILABLE_OR_CHANGED") return false;
    } else if (r.status === "STARTED") {
      if (r.query === null || r.attempted_source_requests !== null || r.reason_code !== "SOURCE_OUTCOME_UNKNOWN" || v.created) return false;
    } else return false;
  }
  return v.source_requests === (v.created ? r.attempted_source_requests : 0);
}
