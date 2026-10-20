import { sameProtocolRef, validProtocolRef, type ProtocolNoticeRef } from "./eis-protocols";
import type { SourceProvenance } from "./eis-characteristics";

export type ReviewRequest = { notice: ProtocolNoticeRef; content_uid: string; expected_document_sha256: string };
export type ReviewCursor = { offset: number; character_offset: number; limit: number };
export type ReviewPageBlock = { block_index: number; character_start: number; character_end: number;
  source_character_count: number; text: string; provenance: SourceProvenance; text_truncated: boolean };
export type ReviewPage = {
  review_version: "eis-native-review-v1"; sha256: string; filename: string; byte_count: number;
  extraction_input_byte_limit: 4194304; extraction_expanded_byte_limit: 33554432;
  extraction_source_unit_limit: 20000; extraction_character_limit: 1000000;
  extraction_status: "PASS" | "FAIL" | "UNKNOWN"; extraction_reasons: string[]; rejection_code: string | null;
  source_units_total: number | null; source_units_extracted: number | null;
  characters_extracted: number | null; blocks_extracted_total: number | null;
  offset: number; character_offset: number; limit: number; retained_total: number; retained_characters: number;
  retention_truncated: boolean; retention_reasons: string[]; retention_block_limit: 1000;
  retention_character_limit: 100000; text_scope: "SUPPORTED_DOCX_BODY_PARAGRAPHS_AND_TABLES";
  retained_extracted_text_complete: boolean; native_text_completeness: "UNKNOWN";
  page_start: number; next_offset: number | null; next_character_offset: number | null;
  blocks: ReviewPageBlock[]; page_text_characters: number; page_text_truncated: boolean;
  page_reasons: string[]; delivery_lead_indices: number[]; structured_delivery: "UNKNOWN";
  document_role: "UNKNOWN"; position_association: "UNKNOWN"; approved_requirements: "UNKNOWN";
  full_tspec_completeness: "UNKNOWN"; participation: "UNKNOWN";
};
export type SavedReviewPage = {
  request: ReviewRequest; filename: string; source_url: string; source_locator: string;
  observation_id: string; observed_at: string; analyzed_at: string; analysis_created: boolean;
  page: ReviewPage; source_requests: 0; jobs_created: 0; requirement_status: "UNKNOWN";
  document_role: "UNKNOWN"; position_association: "UNKNOWN"; full_tspec_completeness: "UNKNOWN";
};
export type ReviewReadState = { result?: SavedReviewPage; error?: string };
export const firstReviewCursor: ReviewCursor = { offset: 0, character_offset: 0, limit: 25 };
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const keys = (v: Record<string, unknown>, names: string) => {
  const expected = names.split(" ");
  return Object.keys(v).length === expected.length && expected.every(k => Object.hasOwn(v, k));
};
const integer = (v: unknown, min: number, max: number): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max;
const text = (v: unknown, max = 4096): v is string => typeof v === "string" && [...v].length > 0 && [...v].length <= max;
const filename = (v: unknown): v is string => text(v, 1024) && !/[\\/\x00:]/.test(v) && /\.docx$/i.test(v) && v !== ".docx";
const time = (v: unknown) => typeof v === "string" && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
const list = (v: unknown, allowed: readonly string[], max: number): v is string[] => Array.isArray(v) && v.length <= max && v.every(x => typeof x === "string" && allowed.includes(x));
const extractionReasons = ["OCR_REQUIRED", "UNSUPPORTED_FORMAT", "EXTERNAL_LINKS_IGNORED", "EMBEDDED_MEDIA_IGNORED", "FORMULAS_IGNORED", "UNSUPPORTED_SOURCE_UNITS", "LAYOUT_NOT_VERIFIED", "CONVERTER_UNAVAILABLE", "DOCUMENT_REJECTED"];
const rejections = ["INPUT_TOO_LARGE", "FILENAME_INVALID", "MEDIA_TYPE_MISMATCH", "MAGIC_MISMATCH", "MACRO_ENABLED_FORMAT", "ENCRYPTED_DOCUMENT", "MALFORMED_CONTAINER", "ZIP_MEMBER_LIMIT", "ZIP_EXPANSION_LIMIT", "SOURCE_UNIT_LIMIT", "EXTRACTED_TEXT_LIMIT", "PARSE_FAILED", "UNSUPPORTED_BIFF_VERSION", "UNSUPPORTED_DOC_VERSION", "CONVERTER_RESOURCE_LIMIT"];
export function validReviewRequest(v: unknown): v is ReviewRequest {
  return record(v) && keys(v, "notice content_uid expected_document_sha256") && validProtocolRef(v.notice) &&
    typeof v.content_uid === "string" && /^[0-9A-F]{32}$/.test(v.content_uid) &&
    typeof v.expected_document_sha256 === "string" && /^[0-9a-f]{64}$/.test(v.expected_document_sha256);
}
export function validReviewCursor(v: unknown): v is ReviewCursor {
  return record(v) && keys(v, "offset character_offset limit") && integer(v.offset, 0, 999) &&
    integer(v.character_offset, 0, 99999) && integer(v.limit, 1, 25);
}
export function reviewRequestKey(v: ReviewRequest): string { return JSON.stringify([v.notice.purchase_number,
  v.notice.version_number, v.notice.notice_xml_sha256, v.content_uid, v.expected_document_sha256]); }

export function reviewPageMatches(value: unknown, request: ReviewRequest, cursor: ReviewCursor,
  allowCreated = false): value is SavedReviewPage {
  if (!validReviewRequest(request) || !validReviewCursor(cursor) || !record(value) ||
    !keys(value, "request filename source_url source_locator observation_id observed_at analyzed_at analysis_created page source_requests jobs_created requirement_status document_role position_association full_tspec_completeness") ||
    !validReviewRequest(value.request) || !sameProtocolRef(value.request.notice, request.notice) ||
    reviewRequestKey(value.request) !== reviewRequestKey(request) || !filename(value.filename) ||
    !text(value.source_url) || !text(value.source_locator) || !text(value.observation_id, 128) ||
    !time(value.observed_at) || !time(value.analyzed_at) || typeof value.analysis_created !== "boolean" ||
    (!allowCreated && value.analysis_created) || value.source_requests !== 0 || value.jobs_created !== 0 ||
    [value.requirement_status, value.document_role, value.position_association, value.full_tspec_completeness].some(x => x !== "UNKNOWN")) return false;
  const p = value.page;
  if (!record(p) || !keys(p, "review_version sha256 filename byte_count extraction_input_byte_limit extraction_expanded_byte_limit extraction_source_unit_limit extraction_character_limit extraction_status extraction_reasons rejection_code source_units_total source_units_extracted characters_extracted blocks_extracted_total offset character_offset limit retained_total retained_characters retention_truncated retention_reasons retention_block_limit retention_character_limit text_scope retained_extracted_text_complete native_text_completeness page_start next_offset next_character_offset blocks page_text_characters page_text_truncated page_reasons delivery_lead_indices structured_delivery document_role position_association approved_requirements full_tspec_completeness participation") ||
    p.review_version !== "eis-native-review-v1" || p.sha256 !== request.expected_document_sha256 || p.filename !== value.filename ||
    !integer(p.byte_count, 1, 4194304) || p.extraction_input_byte_limit !== 4194304 || p.extraction_expanded_byte_limit !== 33554432 ||
    p.extraction_source_unit_limit !== 20000 || p.extraction_character_limit !== 1000000 ||
    !["PASS", "FAIL", "UNKNOWN"].includes(String(p.extraction_status)) || !list(p.extraction_reasons, extractionReasons, 16) ||
    !(p.rejection_code === null || (typeof p.rejection_code === "string" && rejections.includes(p.rejection_code))) ||
    p.offset !== cursor.offset || p.character_offset !== cursor.character_offset || p.limit !== cursor.limit || p.page_start !== p.offset ||
    !integer(p.retained_total, 0, 1000) || !integer(p.retained_characters, 0, 100000) ||
    typeof p.retention_truncated !== "boolean" || !list(p.retention_reasons, ["RETAINED_BLOCK_LIMIT", "RETAINED_CHARACTER_LIMIT"], 2) ||
    p.retention_block_limit !== 1000 || p.retention_character_limit !== 100000 || p.text_scope !== "SUPPORTED_DOCX_BODY_PARAGRAPHS_AND_TABLES" ||
    typeof p.retained_extracted_text_complete !== "boolean" ||
    [p.native_text_completeness, p.structured_delivery, p.document_role, p.position_association, p.approved_requirements, p.full_tspec_completeness, p.participation].some(x => x !== "UNKNOWN") ||
    !Array.isArray(p.blocks) || p.blocks.length > cursor.limit || !integer(p.page_text_characters, 0, 16000) ||
    typeof p.page_text_truncated !== "boolean" || !list(p.page_reasons, ["PAGE_TEXT_LIMIT"], 1) ||
    !Array.isArray(p.delivery_lead_indices) || p.delivery_lead_indices.length > 25) return false;
  const totals = [p.source_units_total, p.source_units_extracted, p.characters_extracted, p.blocks_extracted_total];
  if (p.rejection_code !== null) {
    if (p.extraction_status !== "UNKNOWN" || !p.extraction_reasons.includes("DOCUMENT_REJECTED") || totals.some(x => x !== null) ||
      p.retained_total !== 0 || p.retained_characters !== 0 || p.retention_truncated || p.retained_extracted_text_complete) return false;
  } else {
    if (!integer(p.source_units_total, 0, 20000) || !integer(p.source_units_extracted, 0, 20000) ||
      !integer(p.characters_extracted, 0, 1000000) || !integer(p.blocks_extracted_total, 0, 20000) ||
      p.source_units_extracted > p.source_units_total || p.source_units_extracted !== p.blocks_extracted_total ||
      p.retained_total > p.blocks_extracted_total || p.retained_characters > p.characters_extracted ||
      p.retention_truncated !== (p.retained_total < p.blocks_extracted_total) ||
      (p.retention_truncated ? p.retained_characters >= p.characters_extracted : p.retained_characters !== p.characters_extracted)) return false;
  }
  if (p.retention_truncated !== !!p.retention_reasons.length || p.retained_extracted_text_complete !==
    (p.rejection_code === null && !p.retention_truncated && p.retained_total > 0 && p.retained_characters > 0)) return false;
  const blocks = p.blocks;
  let chars = 0;
  for (let i = 0; i < p.blocks.length; i++) {
    const b = p.blocks[i];
    if (!record(b) || !keys(b, "block_index character_start character_end source_character_count text provenance text_truncated") ||
      b.block_index !== cursor.offset + i || !integer(b.block_index, 0, p.retained_total - 1) ||
      !integer(b.character_start, 0, 99999) || !integer(b.character_end, 1, 100000) ||
      !integer(b.source_character_count, 1, p.retained_characters) || b.character_start >= b.character_end || b.character_end > b.source_character_count ||
      !text(b.text, 16000) || [...b.text].length !== b.character_end - b.character_start ||
      b.character_start !== (i === 0 ? cursor.character_offset : 0) ||
      (i < p.blocks.length - 1 && b.character_end !== b.source_character_count) ||
      b.text_truncated !== (b.character_start !== 0 || b.character_end !== b.source_character_count) ||
      !record(b.provenance) || !keys(b.provenance, "document_id locator extractor confidence") ||
      b.provenance.document_id !== p.sha256 || !text(b.provenance.locator) || b.provenance.extractor !== "native_docx" ||
      typeof b.provenance.confidence !== "number" || !Number.isFinite(b.provenance.confidence) || b.provenance.confidence < 0 || b.provenance.confidence > 1) return false;
    chars += [...b.text].length;
  }
  if (chars !== p.page_text_characters || chars > p.retained_characters ||
    p.page_text_truncated !== p.blocks.some(b => b.text_truncated) || p.page_text_truncated !== !!p.page_reasons.length ||
    new Set(p.delivery_lead_indices).size !== p.delivery_lead_indices.length ||
    p.delivery_lead_indices.some(x => !integer(x, 0, 999) || !blocks.some(b => b.block_index === x))) return false;
  if ((p.next_offset === null) !== (p.next_character_offset === null)) return false;
  const last = p.blocks.at(-1);
  if (!last) {
    if (cursor.offset < p.retained_total || cursor.character_offset !== 0 || p.next_offset !== null) return false;
  } else if (p.next_offset === null) {
    if (last.block_index + 1 !== p.retained_total || last.character_end !== last.source_character_count) return false;
  } else {
    if (!integer(p.next_offset, 0, p.retained_total - 1) || !integer(p.next_character_offset, 0, 99999)) return false;
    if (last.character_end < last.source_character_count) {
      if (p.next_offset !== last.block_index || p.next_character_offset !== last.character_end || chars !== 16000) return false;
    } else if (p.next_offset !== last.block_index + 1 || p.next_character_offset !== 0 ||
      (p.blocks.length < cursor.limit && chars < 16000)) return false;
  }
  return new TextEncoder().encode(JSON.stringify(value)).length <= 256 * 1024;
}
