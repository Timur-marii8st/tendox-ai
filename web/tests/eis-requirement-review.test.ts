import assert from "node:assert/strict";
import test from "node:test";
import fixture from "./fixtures/eis-requirement-review.json";
import { validProposalRequest, validDecisionRequest, proposalMatches, decisionMatches, comparisonMatches, savedProposalMatches, paperFormat } from "../src/lib/eis-requirement-review";
test("exact synthetic proposal decision comparison retain unknown rows",() => {
  assert.ok(validProposalRequest(fixture.proposal_request)); assert.ok(proposalMatches(fixture.proposal,fixture.proposal_request));
  assert.ok(validDecisionRequest(fixture.decision_request)); assert.ok(decisionMatches(fixture.decision,fixture.proposal));
  assert.ok(comparisonMatches(fixture.comparison,fixture.proposal)); assert.ok(comparisonMatches(fixture.mandatory_failure)); assert.ok(comparisonMatches(fixture.unconfirmed));
  assert.ok(savedProposalMatches({proposal:fixture.proposal,created:true,source_requests:0,jobs_created:0},fixture.proposal_request));
});
test("closed format grammar does not normalize grade tolerance or lowercase",() => {
  for (const v of ["A4","А4"]) assert.equal(paperFormat(v),"A4");
  for (const v of ["a4","В 4","не ниже С","A4 или A3","A11","80 ± 3"]) assert.equal(paperFormat(v),null);
});
test("reject missing rows stale source and caller execution permissions",() => {
  const missing = structuredClone(fixture.proposal); missing.request.rows.pop(); assert.ok(!proposalMatches(missing));
  const stale = structuredClone(fixture.proposal); stale.request.expected_preview_sha256 = "f".repeat(64); assert.ok(!proposalMatches(stale));
  assert.ok(!validProposalRequest({...fixture.proposal_request,approved:true}));
  assert.ok(!proposalMatches({...fixture.proposal,source_requests:1}));
});
test("reject selfreview digest binding substitution and unknown confirmation",() => {
  const own = structuredClone(fixture.decision); own.reviewed_by = own.proposal.prepared_by; assert.ok(!decisionMatches(own));
  const substituted = structuredClone(fixture.decision); substituted.request.expected_proposal_sha256 = "f".repeat(64); assert.ok(!decisionMatches(substituted));
  const bad = structuredClone(fixture.decision); bad.request.confirmed_rows = [25]; assert.ok(!decisionMatches(bad));
});
test("reject forged PASS missing hard gate and aggregate PASS",() => {
  const forged = structuredClone(fixture.unconfirmed); forged.rows[0].status = "PASS"; assert.ok(!comparisonMatches(forged));
  assert.ok(!comparisonMatches({...fixture.mandatory_failure,candidate_blocked:false}));
  assert.ok(!comparisonMatches({...fixture.comparison,technical:"PASS"}));
  const manual = structuredClone(fixture.comparison); manual.rows[1].status = "PASS"; assert.ok(!comparisonMatches(manual));
});
test("reject wrong supplier evidence",() => {
  const forged = structuredClone(fixture.comparison); assert.ok(forged.rows[0].supplier_provenance); forged.rows[0].supplier_provenance.document_id = "f".repeat(64); assert.ok(!comparisonMatches(forged));
});
test("reject padded reviewer identity and forged engine explanation",() => {
  const padded = structuredClone(fixture.decision); padded.reviewed_by = ` ${padded.proposal.prepared_by} `; assert.ok(!decisionMatches(padded));
  const forged = structuredClone(fixture.comparison); assert.ok(forged.rows[0].check); forged.rows[0].check.reason = "Fabricated explanation"; assert.ok(!comparisonMatches(forged));
  const requirement = structuredClone(fixture.comparison); assert.ok(requirement.rows[0].check); requirement.rows[0].check.requirement.provenance.document_id = "f".repeat(64); assert.ok(!comparisonMatches(requirement));
  const actor = structuredClone(fixture.proposal); actor.prepared_by = " "; assert.ok(!proposalMatches(actor));
});
