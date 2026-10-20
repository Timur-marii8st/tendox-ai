import { requirementPreviewMatches, validRequirementPreviewRequest, type RequirementPreview, type RequirementPreviewRequest, type RequirementTableRow } from "./eis-requirement-preview";
import type { SourceProvenance } from "./eis-characteristics";

export type RowChoice = { source_row: number; mode: "MANUAL" | "PAPER_FORMAT"; supplier_index: number | null; mandatory: boolean | null };
export type ProposalRequest = { preview: RequirementPreviewRequest; expected_preview_sha256: string; rows: RowChoice[]; note: string };
export type RequirementProposal = { company_id: string; proposal_id: string; request: ProposalRequest; preview: RequirementPreview; prepared_by: string; prepared_at: string; proposal_sha256: string; source_requests: 0; jobs_created: 0 };
export type DecisionRequest = { proposal_id: string; expected_proposal_sha256: string; normative_document: boolean; position_association: boolean; confirmed_rows: number[]; note: string };
export type RequirementDecision = { company_id: string; decision_id: string; request: DecisionRequest; proposal: RequirementProposal; reviewed_by: string; reviewed_at: string; decision_sha256: string; source_requests: 0; jobs_created: 0 };
export type ReviewComparisonRow = { source_row: number; mode: RowChoice["mode"]; mandatory: boolean | null; status: "PASS" | "FAIL" | "UNKNOWN"; reason: "MANUAL_REVIEW_REQUIRED" | "NOT_CONFIRMED" | "GLOBAL_CONFIRMATION_MISSING" | "FORMAT_CHECKED"; check: { verdict: string; actual: string | null; reason: string; evidence: string | null; requirement: { property: string; operator: string; value: string; unit: string | null; mandatory: boolean; weight: number; raw_text: string; provenance: SourceProvenance } } | null; supplier_provenance: SourceProvenance | null };
export type RequirementComparison = { company_id: string; proposal_id: string; decision_id: string; proposal_sha256: string; decision_sha256: string; decision: RequirementDecision; rows: ReviewComparisonRow[]; candidate_blocked: boolean; technical: "UNKNOWN"; full_tspec_completeness: "UNKNOWN"; participation: "UNKNOWN"; comparison_sha256: string; source_requests: 0; jobs_created: 0 };
export type SavedRequirementProposal = { proposal: RequirementProposal; created: boolean; source_requests: 0; jobs_created: 0 };
export type SavedRequirementDecision = { decision: RequirementDecision; created: boolean; source_requests: 0; jobs_created: 0 };
export type RequirementReviewState<T> = { result?: T; error?: string };
const rec = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const sha = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
export const validReviewId = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v);
const text = (v: unknown, max = 1000): v is string => typeof v === "string" && v.length > 0 && [...v].length <= max;
const identity = (v: unknown): v is string => text(v,200) && v.trim() === v && v.trim().length > 0;
const time = (v: unknown) => typeof v === "string" && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
const keys = (v: Record<string, unknown>, names: string) => Object.keys(v).sort().join(" ") === names.split(" ").sort().join(" ");
export function sameReviewValue(a: unknown, b: unknown): boolean {
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x,i) => sameReviewValue(x,b[i]));
  if (rec(a) && rec(b)) return Object.keys(a).length === Object.keys(b).length && Object.keys(a).every(k => Object.hasOwn(b,k) && sameReviewValue(a[k],b[k]));
  return a === b;
}
export function paperFormat(v: string): string | null {
  const m = /^([ABАВ])(10|[0-9])$/.exec(v.trim());
  return m ? `${({А:"A",В:"B"} as Record<string,string>)[m[1].toUpperCase()] ?? m[1].toUpperCase()}${m[2]}` : null;
}
const label = (v: string) => v.trim().toLowerCase();
export function formatSupplierIndex(row: RequirementTableRow, preview: RequirementPreview): number | null {
  const raw = (col: number) => row.cells.find(c => c.column === col)?.text;
  if (row.kind !== "CHARACTERISTIC" || !["формат","формат бумаги"].includes(label(raw(1) ?? "")) || !paperFormat(raw(3) ?? "") || row.unit_raw !== null || preview.product.details.status !== "EXTRACTED") return null;
  const matches = preview.product.details.characteristics.flatMap((c,i) => ["формат","формат бумаги"].includes(label(c.label_raw)) ? [i+1] : []);
  return matches.length === 1 && paperFormat(preview.product.details.characteristics[matches[0]-1].value_raw) ? matches[0] : null;
}
export function validProposalRequest(v: unknown): v is ProposalRequest {
  return rec(v) && keys(v,"preview expected_preview_sha256 rows note") && validRequirementPreviewRequest(v.preview) && sha(v.expected_preview_sha256) && typeof v.note === "string" && [...v.note].length <= 1000 && Array.isArray(v.rows) && v.rows.length >= 1 && v.rows.length <= 24 && v.rows.every((r,i) => rec(r) && keys(r,"source_row mode supplier_index mandatory") && r.source_row === i+2 && (r.mandatory === null || typeof r.mandatory === "boolean") && ((r.mode === "MANUAL" && r.supplier_index === null) || (r.mode === "PAPER_FORMAT" && Number.isInteger(r.supplier_index) && Number(r.supplier_index) >= 1 && Number(r.supplier_index) <= 16 && typeof r.mandatory === "boolean")));
}
export function proposalMatches(v: unknown, expected?: ProposalRequest, preview?: RequirementPreview): v is RequirementProposal {
  if (!rec(v) || !keys(v,"company_id proposal_id request preview prepared_by prepared_at proposal_sha256 source_requests jobs_created") || v.source_requests !== 0 || v.jobs_created !== 0 || !identity(v.company_id) || !validReviewId(v.proposal_id) || !identity(v.prepared_by) || !time(v.prepared_at) || !sha(v.proposal_sha256) || !validProposalRequest(v.request) || !requirementPreviewMatches(v.preview,v.request.preview) || v.request.expected_preview_sha256 !== v.preview.preview_sha256 || v.request.rows.length !== v.preview.table.rows.length || (expected && !sameReviewValue(v.request,expected)) || (preview && !sameReviewValue(v.preview,preview))) return false;
  return v.request.rows.every((r,i) => r.mode === "MANUAL" || r.supplier_index === formatSupplierIndex((v.preview as RequirementPreview).table.rows[i],v.preview as RequirementPreview));
}
export function validDecisionRequest(v: unknown): v is DecisionRequest {
  return rec(v) && keys(v,"proposal_id expected_proposal_sha256 normative_document position_association confirmed_rows note") && validReviewId(v.proposal_id) && sha(v.expected_proposal_sha256) && typeof v.normative_document === "boolean" && typeof v.position_association === "boolean" && typeof v.note === "string" && [...v.note].length <= 1000 && Array.isArray(v.confirmed_rows) && v.confirmed_rows.length <= 24 && v.confirmed_rows.every((n,i,a) => Number.isInteger(n) && n >= 2 && n <= 25 && (i === 0 || n > a[i-1]));
}
export function decisionMatches(v: unknown, proposal?: RequirementProposal): v is RequirementDecision {
  if (!rec(v) || !keys(v,"company_id decision_id request proposal reviewed_by reviewed_at decision_sha256 source_requests jobs_created") || v.source_requests !== 0 || v.jobs_created !== 0 || !proposalMatches(v.proposal) || !validReviewId(v.decision_id) || v.company_id !== v.proposal.company_id || !identity(v.reviewed_by) || v.reviewed_by === v.proposal.prepared_by || !time(v.reviewed_at) || !sha(v.decision_sha256) || Date.parse(v.reviewed_at as string) < Date.parse(v.proposal.prepared_at) || !validDecisionRequest(v.request) || v.request.proposal_id !== v.proposal.proposal_id || v.request.expected_proposal_sha256 !== v.proposal.proposal_sha256 || (proposal && !sameReviewValue(v.proposal,proposal))) return false;
  return v.request.confirmed_rows.every(n => (v.proposal as RequirementProposal).request.rows.some(r => r.source_row === n && r.mode === "PAPER_FORMAT"));
}
export function comparisonMatches(v: unknown, proposal?: RequirementProposal): v is RequirementComparison {
  if (!rec(v) || !keys(v,"company_id proposal_id decision_id proposal_sha256 decision_sha256 decision rows candidate_blocked technical full_tspec_completeness participation comparison_sha256 source_requests jobs_created") || v.source_requests !== 0 || v.jobs_created !== 0 || !decisionMatches(v.decision,proposal) || v.company_id !== v.decision.company_id || v.proposal_id !== v.decision.proposal.proposal_id || v.decision_id !== v.decision.decision_id || v.proposal_sha256 !== v.decision.proposal.proposal_sha256 || v.decision_sha256 !== v.decision.decision_sha256 || !sha(v.comparison_sha256) || v.technical !== "UNKNOWN" || v.full_tspec_completeness !== "UNKNOWN" || v.participation !== "UNKNOWN" || !Array.isArray(v.rows) || v.rows.length !== v.decision.proposal.request.rows.length || typeof v.candidate_blocked !== "boolean") return false;
  const decision = v.decision, p = decision.proposal;
  for (const [i,r] of v.rows.entries()) {
    const choice = p.request.rows[i], raw = p.preview.table.rows[i];
    if (!rec(r) || !keys(r,"source_row mode mandatory status reason check supplier_provenance") || r.source_row !== choice.source_row || r.mode !== choice.mode || r.mandatory !== choice.mandatory) return false;
    let status = "UNKNOWN", reason = "MANUAL_REVIEW_REQUIRED";
    if (choice.mode === "PAPER_FORMAT") {
      reason = "GLOBAL_CONFIRMATION_MISSING";
      if (decision.request.normative_document && decision.request.position_association) {
        reason = "NOT_CONFIRMED";
        if (decision.request.confirmed_rows.includes(choice.source_row)) {
          reason = "FORMAT_CHECKED";
          const required = paperFormat(raw.cells.find(c => c.column === 3)!.text);
          const actual = paperFormat(p.preview.product.details.characteristics[choice.supplier_index!-1].value_raw);
          status = required === actual ? "PASS" : "FAIL";
        }
      }
    }
    if (r.status !== status || r.reason !== reason || (status === "UNKNOWN" ? r.check !== null || r.supplier_provenance !== null : !rec(r.check) || r.check.verdict !== status || !rec(r.check.requirement) || r.check.requirement.mandatory !== choice.mandatory || !rec(r.supplier_provenance) || r.supplier_provenance.document_id !== p.preview.product.details.html_sha256 || r.supplier_provenance.locator !== p.preview.product.details.characteristics[choice.supplier_index!-1].value_locator)) return false;
    if (status !== "UNKNOWN") {
      const valueCell = raw.cells.find(c => c.column === 3)!, nameCell = raw.cells.find(c => c.column === 1)!;
      const fact = p.preview.product.details.characteristics[choice.supplier_index!-1], required = paperFormat(valueCell.text)!, actual = paperFormat(fact.value_raw)!;
      const expectedRequirement = {property:"paper_format",operator:"==",value:required,unit:null,mandatory:choice.mandatory,weight:1,raw_text:`${nameCell.text}: ${valueCell.text}`,provenance:valueCell.provenance};
      const expectedProvenance = {document_id:fact.html_sha256,locator:fact.value_locator,extractor:"api",confidence:1};
      const expectedReason = status === "PASS" ? "значение совпадает с требуемым" : `требуется paper_format == ${required}, фактически ${actual}${choice.mandatory ? ". Требование обязательное — товар не проходит ТЗ" : ""}`;
      if (!rec(r.check) || !keys(r.check,"requirement verdict actual reason evidence") || !sameReviewValue(r.check.requirement,expectedRequirement) || !sameReviewValue(r.supplier_provenance,expectedProvenance) || r.check.actual !== actual || r.check.evidence !== `${fact.html_sha256}, ${fact.value_locator}` || r.check.reason !== expectedReason) return false;
    }
  }
  return v.candidate_blocked === v.rows.some(r => r.status === "FAIL" && r.mandatory === true);
}
export function savedProposalMatches(v: unknown, expected?: ProposalRequest, preview?: RequirementPreview): v is SavedRequirementProposal {
  return rec(v) && keys(v,"proposal created source_requests jobs_created") && typeof v.created === "boolean" && v.source_requests === 0 && v.jobs_created === 0 && proposalMatches(v.proposal,expected,preview);
}
export function savedDecisionMatches(v: unknown, proposal?: RequirementProposal): v is SavedRequirementDecision {
  return rec(v) && keys(v,"decision created source_requests jobs_created") && typeof v.created === "boolean" && v.source_requests === 0 && v.jobs_created === 0 && decisionMatches(v.decision,proposal);
}
