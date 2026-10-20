import test from "node:test";
import assert from "node:assert/strict";
import fixture from "./fixtures/eis-position-association.json";
import { associationMatches, validAssociationRequest, validAssociationListRequest, validAssociationDetailRequest,
  associationListMatches, associationDetailMatches, type SavedAssociation, type AssociationReadScope,
  type AssociationListRequest, type AssociationListResult, type AssociationDetailRequest } from "../src/lib/eis-position-association";
const original = fixture as SavedAssociation;
test("exact two-page Unicode source spans read and replay", () => {
  assert.ok(validAssociationRequest(original.report.request));
  assert.ok(associationMatches(original, original.report.request));
  assert.ok(associationMatches({ ...original, created: true }, original.report.request, true));
  assert.equal(associationMatches({ ...original, created: true }, original.report.request), false);
  assert.equal([...original.report.fragments[0].text].length, 8);
});

const scope: AssociationReadScope = { position: original.report.request.position, document: original.report.request.document,
  analyzer_version: original.report.request.analyzer_version };
const listRequest: AssociationListRequest = { scope, cursor: null, limit: 20 };
const listing: AssociationListResult = { request: listRequest, items: [{ association_id: original.report.association_id,
  created_at: original.report.created_at, linked_by: original.report.linked_by,
  fragment_count: original.report.fragments.length, selected_characters: original.report.selected_characters }],
  next_cursor: null, source_requests: 0, jobs_created: 0, writes: 0 };
const detailRequest: AssociationDetailRequest = { scope, association_id: original.report.association_id };

test("restore accepts exact scope and ID without any client fragment selectors", () => {
  assert.ok(validAssociationListRequest(listRequest)); assert.ok(validAssociationDetailRequest(detailRequest));
  assert.ok(associationListMatches(listing, listRequest)); assert.ok(associationDetailMatches(original, detailRequest));
  assert.ok(associationListMatches({ ...listing, items: [] }, listRequest));
  for (const request of [{ ...listRequest, limit: true }, { ...listRequest, limit: 21 },
    { ...listRequest, cursor: { created_at: original.report.created_at, association_id: "not-uuid" } },
    { ...listRequest, scope: { ...scope, fragments: original.report.request.fragments } },
    { ...detailRequest, association_id: "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA" },
    { ...detailRequest, scope: { ...scope, analyzer_version: "eis-native-v3" } }]) {
    assert.equal(validAssociationListRequest(request) || validAssociationDetailRequest(request), false);
  }
});

test("metadata pages fail closed on request drift, duplicates, writes, unexpected text and dishonest cursor", () => {
  for (const mutate of [
    (v: AssociationListResult) => { v.request.scope.position.selection.source_index++; },
    (v: AssociationListResult) => { v.request.limit = 1; },
    (v: AssociationListResult) => { v.items.push({ ...v.items[0] }); },
    (v: AssociationListResult) => { v.writes = 1 as 0; },
    (v: AssociationListResult) => { v.items[0].fragment_count = 11; },
    (v: AssociationListResult) => { Object.assign(v.items[0], { text: "untrusted" }); },
    (v: AssociationListResult) => { v.next_cursor = { created_at: v.items[0].created_at, association_id: v.items[0].association_id }; },
  ]) { const value = structuredClone(listing); mutate(value); assert.equal(associationListMatches(value, listRequest), false); }
  for (const mutate of [
    (v: SavedAssociation) => { v.report.association_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"; },
    (v: SavedAssociation) => { v.created = true; },
    (v: SavedAssociation) => { v.report.request.position.selection.source_index++; },
    (v: SavedAssociation) => { v.report.document_sha256 = "f".repeat(64); },
  ]) { const value = structuredClone(original); mutate(value); assert.equal(associationDetailMatches(value, detailRequest), false); }
});

test("pagination preserves microseconds and stable UUID ordering, binds cursor exactly", () => {
  const request = { ...listRequest, limit: 2 };
  const a = { ...listing.items[0], created_at: "2026-10-06T08:00:00.123456Z", association_id: "11111111-1111-1111-1111-111111111111" };
  const b = { ...a, created_at: "2026-10-06T08:00:00.123455Z", association_id: "ffffffff-ffff-ffff-ffff-ffffffffffff" };
  const cursor = { created_at: b.created_at, association_id: b.association_id };
  const page: AssociationListResult = { ...listing, request, items: [a, b], next_cursor: cursor };
  assert.ok(associationListMatches(page, request));
  assert.equal(associationListMatches({ ...page, items: [b, a] }, request), false);
  assert.equal(associationListMatches({ ...page, next_cursor: { ...cursor, association_id: a.association_id } }, request), false);
  const nextRequest = { ...request, cursor };
  const c = { ...b, association_id: "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee" };
  const nextPage = { ...page, request: nextRequest, items: [c], next_cursor: null };
  assert.ok(associationListMatches(nextPage, nextRequest));
  assert.equal(associationListMatches({ ...nextPage, items: [b] }, nextRequest), false);
  assert.equal(associationListMatches(nextPage, { ...nextRequest, cursor: { ...cursor, created_at: a.created_at } }), false);
});
test("request selectors reject overlap, foreign notice, extra text and coercion", () => {
  for (const mutate of [
    (r: typeof original.report.request) => { r.fragments.push({ ...r.fragments[0] }); },
    (r: typeof original.report.request) => { r.document.notice.notice_xml_sha256 = "f".repeat(64); },
    (r: typeof original.report.request) => { Object.assign(r.fragments[0], { text: "подмена" }); },
    (r: typeof original.report.request) => { r.fragments[0].character_start = true as unknown as number; },
    (r: typeof original.report.request) => { r.fragments[0].character_end = 16001; },
  ]) { const request = structuredClone(original.report.request); mutate(request); assert.equal(validAssociationRequest(request), false); }
});
test("source SHA, range, counts, revision and UNKNOWN claims fail closed", () => {
  for (const mutate of [
    (v: SavedAssociation) => { v.report.fragments[0].provenance.document_id = "f".repeat(64); },
    (v: SavedAssociation) => { v.report.fragments[0].provenance.locator = "fake locator"; },
    (v: SavedAssociation) => { v.report.fragments[0].text += "x"; },
    (v: SavedAssociation) => { v.report.fragments[0].source_character_count = 7; },
    (v: SavedAssociation) => { v.report.selected_characters = 15; },
    (v: SavedAssociation) => { v.report.retained_total = 25; },
    (v: SavedAssociation) => { v.report.request.analyzer_version = "eis-native-v3" as "eis-native-review-v1"; },
    (v: SavedAssociation) => { v.report.technical = "PASS" as "UNKNOWN"; },
    (v: SavedAssociation) => { Object.assign(v.report, { company_id: "foreign" }); },
  ]) { const value = structuredClone(original); mutate(value); assert.equal(associationMatches(value, original.report.request), false); }
});
