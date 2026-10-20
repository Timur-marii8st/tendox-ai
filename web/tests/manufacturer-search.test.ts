import assert from "node:assert/strict";
import test from "node:test";

import { EAEU_PRODUCTS_URL, manufacturerDossierMatches, manufacturerReportMatches, manufacturerSearchSummariesMatch, savedManufacturerSearchMatches, validManufacturerSearchRequest } from "../src/lib/manufacturer-search";

const request = { command_id: "123e4567-e89b-12d3-a456-426614174000", query: "промышленный насос" };
const candidate = { source_record_index: 1, record_id: "a".repeat(24), registry_number: "RU.123", product_name: "Насос", manufacturer_name: "Завод", record_url: `https://goszakupki.eaeunion.org/erpt/ru/registers/products/list/card/${"a".repeat(24)}`, document_expires_on: null, document_validity: "UNKNOWN", document_validity_reason: "EXPIRY_UNKNOWN", role: "MANUFACTURER_SOURCE_DECLARATION", identity: "UNKNOWN", website: "UNKNOWN", seller: "UNKNOWN", brand: "UNKNOWN", technical: "UNKNOWN", quote: "UNKNOWN" } as const;
const report = { schema_version: "manufacturer-search-v1", run_id: "223e4567-e89b-12d3-a456-426614174000", command_id: request.command_id, query: request.query, source: "EAEU_PRODUCTS", source_url: EAEU_PRODUCTS_URL, status: "COMPLETED", reason_code: "VERIFIED_RESPONSE", created_at: "2026-10-06T10:00:00+03:00", finished_at: "2026-10-06T10:00:01+03:00", request_sha256: "b".repeat(64), response_sha256: "c".repeat(64), response_byte_size: 123, matched_count: 1, candidates: [candidate] } as const;

test("validates the bounded saved EAEU response and server command", () => {
  assert.ok(validManufacturerSearchRequest(request));
  assert.ok(manufacturerReportMatches(report));
  assert.ok(savedManufacturerSearchMatches({ report, created: true, source_requests: 1 }, request, true));
});
test("fails closed for incomplete outcomes and unsupported claims", () => {
  const started = { ...report, status: "STARTED", reason_code: "SOURCE_OUTCOME_UNKNOWN", finished_at: null, response_sha256: null, response_byte_size: null, matched_count: null, candidates: [] };
  assert.ok(manufacturerReportMatches(started));
  assert.ok(!manufacturerReportMatches({ ...report, candidates: [{ ...candidate, identity: "PASS" }] }));
  assert.ok(!manufacturerReportMatches({ ...report, source_url: "https://evil.test/" }));
  assert.ok(!manufacturerReportMatches({ ...report, candidates: [{ ...candidate, document_validity: "FAIL", document_validity_reason: "EXPIRY_UNKNOWN" }] }));
  assert.ok(!savedManufacturerSearchMatches({ report, created: false, source_requests: 1 }, request));
});
test("validates list and retained-response dossier linkage", () => {
  assert.ok(manufacturerSearchSummariesMatch([{ run_id: report.run_id, query: report.query, status: report.status, created_at: report.created_at, finished_at: report.finished_at, candidate_count: 1, matched_count: 1 }]));
  const dossier = { run_id: report.run_id, candidate, verified_from_retained_response: true, provenance: { source: "EAEU_PRODUCTS", source_url: EAEU_PRODUCTS_URL, response_sha256: report.response_sha256, source_record_index: 1, field_locators: { record_id: "result[0]._id.$oid", registry_number: "result[0].registrynumber", product_name: "result[0].goodsname", manufacturer_name: "result[0].name", document_expires_on: "result[0].expertactenddate" } } };
  assert.ok(manufacturerDossierMatches(dossier, report.run_id, candidate.record_id));
  assert.ok(!manufacturerDossierMatches({ ...dossier, verified_from_retained_response: false }, report.run_id, candidate.record_id));
  assert.ok(!manufacturerDossierMatches({ ...dossier, provenance: { ...dossier.provenance, field_locators: { ...dossier.provenance.field_locators, manufacturer_name: "result[1].name" } } }));
});

test("rejects changed record links, oversized evidence and impossible dates", () => {
  assert.ok(!manufacturerReportMatches({ ...report, response_byte_size: 524289 }));
  assert.ok(!manufacturerReportMatches({ ...report, candidates: [{ ...candidate, record_url: candidate.record_url.replace("a".repeat(24), "b".repeat(24)) }] }));
  assert.ok(!manufacturerReportMatches({ ...report, candidates: [{ ...candidate, document_expires_on: "2026-02-31", document_validity_reason: "CURRENT_STATUS_UNVERIFIED" }] }));
  assert.ok(!manufacturerReportMatches({ ...report, candidates: [{ ...candidate, document_expires_on: null, document_validity_reason: "CURRENT_STATUS_UNVERIFIED" }] }));
});
