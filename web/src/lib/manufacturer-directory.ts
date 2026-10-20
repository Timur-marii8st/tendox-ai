import type { ReviewStatus, ManufacturerProposal } from "./manufacturer-review";

export type DirectoryEvidence = {
  proposal_id: string; proposal_sha256: string; decision_id: string | null;
  decision_sha256: string | null; dossier_sha256: string;
  identity: ManufacturerProposal["claimed_identity"]; current_status: ReviewStatus;
};
export type DirectoryRecord = {
  record_id: string; source_record_index: number; registry_number: string;
  product_name: string; source_manufacturer_name: string; record_url: string;
  document_expires_on: string | null; source_status: "FAIL" | "UNKNOWN";
  review_status: ReviewStatus; status: ReviewStatus; reason_codes: string[];
  review_evidence: DirectoryEvidence[];
};
export type ManufacturerGroup = {
  key: Omit<ManufacturerProposal["claimed_identity"], "legal_name">;
  legal_name: string; record_ids: string[]; product_names: string[];
  status: "PASS" | "UNKNOWN"; reason_codes: string[];
  proposal_ids: string[]; decision_sha256s: string[];
};
export type ManufacturerDirectory = {
  schema_version: "manufacturer-directory-v1"; run_id: string;
  response_sha256: string | null; evaluated_at: string;
  coverage: "COMPLETE" | "INCOMPLETE"; overall_status: ReviewStatus;
  review_count: number; records: DirectoryRecord[]; groups: ManufacturerGroup[];
  unreviewed_record_ids: string[]; technical: "UNKNOWN"; seller: "UNKNOWN";
  website: "UNKNOWN"; quote: "UNKNOWN"; participation: "UNKNOWN";
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const SHA = /^[0-9a-f]{64}$/;
const RECORD = /^[0-9a-f]{24}$/;
const reasons = new Set([
  "REVIEW_COVERAGE_INCOMPLETE", "REGISTRY_DOCUMENT_EXPIRED",
  "REGISTRY_DOCUMENT_CURRENT_STATUS_UNKNOWN", "REVIEW_MISSING", "REVIEW_UNKNOWN",
  "REVIEW_FAIL", "IDENTITY_CONFLICT", "LEGAL_NAME_CONFLICT", "INDEPENDENT_REVIEW_PASS",
]);
const object = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const keys = (v: Record<string, unknown>, names: string) => {
  const expected = names.split(" ");
  return Object.keys(v).length === expected.length && expected.every(k => Object.hasOwn(v, k));
};
const text = (v: unknown, max: number): v is string =>
  typeof v === "string" && v.trim().length > 0 && v.length <= max;
const status = (v: unknown): v is ReviewStatus => ["PASS", "FAIL", "UNKNOWN"].includes(String(v));
const uuid = (v: unknown): v is string => typeof v === "string" && UUID.test(v);
const sha = (v: unknown): v is string => typeof v === "string" && SHA.test(v);
const recordId = (v: unknown): v is string => typeof v === "string" && RECORD.test(v);
const int = (v: unknown, max: number): v is number =>
  typeof v === "number" && Number.isSafeInteger(v) && v >= 0 && v <= max;
const array = <T>(v: unknown, max: number, test: (v: unknown) => v is T): v is T[] =>
  Array.isArray(v) && v.length <= max && v.every(test);
const reasonList = (v: unknown): v is string[] => array(v, 10,
  (x): x is string => typeof x === "string" && reasons.has(x));
const identity = (v: unknown): v is ManufacturerProposal["claimed_identity"] =>
  object(v) && keys(v, "legal_name country_code identifier_scheme registration_id") &&
  text(v.legal_name, 500) && typeof v.country_code === "string" && /^[A-Z]{2}$/.test(v.country_code) &&
  typeof v.identifier_scheme === "string" && /^[A-Z0-9._-]{1,80}$/.test(v.identifier_scheme) &&
  text(v.registration_id, 120);
function evidence(v: unknown): v is DirectoryEvidence {
  return object(v) && keys(v, "proposal_id proposal_sha256 decision_id decision_sha256 dossier_sha256 identity current_status") &&
    uuid(v.proposal_id) && sha(v.proposal_sha256) && sha(v.dossier_sha256) && identity(v.identity) &&
    status(v.current_status) && ((v.decision_id === null && v.decision_sha256 === null && v.current_status === "UNKNOWN") ||
      (uuid(v.decision_id) && sha(v.decision_sha256)));
}
function record(v: unknown): v is DirectoryRecord {
  if (!object(v) || !keys(v, "record_id source_record_index registry_number product_name source_manufacturer_name record_url document_expires_on source_status review_status status reason_codes review_evidence")) return false;
  return recordId(v.record_id) && int(v.source_record_index, 10) && v.source_record_index > 0 &&
    text(v.registry_number, 80) && text(v.product_name, 500) && text(v.source_manufacturer_name, 500) &&
    v.record_url === `https://goszakupki.eaeunion.org/erpt/ru/registers/products/list/card/${v.record_id}` &&
    (v.document_expires_on === null || typeof v.document_expires_on === "string" &&
      /^\d{4}-\d{2}-\d{2}$/.test(v.document_expires_on) &&
      !Number.isNaN(Date.parse(v.document_expires_on)) && new Date(v.document_expires_on).toISOString().slice(0, 10) === v.document_expires_on) &&
    ["FAIL", "UNKNOWN"].includes(String(v.source_status)) && status(v.review_status) && status(v.status) &&
    reasonList(v.reason_codes) && array(v.review_evidence, 20, evidence) &&
    (v.source_status !== "FAIL" || v.status === "FAIL") &&
    (v.review_status !== "FAIL" || v.status === "FAIL") &&
    (v.status !== "PASS" || (v.review_status === "PASS" && v.source_status === "UNKNOWN" &&
      v.review_evidence.length > 0 && v.review_evidence.every(x => x.current_status === "PASS") &&
      v.reason_codes.includes("INDEPENDENT_REVIEW_PASS") &&
      !v.reason_codes.some(x => ["LEGAL_NAME_CONFLICT", "IDENTITY_CONFLICT", "REVIEW_COVERAGE_INCOMPLETE"].includes(x))));
}
function group(v: unknown): v is ManufacturerGroup {
  return object(v) && keys(v, "key legal_name record_ids product_names status reason_codes proposal_ids decision_sha256s") &&
    object(v.key) && keys(v.key, "country_code identifier_scheme registration_id") &&
    identity({ ...v.key, legal_name: "shape" }) && text(v.legal_name, 500) &&
    array(v.record_ids, 10, recordId) && v.record_ids.length > 0 &&
    array(v.product_names, 10, (x): x is string => text(x, 500)) && v.product_names.length === v.record_ids.length &&
    (v.status === "PASS" || v.status === "UNKNOWN") && reasonList(v.reason_codes) &&
    array(v.proposal_ids, 20, uuid) && array(v.decision_sha256s, 20, sha);
}
export function directoryMatches(v: unknown, runId: string, responseSha: string | null): v is ManufacturerDirectory {
  if (!object(v) || !keys(v, "schema_version run_id response_sha256 evaluated_at coverage overall_status review_count records groups unreviewed_record_ids technical seller website quote participation")) return false;
  if (v.schema_version !== "manufacturer-directory-v1" || !uuid(v.run_id) || v.run_id !== runId ||
    v.response_sha256 !== responseSha || (v.response_sha256 !== null && !sha(v.response_sha256)) ||
    typeof v.evaluated_at !== "string" || !/(Z|[+-]\d{2}:\d{2})$/.test(v.evaluated_at) || Number.isNaN(Date.parse(v.evaluated_at)) ||
    !["COMPLETE", "INCOMPLETE"].includes(String(v.coverage)) || !status(v.overall_status) ||
    !int(v.review_count, 20) || !array(v.records, 10, record) || !array(v.groups, 10, group) ||
    !array(v.unreviewed_record_ids, 10, recordId) ||
    [v.technical, v.seller, v.website, v.quote, v.participation].some(x => x !== "UNKNOWN")) return false;
  const records = v.records;
  const asOf = new Date(v.evaluated_at).toISOString().slice(0, 10);
  for (const r of records) {
    if (r.document_expires_on !== null && r.document_expires_on < asOf && r.source_status !== "FAIL") return false;
    if (r.status === "PASS" && new Set(r.review_evidence.map(x => JSON.stringify(x.identity))).size !== 1) return false;
  }
  if (new Set(records.map(x => x.record_id)).size !== records.length ||
    (v.coverage === "COMPLETE" && records.reduce((n, x) => n + x.review_evidence.length, 0) !== v.review_count)) return false;
  if (v.coverage === "INCOMPLETE" && (v.overall_status !== "UNKNOWN" || v.groups.length > 0 || records.some(x => x.status === "PASS"))) return false;
  if (v.overall_status === "PASS" && (records.length === 0 || records.some(x => x.status !== "PASS"))) return false;
  if (v.overall_status === "FAIL" && !records.some(x => x.status === "FAIL")) return false;
  const pending = records.filter(x => x.review_evidence.length === 0).map(x => x.record_id);
  if (v.coverage === "COMPLETE" && (pending.length !== v.unreviewed_record_ids.length || !pending.every(x => (v.unreviewed_record_ids as string[]).includes(x)))) return false;
  if (new Set(v.unreviewed_record_ids).size !== v.unreviewed_record_ids.length || !v.unreviewed_record_ids.every(id => records.some(r => r.record_id === id))) return false;
  return v.groups.every(g => g.record_ids.every((id, i) => {
    const r = records.find(x => x.record_id === id);
    return r && g.product_names[i] === r.product_name &&
      (g.status !== "PASS" || r.status === "PASS") &&
      r.review_evidence.some(x => x.current_status === "PASS" &&
        x.identity.country_code === g.key.country_code && x.identity.identifier_scheme === g.key.identifier_scheme &&
        x.identity.registration_id === g.key.registration_id && g.proposal_ids.includes(x.proposal_id) &&
        x.decision_sha256 !== null && g.decision_sha256s.includes(x.decision_sha256) &&
        (g.status !== "PASS" || x.identity.legal_name === g.legal_name));
  }));
}
