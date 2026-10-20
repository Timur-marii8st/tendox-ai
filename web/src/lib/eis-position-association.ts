import { validSupplierSearchRequest, supplierSearchRequestKey, type SupplierSearchRequest } from "./eis-supplier-search";
import { validReviewRequest, reviewRequestKey, type ReviewRequest } from "./eis-document-review";
import { sameProtocolRef } from "./eis-protocols";
import type { SourceProvenance, TextFact } from "./eis-characteristics";

export type FragmentSelection = { block_index: number; character_start: number; character_end: number };
export type AssociationRequest = { position: SupplierSearchRequest; document: ReviewRequest;
  analyzer_version: "eis-native-review-v1"; fragments: FragmentSelection[] };
export type AssociatedFragment = { selection: FragmentSelection; text: string;
  provenance: SourceProvenance; source_character_count: number };
export type AssociationReport = { policy_version: "eis-position-fragment-association-v1";
  association_id: string; request: AssociationRequest; position_sha256: string; position_name: TextFact;
  analysis_sha256: string; document_sha256: string; filename: string; observation_id: string; observed_at: string;
  analyzed_at: string; created_at: string; linked_by: string; fragments: AssociatedFragment[];
  retained_total: number; retained_characters: number; selected_characters: number;
  association_status: "OPERATOR_LINKED"; requirement_status: "UNKNOWN";
  full_tspec_completeness: "UNKNOWN"; technical: "UNKNOWN"; quote: "UNKNOWN";
  participation: "UNKNOWN"; source_requests: 0; jobs_created: 0 };
export type SavedAssociation = { report: AssociationReport; created: boolean };
export type AssociationState = { result?: SavedAssociation; error?: string };
export type AssociationReadScope = Omit<AssociationRequest, "fragments">;
export type AssociationCursor = { created_at: string; association_id: string };
export type AssociationListRequest = { scope: AssociationReadScope; cursor: AssociationCursor | null; limit: number };
export type AssociationMetadata = AssociationCursor & { linked_by: string; fragment_count: number; selected_characters: number };
export type AssociationListResult = { request: AssociationListRequest; items: AssociationMetadata[];
  next_cursor: AssociationCursor | null; source_requests: 0; jobs_created: 0; writes: 0 };
export type AssociationDetailRequest = { scope: AssociationReadScope; association_id: string };
export type AssociationListState = { result?: AssociationListResult; error?: string };
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const keys = (v: Record<string, unknown>, names: string) => {
  const expected = names.split(" "); return Object.keys(v).length === expected.length && expected.every(k => Object.hasOwn(v, k));
};
const integer = (v: unknown, min: number, max: number): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max;
const text = (v: unknown, max = 4096): v is string => typeof v === "string" && [...v].length > 0 && [...v].length <= max;
const sha = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
const time = (v: unknown) => typeof v === "string" && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
const uuid = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v);
function span(v: unknown): v is FragmentSelection {
  return record(v) && keys(v, "block_index character_start character_end") && integer(v.block_index, 0, 999) &&
    integer(v.character_start, 0, 99999) && integer(v.character_end, 1, 100000) && v.character_end > v.character_start;
}
export function validAssociationRequest(v: unknown): v is AssociationRequest {
  if (!record(v) || !keys(v, "position document analyzer_version fragments") || !validSupplierSearchRequest(v.position) ||
    !validReviewRequest(v.document) || !sameProtocolRef(v.position.selection.notice, v.document.notice) ||
    v.analyzer_version !== "eis-native-review-v1" || !Array.isArray(v.fragments) || !v.fragments.length || v.fragments.length > 10) return false;
  let previous: FragmentSelection | undefined, characters = 0;
  for (const f of v.fragments) {
    if (!span(f) || (previous && (f.block_index < previous.block_index ||
      (f.block_index === previous.block_index && f.character_start < previous.character_end)))) return false;
    characters += f.character_end - f.character_start; previous = f;
  }
  return characters <= 16000;
}
export function associationRequestKey(v: AssociationRequest): string {
  return JSON.stringify([supplierSearchRequestKey(v.position), reviewRequestKey(v.document), v.analyzer_version,
    v.fragments.map(f => [f.block_index, f.character_start, f.character_end])]);
}
function provenance(v: unknown, digest: string, native: boolean): v is SourceProvenance {
  return record(v) && keys(v, "document_id locator extractor confidence") && v.document_id === digest && text(v.locator) &&
    v.extractor === (native ? "native_docx" : "api") && typeof v.confidence === "number" && Number.isFinite(v.confidence) && v.confidence >= 0 && v.confidence <= 1;
}
export function associationMatches(v: unknown, request: AssociationRequest, save = false): v is SavedAssociation {
  if (!validAssociationRequest(request) || !record(v) || !keys(v, "report created") || typeof v.created !== "boolean" || (!save && v.created) || !record(v.report)) return false;
  const r = v.report;
  if (!keys(r, "policy_version association_id request position_sha256 position_name analysis_sha256 document_sha256 filename observation_id observed_at analyzed_at created_at linked_by fragments retained_total retained_characters selected_characters association_status requirement_status full_tspec_completeness technical quote participation source_requests jobs_created") ||
    r.policy_version !== "eis-position-fragment-association-v1" || !validAssociationRequest(r.request) || associationRequestKey(r.request) !== associationRequestKey(request) ||
    typeof r.association_id !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(r.association_id) ||
    !sha(r.position_sha256) || !sha(r.analysis_sha256) || r.document_sha256 !== request.document.expected_document_sha256 ||
    !text(r.filename, 1024) || /[\\/\x00:]/.test(r.filename) || !/\.docx$/i.test(r.filename) ||
    !text(r.observation_id, 200) || !text(r.linked_by, 200) || !time(r.observed_at) || !time(r.analyzed_at) || !time(r.created_at) ||
    !integer(r.retained_total, 1, 1000) || !integer(r.retained_characters, 1, 100000) || !integer(r.selected_characters, 1, 16000) ||
    r.selected_characters > r.retained_characters || r.association_status !== "OPERATOR_LINKED" ||
    ![r.requirement_status, r.full_tspec_completeness, r.technical, r.quote, r.participation].every(x => x === "UNKNOWN") ||
    r.source_requests !== 0 || r.jobs_created !== 0 || !Array.isArray(r.fragments) || r.fragments.length !== request.fragments.length) return false;
  if (!record(r.position_name) || !keys(r.position_name, "value raw provenance") ||
    ![r.position_name.value, r.position_name.raw].every(x => x === null || text(x)) ||
    !provenance(r.position_name.provenance, request.position.selection.notice.notice_xml_sha256, false)) return false;
  let total = 0;
  for (let i = 0; i < r.fragments.length; i++) {
    const f = r.fragments[i], expected = request.fragments[i];
    if (!record(f) || !keys(f, "selection text provenance source_character_count") || !span(f.selection) ||
      f.selection.block_index !== expected.block_index || f.selection.character_start !== expected.character_start || f.selection.character_end !== expected.character_end ||
      f.selection.block_index >= r.retained_total || !integer(f.source_character_count, 1, 100000) || f.selection.character_end > f.source_character_count ||
      !text(f.text, 16000) || [...f.text].length !== expected.character_end - expected.character_start ||
      !provenance(f.provenance, request.document.expected_document_sha256, true) ||
      !f.provenance.locator.endsWith(` :: characters[${expected.character_start}:${expected.character_end}]`)) return false;
    total += [...f.text].length;
  }
  return total === r.selected_characters;
}

export function validAssociationScope(v: unknown): v is AssociationReadScope {
  return record(v) && keys(v, "position document analyzer_version") && validSupplierSearchRequest(v.position) &&
    validReviewRequest(v.document) && sameProtocolRef(v.position.selection.notice, v.document.notice) && v.analyzer_version === "eis-native-review-v1";
}
export function associationScopeKey(v: AssociationReadScope): string {
  return JSON.stringify([supplierSearchRequestKey(v.position), reviewRequestKey(v.document), v.analyzer_version]);
}
function validCursor(v: unknown): v is AssociationCursor {
  return record(v) && keys(v, "created_at association_id") && time(v.created_at) && uuid(v.association_id);
}
export function validAssociationListRequest(v: unknown): v is AssociationListRequest {
  return record(v) && keys(v, "scope cursor limit") && validAssociationScope(v.scope) &&
    (v.cursor === null || validCursor(v.cursor)) && integer(v.limit, 1, 20);
}
export function validAssociationDetailRequest(v: unknown): v is AssociationDetailRequest {
  return record(v) && keys(v, "scope association_id") && validAssociationScope(v.scope) && uuid(v.association_id);
}
function cursorKey(v: AssociationCursor | null) { return v === null ? "" : JSON.stringify([v.created_at, v.association_id]); }
// Preserve microseconds; Date.parse alone would merge distinct PostgreSQL timestamps.
function instant(v: string): bigint | undefined {
  const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/.exec(v);
  if (!match) return undefined;
  const milliseconds = Date.parse(match[1] + match[3]);
  return Number.isFinite(milliseconds) ? BigInt(milliseconds) * BigInt(1000) + BigInt((match[2] ?? "").padEnd(6, "0")) : undefined;
}
function earlier(a: AssociationCursor, b: AssociationCursor): boolean {
  const left = instant(a.created_at), right = instant(b.created_at);
  return left !== undefined && right !== undefined && (left < right || (left === right && a.association_id < b.association_id));
}
export function associationListMatches(v: unknown, request: AssociationListRequest): v is AssociationListResult {
  if (!validAssociationListRequest(request) || !record(v) || !keys(v, "request items next_cursor source_requests jobs_created writes") ||
    !validAssociationListRequest(v.request) || associationScopeKey(v.request.scope) !== associationScopeKey(request.scope) ||
    cursorKey(v.request.cursor) !== cursorKey(request.cursor) || v.request.limit !== request.limit ||
    v.source_requests !== 0 || v.jobs_created !== 0 || v.writes !== 0 || !Array.isArray(v.items) || v.items.length > request.limit) return false;
  let previous = request.cursor;
  const ids = new Set<string>();
  for (const item of v.items) {
    if (!record(item) || !keys(item, "association_id created_at linked_by fragment_count selected_characters") ||
      !uuid(item.association_id) || !time(item.created_at) || instant(item.created_at as string) === undefined ||
      !text(item.linked_by, 200) || !integer(item.fragment_count, 1, 10) || !integer(item.selected_characters, 1, 16000) ||
      item.selected_characters < item.fragment_count || ids.has(item.association_id) ||
      (previous && !earlier(item as AssociationMetadata, previous))) return false;
    ids.add(item.association_id); previous = item as AssociationMetadata;
  }
  if (v.next_cursor === null) return true;
  return validCursor(v.next_cursor) && v.items.length === request.limit && previous !== null &&
    cursorKey(v.next_cursor) === cursorKey(previous);
}
export function associationDetailMatches(v: unknown, request: AssociationDetailRequest): v is SavedAssociation {
  return validAssociationDetailRequest(request) && record(v) && record(v.report) &&
    validAssociationRequest(v.report.request) && associationScopeKey(v.report.request) === associationScopeKey(request.scope) &&
    v.report.association_id === request.association_id && associationMatches(v, v.report.request);
}
