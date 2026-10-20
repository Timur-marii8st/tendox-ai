import { supplierPageObservationMatches, supplierPageRequestKey, validSupplierPageRequest,
  type SupplierPageRequest, type PageObservation } from "./eis-supplier-page";

export type SupplierCatalogRequest = { page: SupplierPageRequest; page_run_id: string; search_run_id: string | null; product_index: number | null };
export type CatalogSearchSpec = { source_url: string; query: string; raw_action: string; field: "q"; search_url: string; html_sha256: string; locator: string };
export type CatalogLink = { index: number; dom_ordinal: number; title: string; raw_href: string; url: string; html_sha256: string; locator: string; technical_status: "UNKNOWN"; price_status: "UNKNOWN" };
export type CatalogLinks = { revision: "bumaga-s-v1"; source_url: string; html_sha256: string; status: "FOUND" | "EMPTY" | "UNSUPPORTED" | "LIMIT_EXCEEDED"; links: CatalogLink[]; scanned_count: number; returned_count: number; truncated: boolean; coverage: "UNKNOWN" };
export type SupplierCatalogReport = { policy_version: "eis-position-supplier-catalog-v1"; run_id: string; request: SupplierCatalogRequest;
  parent_page_report_sha256: string; position_sha256: string; created_at: string; stage: "SEARCH" | "PRODUCT";
  search_spec: CatalogSearchSpec | null; selected_link: CatalogLink | null; parent_search_report_sha256: string | null;
  status: "STARTED" | "COMPLETED"; reason_code: "SOURCE_OUTCOME_UNKNOWN" | "FIXED_CATALOG_OBSERVATION";
  observation: PageObservation | null; links: CatalogLinks | null; attempted_source_requests: number | null;
  source_body_sha256: string | null; source_body_byte_count: number | null;
  supplier_identity: "UNKNOWN"; price_comparability: "UNKNOWN"; tax: "UNKNOWN"; stock: "UNKNOWN";
  delivery: "UNKNOWN"; technical: "UNKNOWN"; quote: "UNKNOWN"; participation: "UNKNOWN" };
export type SavedSupplierCatalog = { report: SupplierCatalogReport; created: boolean; source_requests: number; jobs_created: 0 };
export type SupplierCatalogState = { result?: SavedSupplierCatalog; error?: string };
const rec = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const keys = (v: Record<string, unknown>, names: string) => { const list = names.split(" "); return Object.keys(v).length === list.length && list.every(k => Object.hasOwn(v, k)); };
const text = (v: unknown, max: number): v is string => typeof v === "string" && v.length > 0 && [...v].length <= max;
const sha = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
const uuid = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(v);
const int = (v: unknown, min: number, max: number): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max;
const time = (v: unknown) => typeof v === "string" && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
function siteUrl(v: unknown): v is string {
  if (!text(v, 2048) || !v.startsWith("https://bumaga-s.ru/")) return false;
  try { const u = new URL(v); return u.hostname === "bumaga-s.ru" && u.protocol === "https:" && !u.username && !u.password && !u.port && !u.hash && !/[\x00-\x20\\]/.test(v); } catch { return false; }
}
function productUrl(v: unknown): v is string {
  if (!siteUrl(v)) return false;
  try { const p = decodeURIComponent(new URL(v).pathname); return p.startsWith("/товар/") && p.length > 7 && !p.split("/").some(x => [".", ".."].includes(x)) && !p.includes("\\"); } catch { return false; }
}
export function validSupplierCatalogRequest(v: unknown): v is SupplierCatalogRequest {
  return rec(v) && keys(v, "page page_run_id search_run_id product_index") && validSupplierPageRequest(v.page) && uuid(v.page_run_id) &&
    ((v.search_run_id === null && v.product_index === null) || uuid(v.search_run_id) && int(v.product_index, 1, 10));
}
export function supplierCatalogRequestKey(v: SupplierCatalogRequest) {
  return `${supplierPageRequestKey(v.page)}:${v.page_run_id}:${v.search_run_id}:${v.product_index}`;
}
function link(v: unknown, digest?: string, sourceUrl?: string): v is CatalogLink {
  if (!rec(v) || !keys(v, "index dom_ordinal title raw_href url html_sha256 locator technical_status price_status") ||
    !int(v.index, 1, 10) || !int(v.dom_ordinal, 1, 50000) || !text(v.title, 300) || !text(v.raw_href, 2048) ||
    !productUrl(v.url) || !sha(v.html_sha256) || digest && v.html_sha256 !== digest || !text(v.locator, 200) ||
    v.technical_status !== "UNKNOWN" || v.price_status !== "UNKNOWN") return false;
  // PRODUCT retains the selected link; its SEARCH base is checked through the
  // exact expectedLink. Only the SEARCH report can prove raw relative resolution.
  if (!sourceUrl) return true;
  try { const raw = new URL(v.raw_href, sourceUrl); raw.hash = ""; return productUrl(raw.href) && decodeURI(raw.href) === decodeURI(new URL(v.url).href); } catch { return false; }
}
function searchSpec(v: unknown): v is CatalogSearchSpec {
  if (!rec(v) || !keys(v, "source_url query raw_action field search_url html_sha256 locator") || !siteUrl(v.source_url) ||
    !text(v.query, 150) || v.query.trim().replace(/\s+/g, " ") !== v.query || /[\p{C}]/u.test(v.query) ||
    !text(v.raw_action, 2048) || v.field !== "q" || !siteUrl(v.search_url) || !sha(v.html_sha256) || !text(v.locator, 200)) return false;
  try {
    const action = new URL(v.raw_action, v.source_url), target = new URL(v.search_url);
    return action.href === "https://bumaga-s.ru/categories/search" && target.pathname === "/categories/search" &&
      [...target.searchParams.keys()].length === 1 && target.searchParams.get("q") === v.query;
  } catch { return false; }
}
function links(v: unknown, o: PageObservation): v is CatalogLinks {
  return rec(v) && keys(v, "revision source_url html_sha256 status links scanned_count returned_count truncated coverage") &&
    v.revision === "bumaga-s-v1" && v.source_url === o.final_url && v.html_sha256 === o.html_sha256 &&
    ["FOUND", "EMPTY", "UNSUPPORTED", "LIMIT_EXCEEDED"].includes(String(v.status)) &&
    Array.isArray(v.links) && v.links.length <= 10 && v.returned_count === v.links.length && int(v.scanned_count, v.links.length, 50000) &&
    typeof v.truncated === "boolean" && v.coverage === "UNKNOWN" && ((v.status === "FOUND") === !!v.links.length) &&
    v.links.every((l, i) => link(l, o.html_sha256 ?? undefined, o.final_url) && l.index === i + 1) &&
    new Set(v.links.map(l => l.url)).size === v.links.length;
}
export function supplierCatalogMatches(v: unknown, request: SupplierCatalogRequest, prepare = false, expectedLink?: CatalogLink): v is SavedSupplierCatalog {
  if (!validSupplierCatalogRequest(request) || !rec(v) || !keys(v, "report created source_requests jobs_created") ||
    typeof v.created !== "boolean" || !prepare && v.created || !int(v.source_requests, 0, 3) || v.jobs_created !== 0 || !rec(v.report)) return false;
  const r = v.report;
  if (!keys(r, "policy_version run_id request parent_page_report_sha256 position_sha256 created_at stage search_spec selected_link parent_search_report_sha256 status reason_code observation links attempted_source_requests source_body_sha256 source_body_byte_count supplier_identity price_comparability tax stock delivery technical quote participation") ||
    r.policy_version !== "eis-position-supplier-catalog-v1" || !uuid(r.run_id) || !validSupplierCatalogRequest(r.request) ||
    supplierCatalogRequestKey(r.request) !== supplierCatalogRequestKey(request) || !sha(r.parent_page_report_sha256) || !sha(r.position_sha256) || !time(r.created_at) ||
    [r.supplier_identity, r.price_comparability, r.tax, r.stock, r.delivery, r.technical, r.quote, r.participation].some(x => x !== "UNKNOWN")) return false;
  let target: string;
  if (request.search_run_id === null) {
    if (r.stage !== "SEARCH" || !searchSpec(r.search_spec) || r.selected_link !== null || r.parent_search_report_sha256 !== null) return false;
    target = r.search_spec.search_url;
  } else {
    if (r.stage !== "PRODUCT" || r.search_spec !== null || r.links !== null || !sha(r.parent_search_report_sha256) ||
      !link(r.selected_link) || r.selected_link.index !== request.product_index) return false;
    const chosen = r.selected_link;
    if (expectedLink && (Object.keys(expectedLink) as (keyof CatalogLink)[]).some(k => chosen[k] !== expectedLink[k])) return false;
    target = r.selected_link.url;
  }
  if (r.status === "STARTED") return !v.created && v.source_requests === 0 && r.reason_code === "SOURCE_OUTCOME_UNKNOWN" &&
    r.observation === null && r.links === null && r.attempted_source_requests === null && r.source_body_sha256 === null && r.source_body_byte_count === null;
  if (r.status !== "COMPLETED" || r.reason_code !== "FIXED_CATALOG_OBSERVATION" || !supplierPageObservationMatches(r.observation, target) ||
    !siteUrl(r.observation.final_url) || r.observation.hops.some(h => !siteUrl(h.url)) ||
    r.source_body_sha256 !== r.observation.html_sha256 || r.source_body_byte_count !== r.observation.byte_count ||
    r.attempted_source_requests !== r.observation.dispatch_count || v.source_requests !== (v.created ? r.observation.dispatch_count : 0)) return false;
  return r.stage === "PRODUCT" || (r.observation.status !== "COMPLETED" || r.observation.html_sha256 === null ? r.links === null : links(r.links, r.observation));
}
