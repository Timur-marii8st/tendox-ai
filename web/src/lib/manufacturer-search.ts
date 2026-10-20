export const EAEU_PRODUCTS_URL = "https://goszakupki.eaeunion.org/spd/find?collection=erpt.v_goodscollection_prod_public&limit=10&sort=%7B%22publishdate%22%3A-1%7D";

export type ManufacturerSearchRequest = { command_id: string; query: string };
export type ManufacturerCandidate = {
  source_record_index: number;
  record_id: string;
  registry_number: string;
  product_name: string;
  manufacturer_name: string;
  record_url: string;
  document_expires_on: string | null;
  document_validity: "FAIL" | "UNKNOWN";
  document_validity_reason: "EXPIRED" | "EXPIRY_UNKNOWN" | "CURRENT_STATUS_UNVERIFIED";
  role: "MANUFACTURER_SOURCE_DECLARATION";
  identity: "UNKNOWN";
  website: "UNKNOWN";
  seller: "UNKNOWN";
  brand: "UNKNOWN";
  technical: "UNKNOWN";
  quote: "UNKNOWN";
};
export type ManufacturerSearchReport = {
  schema_version: "manufacturer-search-v1";
  run_id: string;
  command_id: string;
  query: string;
  source: "EAEU_PRODUCTS";
  source_url: typeof EAEU_PRODUCTS_URL;
  status: "STARTED" | "COMPLETED" | "SOURCE_ERROR";
  reason_code: "SOURCE_OUTCOME_UNKNOWN" | "VERIFIED_RESPONSE" | "SOURCE_UNAVAILABLE_OR_CHANGED";
  created_at: string;
  finished_at: string | null;
  request_sha256: string;
  response_sha256: string | null;
  response_byte_size: number | null;
  matched_count: number | null;
  candidates: ManufacturerCandidate[];
};
export type SavedManufacturerSearch = { report: ManufacturerSearchReport; created: boolean; source_requests: 0 | 1 };
export type ManufacturerSearchSummary = {
  run_id: string;
  query: string;
  status: ManufacturerSearchReport["status"];
  created_at: string;
  finished_at: string | null;
  candidate_count: number;
  matched_count: number | null;
};
export type ManufacturerDossier = {
  run_id: string;
  candidate: ManufacturerCandidate;
  verified_from_retained_response: true;
  provenance: {
    source: "EAEU_PRODUCTS";
    source_url: typeof EAEU_PRODUCTS_URL;
    response_sha256: string;
    source_record_index: number;
    field_locators: Record<string, string>;
  };
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const RECORD_ID = /^[0-9a-f]{24}$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const AWARE_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/;
const OFFICIAL_RECORD_URL = /^https:\/\/goszakupki\.eaeunion\.org\/erpt\/ru\/registers\/products\/list\/card\/[0-9a-f]{24}$/;

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function exactKeys(value: Record<string, unknown>, names: string): boolean {
  const expected = names.split(" ");
  return Object.keys(value).length === expected.length && expected.every((name) => Object.hasOwn(value, name));
}
function text(value: unknown, max = 1_000): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.length <= max;
}
function awareTime(value: unknown): value is string {
  return typeof value === "string" && AWARE_TIME.test(value) && !Number.isNaN(Date.parse(value));
}
function date(value: unknown): value is string {
  return typeof value === "string" && DATE.test(value) && !Number.isNaN(Date.parse(`${value}T00:00:00Z`)) && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
}
function query(value: unknown): value is string {
  return text(value, 80) && !/[\x00-\x1f]/.test(value) && value.trim() === value && value.split(/\s+/).join(" ") === value && value.trim().split(/\s+/).length <= 5;
}
function nullableSha(value: unknown): value is string | null {
  return value === null || (typeof value === "string" && SHA256.test(value));
}
function nullableInteger(value: unknown): value is number | null {
  return value === null || nonnegativeInteger(value);
}
function nonnegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

export function validManufacturerSearchRequest(value: unknown): value is ManufacturerSearchRequest {
  return object(value) && exactKeys(value, "command_id query") && typeof value.command_id === "string" && UUID.test(value.command_id) && query(value.query);
}

export function manufacturerCandidateMatches(value: unknown): value is ManufacturerCandidate {
  if (!object(value) || !exactKeys(value, "source_record_index record_id registry_number product_name manufacturer_name record_url document_expires_on document_validity document_validity_reason role identity website seller brand technical quote")) return false;
  if (!nonnegativeInteger(value.source_record_index) || value.source_record_index < 1 || value.source_record_index > 10 ||
    typeof value.record_id !== "string" || !RECORD_ID.test(value.record_id) || !text(value.registry_number, 500) ||
    !text(value.product_name, 500) || !text(value.manufacturer_name, 500) || typeof value.record_url !== "string" || !OFFICIAL_RECORD_URL.test(value.record_url) || !value.record_url.endsWith("/" + value.record_id) ||
    !(value.document_expires_on === null || date(value.document_expires_on)) || value.role !== "MANUFACTURER_SOURCE_DECLARATION" ||
    [value.identity, value.website, value.seller, value.brand, value.technical, value.quote].some((status) => status !== "UNKNOWN")) return false;
  if (value.document_validity === "FAIL") return value.document_expires_on !== null && value.document_validity_reason === "EXPIRED";
  return value.document_validity === "UNKNOWN" && (value.document_expires_on === null ? value.document_validity_reason === "EXPIRY_UNKNOWN" : value.document_validity_reason === "CURRENT_STATUS_UNVERIFIED");
}

export function manufacturerReportMatches(value: unknown): value is ManufacturerSearchReport {
  if (!object(value) || !exactKeys(value, "schema_version run_id command_id query source source_url status reason_code created_at finished_at request_sha256 response_sha256 response_byte_size matched_count candidates") ||
    value.schema_version !== "manufacturer-search-v1" || typeof value.run_id !== "string" || !UUID.test(value.run_id) || typeof value.command_id !== "string" || !UUID.test(value.command_id) ||
    !query(value.query) || value.source !== "EAEU_PRODUCTS" || value.source_url !== EAEU_PRODUCTS_URL || !awareTime(value.created_at) ||
    !(value.finished_at === null || awareTime(value.finished_at)) || typeof value.request_sha256 !== "string" || !SHA256.test(value.request_sha256) ||
    !nullableSha(value.response_sha256) || !nullableInteger(value.response_byte_size) || (typeof value.response_byte_size === "number" && value.response_byte_size > 524288) || !nullableInteger(value.matched_count) ||
    !Array.isArray(value.candidates) || value.candidates.length > 10 || !value.candidates.every(manufacturerCandidateMatches)) return false;
  const ids = new Set(value.candidates.map((candidate) => candidate.record_id));
  if (ids.size !== value.candidates.length || value.finished_at !== null && Date.parse(value.finished_at) < Date.parse(value.created_at)) return false;
  if (value.status === "STARTED") return value.reason_code === "SOURCE_OUTCOME_UNKNOWN" && value.finished_at === null && value.response_sha256 === null && value.response_byte_size === null && value.matched_count === null && value.candidates.length === 0;
  if (value.status === "COMPLETED") return value.reason_code === "VERIFIED_RESPONSE" && value.finished_at !== null && value.response_sha256 !== null && value.response_byte_size !== null && value.matched_count !== null && value.matched_count >= value.candidates.length;
  return value.status === "SOURCE_ERROR" && value.reason_code === "SOURCE_UNAVAILABLE_OR_CHANGED" && value.finished_at !== null && value.matched_count === null && value.candidates.length === 0 && ((value.response_sha256 === null) === (value.response_byte_size === null));
}

export function savedManufacturerSearchMatches(value: unknown, request?: ManufacturerSearchRequest, allowCreated = false): value is SavedManufacturerSearch {
  if (!object(value) || !exactKeys(value, "report created source_requests") || typeof value.created !== "boolean" || (!allowCreated && value.created) ||
    (value.source_requests !== 0 && value.source_requests !== 1) || !manufacturerReportMatches(value.report)) return false;
  if (request && (!validManufacturerSearchRequest(request) || value.report.command_id !== request.command_id || value.report.query !== request.query)) return false;
  return value.source_requests === (value.created && value.report.status !== "STARTED" ? 1 : 0);
}

export function manufacturerSearchSummariesMatch(value: unknown): value is ManufacturerSearchSummary[] {
  return Array.isArray(value) && value.length <= 20 && value.every((item) => object(item) && exactKeys(item, "run_id query status created_at finished_at candidate_count matched_count") &&
    typeof item.run_id === "string" && UUID.test(item.run_id) && query(item.query) && ["STARTED", "COMPLETED", "SOURCE_ERROR"].includes(String(item.status)) &&
    awareTime(item.created_at) && (item.finished_at === null || awareTime(item.finished_at)) && nonnegativeInteger(item.candidate_count) && item.candidate_count <= 10 && nullableInteger(item.matched_count));
}

export function manufacturerDossierMatches(value: unknown, runId?: string, recordId?: string): value is ManufacturerDossier {
  if (!object(value) || !exactKeys(value, "run_id candidate verified_from_retained_response provenance") || typeof value.run_id !== "string" || !UUID.test(value.run_id) ||
    !manufacturerCandidateMatches(value.candidate) || value.verified_from_retained_response !== true || !object(value.provenance) ||
    !exactKeys(value.provenance, "source source_url response_sha256 source_record_index field_locators") || value.provenance.source !== "EAEU_PRODUCTS" || value.provenance.source_url !== EAEU_PRODUCTS_URL || typeof value.provenance.response_sha256 !== "string" || !SHA256.test(value.provenance.response_sha256) || value.provenance.source_record_index !== value.candidate.source_record_index || !object(value.provenance.field_locators) || Object.keys(value.provenance.field_locators).length === 0 || Object.entries(value.provenance.field_locators).some(([key, locator]) => !text(key, 100) || !text(locator, 2_000))) return false;
  const prefix = `result[${value.candidate.source_record_index - 1}]`;
  const locators = value.provenance.field_locators;
  const expected: Record<string, string> = { record_id: `${prefix}._id.$oid`, registry_number: `${prefix}.registrynumber`, product_name: `${prefix}.goodsname`, manufacturer_name: `${prefix}.name`, document_expires_on: `${prefix}.expertactenddate` };
  if (!exactKeys(locators, Object.keys(expected).join(" ")) || Object.entries(expected).some(([key, locator]) => locators[key] !== locator)) return false;
  return (!runId || value.run_id === runId) && (!recordId || value.candidate.record_id === recordId);
}
