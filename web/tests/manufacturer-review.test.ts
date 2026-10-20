import assert from "node:assert/strict";
import test from "node:test";
import { artifactMatches, savedDecisionMatches, savedProposalMatches, validArtifactCommand, validDecisionCommand, validProposalCommand, type DecisionCommand, type ManufacturerProposal } from "../src/lib/manufacturer-review";

const uuid = (n: number) => `${n}23e4567-e89b-12d3-a456-42661417400${n}`;
const artifact = { artifact_id: uuid(1), command_id: uuid(2), source_title: "Реестр", source_url: "https://example.test/source", origin_status: "CLAIMED_BY_UPLOADER", original_filename: "a.pdf", media_type: "application/pdf", byte_size: 8, sha256: "a".repeat(64), uploaded_by: "operator-a", uploaded_at: "2026-10-06T10:00:00Z" } as const;
const proposalCommand = { command_id: uuid(3), run_id: uuid(4), record_id: "a".repeat(24), claimed_identity: { legal_name: "ООО Завод", country_code: "RU", identifier_scheme: "INN", registration_id: "123" }, citations: [{ artifact_id: artifact.artifact_id, artifact_sha256: artifact.sha256, page: 1, locator: "строка 2", quote: "Изготовитель: ООО Завод", claims: ["COUNTRY", "IDENTIFIER_SCHEME", "LEGAL_NAME", "MANUFACTURER_ROLE", "REGISTRATION_ID"] }] } as const;
const proposal: ManufacturerProposal = { schema_version: "manufacturer-review-proposal-v1", proposal_id: uuid(5), command_id: proposalCommand.command_id, dossier: { run_id: proposalCommand.run_id, record_id: proposalCommand.record_id, response_sha256: "b".repeat(64), source_record_index: 1, registry_number: "EAEU-1", product_name: "Бумага", source_manufacturer_name: "Завод", record_url: `https://goszakupki.eaeunion.org/erpt/ru/registers/products/list/card/${proposalCommand.record_id}`, document_expires_on: null, role: "MANUFACTURER_SOURCE_DECLARATION" }, dossier_sha256: "c".repeat(64), claimed_identity: proposalCommand.claimed_identity, citations: proposalCommand.citations.map(c => ({ ...c, claims: [...c.claims] })), proposed_by: "operator-a", proposed_at: "2026-10-06T10:00:00Z", proposal_sha256: "d".repeat(64) };
const decision: DecisionCommand = { command_id: uuid(6), identity_status: "PASS", role_status: "PASS", official_origin_confirmed: true, identity_fields_confirmed: true, exact_product_link_confirmed: true, effective_until: "2027-10-06T10:00:00Z", rationale: "Проверены реквизиты и точная товарная запись.", citation_indexes: [0] };

test("artifact command and response validation are fail-closed", () => {
  assert.ok(artifactMatches(artifact));
  assert.ok(!artifactMatches({ ...artifact, media_type: "text/plain" }));
  assert.ok(validArtifactCommand({ command_id: artifact.command_id, source_title: artifact.source_title, source_url: artifact.source_url, original_filename: artifact.original_filename, content_base64: "JVBERg==" }));
  assert.ok(!validArtifactCommand({ command_id: artifact.command_id, source_title: artifact.source_title, source_url: "http://example.test", original_filename: artifact.original_filename, content_base64: "JVBERg==" }));
});

test("proposal response must echo the exact persisted command", () => {
  assert.ok(validProposalCommand(proposalCommand));
  assert.ok(savedProposalMatches({ proposal, created: true }, proposalCommand));
  assert.ok(!savedProposalMatches({ proposal: { ...proposal, command_id: uuid(7) }, created: true }, proposalCommand));
});

test("PASS requires selected claims, confirmations and future expiry", () => {
  const now = new Date("2026-10-06T11:00:00Z");
  assert.ok(validDecisionCommand(decision, proposal, now));
  assert.ok(!validDecisionCommand({ ...decision, official_origin_confirmed: false }, proposal, now));
  assert.ok(!validDecisionCommand({ ...decision, effective_until: "2026-10-06T10:00:00Z" }, proposal, now));
  assert.ok(!validDecisionCommand({ ...decision, citation_indexes: [1] }, proposal, now));
  assert.ok(!validDecisionCommand({ ...decision, identity_status: "UNKNOWN", role_status: "PASS" }, proposal, now));
});

test("decision response is bound to proposal and exact command", () => {
  const saved = { decision: { schema_version: "manufacturer-review-decision-v1", decision_id: uuid(7), ...decision, proposal_id: proposal.proposal_id, proposal_sha256: proposal.proposal_sha256, dossier_sha256: proposal.dossier_sha256, reviewed_by: "reviewer-b", reviewed_at: "2026-10-06T11:00:00Z", decision_sha256: "e".repeat(64) }, current_status: "PASS", created: true };
  assert.ok(savedDecisionMatches(saved, proposal, decision, [artifact]));
  assert.ok(!savedDecisionMatches({ ...saved, decision: { ...saved.decision, rationale: "Другое" } }, proposal, decision));
  assert.ok(!savedDecisionMatches({ ...saved, decision: { ...saved.decision, reviewed_by: proposal.proposed_by } }, proposal, decision, [artifact]));
  assert.ok(!savedDecisionMatches({ ...saved, decision: { ...saved.decision, reviewed_by: artifact.uploaded_by } }, proposal, decision, [artifact]));
});

test("GET rejects unsupported PASS and accepts historically valid expired PASS as current FAIL", () => {
  const baseDecision = { schema_version: "manufacturer-review-decision-v1", decision_id: uuid(7), ...decision, proposal_id: proposal.proposal_id, proposal_sha256: proposal.proposal_sha256, dossier_sha256: proposal.dossier_sha256, reviewed_by: "reviewer-b", reviewed_at: "2026-10-06T11:00:00Z", decision_sha256: "e".repeat(64) } as const;
  assert.ok(!savedDecisionMatches({ decision: { ...baseDecision, official_origin_confirmed: false }, current_status: "PASS", created: false }, proposal, undefined, [artifact], new Date("2026-10-07T00:00:00Z")));
  assert.ok(!savedDecisionMatches({ decision: { ...baseDecision, citation_indexes: [1] }, current_status: "PASS", created: false }, proposal, undefined, [artifact], new Date("2026-10-07T00:00:00Z")));
  const expired = { ...baseDecision, effective_until: "2026-10-07T00:00:00Z" };
  assert.ok(!savedDecisionMatches({ decision: expired, current_status: "PASS", created: false }, proposal, undefined, [artifact], new Date("2026-10-08T00:00:00Z")));
  assert.ok(savedDecisionMatches({ decision: expired, current_status: "FAIL", created: false }, proposal, undefined, [artifact], new Date("2026-10-08T00:00:00Z")));
});

test("proposal rejects mismatched record URL and impossible calendar date", () => {
  assert.ok(!savedProposalMatches({ proposal: { ...proposal, dossier: { ...proposal.dossier, record_url: `https://goszakupki.eaeunion.org/erpt/ru/registers/products/list/card/${"b".repeat(24)}` } }, created: false }));
  assert.ok(!savedProposalMatches({ proposal: { ...proposal, dossier: { ...proposal.dossier, document_expires_on: "2026-02-30" } }, created: false }));
});
