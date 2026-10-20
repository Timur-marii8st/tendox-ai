import assert from "node:assert/strict";
import test from "node:test";
import { directoryMatches } from "../src/lib/manufacturer-directory";

const run = "00000000-0000-0000-0000-000000000001";
const record = "0123456789abcdef01234567";
const proposal = "00000000-0000-0000-0000-000000000002";
const sha = "a".repeat(64);
function fixture() {
  return {
    schema_version: "manufacturer-directory-v1", run_id: run, response_sha256: sha,
    evaluated_at: "2026-10-06T12:00:00Z", coverage: "COMPLETE", overall_status: "PASS", review_count: 1,
    records: [{ record_id: record, source_record_index: 1, registry_number: "1", product_name: "Pump",
      source_manufacturer_name: "Factory", record_url: `https://goszakupki.eaeunion.org/erpt/ru/registers/products/list/card/${record}`,
      document_expires_on: "2027-01-01", source_status: "UNKNOWN", review_status: "PASS", status: "PASS",
      reason_codes: ["INDEPENDENT_REVIEW_PASS"], review_evidence: [{ proposal_id: proposal, proposal_sha256: sha,
        decision_id: "00000000-0000-0000-0000-000000000003", decision_sha256: sha, dossier_sha256: sha,
        identity: { legal_name: "Factory", country_code: "RU", identifier_scheme: "INN", registration_id: "1234567890" }, current_status: "PASS" }] }],
    groups: [{ key: { country_code: "RU", identifier_scheme: "INN", registration_id: "1234567890" }, legal_name: "Factory",
      record_ids: [record], product_names: ["Pump"], status: "PASS", reason_codes: ["INDEPENDENT_REVIEW_PASS"], proposal_ids: [proposal], decision_sha256s: [sha] }],
    unreviewed_record_ids: [] as string[], technical: "UNKNOWN", seller: "UNKNOWN", website: "UNKNOWN", quote: "UNKNOWN", participation: "UNKNOWN",
  };
}
test("directory must match exact source snapshot and keeps commercial status unknown", () => {
  assert.ok(directoryMatches(fixture(), run, sha));
  assert.equal(directoryMatches(fixture(), run, "b".repeat(64)), false);
  assert.equal(directoryMatches({ ...fixture(), quote: "PASS" }, run, sha), false);
});
test("unsupported source, record, group and overflow PASS fail closed", () => {
  for (const change of [
    (x: ReturnType<typeof fixture>) => { x.records[0].source_status = "FAIL"; },
    (x: ReturnType<typeof fixture>) => { x.records[0].review_evidence[0].current_status = "FAIL"; },
    (x: ReturnType<typeof fixture>) => { x.groups[0].key.registration_id = "different"; },
    (x: ReturnType<typeof fixture>) => { x.groups[0].legal_name = "Different"; },
    (x: ReturnType<typeof fixture>) => { x.coverage = "INCOMPLETE"; },
    (x: ReturnType<typeof fixture>) => { x.records[0].document_expires_on = "2026-02-30"; },
  ]) {
    const value = fixture(); change(value);
    assert.equal(directoryMatches(value, run, sha), false);
  }
});
test("incomplete bounded selection is UNKNOWN and has no groups", () => {
  const value = fixture();
  value.coverage = "INCOMPLETE"; value.overall_status = "UNKNOWN"; value.review_count = 20;
  value.groups = []; value.records[0].review_status = "UNKNOWN"; value.records[0].status = "UNKNOWN";
  value.records[0].review_evidence = []; value.unreviewed_record_ids = [record];
  value.records[0].reason_codes = ["REVIEW_COVERAGE_INCOMPLETE"];
  assert.ok(directoryMatches(value, run, sha));
});
