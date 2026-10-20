import assert from "node:assert/strict";
import test from "node:test";
import fixture from "./fixtures/eis-document-review.json";
import continuation from "./fixtures/eis-document-review-continuation.json";
import { firstReviewCursor, reviewPageMatches, validReviewCursor, validReviewRequest } from "../src/lib/eis-document-review";

test("exact synthetic DOCX page and lossless emoji continuation use Python codepoints", () => {
  assert.ok(reviewPageMatches(fixture, fixture.request, firstReviewCursor));
  assert.equal([...fixture.page.blocks[0].text].length, 16000);
  assert.notEqual(fixture.page.blocks[0].text.length, 16000);
  assert.equal(fixture.page.next_offset, 0);
  assert.equal(fixture.page.next_character_offset, 16000);
  assert.ok(reviewPageMatches(continuation, continuation.request, { offset: 0, character_offset: 16000, limit: 25 }));
});
test("strict request and cursor reject extras, booleans, coercion and out of bounds", () => {
  for (const changed of [{ ...fixture.request, company_id: "foreign" },
    { ...fixture.request, notice: { ...fixture.request.notice, version_number: true } },
    { ...fixture.request, content_uid: "a".repeat(32) },
    { ...fixture.request, expected_document_sha256: "a".repeat(63) }]) assert.equal(validReviewRequest(changed), false);
  for (const cursor of [{ offset: true, character_offset: 0, limit: 25 },
    { offset: "0", character_offset: 0, limit: 25 }, { offset: 0, character_offset: -1, limit: 25 },
    { offset: 0, character_offset: 0, limit: 26 }, { offset: 1000, character_offset: 0, limit: 25 }]) assert.equal(validReviewCursor(cursor), false);
});
test("read never accepts newly created artifact; prepare may", () => {
  const changed = { ...fixture, analysis_created: true };
  assert.equal(reviewPageMatches(changed, fixture.request, firstReviewCursor), false);
  assert.ok(reviewPageMatches(changed, fixture.request, firstReviewCursor, true));
});
test("wrong exact ref, requested cursor and provenance never render as selected evidence", () => {
  for (const mutate of [
    (v: typeof fixture) => { v.request.content_uid = "F".repeat(32); },
    (v: typeof fixture) => { v.request.notice.notice_xml_sha256 = "f".repeat(64); },
    (v: typeof fixture) => { v.page.offset = 1; },
    (v: typeof fixture) => { v.page.character_offset = 1; },
    (v: typeof fixture) => { v.page.blocks[0].provenance.document_id = "f".repeat(64); },
    (v: typeof fixture) => { v.page.blocks[0].character_end = 15999; },
  ]) { const v = structuredClone(fixture); mutate(v); assert.equal(reviewPageMatches(v, fixture.request, firstReviewCursor), false); }
});
test("contradictory counts, completeness, unknown keys and false conclusion are blocked", () => {
  for (const change of [
    { native_text_completeness: "PASS" }, { full_tspec_completeness: "PASS" }, { participation: "PARTICIPATE" },
    { retained_extracted_text_complete: false }, { characters_extracted: 1 }, { source_units_total: 0 },
    { retention_truncated: true }, { page_text_characters: 15999 }, { delivery_lead_indices: [999] },
    { next_character_offset: null }, { next_offset: 1 }, { next_offset: null, next_character_offset: null },
    { invented_fact: true }, { extraction_reasons: ["constructor"] }, { rejection_code: "constructor" },
    { retention_character_limit: 99999 }, { blocks: [] },
  ]) assert.equal(reviewPageMatches({ ...fixture, page: { ...fixture.page, ...change } }, fixture.request, firstReviewCursor), false, JSON.stringify(change));
  assert.equal(reviewPageMatches({ ...fixture, source_requests: 1 }, fixture.request, firstReviewCursor), false);
});
test("continuation cannot silently skip a tail or invent a following block", () => {
  const c = { offset: 0, character_offset: 16000, limit: 25 };
  const v = structuredClone(continuation); v.page.blocks[0].character_start++;
  assert.equal(reviewPageMatches(v, fixture.request, c), false);
  const v2 = structuredClone(continuation); v2.page.blocks[1].block_index++;
  assert.equal(reviewPageMatches(v2, fixture.request, c), false);
});
