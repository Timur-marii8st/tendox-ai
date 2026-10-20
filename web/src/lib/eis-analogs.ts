// Public wire contract. Authentication and network access stay in the server adapter.
import { sameProtocolRef, validProtocolRef, type ProtocolNoticeRef } from "./eis-protocols";

export type AnalogRequest = {
  target: ProtocolNoticeRef; source_index: number; query: string; lookback_days: number;
};
export type AnalogEvidence = { document_id: string; locator: string; extractor: "api"; confidence: number };
export type AnalogFact = { value: string | null; provenance: AnalogEvidence };
export type AnalogPosition = {
  source_index: number; name: AnalogFact; ktru: AnalogFact; okpd2: AnalogFact;
  quantity: AnalogFact; unit: AnalogFact;
};
export type AnalogNotice = {
  notice: ProtocolNoticeRef; document_type: string; source_member: string;
  published_at: AnalogFact; deadline: AnalogFact; positions: AnalogPosition[];
  positions_total: number; lot_parse_status: "PARSED" | "UNKNOWN";
};
export const analogDimensions = ["SUBJECT", "VOLUME", "PERIOD", "HISTORY", "TECHNICAL", "DELIVERY_REGION"] as const;
export type AnalogDimension = typeof analogDimensions[number];
export type AnalogCriterion = {
  dimension: AnalogDimension; status: "PASS" | "FAIL" | "UNKNOWN"; reason: string;
  target_value: string | null; candidate_value: string | null; evidence: AnalogEvidence[];
};
export type AnalogRow = {
  notice: ProtocolNoticeRef; source_index: number | null;
  disposition: "EXCLUDED" | "NEEDS_REVIEW"; comparability: "FAIL" | "UNKNOWN"; criteria: AnalogCriterion[];
};
export type OmittedAnalogCandidate = {
  notice: ProtocolNoticeRef;
  reason: "CANDIDATE_NOTICE_PAYLOAD_LIMIT" | "CANDIDATE_TOTAL_PAYLOAD_LIMIT";
  payload_bytes: number; limit_bytes: number;
  measurement_source: "SAVED_NOTICE_LOT_ITEMS_JSONB_OCTET_LENGTH";
};
export const analogUnknownFields = ["coverage", "sample_completeness", "lexical_recall", "source_freshness",
  "supplier_identity", "lot_association", "competition_prediction", "participation", "profit"] as const;
export type AnalogReport = Record<typeof analogUnknownFields[number], "UNKNOWN"> & {
  request: AnalogRequest; checked_at: string; policy_version: "eis-analog-retrieval-v1" | "eis-analog-retrieval-v2";
  scope: "BOUNDED_SAVED_HISTORICAL_TOKEN_PREFILTER"; target: AnalogNotice;
  period_start: string | null; period_end: string | null; candidates: AnalogNotice[]; rows: AnalogRow[];
  selected_notices: number; evaluated_positions: number; excluded_rows: number; review_rows: number;
  selection_truncated: boolean; uninspected_positions: number; reasons: string[]; source_requests: 0;
  omitted_candidates?: OmittedAnalogCandidate[];
};
export type AnalogReadState = { result?: AnalogReport; error?: string };
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const integer = (v: unknown, min: number, max = Number.MAX_SAFE_INTEGER): v is number =>
  typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max;
const nullableText = (v: unknown): v is string | null => v === null || typeof v === "string";
const awareTime = (v: unknown): v is string => typeof v === "string" &&
  /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
export function validAnalogRequest(v: unknown): v is AnalogRequest {
  return record(v) && Object.keys(v).length === 4 && validProtocolRef(v.target) &&
    integer(v.source_index, 1, 25) && typeof v.query === "string" &&
    v.query.trim().length > 0 && [...v.query].length <= 120 && integer(v.lookback_days, 1, 730);
}
export function analogRequestKey(v: AnalogRequest): string {
  return JSON.stringify([v.target.purchase_number, v.target.version_number, v.target.notice_xml_sha256,
    v.source_index, v.query, v.lookback_days]);
}
function evidence(v: unknown): v is AnalogEvidence {
  return record(v) && typeof v.document_id === "string" && /^[0-9a-f]{64}$/.test(v.document_id) &&
    typeof v.locator === "string" && v.locator.length > 0 && v.extractor === "api" &&
    typeof v.confidence === "number" && Number.isFinite(v.confidence) && v.confidence >= 0 && v.confidence <= 1;
}
function fact(v: unknown, sha: string): v is AnalogFact {
  return record(v) && nullableText(v.value) && evidence(v.provenance) && v.provenance.document_id === sha;
}
function notice(v: unknown): v is AnalogNotice {
  if (!record(v) || !validProtocolRef(v.notice) || typeof v.source_member !== "string" || !v.source_member ||
    typeof v.document_type !== "string" || !integer(v.positions_total, 0) ||
    typeof v.lot_parse_status !== "string" || !["PARSED", "UNKNOWN"].includes(v.lot_parse_status) || !Array.isArray(v.positions) ||
    v.positions.length > 25 || v.positions.length > v.positions_total) return false;
  const sha = v.notice.notice_xml_sha256;
  if (![v.published_at, v.deadline].every(f => fact(f, sha) && (f.value === null || awareTime(f.value)))) return false;
  return v.positions.every((p, i) => record(p) && p.source_index === i + 1 &&
    [p.name, p.ktru, p.okpd2, p.quantity, p.unit].every(f => fact(f, sha)) &&
    fact(p.quantity, sha) &&
    (p.quantity.value === null || (p.quantity.value.length <= 64 &&
      /^[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$/.test(p.quantity.value))));
}
// Validate binding, resource bounds, provenance and verdict consistency; do not re-run domain policy in JS.
export function analogReportMatches(v: unknown, request: AnalogRequest): v is AnalogReport {
  if (!record(v) || !validAnalogRequest(v.request) || analogRequestKey(v.request) !== analogRequestKey(request) ||
    typeof v.policy_version !== "string" ||
    !["eis-analog-retrieval-v1", "eis-analog-retrieval-v2"].includes(v.policy_version) ||
    v.scope !== "BOUNDED_SAVED_HISTORICAL_TOKEN_PREFILTER" ||
    v.source_requests !== 0 || !analogUnknownFields.every(k => v[k] === "UNKNOWN") || !awareTime(v.checked_at) ||
    !notice(v.target) || !sameProtocolRef(v.target.notice, request.target) ||
    !v.target.positions.some(p => p.source_index === request.source_index) ||
    ![v.period_start, v.period_end].every(t => t === null || awareTime(t)) ||
    !Array.isArray(v.candidates) || v.candidates.length > 20 || !v.candidates.every(notice) ||
    !Array.isArray(v.rows) || v.rows.length > 500 || typeof v.selection_truncated !== "boolean" ||
    !Array.isArray(v.reasons) || !v.reasons.every(r => typeof r === "string")) return false;
  const candidates = v.candidates as AnalogNotice[];
  const omissions = Object.hasOwn(v, "omitted_candidates") ? v.omitted_candidates : [];
  if ((v.policy_version === "eis-analog-retrieval-v2" && !Object.hasOwn(v, "omitted_candidates")) ||
    !Array.isArray(omissions) || omissions.length + candidates.length > 20 ||
    (v.policy_version === "eis-analog-retrieval-v1" && omissions.length > 0)) return false;
  const omittedNumbers = new Set<string>();
  for (const omitted of omissions) {
    if (!record(omitted) || Object.keys(omitted).length !== 5 || !validProtocolRef(omitted.notice) ||
      !integer(omitted.payload_bytes, 1) || !integer(omitted.limit_bytes, 0, 2 * 1024 * 1024) ||
      omitted.payload_bytes <= omitted.limit_bytes ||
      omitted.measurement_source !== "SAVED_NOTICE_LOT_ITEMS_JSONB_OCTET_LENGTH" ||
      (omitted.reason !== "CANDIDATE_NOTICE_PAYLOAD_LIMIT" && omitted.reason !== "CANDIDATE_TOTAL_PAYLOAD_LIMIT") ||
      (omitted.reason === "CANDIDATE_NOTICE_PAYLOAD_LIMIT" &&
        (omitted.limit_bytes < 1 || omitted.limit_bytes > 256 * 1024)) ||
      (omitted.reason === "CANDIDATE_TOTAL_PAYLOAD_LIMIT" && omitted.payload_bytes > 256 * 1024) ||
      omitted.notice.purchase_number === request.target.purchase_number ||
      candidates.some(c => c.notice.purchase_number === (omitted.notice as ProtocolNoticeRef).purchase_number) ||
      omittedNumbers.has(omitted.notice.purchase_number)) return false;
    omittedNumbers.add(omitted.notice.purchase_number);
  }
  if (new Set(candidates.map(c => c.notice.purchase_number)).size !== candidates.length ||
    candidates.some(c => c.notice.purchase_number === request.target.purchase_number) ||
    v.selected_notices !== candidates.length ||
    v.evaluated_positions !== candidates.reduce((n, c) => n + c.positions.length, 0) ||
    v.uninspected_positions !== candidates.reduce((n, c) => n + c.positions_total - c.positions.length, 0) ||
    v.rows.length !== candidates.reduce((n, c) => n + Math.max(1, c.positions.length), 0)) return false;
  const seen = new Set<string>(); let excluded = 0;
  for (const row of v.rows) {
    if (!record(row) || !validProtocolRef(row.notice)) return false;
    const candidate = candidates.find(c => sameProtocolRef(c.notice, row.notice as ProtocolNoticeRef));
    if (!candidate || !(row.source_index === null ? candidate.positions.length === 0 :
      candidate.positions.some(p => p.source_index === row.source_index))) return false;
    const key = `${candidate.notice.purchase_number}:${row.source_index}`;
    if (seen.has(key)) return false; seen.add(key);
    if (!Array.isArray(row.criteria) || row.criteria.length !== 6 ||
      new Set(row.criteria.map(c => c?.dimension)).size !== 6) return false;
    for (const c of row.criteria) {
      if (!record(c) || !analogDimensions.includes(c.dimension as AnalogDimension) ||
        typeof c.status !== "string" || !["PASS", "FAIL", "UNKNOWN"].includes(c.status) || typeof c.reason !== "string" ||
        !nullableText(c.target_value) || !nullableText(c.candidate_value) || !Array.isArray(c.evidence) ||
        !c.evidence.every(evidence) || ![request.target.notice_xml_sha256, candidate.notice.notice_xml_sha256]
          .every(sha => (c.evidence as AnalogEvidence[]).some(e => e.document_id === sha)) ||
        (["TECHNICAL", "DELIVERY_REGION"].includes(String(c.dimension)) && c.status !== "UNKNOWN")) return false;
    }
    const fail = row.criteria.some(c => c.status === "FAIL");
    if (row.disposition !== (fail ? "EXCLUDED" : "NEEDS_REVIEW") || row.comparability !== (fail ? "FAIL" : "UNKNOWN")) return false;
    if (fail) excluded++;
  }
  return v.excluded_rows === excluded && v.review_rows === v.rows.length - excluded;
}
export async function loadAnalogsForRequest(request: AnalogRequest,
  read: (request: AnalogRequest) => Promise<AnalogReadState>): Promise<AnalogReadState> {
  if (!validAnalogRequest(request)) return { error: "Выберите позицию 1–25, запрос до 120 символов и период 1–730 дней." };
  const snapshot: AnalogRequest = { ...request, target: { ...request.target } };
  try {
    const response = await read(snapshot);
    if (response.result) return analogReportMatches(response.result, snapshot) ? response :
      { error: "Ответ не соответствует выбранной карточке, позиции или условиям. Повторите запрос." };
    return { error: response.error ?? "Историческая выборка сейчас недоступна. Повторите запрос." };
  } catch {
    return { error: "Не удалось прочитать историческую выборку. Проверьте соединение и повторите запрос." };
  }
}
// Input changes and unmount invalidate outstanding responses, including transport errors.
export function createAnalogReadSession() {
  let revision = 0;
  return {
    invalidate() { revision++; },
    async read(request: AnalogRequest, read: (request: AnalogRequest) => Promise<AnalogReadState>) {
      const current = ++revision;
      const state = await loadAnalogsForRequest(request, read);
      return current === revision ? state : undefined;
    },
  };
}
