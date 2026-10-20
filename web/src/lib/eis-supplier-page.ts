import { validSupplierSearchRequest, supplierSearchRequestKey, type SupplierSearchRequest } from "./eis-supplier-search";
import { safeSerpLink, type SearchEngine, type SerpLink } from "./eis-supplier-serp";

export type SupplierPageRequest = { position: SupplierSearchRequest; serp_run_id: string; engine: SearchEngine; rank: number };
export type DeclaredFact = { value: string; html_sha256: string; locator: string };
export type DisplayedPrice = { amount: string; raw_amount: string; currency: string | null;
  price_kind: "EXACT" | "LOW" | "HIGH"; html_sha256: string; locator: string };
export type ProductObservation = { locator: string; name: DeclaredFact | null; brand: DeclaredFact | null;
  manufacturer: DeclaredFact | null; seller: DeclaredFact | null; sku: DeclaredFact | null; prices: DisplayedPrice[] };
export type PageHop = { url: string; http_status: number | null; location: string | null };
export type PageObservation = { source_url: string; final_url: string; observed_at: string;
  status: "COMPLETED" | "BLOCKED" | "RATE_LIMITED" | "TIMEOUT" | "SOURCE_ERROR" | "UNSAFE_URL" | "RESOURCE_LIMIT" | "UNSUPPORTED_CONTENT";
  reason_code: string; http_status: number | null;
  extraction_status: "EXTRACTED" | "EMPTY" | "AMBIGUOUS" | "LIMIT_EXCEEDED" | "NOT_ATTEMPTED";
  page_kind: "PRODUCT" | "CATEGORY" | "ARTICLE" | "UNKNOWN";
  html_sha256: string | null; byte_count: number | null; dispatch_count: number; redirect_count: number;
  hops: PageHop[]; products: ProductObservation[]; technical_status: "UNKNOWN"; quote_status: "UNKNOWN";
  configured_cost_status: "UNKNOWN"; identity_status: "UNKNOWN" };
export type SupplierPageReport = { policy_version: "eis-position-supplier-page-v1"; run_id: string;
  request: SupplierPageRequest; parent_report_sha256: string; position_sha256: string; link: SerpLink;
  created_at: string; status: "STARTED" | "COMPLETED";
  reason_code: "SOURCE_OUTCOME_UNKNOWN" | "FIXED_PUBLIC_PAGE_OBSERVATION";
  observation: PageObservation | null; attempted_source_requests: number | null;
  source_body_sha256: string | null; source_body_byte_count: number | null;
  supplier_identity: "UNKNOWN"; price_comparability: "UNKNOWN"; tax: "UNKNOWN"; stock: "UNKNOWN";
  delivery: "UNKNOWN"; technical: "UNKNOWN"; quote: "UNKNOWN"; participation: "UNKNOWN" };
export type SavedSupplierPage = { report: SupplierPageReport; created: boolean; source_requests: number; jobs_created: 0 };
export type SupplierPageState = { result?: SavedSupplierPage; error?: string };

const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const keys = (v: Record<string, unknown>, list: string) => { const names = list.split(" "); return Object.keys(v).length === names.length && names.every(k => Object.hasOwn(v, k)); };
const text = (v: unknown, max: number): v is string => typeof v === "string" && v.length > 0 && [...v].length <= max;
const sha = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
const uuid = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(v);
const integer = (v: unknown, min: number, max: number): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max;
const time = (v: unknown) => typeof v === "string" && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
export function validSupplierPageRequest(v: unknown): v is SupplierPageRequest {
  return record(v) && keys(v, "position serp_run_id engine rank") && validSupplierSearchRequest(v.position) && uuid(v.serp_run_id) &&
    ["BING", "BRAVE", "DUCKDUCKGO", "MOJEEK", "YANDEX", "GOOGLE"].includes(String(v.engine)) && integer(v.rank, 1, 50);
}
export function supplierPageRequestKey(v: SupplierPageRequest) {
  return `${supplierSearchRequestKey(v.position)}:${v.serp_run_id}:${v.engine}:${v.rank}`;
}
function sameRequest(a: unknown, b: SupplierPageRequest): a is SupplierPageRequest {
  return validSupplierPageRequest(a) && supplierPageRequestKey(a) === supplierPageRequestKey(b);
}
function declared(v: unknown, digest: string): v is DeclaredFact {
  return record(v) && keys(v, "value html_sha256 locator") && text(v.value, 500) && v.html_sha256 === digest && text(v.locator, 200);
}
// Compare decimal strings exactly, including exponent notation, without a floating conversion.
function decimalKey(value: string): string | null {
  const match = /^(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d+))?$/.exec(value);
  if (!match) return null;
  let digits = (match[1] + (match[2] ?? "")).replace(/^0+/, "");
  if (!digits) return null;
  let exponent = BigInt(match[3] ?? "0") - BigInt((match[2] ?? "").length);
  const trimmed = digits.replace(/0+$/, "");
  exponent += BigInt(digits.length - trimmed.length); digits = trimmed;
  return `${digits}:${exponent}`;
}
function price(v: unknown, digest: string): v is DisplayedPrice {
  return record(v) && keys(v, "amount raw_amount currency price_kind html_sha256 locator") &&
    typeof v.amount === "string" && /^\d{1,16}(?:\.\d{1,2})?$/.test(v.amount) &&
    v.amount.replace(".", "").length <= 18 && /[1-9]/.test(v.amount) && text(v.raw_amount, 80) &&
    decimalKey(v.raw_amount) === decimalKey(v.amount) &&
    (v.currency === null || typeof v.currency === "string" && /^[A-Z]{3}$/.test(v.currency)) &&
    ["EXACT", "LOW", "HIGH"].includes(String(v.price_kind)) && v.html_sha256 === digest && text(v.locator, 200);
}
export function supplierPageObservationMatches(v: unknown, source: string): v is PageObservation {
  if (!record(v) || !keys(v, "source_url final_url observed_at status reason_code http_status extraction_status page_kind html_sha256 byte_count dispatch_count redirect_count hops products technical_status quote_status configured_cost_status identity_status") ||
    v.source_url !== source || !safeSerpLink(v.final_url) || !time(v.observed_at) ||
    !integer(v.dispatch_count, 0, 3) || !integer(v.redirect_count, 0, 2) ||
    !Array.isArray(v.hops) || v.hops.length !== v.dispatch_count || !Array.isArray(v.products) || v.products.length > 20 ||
    [v.technical_status, v.quote_status, v.configured_cost_status, v.identity_status].some(x => x !== "UNKNOWN") ||
    ((v.html_sha256 === null) !== (v.byte_count === null)) ||
    (v.html_sha256 !== null && (!sha(v.html_sha256) || !integer(v.byte_count, 1, 2097152))) ||
    !(v.http_status === null || integer(v.http_status, 100, 599)) ||
    !["PRODUCT", "CATEGORY", "ARTICLE", "UNKNOWN"].includes(String(v.page_kind)) ||
    !["EXTRACTED", "EMPTY", "AMBIGUOUS", "LIMIT_EXCEEDED", "NOT_ATTEMPTED"].includes(String(v.extraction_status))) return false;
  const reasons: Record<string, string[]> = {
    COMPLETED: ["HTML_OBSERVED"], BLOCKED: ["ACCESS_BLOCKED"], RATE_LIMITED: ["RATE_LIMITED"],
    TIMEOUT: ["DEADLINE_EXCEEDED"], SOURCE_ERROR: ["TRANSPORT_FAILED", "HTTP_ERROR"],
    UNSAFE_URL: ["URL_UNSAFE", "DNS_UNSAFE"], RESOURCE_LIMIT: ["REDIRECT_LIMIT", "BODY_LIMIT"],
    UNSUPPORTED_CONTENT: ["CONTENT_ENCODING_UNSUPPORTED", "CONTENT_TYPE_UNSUPPORTED"],
  };
  if (typeof v.status !== "string" || !Object.hasOwn(reasons, v.status) || !reasons[v.status].includes(String(v.reason_code))) return false;
  if (v.redirect_count !== Math.max(0, v.dispatch_count - 1)) return false;
  for (let i = 0; i < v.hops.length; i++) {
    const hop = v.hops[i];
    if (!record(hop) || !keys(hop, "url http_status location") || !safeSerpLink(hop.url) || !hop.url.startsWith("https://") ||
      !(hop.http_status === null || integer(hop.http_status, 100, 599)) || !(hop.location === null || typeof hop.location === "string" && [...hop.location].length <= 2048)) return false;
    if (i === 0 && hop.url !== source) return false;
  }
  if (v.final_url !== (v.hops.length ? v.hops.at(-1).url : source) || v.http_status !== (v.hops.length ? v.hops.at(-1).http_status : null)) return false;
  if (v.status === "COMPLETED") {
    if (v.http_status !== 200 || v.html_sha256 === null || !v.dispatch_count || v.extraction_status === "NOT_ATTEMPTED") return false;
  } else if (v.products.length || v.extraction_status !== "NOT_ATTEMPTED" || v.page_kind !== "UNKNOWN") return false;
  if (["EMPTY", "LIMIT_EXCEEDED"].includes(String(v.extraction_status)) && v.products.length) return false;
  if (v.extraction_status === "EXTRACTED" && !v.products.length) return false;
  for (const p of v.products) {
    if (!record(p) || !keys(p, "locator name brand manufacturer seller sku prices") || !text(p.locator, 200) ||
      ![p.name, p.brand, p.manufacturer, p.seller, p.sku].every(x => x === null || declared(x, v.html_sha256 as string)) ||
      !Array.isArray(p.prices) || p.prices.length > 20 || !p.prices.every(x => price(x, v.html_sha256 as string))) return false;
  }
  return true;
}
export function supplierPageMatches(v: unknown, request: SupplierPageRequest, prepare = false, expectedLink?: SerpLink): v is SavedSupplierPage {
  if (!validSupplierPageRequest(request) || !record(v) || !keys(v, "report created source_requests jobs_created") ||
    typeof v.created !== "boolean" || (!prepare && v.created) || !integer(v.source_requests, 0, 3) || v.jobs_created !== 0 || !record(v.report)) return false;
  const r = v.report;
  if (!keys(r, "policy_version run_id request parent_report_sha256 position_sha256 link created_at status reason_code observation attempted_source_requests source_body_sha256 source_body_byte_count supplier_identity price_comparability tax stock delivery technical quote participation") ||
    r.policy_version !== "eis-position-supplier-page-v1" || !uuid(r.run_id) || !sameRequest(r.request, request) || !sha(r.parent_report_sha256) || !sha(r.position_sha256) || !time(r.created_at) ||
    [r.supplier_identity, r.price_comparability, r.tax, r.stock, r.delivery, r.technical, r.quote, r.participation].some(x => x !== "UNKNOWN") ||
    !record(r.link) || !keys(r.link, "rank title snippet url dom_sha256 locator role_status price_status technical_status") ||
    r.link.rank !== request.rank || !safeSerpLink(r.link.url) || !text(r.link.title, 300) || typeof r.link.snippet !== "string" || [...r.link.snippet].length > 1200 ||
    !sha(r.link.dom_sha256) || !text(r.link.locator, 150) || [r.link.role_status, r.link.price_status, r.link.technical_status].some(x => x !== "UNKNOWN")) return false;
  const link = r.link;
  if (expectedLink && Object.entries(expectedLink).some(([k, value]) => link[k] !== value)) return false;
  if (r.status === "STARTED") return !v.created && v.source_requests === 0 && r.reason_code === "SOURCE_OUTCOME_UNKNOWN" &&
    r.observation === null && r.attempted_source_requests === null && r.source_body_sha256 === null && r.source_body_byte_count === null;
  return r.status === "COMPLETED" && r.reason_code === "FIXED_PUBLIC_PAGE_OBSERVATION" && supplierPageObservationMatches(r.observation, r.link.url) &&
    r.source_body_sha256 === r.observation.html_sha256 && r.source_body_byte_count === r.observation.byte_count &&
    r.attempted_source_requests === r.observation.dispatch_count && v.source_requests === (v.created ? r.observation.dispatch_count : 0);
}
