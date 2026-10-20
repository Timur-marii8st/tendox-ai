import { validSupplierSearchRequest, supplierSearchRequestKey, type SupplierSearchRequest } from "./eis-supplier-search";
import type { TextFact } from "./eis-characteristics";

export type SearchEngine = "BING" | "BRAVE" | "DUCKDUCKGO" | "MOJEEK" | "YANDEX" | "GOOGLE";
export type SerpStatus = "COMPLETED" | "EMPTY" | "BLOCKED" | "RATE_LIMITED" | "TIMEOUT" | "SOURCE_CHANGED" | "SOURCE_ERROR" | "BROWSER_UNAVAILABLE" | "COOLDOWN";
export type SerpLink = { rank: number; title: string; snippet: string; url: string; dom_sha256: string; locator: string;
  role_status: "UNKNOWN"; price_status: "UNKNOWN"; technical_status: "UNKNOWN" };
export type EngineAttempt = { engine: SearchEngine; query: string; source_url: string; observed_at: string;
  status: SerpStatus; reason_code: string; dom_sha256: string | null; byte_count: number | null; links: SerpLink[];
  scanned_count: number; returned_count: number; truncated: boolean; elapsed_ms: number; browser_navigation_count: 0 | 1 };
export type SearchBatch = { query: string; attempts: EngineAttempt[]; status: "COMPLETED" | "PARTIAL" | "UNAVAILABLE";
  coverage: "UNKNOWN"; supplierpage_requests: 0 };
export type SupplierSerpReport = { policy_version: "eis-position-supplier-serp-v1" | "eis-position-supplier-serp-v2"; run_id: string;
  request: SupplierSearchRequest; position_sha256: string; position_name: TextFact; query: string | null;
  query_scope: "PUBLIC_POSITION_NAME_FIXED_SUPPLIER_TERMS";
  status: "STARTED" | "QUERY_NOT_COVERED" | "COMPLETED" | "PARTIAL" | "UNAVAILABLE";
  reason_code: "SOURCE_OUTCOME_UNKNOWN" | "PUBLIC_POSITION_NAME_UNAVAILABLE" | "FIXED_MULTI_ENGINE_SERP" | "ALL_ENGINES_UNAVAILABLE";
  created_at: string; batch: SearchBatch | null; attempted_source_requests: number | null;
  source_bundle_sha256: string | null; source_bundle_byte_count: number | null;
  full_market_coverage: "UNKNOWN"; supplier_identity: "UNKNOWN"; price: "UNKNOWN"; stock: "UNKNOWN";
  delivery: "UNKNOWN"; technical: "UNKNOWN"; quote: "UNKNOWN"; participation: "UNKNOWN" };
export type SavedSupplierSerp = { report: SupplierSerpReport; created: boolean; source_requests: number; jobs_created: 0 };
export type SupplierSerpState = { result?: SavedSupplierSerp; error?: string };
export const serpEngines = ["BING", "YANDEX", "GOOGLE"] as const;
export const historicalExpandedSerpEngines = ["BING", "BRAVE", "DUCKDUCKGO", "MOJEEK", "YANDEX", "GOOGLE"] as const;
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const keys = (v: Record<string, unknown>, names: string) => { const expected = names.split(" "); return Object.keys(v).length === expected.length && expected.every(k => Object.hasOwn(v, k)); };
const integer = (v: unknown, min: number, max: number): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max;
const text = (v: unknown, max: number, empty = false): v is string => typeof v === "string" && (empty || v.length > 0) && [...v].length <= max;
const sha = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
const time = (v: unknown) => typeof v === "string" && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
export function supplierSerpQuery(name: string | null | undefined): string | null {
  if (typeof name !== "string" || /\p{C}/u.test(name)) return null;
  const normalized = name.trim().split(/\s+/u).join(" ");
  if (!normalized || [...normalized].length > 150 || ["unknown", "неизвестно", "n/a"].includes(normalized.toLowerCase())) return null;
  return `${normalized} производитель поставщик купить оптом`;
}
export function serpSourceUrl(engine: SearchEngine, query: string) {
  const base = { BING: "https://www.bing.com/search", BRAVE: "https://search.brave.com/search", DUCKDUCKGO: "https://html.duckduckgo.com/html/", MOJEEK: "https://www.mojeek.com/search", YANDEX: "https://yandex.ru/search/", GOOGLE: "https://www.google.com/search" }[engine];
  return base + "?" + (engine === "YANDEX" ? "text=" : "q=") + encodeURIComponent(query).replace(/[!'()*]/g, c => "%" + c.charCodeAt(0).toString(16).toUpperCase()).replace(/%20/g, "+");
}
export function safeSerpLink(v: unknown): v is string {
  if (!text(v, 2048) || /[\x00-\x20\x7f\\]/.test(v)) return false;
  try {
    const url = new URL(v), host = url.hostname.toLowerCase();
    const raw = /^(https?):\/\/([^/?#]+)(\/[^#]*)$/.exec(v);
    return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password && !url.port && !url.hash &&
      /^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$/.test(host) && host.includes(".") && /[a-z]/.test(host.split(".").at(-1) ?? "") &&
      !["localhost", "local", "internal", "lan", "test", "invalid", "example", "onion"].some(t => host.endsWith(`.${t}`)) &&
      !["bing.com", "bing.net", "brave.com", "duckduckgo.com", "mojeek.com", "yandex.ru", "yandex.com", "google.com", "gstatic.com", "yastatic.net"].some(t => host === t || host.endsWith(`.${t}`)) &&
      raw !== null && raw[2] === host;
  } catch { return false; }
}
function attempt(v: unknown, engine: SearchEngine, query: string): v is EngineAttempt {
  if (!record(v) || !keys(v, "engine query source_url observed_at status reason_code dom_sha256 byte_count links scanned_count returned_count truncated elapsed_ms browser_navigation_count") ||
    v.engine !== engine || v.query !== query || v.source_url !== serpSourceUrl(engine, query) || !time(v.observed_at) ||
    !integer(v.browser_navigation_count, 0, 1) || !integer(v.elapsed_ms, 0, 90000) || !integer(v.scanned_count, 0, 50) ||
    !integer(v.returned_count, 0, 10) || typeof v.truncated !== "boolean" || !Array.isArray(v.links) || v.returned_count !== v.links.length ||
    ((v.dom_sha256 === null) !== (v.byte_count === null)) || (v.dom_sha256 !== null && (!sha(v.dom_sha256) || !integer(v.byte_count, 1, 8388608)))) return false;
  const reasons: Record<string, string[]> = { COMPLETED: ["ORGANIC_LINKS_FOUND"], EMPTY: ["EXPLICIT_EMPTY"], BLOCKED: ["ACCESS_BLOCKED"],
    RATE_LIMITED: ["RATE_LIMITED"], TIMEOUT: ["TIMEOUT", "BATCH_TIMEOUT"], SOURCE_CHANGED: ["DOM_LIMIT", "QUERY_BINDING_INVALID", "ORGANIC_STRUCTURE_UNVERIFIED"],
    SOURCE_ERROR: ["SOURCE_ERROR"], BROWSER_UNAVAILABLE: ["BROWSER_UNAVAILABLE"], COOLDOWN: ["ENGINE_COOLDOWN"] };
  if (typeof v.status !== "string" || !Object.hasOwn(reasons, v.status) || !reasons[v.status].includes(String(v.reason_code))) return false;
  if (["COOLDOWN", "BROWSER_UNAVAILABLE"].includes(v.status) && (v.browser_navigation_count !== 0 || v.dom_sha256 !== null)) return false;
  if (v.status === "COMPLETED") { if (!v.links.length || v.dom_sha256 === null || v.browser_navigation_count !== 1 || v.scanned_count < v.links.length) return false; }
  else if (v.links.length || v.returned_count || v.truncated) return false;
  if (v.status === "EMPTY" && (v.dom_sha256 === null || v.scanned_count !== 0 || v.browser_navigation_count !== 1)) return false;
  const locatorPrefixes: Partial<Record<SearchEngine, string>> = { BING: 'locator("li.b_algo").nth(', BRAVE: 'locator("#results .snippet[data-type=web]").nth(', DUCKDUCKGO: 'locator(".result.results_links.web-result:not(.result--ad)").nth(', MOJEEK: 'locator("ul.results-standard > li:not(.ad):not(.sponsored)").nth(', YANDEX: 'locator("li.serp-item").nth(', GOOGLE: 'locator("#search a:has(h3)").nth(' };
  const urls = new Set<string>(); let rank = 0;
  const allowedPrefixes = [locatorPrefixes[engine], ...(engine === "YANDEX" ? ['locator("ul[aria-label=\'Результаты поиска\'] > li").nth('] : [])];
  for (const link of v.links) {
    if (!record(link)) return false;
    const locator = link.locator;
    if (!keys(link, "rank title snippet url dom_sha256 locator role_status price_status technical_status") ||
      !integer(link.rank, rank + 1, 50) || !text(link.title, 300) || !text(link.snippet, 1200, true) || !safeSerpLink(link.url) ||
      urls.has(link.url) || link.dom_sha256 !== v.dom_sha256 || !text(locator, 256) || !allowedPrefixes.some(prefix => !!prefix && locator.startsWith(prefix)) ||
      [link.role_status, link.price_status, link.technical_status].some(x => x !== "UNKNOWN")) return false;
    urls.add(link.url); rank = link.rank;
  }
  return true;
}
export function supplierSerpMatches(v: unknown, request: SupplierSearchRequest, prepare = false): v is SavedSupplierSerp {
  if (!validSupplierSearchRequest(request) || !record(v) || !keys(v, "report created source_requests jobs_created") ||
    typeof v.created !== "boolean" || (!prepare && v.created) || !integer(v.source_requests, 0, 6) || v.jobs_created !== 0 || !record(v.report)) return false;
  const r = v.report;
  if (!keys(r, "policy_version run_id request position_sha256 position_name query query_scope status reason_code created_at batch attempted_source_requests source_bundle_sha256 source_bundle_byte_count full_market_coverage supplier_identity price stock delivery technical quote participation") ||
    !["eis-position-supplier-serp-v1", "eis-position-supplier-serp-v2"].includes(String(r.policy_version)) || typeof r.run_id !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(r.run_id) ||
    !validSupplierSearchRequest(r.request) || supplierSearchRequestKey(r.request) !== supplierSearchRequestKey(request) || !sha(r.position_sha256) || !time(r.created_at) ||
    r.query_scope !== "PUBLIC_POSITION_NAME_FIXED_SUPPLIER_TERMS" ||
    [r.full_market_coverage, r.supplier_identity, r.price, r.stock, r.delivery, r.technical, r.quote, r.participation].some(x => x !== "UNKNOWN") ||
    !record(r.position_name) || !keys(r.position_name, "value raw provenance") ||
    ![r.position_name.value, r.position_name.raw].every(x => x === null || text(x, 4096)) || !record(r.position_name.provenance) ||
    !keys(r.position_name.provenance, "document_id locator extractor confidence") || r.position_name.provenance.document_id !== request.selection.notice.notice_xml_sha256 ||
    r.position_name.provenance.extractor !== "api" || !text(r.position_name.provenance.locator, 4096) ||
    typeof r.position_name.provenance.confidence !== "number" || !Number.isFinite(r.position_name.provenance.confidence) || r.position_name.provenance.confidence < 0 || r.position_name.provenance.confidence > 1 ||
    r.query !== supplierSerpQuery(r.position_name.value as string | null)) return false;
  if (r.status === "QUERY_NOT_COVERED") return r.query === null && r.batch === null && r.reason_code === "PUBLIC_POSITION_NAME_UNAVAILABLE" &&
    r.attempted_source_requests === 0 && v.source_requests === 0 && r.source_bundle_sha256 === null && r.source_bundle_byte_count === null;
  if (!text(r.query, 240)) return false;
  if (r.status === "STARTED") return !v.created && v.source_requests === 0 && r.batch === null && r.reason_code === "SOURCE_OUTCOME_UNKNOWN" &&
    r.attempted_source_requests === null && r.source_bundle_sha256 === null && r.source_bundle_byte_count === null;
  const policyEngines: readonly SearchEngine[] = r.policy_version === "eis-position-supplier-serp-v1" ? serpEngines : historicalExpandedSerpEngines;
  const bundleLimit = r.policy_version === "eis-position-supplier-serp-v1" ? 8_388_608 : 13_631_488;
  if (!record(r.batch) || !keys(r.batch, "query attempts status coverage supplierpage_requests") || r.batch.query !== r.query ||
    r.batch.status !== r.status || r.batch.coverage !== "UNKNOWN" || r.batch.supplierpage_requests !== 0 ||
    !Array.isArray(r.batch.attempts) || r.batch.attempts.length !== policyEngines.length ||
    !r.batch.attempts.every((a, i) => attempt(a, policyEngines[i], r.query as string))) return false;
  const attempts = r.batch.attempts as EngineAttempt[];
  const completed = attempts.filter(a => ["COMPLETED", "EMPTY"].includes(a.status)).length;
  const status = completed === policyEngines.length ? "COMPLETED" : completed ? "PARTIAL" : "UNAVAILABLE";
  const navigations = attempts.reduce((n, a) => n + a.browser_navigation_count, 0);
  const captured = attempts.some(a => a.dom_sha256 !== null);
  return r.status === status && r.reason_code === (status === "UNAVAILABLE" ? "ALL_ENGINES_UNAVAILABLE" : "FIXED_MULTI_ENGINE_SERP") &&
    r.attempted_source_requests === navigations && v.source_requests === (v.created ? navigations : 0) &&
    (captured ? sha(r.source_bundle_sha256) && integer(r.source_bundle_byte_count, 1, bundleLimit) : r.source_bundle_sha256 === null && r.source_bundle_byte_count === null);
}
