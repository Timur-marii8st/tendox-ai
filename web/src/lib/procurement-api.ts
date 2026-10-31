import "server-only";
import { cookies } from "next/headers";
import { profileCookie } from "./company-profile-api";
import { validProposalRequest, validDecisionRequest, validReviewId, savedProposalMatches, savedDecisionMatches, comparisonMatches, type ProposalRequest, type DecisionRequest, type RequirementProposal, type SavedRequirementProposal, type SavedRequirementDecision, type RequirementComparison } from "./eis-requirement-review";
import { validRequirementPreviewRequest, requirementPreviewMatches, type RequirementPreviewRequest, type RequirementPreview } from "./eis-requirement-preview";
import { validSupplierPageRequest, supplierPageMatches, type SupplierPageRequest, type SavedSupplierPage } from "./eis-supplier-page";
import { validSupplierProductRequest, supplierProductMatches, type SupplierProductRequest, type SavedSupplierProduct } from "./eis-supplier-product";
import { validSupplierCatalogRequest, supplierCatalogMatches, type SupplierCatalogRequest, type SavedSupplierCatalog } from "./eis-supplier-catalog";
import { supplierSerpMatches, type SavedSupplierSerp } from "./eis-supplier-serp";
import { validAssociationRequest, associationMatches, validAssociationListRequest, validAssociationDetailRequest,
  associationListMatches, associationDetailMatches, type AssociationRequest, type SavedAssociation,
  type AssociationListRequest, type AssociationListResult, type AssociationDetailRequest } from "./eis-position-association";
import { validSupplierSearchRequest, supplierSearchMatches, type SupplierSearchRequest, type SavedSupplierSearch } from "./eis-supplier-search";
import { firstReviewCursor, reviewPageMatches, validReviewCursor, validReviewRequest, type ReviewCursor, type ReviewRequest, type SavedReviewPage } from "./eis-document-review";
import { analogReportMatches, validAnalogRequest, type AnalogRequest, type AnalogReport } from "./eis-analogs";
import { characteristicReportMatches, validCharacteristicRequest, type CharacteristicPairRequest, type CharacteristicPairReport } from "./eis-characteristics";
import { protocolReportMatches, validProtocolRef, type HistoricalProtocolReport } from "./eis-protocols";
import type { DocumentAnalysis, DiscoveryCostInput, DiscoveryEstimate } from "./eis-workflow-api";

export type SourceEstimateRequest = { notice: MixedNoticeRef; lot_index: number | null; costs: DiscoveryCostInput };
export type SourceEstimateResult = {
  request: SourceEstimateRequest; checked_at: string; actor_id: string; input_sha256: string;
  manual_provenance: { document_id: string; locator: string; extractor: string };
  ceiling: { value: string | null; raw: string | null; provenance: { document_id: string; locator: string } };
  ceiling_rub: string | null;
  lot_ordinal: { value: string | null } | null; currency: { value: string | null } | null;
  blocking_reasons: string[]; source_reasons: string[]; estimate: DiscoveryEstimate;
  source_schema_status: "PASS" | "FAIL" | "UNKNOWN";
  source_price_kind: Eis223SourcePriceKind | null;
  cancellation_state?: Eis223RejectionState | null;
  lot_cancellation_state?: Eis223LotCancellationState | null;
  selected_lot_cancellation_state?: Eis223SelectedLotCancellationState | null;
  calculation_kind: "PRELIMINARY"; quote_status: "UNKNOWN"; requirement_status: "UNKNOWN";
  full_cost_review: "UNKNOWN"; eligibility: "UNKNOWN"; coverage: "UNKNOWN"; profit_order_status: "UNKNOWN";
};
export function estimateSourceNotice(payload: SourceEstimateRequest): Promise<SourceEstimateResult> {
  return request<SourceEstimateResult>("/v1/tender-discovery/eis-source-estimate", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
}

export type NoticeDocumentRef = {
  purchase_number: string; version_number: number; notice_xml_sha256: string;
};
export async function readCharacteristicPair(payload: CharacteristicPairRequest): Promise<CharacteristicPairReport> {
  if (!validCharacteristicRequest(payload)) throw new ApiError(422);
  const report = await request<unknown>("/v1/tender-discovery/eis-characteristic-pair", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    signal: AbortSignal.timeout(30_000),
  });
  if (!characteristicReportMatches(report, payload)) throw new ApiError(422);
  return report;
}
export async function readHistoricalAnalogs(payload: AnalogRequest): Promise<AnalogReport> {
  if (!validAnalogRequest(payload)) throw new ApiError(422);
  const report = await request<unknown>("/v1/tender-discovery/eis-analog-candidates", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    signal: AbortSignal.timeout(30_000),
  });
  if (!analogReportMatches(report, payload)) throw new ApiError(422);
  return report;
}
export async function readHistoricalProtocols(ref: NoticeDocumentRef): Promise<HistoricalProtocolReport> {
  if (!validProtocolRef(ref)) throw new ApiError(422);
  const params = new URLSearchParams({ purchase_number: ref.purchase_number,
    version_number: String(ref.version_number), notice_xml_sha256: ref.notice_xml_sha256 });
  const report = await request<HistoricalProtocolReport>(`/v1/tender-discovery/eis-protocols?${params}`,
    { signal: AbortSignal.timeout(30_000) });
  if (!protocolReportMatches(report, ref)) throw new ApiError(422);
  return report;
}
export type Document223Status = {
  cancellation_state?: Eis223RejectionState | null;
  lot_cancellation_state?: Eis223LotCancellationState | null;
  manifest: { notice: NoticeDocumentRef; status: "READY" | "UNKNOWN"; reasons: string[];
    source_manifest_coverage: "UNKNOWN" };
  checked_at: string; version_status: "CURRENT_KNOWN_VERSION" | "STALE";
  blocked_reasons: string[]; download_status: "INCOMPLETE" | "COMPLETE_LISTED_SET" | "UNKNOWN_MANIFEST";
  review_status: "UNKNOWN"; eligibility: "UNKNOWN"; economics_status: "UNKNOWN";
  requested: boolean; queue_status: "NOT_REQUESTED" | "QUEUED" | "COMPLETE" | "BLOCKED" | "ATTENTION_REQUIRED";
  documents: Array<{ reference: { ordinal: number; filename: string | null;
    content_uid: string | null; source_url: string | null; source_locator: string;
    status: "READY" | "UNKNOWN"; reasons: string[]; declared_byte_count: null };
    received: boolean; analysis: DocumentAnalysis | null; attempt_count: number; last_failure: string | null }>;
};

export function readIndexed223Documents(ref: NoticeDocumentRef): Promise<Document223Status> {
  return request<Document223Status>(`/v1/tender-discovery/eis-223-documents/${encodeURIComponent(ref.purchase_number)}?version=${ref.version_number}&xml_sha256=${encodeURIComponent(ref.notice_xml_sha256)}`);
}
export function requestIndexed223Documents(ref: NoticeDocumentRef): Promise<Document223Status> {
  return request<Document223Status>("/v1/tender-discovery/eis-223-document-jobs", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(ref),
  });
}
export type DocumentCollectionStatus = {
  notice: NoticeDocumentRef; current_version_number: number; current_xml_sha256: string;
  version_status: "CURRENT_KNOWN_VERSION" | "STALE"; requested: boolean;
  listed_count: number; received_count: number; pending_count: number;
  analysis_pending_count?: number;
  download_status: "NOT_REQUESTED" | "UNKNOWN_MANIFEST" | "QUEUED" | "INCOMPLETE" | "COMPLETE_LISTED_SET";
  extraction_status: "EXTRACTED" | "UNKNOWN"; review_status: "UNKNOWN";
  source_manifest_coverage: "UNKNOWN"; analyzer_version: string;
  read_gate?: { checked_at: string; notice: NoticeDocumentRef;
    blocked_reasons: Array<"NOTICE_VERSION_STALE" | "DEADLINE_EXPIRED" | "PROCEDURE_BLOCKED">;
    evidence: string[] } | null;
  documents: Array<{
    content_uid: string; filename: string; source_url: string; source_locator: string;
    declared_byte_count: number; received_byte_count: number | null; sha256: string | null;
    fetch_status: "PENDING" | "RECEIVED" | "SIZE_MISMATCH" | "FAILED";
    extraction_status: "PASS" | "FAIL" | "UNKNOWN"; reasons: string[];
    requirement_candidate_count: number; condition_snippet_count: number; observed_at: string | null;
  }>;
};
export type DocumentSelectionResult = {
  query: string; compared_at: string; inspected_current_notices: number;
  matched_count: number; eligible_count: number; selection_kind: "PRELIMINARY";
  jobs: DocumentCollectionStatus[]; rejected: { notice: NoticeDocumentRef; reason: string }[];
};
export type EisCompetitionCriteria = {
  source_xml_sha256: string; document_type: string;
  source_status: "EXTRACTED" | "UNKNOWN" | "NOT_APPLICABLE";
  weight_integrity: "CONSISTENT" | "UNKNOWN" | "NOT_APPLICABLE";
  supplier_score_status: "UNKNOWN"; qualification_status: "UNKNOWN"; review_status: "UNKNOWN";
  reasons: string[];
  criteria: Array<{ kind: "COST" | "QUALITATIVE" | "UNKNOWN";
    code: string | null; code_provenance: Provenance | null;
    label: string; label_provenance: Provenance | null;
    additional_info: string | null; additional_info_provenance: Provenance | null;
    indicators_status: "PRESENT_UNREVIEWED" | "NOT_OBSERVED" | "UNKNOWN";
    provenance: Provenance; reasons: string[];
    weights: Array<{ band: "STANDARD" | "DISCOUNT_BELOW_25" | "DISCOUNT_AT_LEAST_25" | "UNKNOWN";
      value_percent: string | null; raw_value: string; provenance: Provenance }> }>;
};
export type EisEvidenceBridge = {
  checked_at: string; notice: NoticeDocumentRef; title: string; source_member: string;
  document_type: string; published_at: string | null; deadline: string | null;
  nmck_rub: string | null; nmck_provenance: Provenance | null;
  lot_parse_status: string;
  lot_items: Array<{ name: string; quantity: string | null; unit: string | null;
    ktru_code: string | null; okpd2_code: string | null;
    unit_price_rub: string | null; line_sum_rub: string | null; locator: string }>;
  collection: DocumentCollectionStatus;
  documents: Array<{ content_uid: string;
    role_hint: "TECHNICAL_SPECIFICATION" | "CONTRACT_DRAFT" | "PRICE_JUSTIFICATION" |
      "APPLICATION_INSTRUCTIONS" | "UNKNOWN"; role_status: "UNKNOWN";
    conditions_total?: number; conditions_truncated?: boolean;
    conditions: Array<{ kind: string; excerpt: string; truncated: boolean; provenance: Provenance;
      context_status?: "ADJACENT_UNREVIEWED" | "NOT_ATTACHED" | "UNKNOWN";
      context?: Array<{ excerpt: string; truncated: boolean; provenance: Provenance }> }> }>;
  application_status: "FAIL" | "UNKNOWN"; application_reasons: string[];
  requirement_status: "UNKNOWN"; completeness_status: "UNKNOWN";
  economic_status: "BLOCKED" | "UNKNOWN"; economic_missing: string[]; review_gaps: string[];
  competition_criteria?: EisCompetitionCriteria | null;
  position_set?: PositionEvidenceSet | null;
};
export type EisPreliminaryCostInput = {
  goods: string; expenses: string; vat_rate: string; basis: string;
  costs_complete_ack: boolean;
};
export type EisComparisonResult = {
  checked_at: string; comparison_kind: "PRELIMINARY";
  scope: "SELECTED_KNOWN_XML_VERSIONS"; coverage: "UNKNOWN"; profit_order_status: "UNKNOWN";
  rows: Array<{ evidence: EisEvidenceBridge; deadline_provenance: Provenance | null;
    readiness_status: "BLOCKED" | "NEEDS_ANALYSIS";
    blocking_reasons: Array<"NOTICE_VERSION_STALE" | "DEADLINE_EXPIRED" | "PROCEDURE_BLOCKED">;
    reasons: string[] }>;
};

export function compareIndexedNotices(notices: NoticeDocumentRef[]): Promise<EisComparisonResult> {
  return request<EisComparisonResult>("/v1/tender-discovery/eis-comparison", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ notices }),
  });
}
export type Comparison223Result = {
  checked_at: string; comparison_kind: "PRELIMINARY"; scope: "SELECTED_KNOWN_XML_VERSIONS";
  coverage: "UNKNOWN"; profit_order_status: "UNKNOWN";
  rows: Array<{
    cancellation_state?: Eis223RejectionState | null;
    lot_cancellation_state?: Eis223LotCancellationState | null;
    notice: Eis223SearchResult["matched"][number]["notice"];
    source_window: string; source_response_sha256: string; archive_sha256: string;
    source_schema_status: "PASS" | "FAIL" | "UNKNOWN";
    source_schema_checks: Eis223SearchResult["matched"][number]["source_schema_checks"];
    readiness_status: "BLOCKED" | "NEEDS_ANALYSIS"; blocking_reasons: string[]; reasons: string[];
    download_status: Document223Status["download_status"]; queue_status: Document223Status["queue_status"];
    eligibility: "UNKNOWN"; economics_status: "UNKNOWN";
    position_set?: PositionEvidenceSet | null;
    documents: Array<{
      content_uid: string | null; filename: string | null; source_url: string | null; source_locator: string;
      received: boolean; sha256: string | null; extraction_status: "PASS" | "FAIL" | "UNKNOWN";
      reasons: string[]; snippets: DocumentAnalysis["snippets"]; snippets_total: number;
      preview_truncated: boolean; review_status: "UNKNOWN";
    }>;
  }>;
};
export function compareIndexed223Notices(notices: NoticeDocumentRef[]): Promise<Comparison223Result> {
  return request<Comparison223Result>("/v1/tender-discovery/eis-223-comparison", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ notices }),
  });
}
export type MixedNoticeRef = NoticeDocumentRef & { law: "44" | "223" };
export type PositionFact = { value: string | null; raw: string | null; provenance: Provenance; raw_truncated?: boolean };
export type PositionEvidenceSet = NoticeDocumentRef & {
  law: "44" | "223"; positions_total: number; positions_truncated: boolean;
  specification_completeness: "UNKNOWN"; review_status: "UNKNOWN";
  positions: Array<{
    source_index: number; lot_index: number | null; lot_ordinal: PositionFact | null;
    name: PositionFact; quantity: PositionFact; unit: PositionFact; classification_code: PositionFact;
    ktru_code: PositionFact; unit_price: PositionFact; line_sum: PositionFact; currency: PositionFact;
    provenance: Provenance; characteristics_status: "SOURCE_VALUES" | "UNKNOWN";
    characteristics_total: number; characteristics_truncated: boolean; review_status: "UNKNOWN";
    characteristics: Array<{ name: PositionFact; instruction_code: PositionFact; values_total: number;
      truncated: boolean; review_status: "UNKNOWN";
      values: Array<{ description: PositionFact; minimum: PositionFact; minimum_operator: PositionFact;
        maximum: PositionFact; maximum_operator: PositionFact; unit: PositionFact;
        concrete_values: PositionFact[]; concrete_values_total: number; concrete_values_truncated: boolean }> }>;
  }>;
  native_tables: Array<{ content_uid: string; filename: string; document_sha256: string;
    extraction_status: "PASS" | "FAIL" | "UNKNOWN"; extraction_reasons: string[];
    rows_total: number; truncated: boolean; role_status: "UNKNOWN"; position_association: "UNKNOWN";
    rows: Array<{ cells_total: number; truncated: boolean;
      cells: Array<{ text: string; truncated: boolean; provenance: Provenance }> }> }>;
};
export type Mixed44Row = EisComparisonResult["rows"][number] & {
  law: "44"; source_window: string; source_response_sha256: string;
  archive_sha256: string; source_schema_status: "UNKNOWN";
};
export type MixedComparisonResult = {
  checked_at: string; comparison_kind: "PRELIMINARY"; scope: "SELECTED_KNOWN_XML_VERSIONS";
  coverage: "UNKNOWN"; profit_order_status: "UNKNOWN"; economic_comparability: "UNKNOWN";
  rows: Array<Mixed44Row | (Comparison223Result["rows"][number] & { law: "223" })>;
  position_links: Array<{ left_row: number; right_row: number; left_position: number; right_position: number;
    basis: "NAME" | "KTRU" | "CLASSIFICATION"; differences: string[]; evidence: [Provenance, Provenance];
    equivalence: "UNKNOWN"; price_comparability: "UNKNOWN" }>;
  position_links_truncated: boolean;
};
export function compareMixedNotices(notices: MixedNoticeRef[]): Promise<MixedComparisonResult> {
  return request<MixedComparisonResult>("/v1/tender-discovery/eis-mixed-comparison", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ notices }),
  });
}
export type EisPreliminaryEstimate = {
  notice: NoticeDocumentRef; nmck_rub: string | null; nmck_provenance: Provenance | null;
  application_status: "FAIL" | "UNKNOWN"; requirement_status: "UNKNOWN";
  quote_status: "UNKNOWN"; completeness_status: "UNKNOWN";
  estimate: { status: "ESTIMATE" | "UNKNOWN" | "BLOCKED";
    recommendation: "needs_analysis" | "do_not_participate";
    basis: string; reasons: string[];
    scenarios: Array<{ kind: "base" | "realistic" | "conservative";
      revenue_net: string; costs_net: string; profit: string; margin: string;
      assumptions: string[]; break_even_gross: string; maximum_discount: string; basis: string }>;
  };
  preliminary_guidance: "NEEDS_ANALYSIS" | "DO_NOT_PARTICIPATE";
};

export type RecommendationDecision =
  | "participate"
  | "needs_analysis"
  | "do_not_participate";

export type EisAttachment = { filename: string; url: string; locator: string };
export type EisNoticeLead = {
  purchase_number: string; title: string; customer: string | null;
  nmck: string | null; nmck_currency: string | null; deadline: string | null;
  application_status: "UNKNOWN" | "FAIL"; economic_status: "UNKNOWN";
  match_quality: "STRONG" | "PARTIAL"; match_locator: string;
  explanation: string[]; relevance_points: number; notice_url: string;
  attachments: EisAttachment[]; export_member: string;
  xml_sha256: string; export_sha256: string;
};
export type EisDiscoveryResult = {
  query: string; export_sha256: string; inspected_notices: number;
  rejected_members: number; matched: EisNoticeLead[];
  coverage: "UPLOADED_EXPORT_ONLY"; source_authenticity: "UNKNOWN";
};
export type EisIndexedLead = {
  position_set?: PositionEvidenceSet | null;
  document_type: string;
  purchase_number: string; version_number: number; title: string; notice_url: string;
  nmck_rub: string | null; deadline: string | null;
  application_status: "FAIL" | "UNKNOWN"; economic_status: string;
  match_quality: "STRONG" | "PARTIAL"; matched_terms: string[]; match_locator: string;
  reasons: string[]; source_window: string; source_member: string; xml_sha256: string;
  lot_items: { name: string; ktru_code: string | null; okpd2_code: string | null;
    quantity: string | null; unit: string | null; locator: string }[];
  attachments: EisAttachment[];
};
export type EisIndexSearchScope = "ALL_CACHED" | "NOT_EXPIRED_OR_UNKNOWN";
export type EisIndexedSearchResult = {
  next_cursor?: string | null; page_snapshot_sha256?: string | null; snapshot_at?: string | null;
  search_scope: EisIndexSearchScope;
  total_current_notices: number; excluded_expired_current_notices: number;
  query: string; inspected_current_notices: number; matched_count: number;
  strong_matched_count?: number | null; partial_matched_count?: number | null;
  indexed_windows: number; latest_ingested_at: string | null;
  corpus_coverage: "UNKNOWN"; comparison_kind: "PRELIMINARY";
  planned_windows: number; pending_windows: number; requested_region_codes: number;
  evaluated_candidate_notices: number; unindexed_versions: number;
  latest_source_publication: string | null; source_freshness: "UNKNOWN";
  compared_at: string | null; search_elapsed_ms: number;
  matched: EisIndexedLead[];
};
export type EisDocumentPreview = {
  url: string; filename: string; sha256: string; byte_count: number;
  extraction_status: "PASS" | "FAIL" | "UNKNOWN";
  extraction_reasons: string[]; text_preview: string; preview_truncated: boolean;
  bundle_members: string[];
};
export type EisPublicLead = {
  purchase_number: string; subject: string; customer: string | null;
  law: "44-fz" | "223-fz"; method: string; stage: string;
  nmck_rub: string | null; deadline_date: string | null;
  detail_url: string; documents_url: string | null; matched_terms: string[];
  application_status: "UNKNOWN" | "FAIL"; economic_status: "UNKNOWN";
  source_locator: string; source_sha256: string;
};
export type EisPublicSearchResult = {
  query: string; search_url: string;
  status: "COMPLETED" | "SOURCE_CHANGED" | "BLOCKED" | "RATE_LIMITED" | "SOURCE_ERROR" | "COOLDOWN";
  observed_at: string; source_sha256: string | null; scanned_count: number | null;
  purchase_numbers: string[] | null; unidentified_count: number | null;
  unique_scanned_count: number | null; page_size: 50 | 100; page_number: number;
  unparsed_count: number; source_result_count_floor: number | null;
  source_result_count_exact: boolean; query_exceeds_page_limit: boolean;
  has_more_pages: boolean; coverage: "FIRST_PAGE_ONLY";
  reason: string | null; retry_at: string | null; leads: EisPublicLead[];
};
export type EisLiveVerification = {
  source: {
    purchase_number: string; status: "SYNCED" | "NO_DATA" | "PREPARING" | "SERVICE_ERROR";
    source_response_sha256: string | null; archive_count: number; new_versions: number;
    latest_version_number: number | null; latest_xml_sha256: string | null;
    reason: string | null; coverage: "ONE_NUMBER_ONLY";
  };
  document_job: DocumentCollectionStatus | null;
  document_queue_reason: string | null;
};
export type EisPublicDocument = { filename: string; url: string; source_locator: string };
export type EisPublicDocumentsResult = {
  documents_url: string;
  status: "COMPLETED" | "SOURCE_CHANGED" | "BLOCKED" | "RATE_LIMITED" | "SOURCE_ERROR" | "COOLDOWN";
  observed_at: string; source_sha256: string | null;
  reason: string | null; retry_at: string | null; documents: EisPublicDocument[];
};

export type Provenance = {
  document_id: string;
  locator: string;
  extractor?: string | null;
  confidence?: number | null;
};

export type GateCheck = {
  kind: string;
  status: "PASS" | "FAIL" | "UNKNOWN";
  reason: string;
  evidence: Provenance[];
};

export type HardGateKind = "legal" | "participant" | "company_policy" | "logistics";

export type CaseHardGateAssessmentEvidence = {
  case: ProcurementCase;
  source_case_input_sha256: string;
};

export type CaseHardGateDecisionInput = {
  kind: HardGateKind;
  status: "PASS" | "FAIL" | "UNKNOWN";
  reason: string;
  evidence: Array<{ document_id: string; document_sha256: string; locator: string }>;
};

export type EconomicsScenario = {
  kind: "base" | "realistic" | "conservative";
  assumptions: string[];
  economics: {
    contract_revenue: string;
    nds_rate?: string | null;
    costs: {
      specified_cost_fields?: string[];
      [key: string]: string | string[] | null | undefined;
    };
  };
};

export type ProcurementCase = {
  case_id: string;
  version: number;
  nmck_ex_vat: string;
  nmck_source: Provenance;
  selected_quote?: {
    quote_id: string;
    supplier_id: string;
    amount_ex_vat: string;
    valid_until: string;
    source: Provenance;
  } | null;
  assessment?: { checks: GateCheck[] } | null;
  scenarios?: { scenarios: EconomicsScenario[] } | null;
  tender: {
    tender_id: string;
    customer_name: string;
    subject: string;
    law: string;
    method: string;
    stage: string;
    notice_provenance: Provenance;
    submission?: { closes_at?: string; timezone?: string } | null;
    delivery?: {
      addresses?: Array<{ region?: string; city?: string; address?: string }>;
    } | null;
  };
  rating?: {
    score?: number;
    factors?: Array<{
      name: string;
      points: number;
      explanation: string;
      change_hint?: string | null;
    }>;
  } | null;
};

export type EvaluationRecord = {
  evaluation_id: string;
  audit_event_id: string;
  effective_at: string;
  engine_version: string;
  input_digest: string;
  recommendation: {
    decision: RecommendationDecision;
    reasons: string[];
    realistic_profit?: string | null;
    realistic_margin?: string | null;
    minimum_bid_price?: string | null;
    generated_at: string;
  };
};

export type ParticipationDecisionStatus = "APPROVED" | "REJECTED";

export type ParticipationDecisionRecord = {
  evidence: {
    schema_version: "participation-evaluation-evidence-v1";
    company_id: string;
    evaluation_id: string;
    case_id: string;
    case_version: number;
    effective_at: string;
    case_input_sha256: string;
    engine_version: string;
    recommendation: EvaluationRecord["recommendation"];
    evaluated_by: string;
    evaluated_at: string;
    evidence_sha256: string;
  };
  decision: ParticipationDecision | null;
};

export type ParticipationDecision = {
  schema_version: "participation-decision-v1";
  company_id: string;
  decision_id: string;
  evaluation_id: string;
  evaluation_evidence_sha256: string;
  case_id: string;
  case_version: number;
  status: ParticipationDecisionStatus;
  current_recommendation: EvaluationRecord["recommendation"];
  reason: string;
  decided_by: string;
  decided_at: string;
  external_action_authorized: false;
  decision_sha256: string;
};

export type ApplicationRequirementKind =
  | "FORM"
  | "DECLARATION"
  | "ELIGIBILITY"
  | "CERTIFICATE"
  | "AUTHORITY"
  | "TECHNICAL_PROPOSAL"
  | "PRICE_PROPOSAL"
  | "OTHER";

export type ApplicationDocumentRequirement = {
  ordinal: number;
  kind: ApplicationRequirementKind;
  title: string;
  source_document_id: string;
  source_document_sha256: string;
  source_locator: string;
};

export type ApplicationAttachmentInput = {
  ordinal: number;
  requirement_ordinals: number[];
  document_id: string;
  document_sha256: string;
  submission_filename: string;
};

export type ApplicationAttachment = ApplicationAttachmentInput & {
  original_filename: string;
  media_type: string;
};

export type ApplicationPackage = {
  schema_version: "application-package-v1";
  company_id: string;
  package_id: string;
  case_id: string;
  case_version: number;
  case_input_sha256: string;
  tender_id: string;
  participation_decision_id: string;
  participation_decision_sha256: string;
  evaluation_id: string;
  evaluation_evidence_sha256: string;
  proposed_price_ex_vat: string;
  minimum_bid_price: string;
  currency: "RUB";
  requirements: ApplicationDocumentRequirement[];
  attachments: ApplicationAttachment[];
  current_recommendation: EvaluationRecord["recommendation"];
  coverage_status: "UNKNOWN";
  review_status: "PENDING_REVIEW";
  prepared_by: string;
  prepared_at: string;
  external_action_authorized: false;
  package_sha256: string;
};

export type ApplicationPackageRecord = {
  evidence: {
    case: ProcurementCase;
    participation: ParticipationDecisionRecord;
  };
  package: ApplicationPackage | null;
};

export type ApplicationInventoryAssessment =
  | "CONFIRMED_COMPLETE" | "CONFIRMED_MISSING" | "UNRESOLVED";
export type ApplicationPriceAssessment = "CONFIRMED" | "REJECTED" | "UNRESOLVED";
export type ApplicationRequirementReview = {
  requirement_ordinal: number;
  status: "PASS" | "FAIL" | "UNKNOWN";
  reason: string;
  attachment_ordinals: number[];
};
export type ApplicationAttachmentReview = {
  attachment_ordinal: number;
  status: "PASS" | "FAIL" | "UNKNOWN";
  reason: string;
};
export type ApplicationReviewDecision = {
  schema_version: "application-review-decision-v1";
  company_id: string;
  package_id: string;
  package_sha256: string;
  participation_decision_id: string;
  participation_decision_sha256: string;
  requirement_reviews: ApplicationRequirementReview[];
  attachment_reviews: ApplicationAttachmentReview[];
  inventory_assessment: ApplicationInventoryAssessment;
  inventory_source_document_ids: string[];
  inventory_reason: string;
  price_assessment: ApplicationPriceAssessment;
  price_reason: string;
  current_recommendation: EvaluationRecord["recommendation"];
  deadline_gate: "PASS" | "FAIL" | "UNKNOWN";
  price_gate: "PASS" | "FAIL" | "UNKNOWN";
  status: "PASS" | "FAIL" | "UNKNOWN";
  reason: string;
  reviewed_by: string;
  reviewed_at: string;
  external_action_authorized: false;
  decision_sha256: string;
};
export type ApplicationReviewRecord = {
  evidence: ApplicationPackageRecord;
  decision: ApplicationReviewDecision | null;
};
export type ApplicationSubmissionIntent = {
  schema_version: "application-submission-intent-v1";
  package_id: string;
  package_sha256: string;
  review_decision_sha256: string;
  prepared_by: string;
  request: {
    action_id: string;
    company_id: string;
    tender_id: string;
    action_type: "submit_application";
    payload: {
      schema_version: "application-submission-intent-v1";
      destination: string;
      case_id: string;
      case_version: number;
      package_id: string;
      package_sha256: string;
      review_decision_sha256: string;
      price_ex_vat: string;
      currency: "RUB";
      attachments: Array<{
        ordinal: number;
        document_id: string;
        document_sha256: string;
        submission_filename: string;
        media_type: string;
      }>;
    };
    payload_sha256: string;
    created_at: string;
  };
};
export type ApplicationSubmissionApproval = {
  schema_version: "application-submission-approval-v1";
  company_id: string;
  action_id: string;
  payload_sha256: string;
  status: "APPROVED" | "REJECTED";
  reason: string;
  decided_by: string;
  decided_at: string;
  approval: null | { expires_at: string; approved_at: string; payload_sha256: string };
  external_action_performed: false;
  decision_sha256: string;
};
export type ApplicationSubmissionRecord = {
  evidence: ApplicationReviewRecord;
  intent: ApplicationSubmissionIntent | null;
  decision: ApplicationSubmissionApproval | null;
};
export type ApplicationSubmissionAdmission = {
  schema_version: "application-submission-admission-v1";
  company_id: string;
  package_id: string;
  action_id: string;
  admission_id: string;
  payload_sha256: string;
  approval_decision_sha256: string;
  approved_by: string;
  approval_expires_at: string;
  attachments: Array<{
    ordinal: number;
    document_id: string;
    sha256: string;
    byte_size: number;
    submission_filename: string;
    media_type: string;
  }>;
  admitted_by: string;
  admitted_at: string;
  status: "ADMITTED_NO_DISPATCH";
  external_action_performed: false;
  admission_sha256: string;
};
export type ApplicationSubmissionExecutionRecord = {
  submission: ApplicationSubmissionRecord;
  admission: ApplicationSubmissionAdmission | null;
};
export type ApplicationReviewDocument = {
  document_id: string;
  original_filename: string;
  media_type: string;
  document_role: UploadDocumentRole;
  byte_size: number;
  sha256: string;
  extraction: {
    status: "PASS" | "FAIL" | "UNKNOWN";
    reasons: string[];
    blocks: Array<{ text: string; provenance: Provenance }>;
  };
  created_at: string;
};

export type SourcingRunRecord = {
  company_id: string;
  run_id: string;
  case_id: string;
  case_version: number;
  query: string;
  source_name: string;
  source_url: string;
  status: "COMPLETED" | "SOURCE_ERROR";
  source_sha256?: string | null;
  source_byte_size?: number | null;
  observed_at: string;
  sources: Array<{
    ordinal: number;
    source_name: string;
    source_kind: "MANUFACTURER_CATALOG" | "SUPPLIER_CATALOG";
    source_url: string;
    media_type: "text/html" | "application/pdf";
    status: "COMPLETED" | "SOURCE_ERROR";
    source_sha256?: string | null;
    source_byte_size?: number | null;
    observed_at: string;
    error_code?: string | null;
  }>;
  requirement_set_binding_id?: string | null;
  requirement_set_id?: string | null;
  requirement_set_proposal_sha256?: string | null;
  requirement_set_decision_sha256?: string | null;
  requirement_set_binding_sha256?: string | null;
  technical_scope_status: "UNKNOWN";
  technical_scope_reason: string;
  error_code?: string | null;
  created_at: string;
  shortlist: {
    review_queue: Array<{
      status: "NEEDS_TECHNICAL_REVIEW";
      open_properties: string[];
      lead: {
        lead_id: string;
        supplier: string;
        manufacturer?: string | null;
        source_kind: "MANUFACTURER_CATALOG" | "SUPPLIER_CATALOG";
        product_name: string;
        source_url: string;
        product_url?: string | null;
        source_sha256: string;
        observed_at: string;
      };
    }>;
    rejected: Array<{
      status: "REJECTED";
      open_properties: string[];
      lead: {
        lead_id: string;
        supplier: string;
        manufacturer?: string | null;
        source_kind: "MANUFACTURER_CATALOG" | "SUPPLIER_CATALOG";
        product_name: string;
        source_url: string;
        product_url?: string | null;
        source_sha256: string;
        observed_at: string;
      };
    }>;
  };
};

export type EaeuRegistrySearchResult = {
  query: string;
  fetch_status: "COMPLETED" | "SOURCE_ERROR";
  source_url: string;
  observed_at: string;
  request_sha256: string;
  response_sha256: string | null;
  response_byte_size: number | null;
  matched_count: number | null;
  error_code: string | null;
  candidates: Array<{
    source_record_index: number;
    record_id: string;
    registry_number: string;
    product_name: string;
    manufacturer_name: string;
    record_url: string;
    document_expires_on: string | null;
    suitability: "UNKNOWN";
  }>;
};

export type EaeuManufacturerSearchResult = {
  query: string;
  fetch_status: "COMPLETED" | "SOURCE_ERROR";
  source_url: string;
  observed_at: string;
  request_sha256: string;
  response_sha256: string | null;
  response_byte_size: number | null;
  matched_count: number | null;
  error_code: string | null;
  candidates: Array<{
    source_record_index: number;
    record_id: string;
    identity_code: string;
    manufacturer_name: string;
    member_state_code: string | null;
    suitability: "UNKNOWN";
  }>;
};

export type DirectCatalogSearchResult = {
  query: string;
  site_id: string;
  site_name: string;
  catalog_url: string;
  fetch_status: "COMPLETED" | "SOURCE_ERROR" | "QUERY_NOT_COVERED";
  observed_at: string;
  response_sha256: string | null;
  response_byte_size: number | null;
  error_code: string | null;
  coverage: "ONE_CATEGORY_PAGE_ONLY";
  candidates: Array<{
    title: string;
    url: string;
    supplier: string;
    manufacturer_claim: string | null;
    suitability: "UNKNOWN";
  }>;
};

export type CatalogPageEvidence = {
  page_number: number; source_url: string; observed_at: string;
  status: "COMPLETED" | "SOURCE_ERROR"; sha256: string | null;
  scanned_count: number; matched_count: number; error_code: string | null;
  continuation: "NEXT_PAGE" | "END_REPORTED" | "UNKNOWN";
  continuation_evidence: "LINK" | "PAGE_STATE" | "LINK_AND_PAGE_STATE" | null;
  continuation_locator: string | null;
};

export type YandexBusinessSearchResult = {
  site_id: "yandex_market_business";
  site_name: string;
  query: string;
  category_url: string | null;
  fetch_status: "COMPLETED" | "PARTIAL" | "SOURCE_ERROR" | "QUERY_NOT_COVERED";
  observed_at: string;
  response_sha256: string | null;
  response_byte_size: number | null;
  scanned_count: number | null;
  error_code: string | null;
  coverage: "BOUNDED_CATEGORY_PAGES";
  pages: CatalogPageEvidence[];
  stop_reason: string | null;
  category_key: string | null;
  candidates: Array<{
    title: string;
    url: string;
    source_item_index: number;
    source_page_number: number | null;
    source_page_url: string | null;
    source_sha256: string | null;
    suitability: "UNKNOWN";
  }>;
};

export type SupplierSearchMode = "AUTO" | "HTTP" | "BROWSER";

export type BrowserCatalogAttempt = {
  company_id: string;
  site: "servermall" | "yandex_business" | "supl_biz";
  status: "COMPLETED" | "BLOCKED" | "RATE_LIMITED" | "AUTH_REQUIRED" | "SOURCE_CHANGED" |
    "SOURCE_ERROR" | "TIMEOUT" | "PROFILE_BUSY" | "COOLDOWN" | "QUERY_NOT_COVERED" |
    "BROWSER_UNAVAILABLE" | "WORKER_BUSY" | "PARTIAL";
  source_url: string;
  observed_at: string;
  retry_at: string | null;
  reason: string | null;
  dom_sha256: string | null;
  scanned_count: number | null;
  query_mode: "TITLE_TERMS" | "CATEGORY_PREVIEW";
  pages: CatalogPageEvidence[];
  stop_reason: string | null;
  candidates: Array<{ title: string; url: string; locator: string; suitability: "UNKNOWN";
    seller_name: string | null; seller_url: string | null;
    source_page_number: number | null; source_page_url: string | null; source_sha256: string | null }>;
};

export type DocumentSupplierSearchPlan = {
  schema_version: "supplier-search-plan-v8";
  mode: SupplierSearchMode;
  document_id: string;
  source_document_sha256: string;
  status: "READY" | "NO_PRODUCT_ANCHOR" | "AMBIGUOUS" | "EXTRACTION_UNAVAILABLE";
  query: string | null;
  query_evidence: { query: string; provenance: Provenance } | null;
  alternative_evidence: Array<{ query: string; provenance: Provenance }>;
  destinations: Array<{
    site_id: string;
    site_name: string;
    api_url: string;
    exact_query: string;
    transport: "HTTP" | "HTTP_THEN_BROWSER" | "BROWSER";
    browser_loads_page_resources: boolean;
    page_urls: string[];
    match_policy: "SOURCE_QUERY" | "TITLE_TERMS_V1";
    pagination_policy: "CATEGORY_LINK_OR_STATE_V1" | null;
  }>;
  plan_sha256: string;
};

export type DocumentSupplierSearchRun = {
  plan: DocumentSupplierSearchPlan;
  eaeu_products: EaeuRegistrySearchResult;
  direct_catalog: DirectCatalogSearchResult | null;
  yandex_business: YandexBusinessSearchResult | null;
  browser_attempts: BrowserCatalogAttempt[];
  graviton_catalog: {
    site_name: string; category_key: "servers" | "laptops" | "printers" | "pcs" | null;
    source_url: string; query: string;
    fetch_status: "COMPLETED" | "SOURCE_ERROR" | "QUERY_NOT_COVERED";
    observed_at: string; response_sha256: string | null; scanned_count: number | null;
    candidates: Array<{ title: string; url: string; source_item_index: number;
      manufacturer_claim: "Гравитон"; suitability: "UNKNOWN" }>;
  } | null;
  depo_catalog: {
    site_name: string; source_url: string; query: string;
    fetch_status: "COMPLETED" | "SOURCE_ERROR" | "QUERY_NOT_COVERED";
    observed_at: string; response_sha256: string | null; scanned_count: number | null;
    candidates: Array<{ title: string; url: string; source_item_index: number;
      manufacturer_claim: "DEPO"; suitability: "UNKNOWN" }>;
  } | null;
};

export type RequirementSetMaterializationPreview = {
  schema_version: "requirement-set-materialization-preview-v1";
  company_id: string;
  source_document_id: string;
  source_document_sha256: string;
  table_locator: string;
  expected_entry_count: number;
  numeric_suggestion_count: number;
  preview_sha256: string;
  entries: Array<{
    ordinal: number;
    raw_name: string;
    raw_value: string;
    instruction?: string | null;
    provenance: Provenance;
    numeric_suggestion?: {
      operator: string;
      value: string;
      unit?: string | null;
      source_locators: string[];
    } | null;
  }>;
};

export type ExecutableRequirementSelection = {
  ordinal: number;
  property: string;
  unit?: string | null;
  mandatory: boolean;
  review_note: string;
};

export type ReviewedRequirementSetRecord = {
  proposal: {
    schema_version: "reviewed-requirement-set-proposal-v1";
    company_id: string;
    set_id: string;
    source_document_id: string;
    source_document_sha256: string;
    declared_scope: string;
    expected_entry_count: number;
    prepared_by: string;
    prepared_at: string;
    proposal_sha256: string;
    entries: Array<{
      ordinal: number;
      raw_name: string;
      raw_value: string;
      provenance: Provenance;
      disposition: "EXECUTABLE" | "MANUAL_REVIEW_REQUIRED";
      requirement: {
        property: string;
        operator: string;
        value: string | boolean | string[] | [string, string] | null;
        unit?: string | null;
        mandatory: boolean;
        weight: number;
        raw_text: string;
        provenance: Provenance;
      } | null;
      review_note: string;
    }>;
  };
  decision: ReviewedRequirementSetDecision | null;
};

export type RequirementSetCoverageAssessment = "CONFIRMED" | "UNRESOLVED";
export type RequirementSetNormalizationAssessment = "REVIEWED" | "UNRESOLVED";

export type ReviewedRequirementSetDecision = {
  schema_version: "reviewed-requirement-set-decision-v1";
  company_id: string;
  set_id: string;
  proposal_sha256: string;
  coverage_assessment: RequirementSetCoverageAssessment;
  normalization_assessment: RequirementSetNormalizationAssessment;
  manual_review_entry_ordinals: number[];
  status: "PASS" | "FAIL" | "UNKNOWN";
  reason: string;
  reviewed_by: string;
  reviewed_at: string;
  decision_sha256: string;
};

export type CaseRequirementSetBinding = {
  schema_version: "case-requirement-set-binding-v1";
  company_id: string;
  binding_id: string;
  case_id: string;
  case_version: number;
  set_id: string;
  proposal_sha256: string;
  decision_sha256: string;
  reviewed_by: string;
  bound_by: string;
  bound_at: string;
  binding_sha256: string;
};

export type ServerOfferPartKind =
  | "CHASSIS"
  | "CPU"
  | "MEMORY"
  | "STORAGE"
  | "RAID_CONTROLLER"
  | "NETWORK"
  | "PSU"
  | "COOLING"
  | "RAILS"
  | "CABLE"
  | "LICENSE"
  | "SERVICE"
  | "OTHER";

export type ServerOfferBomLineInput = {
  ordinal: number;
  kind: ServerOfferPartKind;
  manufacturer?: string | null;
  sku: string;
  description: string;
  quantity: string;
  unit: string;
  unit_price_ex_vat?: string | null;
  line_total_ex_vat?: string | null;
  source_locator: string;
};

export type ServerOfferCommercialTermsInput = {
  quote_number: string;
  supplier_id: string;
  supplier_name: string;
  amount_ex_vat: string;
  nds_rate?: string | null;
  currency: "RUB";
  issued_at: string;
  valid_until: string;
  covers_full_scope: boolean | null;
  availability_terms?: string | null;
  delivery_terms?: string | null;
  payment_terms?: string | null;
  source_locator: string;
};

export type ServerOfferProposal = {
  schema_version: "server-offer-proposal-v1";
  company_id: string;
  offer_id: string;
  case_id: string;
  case_version: number;
  requirement_set_binding_id: string;
  requirement_set_binding_sha256: string;
  sourcing_run_id: string;
  lead_id: string;
  lead_product_name: string;
  lead_product_url: string;
  lead_source_sha256: string;
  source_document_id: string;
  source_document_sha256: string;
  bom_lines: Array<Omit<ServerOfferBomLineInput, "source_locator"> & { provenance: Provenance }>;
  commercial_terms: Omit<ServerOfferCommercialTermsInput, "source_locator"> & { provenance: Provenance };
  technical_status: "UNKNOWN";
  review_status: "PENDING_REVIEW";
  prepared_by: string;
  prepared_at: string;
  proposal_sha256: string;
};

export type ServerOfferEvidenceRef = {
  kind: "BOM_LINE" | "COMMERCIAL_TERMS";
  bom_line_ordinal?: number | null;
};

export type ServerOfferRequirementDecision = {
  requirement_ordinal: number;
  status: "PASS" | "FAIL" | "UNKNOWN";
  reason: string;
  evidence: ServerOfferEvidenceRef[];
};

export type ServerOfferBomScopeAssessment =
  | "CONFIRMED_COMPLETE"
  | "CONFIRMED_INCOMPLETE"
  | "UNRESOLVED";
export type ServerOfferCommercialAssessment = "CONFIRMED" | "REJECTED" | "UNRESOLVED";

export type ServerOfferReviewDecision = {
  schema_version: "server-offer-review-decision-v1";
  company_id: string;
  offer_id: string;
  proposal_sha256: string;
  requirement_set_id: string;
  requirement_set_proposal_sha256: string;
  requirement_set_decision_sha256: string;
  requirement_decisions: ServerOfferRequirementDecision[];
  bom_scope_assessment: ServerOfferBomScopeAssessment;
  commercial_terms_assessment: ServerOfferCommercialAssessment;
  quote_gate_status: "PASS" | "FAIL" | "UNKNOWN";
  quote_gate_reason: string;
  status: "PASS" | "FAIL" | "UNKNOWN";
  reason: string;
  reviewed_by: string;
  reviewed_at: string;
  decision_sha256: string;
};

export type ServerOfferReviewRecord = {
  evidence: {
    proposal: ServerOfferProposal;
    requirement_set: ReviewedRequirementSetRecord;
  };
  decision: ServerOfferReviewDecision | null;
};

export type ServerOfferOperatingCostsInput = {
  packaging: string; logistics: string; loading_unloading: string; storage: string;
  installation: string; payroll_travel: string; subcontracting: string; insurance: string;
  finance: string; bank_guarantee: string; platform_fees: string; taxes: string;
  certification: string; warranty: string; risk_reserve: string; penalty_reserve: string;
  other: string;
};

export type ServerOfferScenarioInput = {
  kind: "base" | "realistic" | "conservative";
  contract_revenue: string;
  costs: ServerOfferOperatingCostsInput;
  assumptions: string[];
};

export type ServerOfferEconomicsPackage = {
  schema_version: "server-offer-economics-package-v1";
  company_id: string; economics_id: string; case_id: string; case_version: number;
  case_input_sha256: string; offer_id: string; offer_proposal_sha256: string;
  offer_review_decision_sha256: string; source_document_id: string;
  source_document_sha256: string;
  scenario_set: { scenarios: Array<{
    kind: "base" | "realistic" | "conservative"; assumptions: string[];
    economics: { contract_revenue: string; nds_rate: string; costs: Record<string, string | string[]> };
  }> };
  scenario_status: "COMPLETE"; recommendation_status: "UNKNOWN";
  prepared_by: string; prepared_at: string; package_sha256: string;
};

export type ServerOfferEconomicsRecord = {
  evidence: { case: ProcurementCase; offer_review: ServerOfferReviewRecord };
  package: ServerOfferEconomicsPackage | null;
};

export type CaseCardData = {
  case: ProcurementCase;
  evaluation: EvaluationRecord | null;
  sourcing: SourcingRunRecord | null;
};

export type DashboardData = {
  cases: CaseCardData[];
  error?: "api" | "configuration";
};

export type SearchSourceKind =
  | "TITLE"
  | "FILENAME"
  | "NATIVE_TEXT"
  | "VISION_TAG"
  | "MODEL_BRAND_CATALOG";

export type DocumentSearchHit = {
  source_kind: SearchSourceKind;
  matched_text: string;
  provenance: Provenance;
  status: "PASS" | "FAIL" | "UNKNOWN";
  vision_review_status?: "AI_SUGGESTED" | "HUMAN_CONFIRMED" | null;
  vision_evidence?: {
    producer: string;
    model: string;
    reviewed_by?: string | null;
  } | null;
  model_brand_evidence?: {
    catalog_id: string;
    model: string;
    brand: string;
    catalog_entries: Array<{
      evidence: {
        source_artifact_id?: string | null;
        source_title: string;
        source_url: string;
        source_document_sha256: string;
        locator: string;
      };
    }>;
    model_source_kind: SearchSourceKind;
    model_status: "PASS" | "UNKNOWN";
  } | null;
};

export type DocumentSearchResult = {
  company_id: string;
  document_id: string;
  query: string;
  status: "PASS" | "FAIL" | "UNKNOWN";
  hits: DocumentSearchHit[];
};

export type DocumentSearchPage = {
  query: string;
  effective_at: string;
  results: DocumentSearchResult[];
};

export type DocumentSearchData = {
  page: DocumentSearchPage | null;
  error?: "api" | "configuration" | "validation";
};

export type CompletenessStatus = "PASS" | "FAIL" | "UNKNOWN";

export type UnmappedDisposition =
  | "MATERIAL_REQUIREMENT"
  | "NON_REQUIREMENT"
  | "EXCLUDED_FROM_SCOPE";

export type CompletenessSource = {
  filename: string;
  document_id: string;
  sha256: string;
  role: string;
};

export type CompletenessExtraction = {
  status: string;
  reasons: string[];
};

export type CompletenessMappedRequirement = {
  requirement_id: string;
  text: string;
  status: string;
  provenance: Provenance | null;
};

export type CompletenessUnmappedBlock = {
  block_index: number;
  text: string;
  reason: string;
  provenance: Provenance | null;
};

export type CompletenessReviewSnapshot = {
  evidence_sha256: string;
  source: CompletenessSource;
  extraction: CompletenessExtraction;
  mapped_requirements: CompletenessMappedRequirement[];
  unmapped_blocks: CompletenessUnmappedBlock[];
};

export type CompletenessReviewDecision = {
  evidence_sha256: string;
  status: CompletenessStatus;
  scope: string;
  reason: string;
  reviewer_id: string;
  reviewed_at: string;
};

export type CompletenessReview = {
  review_id: string;
  snapshot: CompletenessReviewSnapshot;
  decision: CompletenessReviewDecision | null;
};

export type CompletenessReviewsData = {
  reviews: CompletenessReview[];
  error?: "api" | "configuration";
};

export type AiRequirementReviewSummary = {
  run_id: string;
  source_document_id: string;
  source_sha256: string;
  report_schema_version: string;
  model: string;
  execution_status: "COMPLETE" | "UNKNOWN";
  completeness_status: "UNKNOWN";
  requirement_candidates_total: number;
  procurement_item_candidates_total: number;
  submitted_by: string;
  submitted_at: string;
  evidence_sha256: string;
  reviewed: boolean;
  reviewed_by: string | null;
  reviewed_at: string | null;
};

export type AiSourceBlock = { block_id: string; text: string; provenance: Provenance };
export type AiRequirementCandidate = {
  candidate_id: string;
  item_name: string | null;
  property: string;
  operator: string;
  value: string | string[] | null;
  unit: string | null;
  mandatory: boolean | null;
  evidence: AiSourceBlock[];
  uncertainties: string[];
};
export type AiEvidenceClaim = { value?: string; raw_value?: string; evidence: AiSourceBlock[] };
export type AiItemCandidate = {
  candidate_id: string;
  item_name: AiEvidenceClaim;
  okpd2_codes: AiEvidenceClaim[];
  ktru_codes: AiEvidenceClaim[];
  unit: AiEvidenceClaim | null;
  quantity: AiEvidenceClaim | null;
  uncertainties: string[];
};
export type AiCandidateDecision = {
  candidate_kind: "REQUIREMENT" | "PROCUREMENT_ITEM";
  candidate_id: string;
  disposition: "ACCEPTED" | "REJECTED" | "NEEDS_CLARIFICATION";
  reason: string;
};
export type AiRequirementReviewDetail = AiRequirementReviewSummary & {
  requirement_candidates: AiRequirementCandidate[];
  procurement_item_candidates: AiItemCandidate[];
  candidate_decisions: AiCandidateDecision[] | null;
};
export type AiRequirementReviewData = {
  reviews: AiRequirementReviewSummary[];
  error?: "api" | "configuration";
};

export type DocumentSetMemberAssessment = "REVIEWED_IN_SCOPE" | "UNRESOLVED";
export type DocumentSetInventoryAssessment = "CONFIRMED_FOR_DECLARED_SCOPE" | "UNRESOLVED";
export type DocumentSetCrossAssessment =
  | "CHECKED_NO_OPEN_ISSUES"
  | "OPEN_ISSUES"
  | "UNRESOLVED";
export type DocumentSetEvidenceReference =
  | { kind: "SOURCE_BLOCK"; member_ordinal: number; extraction_block_index: number }
  | { kind: "MAPPING_FIELD"; member_ordinal: number; field: "delivery_deadline" | "equivalent_allowed" };
export type DocumentSetFinding = {
  finding_id: string;
  kind:
    | "CONFIRMED_MATERIAL_OMISSION"
    | "CONFIRMED_MISSING_DOCUMENT"
    | "UNRESOLVED_CONFLICT"
    | "UNRESOLVED_GAP";
  evidence: DocumentSetEvidenceReference[];
  rationale: string;
  origin: "SERVER" | "REVIEWER";
};
export type DocumentSetConstituentReference = {
  member_ordinal: number;
  review_id: string;
  review_evidence_sha256: string;
  decision_sha256: string;
};
export type DocumentSetMemberAttestation = {
  reference: DocumentSetConstituentReference;
  assessment: DocumentSetMemberAssessment;
  rationale: string;
};
export type DocumentSetReviewEvidence = {
  manifest: {
    company_id: string;
    manifest_id: string;
    scope: string;
    evidence_sha256: string;
    members: Array<{
      ordinal: number;
      source_document_id: string;
      source_document_sha256: string;
      completeness_review_id: string;
      completeness_review_evidence_sha256: string;
    }>;
  };
  constituents: Array<{
    member: DocumentSetReviewEvidence["manifest"]["members"][number];
    decision_sha256: string | null;
    review: {
      snapshot: {
        extraction: { blocks: Array<{ text: string; provenance: Provenance }> };
        mapping: { delivery_deadline: string | null; equivalent_allowed: boolean | null };
      };
      decision: { status: CompletenessStatus } | null;
    };
  }>;
  server_findings: DocumentSetFinding[];
};
export type DocumentSetReviewDecision = {
  company_id: string;
  manifest_id: string;
  manifest_evidence_sha256: string;
  scope: string;
  members: DocumentSetMemberAttestation[];
  inventory_assessment: DocumentSetInventoryAssessment;
  inventory_rationale: string;
  cross_document_assessment: DocumentSetCrossAssessment;
  cross_document_rationale: string;
  findings: DocumentSetFinding[];
  status: CompletenessStatus;
  reason: string;
  decided_by: string;
  decided_at: string;
  decision_sha256: string;
};

export class ApiError extends Error {
  constructor(readonly status: number) {
    super(`API error: ${status}`);
  }
}

export class ConfigurationError extends Error {}

function configuration(): { baseUrl: string; token: string } {
  const { PROCUREMENT_API_URL: url, PROCUREMENT_API_TOKEN: token } = process.env;
  if (!url || !token) {
    throw new ConfigurationError("Procurement API is not configured");
  }
  return { baseUrl: url.replace(/\/$/, ""), token };
}

function aiRequirementsConfiguration(): { baseUrl: string; token: string } {
  const { PROCUREMENT_API_URL: url, PROCUREMENT_AI_REQUIREMENTS_REVIEWER_TOKEN: token } = process.env;
  if (!url || !token) {
    throw new ConfigurationError("AI requirement reviewer API is not configured");
  }
  return { baseUrl: url.replace(/\/$/, ""), token };
}

function documentSetReviewConfiguration(): { baseUrl: string; token: string } {
  const { PROCUREMENT_API_URL: url, PROCUREMENT_DOCUMENT_SET_REVIEWER_TOKEN: token } = process.env;
  if (!url || !token) {
    throw new ConfigurationError("Document-set reviewer API is not configured");
  }
  return { baseUrl: url.replace(/\/$/, ""), token };
}

function requirementSetReviewConfiguration(): { baseUrl: string; token: string } {
  const { PROCUREMENT_API_URL: url, PROCUREMENT_REQUIREMENT_SET_REVIEWER_TOKEN: token } = process.env;
  if (!url || !token) {
    throw new ConfigurationError("Requirement-set reviewer API is not configured");
  }
  return { baseUrl: url.replace(/\/$/, ""), token };
}

function serverOfferReviewConfiguration(): { baseUrl: string; token: string } {
  const { PROCUREMENT_API_URL: url, PROCUREMENT_SERVER_OFFER_REVIEWER_TOKEN: token } = process.env;
  if (!url || !token) {
    throw new ConfigurationError("Server-offer reviewer API is not configured");
  }
  return { baseUrl: url.replace(/\/$/, ""), token };
}

function participationApprovalConfiguration(): { baseUrl: string; token: string } {
  const { PROCUREMENT_API_URL: url, PROCUREMENT_PARTICIPATION_APPROVER_TOKEN: token } = process.env;
  if (!url || !token) {
    throw new ConfigurationError("Participation approver API is not configured");
  }
  return { baseUrl: url.replace(/\/$/, ""), token };
}

function applicationReviewConfiguration(): { baseUrl: string; token: string } {
  const { PROCUREMENT_API_URL: url, PROCUREMENT_APPLICATION_REVIEWER_TOKEN: token } = process.env;
  if (!url || !token) throw new ConfigurationError("Application reviewer API is not configured");
  return { baseUrl: url.replace(/\/$/, ""), token };
}

function submissionApproverConfiguration(): { baseUrl: string; token: string } {
  const { PROCUREMENT_API_URL: url, PROCUREMENT_APPLICATION_SUBMISSION_APPROVER_TOKEN: token } = process.env;
  if (!url || !token) throw new ConfigurationError("Application submission approver API is not configured");
  return { baseUrl: url.replace(/\/$/, ""), token };
}

function submissionExecutorConfiguration(): { baseUrl: string; token: string } {
  const { PROCUREMENT_API_URL: url, PROCUREMENT_APPLICATION_SUBMISSION_EXECUTOR_TOKEN: token } = process.env;
  if (!url || !token) throw new ConfigurationError("Application submission executor API is not configured");
  return { baseUrl: url.replace(/\/$/, ""), token };
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { baseUrl, token } = configuration();
  // Signed-in company searches must never silently use the shared pilot tenant.
  const personal = path.startsWith("/v1/tender-discovery/") ? (await cookies()).get(profileCookie)?.value : undefined;
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${personal ?? token}`);
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    cache: "no-store",
    headers,
    signal: init.signal ?? AbortSignal.timeout(10_000),
  });
  if (!response.ok) {
    throw new ApiError(response.status);
  }
  return (await response.json()) as T;
}

export async function discoverEisExport(file: File, query: string): Promise<EisDiscoveryResult> {
  const form = new FormData();
  form.set("query", query);
  form.set("file", file);
  return request<EisDiscoveryResult>("/v1/tender-discovery/eis-export", {
    method: "POST", body: form, signal: AbortSignal.timeout(30_000),
  });
}

export function searchIndexedEis(
  query: string, searchScope: EisIndexSearchScope = "NOT_EXPIRED_OR_UNKNOWN",
  cursor?: string,
): Promise<EisIndexedSearchResult> {
  return request<EisIndexedSearchResult>(
    `/v1/tender-discovery/eis-index?query=${encodeURIComponent(query)}&search_scope=${searchScope}&page_size=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
    { signal: AbortSignal.timeout(60_000) },
  );
}

export type Eis223TextFact = { value: string | null; raw: string | null; provenance: Provenance };
type Eis223TimeFact = Eis223TextFact & { status: "AWARE" | "UNKNOWN" };
type Eis223DateFact = Eis223TextFact & { timezone_raw: string | null; status: "DATE" | "UNKNOWN" };
export type Eis223LotCancellation = {
  event_type: "purchaseLotCancellation"; event_guid: Eis223TextFact;
  purchase_number: string; purchase_number_provenance: Provenance; purchase_guid: Eis223TextFact;
  created_at: Eis223TimeFact; publication_at: Eis223TimeFact;
  header_guid: Eis223TextFact; header_created_at: Eis223TimeFact; item_guid: Eis223TextFact;
  description_type: "COMMON" | "VARIOUS"; description_type_provenance: Provenance;
  common_cancellation_date: Eis223DateFact; common_cancellation_cause: Eis223TextFact;
  cancelled_lots: Array<{ lot_guid: Eis223TextFact; ordinal: Eis223TextFact; subject: Eis223TextFact;
    joint_lot: Eis223TextFact; cancellation_date: Eis223DateFact; cancellation_cause: Eis223TextFact }>;
  xml_sha256: string; source_member: string;
};
export type Eis223LotCancellationState = {
  purchase_number: string; checked_at: string; evidence_status: "UNKNOWN";
  application_status: "UNKNOWN"; current_procedure_status: "UNKNOWN";
  source_schema_status: "PASS" | "FAIL" | "UNKNOWN";
  operation_hold: boolean; reason_codes: string[]; events: Eis223LotCancellation[];
};
export type Eis223SelectedLotCancellationState = {
  selected_index: number; lot_ordinal: Eis223TextFact; lot_guid: Eis223TextFact | null;
  notice_xml_sha256: string; operation_hold: boolean; application_status: "UNKNOWN";
  association_status: "UNKNOWN"; reason_codes: string[]; apparent_match_event_guids: string[];
};
export type Eis223RejectionState = {
  purchase_number: string; checked_at: string;
  evidence_status: "PASS" | "UNKNOWN"; application_status: "FAIL" | "UNKNOWN";
  current_procedure_status: "UNKNOWN"; operation_hold: boolean; reason_codes: string[];
  events: Array<{ event_type: "purchaseRejection"; event_guid: Eis223TextFact;
    purchase_number: string; purchase_number_provenance: Provenance;
    created_at: Eis223TimeFact; publication_at: Eis223TimeFact; rejection_at: Eis223TimeFact;
    xml_sha256: string; source_member: string }>;
};
export type Eis223SourcePriceKind = "INITIAL_SUM" | "MAX_CONTRACT_PRICE" | "TEXT_ONLY" | "UNKNOWN";
export type Eis223DocumentType = "purchaseNoticeAESMBO" | "purchaseNoticeZKESMBO" | "purchaseNoticeKESMBO" | "purchaseNoticeZPESMBO" | "purchaseNotice";
export type Eis223PositionProjection = {
  law: "223"; document_type: Exclude<Eis223DocumentType, "purchaseNoticeZKESMBO">; purchase_number: string;
  version_number: number; notice_xml_sha256: string; source_member: string;
  parser_version: "eis223-joint-positions-v1"; source_item_coverage: "PASS" | "UNKNOWN";
  specification_completeness: "UNKNOWN"; economics_status: "UNKNOWN"; reasons: string[];
  lots: Array<{ lot_index: number; ordinal: Eis223TextFact; provenance: Provenance;
    customers: Array<{ customer_index: number; name: Eis223TextFact; inn: Eis223TextFact;
      kpp: Eis223TextFact; iko: Eis223TextFact; provenance: Provenance;
      items: Array<{ description: Eis223TextFact; classification_code: Eis223TextFact;
        classification_name: Eis223TextFact; quantity: Eis223TextFact;
        unit_code: Eis223TextFact; unit_name: Eis223TextFact; provenance: Provenance }> }> }>;
};

export type Eis223SearchResult = {
  next_cursor?: string | null; page_snapshot_sha256?: string | null; snapshot_at?: string | null;
  query: string; checked_at: string; indexed_current_notices: number; indexed_windows: number;
  evaluated_candidates: number; matched_count: number; latest_ingested_at: string | null;
  law: "223"; document_types: Eis223DocumentType[];
  coverage: "UNKNOWN"; freshness: "UNKNOWN"; economics_status: "UNKNOWN";
  matched: Array<{
    cancellation_state?: Eis223RejectionState | null;
    lot_cancellation_state?: Eis223LotCancellationState | null;
    position_projection?: Eis223PositionProjection | null;
    notice: {
      law: "223"; document_type: Eis223DocumentType; purchase_number: string;
      version_number: number; xml_sha256: string; source_member: string;
      title: Eis223TextFact; method_name: Eis223TextFact; deadline: Eis223TimeFact;
      publication: Eis223TimeFact; status_raw: Eis223TextFact;
      selected_deadline?: Eis223TimeFact | null;
      hide_purchase_raw?: Eis223TextFact | null;
      hide_purchase_customer_accredited_raw?: Eis223TextFact | null;
      for_small_or_middle_raw?: Eis223TextFact | null;
      is_lot_oriented_raw?: Eis223TextFact | null;
      manifest_additional_count?: Eis223TextFact | null;
      manifest_references?: Array<{ kind: "DOCUMENT_FS" | "PREVIOUS_DOCUMENT";
        guid: Eis223TextFact; content_uid: Eis223TextFact; provenance: Provenance }>;
      application_status: "UNKNOWN"; economics_status: "UNKNOWN"; lot_review_status: "UNKNOWN";
      manifest_status: "COUNT_CONSISTENT" | "UNKNOWN"; manifest_count: Eis223TextFact;
      lots: Array<{
        ordinal: Eis223TextFact; subject: Eis223TextFact; initial_sum: Eis223TextFact;
        currency: Eis223TextFact; initial_sum_rub: string | null;
    currency_numeric?: Eis223TextFact; source_price_formula_present?: boolean | null; source_commodity_price_present?: boolean | null; provenance: Provenance;
        cancelled_raw: Eis223TextFact;
        for_small_or_middle_raw?: Eis223TextFact | null;
        detail_status?: "PRESENT" | "UNKNOWN" | null;
        source_price_kind?: Eis223SourcePriceKind | null;
        source_amount?: Eis223TextFact | null;
        source_rub_equivalent?: Eis223TextFact | null;
        source_price_text?: Eis223TextFact | null;
        source_price_formula?: Eis223TextFact | null;
        source_commodity_price?: Eis223TextFact | null;
        currency_letter_code?: Eis223TextFact | null;
        source_currency_status?: "CONSISTENT" | "UNKNOWN" | null;
        items: Array<{ description: Eis223TextFact; quantity: Eis223TextFact;
          unit_name: Eis223TextFact; provenance: Provenance }>;
      }>;
      attachments: Array<{ filename: Eis223TextFact; content_uid: Eis223TextFact; url: Eis223TextFact;
        not_placement_raw?: Eis223TextFact | null }>;
    };
    source_window: string; source_response_sha256: string; archive_sha256: string;
    match_quality: "STRONG" | "PARTIAL"; matched_terms: string[];
    term_evidence: Array<{ term: string; source_value: string; locator: string; value_kind: string }>;
    matched_lot_ordinal: string | null; application_status: "FAIL" | "UNKNOWN"; reasons: string[];
    source_schema_status: "PASS" | "FAIL" | "UNKNOWN";
    source_schema_checks: Array<{ schema_release: string; xml_sha256: string; tree_sha256: string;
      validator_version: string; checked_at: string; status: "PASS" | "FAIL";
      diagnostics: Array<{ line: number; path: string; type_name: string; message: string }> }>;

  }>;
};

export function searchIndexedEis223(query: string, cursor?: string): Promise<Eis223SearchResult> {
  return request<Eis223SearchResult>(
    `/v1/tender-discovery/eis-223-index?query=${encodeURIComponent(query)}&page_size=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
    { signal: AbortSignal.timeout(60_000) },
  );
}

export type Eis223RegionalCoverage = {
  company_id: string;
  checked_at: string;
  catalog_sha256: string | null;
  catalog_observed_at: string | null;
  catalog_last_success_at: string | null;
  latest_catalog_sha256: string | null;
  latest_catalog_checked_at: string | null;
  catalog_check_status: "ACCEPTED" | "FAILED" | "REVIEW_REQUIRED" | null;
  catalog_check_reason: string | null;
  catalog_source_url: string | null;
  catalog_scope: "UNKNOWN" | "PUBLIC_KLADR_SELECTOR" | "NSI_SUBJECT_RF";
  catalog_regions: number;
  wave_id: string | null;
  start_day: string | null;
  end_day: string | null;
  planned: number;
  attempted: number;
  synced: number;
  no_data: number;
  failed: number;
  unattempted: number;
  due: number;
  cooling: number;
  regions_attempted: number;
  regions_terminal: number;
  old_gaps: number;
  oldest_gap_day: string | null;
  observation_watermark: string | null;
  source_day_lag: number | null;
  first_sweep_finished: boolean;
  scope_status: "UNKNOWN" | "PARTIAL" | "COMPLETE";
  coverage: "UNKNOWN";
  freshness: "UNKNOWN";
  reason: string;
};

export function readEis223RegionalCoverage(): Promise<Eis223RegionalCoverage> {
  return request<Eis223RegionalCoverage>("/v1/tender-discovery/eis-223-coverage");
}

export type EisRefreshStatus = {
  request: {
    request_id: string; company_id: string; payload: { query: string; regions: string[] };
    requested_at: string; expires_at: string; window_keys: string[]; coverage: "UNKNOWN";
  };
  status: "QUEUED" | "PARTIAL" | "POLLED" | "EXPIRED";
  checked_at: string; polled_windows: number; pending_windows: number;
  synced_windows: number; no_data_windows: number; failed_windows: number;
  windows: { window_key: string; outcome: string | null; attempt_id: string | null;
    attempted_at: string | null; response_sha256: string | null; reason: string | null;
    polled_after_request: boolean }[];
  coverage: "UNKNOWN"; freshness: "UNKNOWN";
};

export function requestEisRefresh(query: string, regions: string[]): Promise<EisRefreshStatus> {
  return request<EisRefreshStatus>("/v1/tender-discovery/eis-refresh-requests", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, regions }),
  });
}

export function readEisRefresh(requestId: string): Promise<EisRefreshStatus> {
  return request<EisRefreshStatus>(`/v1/tender-discovery/eis-refresh-requests/${encodeURIComponent(requestId)}`);
}

function documentJobPath(ref: NoticeDocumentRef, suffix = ""): string {
  const params = new URLSearchParams({ version_number: String(ref.version_number),
    notice_xml_sha256: ref.notice_xml_sha256 });
  return `/v1/tender-discovery/eis-document-jobs/${encodeURIComponent(ref.purchase_number)}${suffix}?${params}`;
}

export function requestIndexedDocuments(ref: NoticeDocumentRef): Promise<DocumentCollectionStatus> {
  return request<DocumentCollectionStatus>("/v1/tender-discovery/eis-document-jobs", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(ref),
  });
}

export function selectIndexedDocuments(query: string, maxCandidates = 3): Promise<DocumentSelectionResult> {
  return request<DocumentSelectionResult>("/v1/tender-discovery/eis-document-selection", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, max_candidates: maxCandidates }),
  });
}

export function readIndexedDocuments(ref: NoticeDocumentRef): Promise<DocumentCollectionStatus> {
  return request<DocumentCollectionStatus>(documentJobPath(ref));
}

export function readIndexedDocumentAnalysis(ref: NoticeDocumentRef, uid: string): Promise<DocumentAnalysis> {
  return request<DocumentAnalysis>(documentJobPath(ref, `/${encodeURIComponent(uid)}/analysis`));
}

async function requestReviewPage(payload: ReviewRequest, cursor: ReviewCursor, prepare: boolean): Promise<SavedReviewPage> {
  if (!validReviewRequest(payload) || !validReviewCursor(cursor)) throw new ApiError(422);
  const { baseUrl, token } = configuration();
  const response = await fetch(`${baseUrl}/v1/tender-discovery/eis-document-review/${prepare ? "prepare" : "page"}`, {
    method: "POST", cache: "no-store", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(prepare ? payload : { request: payload, ...cursor }), signal: AbortSignal.timeout(55_000),
  });
  if (!response.ok) { await response.body?.cancel(); throw new ApiError(response.status); }
  if (!response.body || response.headers.get("Cache-Control") !== "no-store" ||
    response.headers.get("content-type")?.split(";", 1)[0] !== "application/json") {
    await response.body?.cancel(); throw new ApiError(422);
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = []; let size = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read(); if (done) break;
      size += value.byteLength;
      if (size > 256 * 1024) { await reader.cancel(); throw new ApiError(422); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  let result: unknown;
  try { result = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); }
  catch { throw new ApiError(422); }
  if (!reviewPageMatches(result, payload, cursor, prepare)) throw new ApiError(422);
  return result;
}

export function prepareIndexedDocumentReview(payload: ReviewRequest): Promise<SavedReviewPage> {
  return requestReviewPage(payload, firstReviewCursor, true);
}
export function readIndexedDocumentReview(payload: ReviewRequest, cursor: ReviewCursor): Promise<SavedReviewPage> {
  return requestReviewPage(payload, cursor, false);
}

export function readIndexedEvidence(ref: NoticeDocumentRef): Promise<EisEvidenceBridge> {
  return request<EisEvidenceBridge>(documentJobPath(ref, "/evidence"));
}

export function estimateIndexedNotice(
  ref: NoticeDocumentRef, costs: EisPreliminaryCostInput,
): Promise<EisPreliminaryEstimate> {
  return request<EisPreliminaryEstimate>(documentJobPath(ref, "/estimate"), {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(costs),
  });
}

export async function inspectEisAttachment(
  attachment: EisAttachment,
): Promise<EisDocumentPreview> {
  return request<EisDocumentPreview>("/v1/tender-discovery/eis-attachment", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: attachment.url, filename: attachment.filename }),
    signal: AbortSignal.timeout(35_000),
  });
}

export function searchLiveEis(query: string): Promise<EisPublicSearchResult> {
  return request<EisPublicSearchResult>(
    `/v1/tender-discovery/eis-live?query=${encodeURIComponent(query)}`,
    { signal: AbortSignal.timeout(45_000) },
  );
}

export function verifyLiveEisNumber(number: string): Promise<EisLiveVerification> {
  return request<EisLiveVerification>(
    `/v1/tender-discovery/eis-live/${encodeURIComponent(number)}/verify`,
    { method: "POST", signal: AbortSignal.timeout(150_000) },
  );
}

export function listLiveEisDocuments(url: string): Promise<EisPublicDocumentsResult> {
  return request<EisPublicDocumentsResult>("/v1/tender-discovery/eis-documents", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }), signal: AbortSignal.timeout(45_000),
  });
}

async function aiRequirementsRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { baseUrl, token } = aiRequirementsConfiguration();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    cache: "no-store",
    headers,
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok) throw new ApiError(response.status);
  return (await response.json()) as T;
}

async function documentSetReviewRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { baseUrl, token } = documentSetReviewConfiguration();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    cache: "no-store",
    headers,
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok) throw new ApiError(response.status);
  return (await response.json()) as T;
}

async function requirementSetReviewRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { baseUrl, token } = requirementSetReviewConfiguration();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    cache: "no-store",
    headers,
    signal: init.signal ?? AbortSignal.timeout(10_000),
  });
  if (!response.ok) throw new ApiError(response.status);
  return (await response.json()) as T;
}

async function serverOfferReviewRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { baseUrl, token } = serverOfferReviewConfiguration();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    cache: "no-store",
    headers,
    signal: init.signal ?? AbortSignal.timeout(10_000),
  });
  if (!response.ok) throw new ApiError(response.status);
  return (await response.json()) as T;
}

async function participationApprovalRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { baseUrl, token } = participationApprovalConfiguration();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    cache: "no-store",
    headers,
    signal: init.signal ?? AbortSignal.timeout(10_000),
  });
  if (!response.ok) throw new ApiError(response.status);
  return (await response.json()) as T;
}

async function applicationReviewRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { baseUrl, token } = applicationReviewConfiguration();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    cache: "no-store",
    headers,
    signal: init.signal ?? AbortSignal.timeout(20_000),
  });
  if (!response.ok) throw new ApiError(response.status);
  return (await response.json()) as T;
}

function participationDecisionPath(evaluationId: string): string {
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/.test(evaluationId)) {
    throw new Error("Invalid evaluation identity");
  }
  return `/v1/evaluations/${encodeURIComponent(evaluationId)}/participation-decision`;
}

export function loadParticipationDecision(
  evaluationId: string,
): Promise<ParticipationDecisionRecord> {
  return participationApprovalRequest(participationDecisionPath(evaluationId));
}

export function decideParticipation(
  evaluationId: string,
  payload: {
    evaluation_evidence_sha256: string;
    status: ParticipationDecisionStatus;
    reason: string;
  },
): Promise<ParticipationDecision> {
  return participationApprovalRequest(participationDecisionPath(evaluationId), {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey() },
    body: JSON.stringify(payload),
  });
}

function applicationPackagePath(decisionId: string): string {
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/.test(decisionId)) {
    throw new Error("Invalid participation decision identity");
  }
  return `/v1/participation-decisions/${encodeURIComponent(decisionId)}/application-package`;
}

export function loadApplicationPackage(
  decisionId: string,
): Promise<ApplicationPackageRecord> {
  return request(applicationPackagePath(decisionId));
}

export function createApplicationPackage(
  decisionId: string,
  payload: {
    participation_decision_sha256: string;
    proposed_price_ex_vat: string;
    requirements: ApplicationDocumentRequirement[];
    attachments: ApplicationAttachmentInput[];
  },
): Promise<ApplicationPackage> {
  return request(applicationPackagePath(decisionId), {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey() },
    body: JSON.stringify(payload),
  });
}

function applicationReviewPath(packageId: string): string {
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/.test(packageId)) {
    throw new Error("Invalid application package identity");
  }
  return `/v1/application-packages/${encodeURIComponent(packageId)}/review`;
}

export function loadApplicationReview(packageId: string): Promise<ApplicationReviewRecord> {
  return applicationReviewRequest(applicationReviewPath(packageId));
}

function applicationSubmissionPath(packageId: string): string {
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/.test(packageId)) {
    throw new Error("Invalid application package identity");
  }
  return `/v1/application-packages/${encodeURIComponent(packageId)}/submission`;
}

async function submissionApproverRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { baseUrl, token } = submissionApproverConfiguration();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${baseUrl}${path}`, {
    ...init, cache: "no-store", headers,
    signal: init.signal ?? AbortSignal.timeout(10_000),
  });
  if (!response.ok) throw new ApiError(response.status);
  return (await response.json()) as T;
}

export function loadApplicationSubmission(packageId: string): Promise<ApplicationSubmissionRecord> {
  return request(applicationSubmissionPath(packageId));
}

export function prepareApplicationSubmission(
  packageId: string,
  payload: { package_sha256: string; review_decision_sha256: string; destination: string },
): Promise<ApplicationSubmissionIntent> {
  return request(applicationSubmissionPath(packageId), {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey() },
    body: JSON.stringify(payload),
  });
}

export function loadApplicationSubmissionForApprover(packageId: string): Promise<ApplicationSubmissionRecord> {
  return submissionApproverRequest(applicationSubmissionPath(packageId));
}

export function decideApplicationSubmission(
  packageId: string,
  payload: { action_id: string; payload_sha256: string; status: "APPROVED" | "REJECTED"; reason: string },
): Promise<ApplicationSubmissionApproval> {
  return submissionApproverRequest(`${applicationSubmissionPath(packageId)}/approval`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey() },
    body: JSON.stringify(payload),
  });
}

async function submissionExecutorRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { baseUrl, token } = submissionExecutorConfiguration();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${baseUrl}${path}`, {
    ...init, cache: "no-store", headers,
    signal: init.signal ?? AbortSignal.timeout(10_000),
  });
  if (!response.ok) throw new ApiError(response.status);
  return (await response.json()) as T;
}

export function loadApplicationSubmissionExecution(packageId: string): Promise<ApplicationSubmissionExecutionRecord> {
  return submissionExecutorRequest(`${applicationSubmissionPath(packageId)}/admission`);
}

export async function downloadApplicationHandoff(packageId: string): Promise<ArrayBuffer> {
  const { baseUrl, token } = submissionExecutorConfiguration();
  const response = await fetch(`${baseUrl}${applicationSubmissionPath(packageId)}/handoff`, {
    cache: "no-store",
    headers: { Authorization: `Bearer ${token}` },
    signal: AbortSignal.timeout(60_000),
  });
  if (!response.ok) throw new ApiError(response.status);
  return response.arrayBuffer();
}

export function claimApplicationSubmission(
  packageId: string,
  payload: { action_id: string; payload_sha256: string; approval_decision_sha256: string },
): Promise<ApplicationSubmissionAdmission> {
  return submissionExecutorRequest(`${applicationSubmissionPath(packageId)}/admission`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey() },
    body: JSON.stringify(payload),
  });
}

export function decideApplicationReview(
  packageId: string,
  payload: {
    package_sha256: string;
    requirement_reviews: ApplicationRequirementReview[];
    attachment_reviews: ApplicationAttachmentReview[];
    inventory_assessment: ApplicationInventoryAssessment;
    inventory_source_document_ids: string[];
    inventory_reason: string;
    price_assessment: ApplicationPriceAssessment;
    price_reason: string;
    reason: string;
  },
): Promise<ApplicationReviewDecision> {
  return applicationReviewRequest(applicationReviewPath(packageId), {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey() },
    body: JSON.stringify(payload),
  });
}

export function loadApplicationReviewDocument(
  documentId: string,
): Promise<ApplicationReviewDocument> {
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/.test(documentId)) {
    throw new Error("Invalid application document identity");
  }
  return applicationReviewRequest(`/v1/documents/${encodeURIComponent(documentId)}`);
}

export async function downloadApplicationReviewDocument(
  packageId: string,
  documentId: string,
): Promise<{ bytes: ArrayBuffer; contentType: string; disposition: string }> {
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/.test(documentId)) {
    throw new Error("Invalid application document identity");
  }
  const { baseUrl, token } = applicationReviewConfiguration();
  const response = await fetch(
    `${baseUrl}${applicationReviewPath(packageId)}/documents/${encodeURIComponent(documentId)}/content`,
    { cache: "no-store", headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(30_000) },
  );
  if (!response.ok) throw new ApiError(response.status);
  return {
    bytes: await response.arrayBuffer(),
    contentType: response.headers.get("content-type") ?? "application/octet-stream",
    disposition: response.headers.get("content-disposition") ?? "attachment",
  };
}

export async function loadDashboard(): Promise<DashboardData> {
  try {
    const page = await request<{ items: ProcurementCase[] }>("/v1/cases?limit=100");
    const cases = await Promise.all(
      page.items.map(async (item): Promise<CaseCardData> => {
        const base = `/v1/cases/${encodeURIComponent(item.case_id)}/versions/${item.version}`;
        const optional = async <T,>(path: string): Promise<T | null> => {
          try {
            return await request<T>(path);
          } catch (error) {
            if (error instanceof ApiError && error.status === 404) return null;
            throw error;
          }
        };
        const [evaluation, sourcing] = await Promise.all([
          optional<EvaluationRecord>(`${base}/evaluations/latest`),
          optional<SourcingRunRecord>(`${base}/sourcing-runs/latest`),
        ]);
        return { case: item, evaluation, sourcing };
      }),
    );
    return { cases };
  } catch (error) {
    return {
      cases: [],
      error: error instanceof ConfigurationError ? "configuration" : "api",
    };
  }
}

export async function searchEaeuRegistry(query: string): Promise<{
  result: EaeuRegistrySearchResult | null;
  error?: "validation" | "configuration" | "api";
}> {
  const normalized = query.trim().replace(/\s+/g, " ");
  if (!normalized || normalized.length > 80 || normalized.split(" ").length > 5) {
    return { result: null, error: "validation" };
  }
  try {
    const path = `/v1/supplier-discovery/eaeu?query=${encodeURIComponent(normalized)}`;
    return { result: await request<EaeuRegistrySearchResult>(path, { signal: AbortSignal.timeout(20_000) }) };
  } catch (error) {
    return {
      result: null,
      error: error instanceof ConfigurationError ? "configuration" : "api",
    };
  }
}

export async function searchEaeuManufacturers(query: string): Promise<{
  result: EaeuManufacturerSearchResult | null;
  error?: "validation" | "configuration" | "api";
}> {
  const normalized = query.trim().replace(/\s+/g, " ");
  if (!normalized || normalized.length > 80 || normalized.split(" ").length > 5) {
    return { result: null, error: "validation" };
  }
  try {
    const path = `/v1/supplier-discovery/eaeu-manufacturers?query=${encodeURIComponent(normalized)}`;
    return { result: await request<EaeuManufacturerSearchResult>(path, { signal: AbortSignal.timeout(20_000) }) };
  } catch (error) {
    return {
      result: null,
      error: error instanceof ConfigurationError ? "configuration" : "api",
    };
  }
}

export async function searchDirectCatalog(query: string): Promise<{
  result: DirectCatalogSearchResult | null;
  error?: "validation" | "configuration" | "api";
}> {
  const normalized = query.trim().replace(/\s+/g, " ");
  if (!normalized || normalized.length > 80 || normalized.split(" ").length > 5) {
    return { result: null, error: "validation" };
  }
  try {
    const path = `/v1/supplier-discovery/direct-catalog?query=${encodeURIComponent(normalized)}`;
    return { result: await request<DirectCatalogSearchResult>(path, { signal: AbortSignal.timeout(25_000) }) };
  } catch (error) {
    return {
      result: null,
      error: error instanceof ConfigurationError ? "configuration" : "api",
    };
  }
}

export async function searchYandexBusinessCategory(query: string): Promise<{
  result: YandexBusinessSearchResult | null;
  error?: "validation" | "configuration" | "api";
}> {
  const normalized = query.trim().replace(/\s+/g, " ");
  if (!normalized || normalized.length > 80 || normalized.split(" ").length > 5) {
    return { result: null, error: "validation" };
  }
  try {
    const path = `/v1/supplier-discovery/yandex-business?query=${encodeURIComponent(normalized)}`;
    return { result: await request<YandexBusinessSearchResult>(path, { signal: AbortSignal.timeout(25_000) }) };
  } catch (error) {
    return {
      result: null,
      error: error instanceof ConfigurationError ? "configuration" : "api",
    };
  }
}

export function loadDocumentSupplierSearchPlan(documentId: string, mode: SupplierSearchMode = "AUTO"): Promise<DocumentSupplierSearchPlan> {
  return request(`/v1/documents/${encodeURIComponent(documentId)}/supplier-search-plan?mode=${mode}`, {
    signal: AbortSignal.timeout(20_000),
  });
}

export function runDocumentSupplierSearch(
  documentId: string,
  planSha256: string,
  mode: SupplierSearchMode = "AUTO",
): Promise<DocumentSupplierSearchRun> {
  return request(`/v1/documents/${encodeURIComponent(documentId)}/supplier-search-runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan_sha256: planSha256, approve_exact_payload: true, mode }),
    signal: AbortSignal.timeout(90_000),
  });
}

export async function loadDocumentSearch(query: string): Promise<DocumentSearchData> {
  const normalized = query.trim();
  if (!normalized || normalized.length > 200 || !/[\p{L}\p{N}]/u.test(normalized)) {
    return { page: null, error: "validation" };
  }
  try {
    const path = `/v1/document-search?query=${encodeURIComponent(normalized)}&limit=50`;
    return { page: await request<DocumentSearchPage>(path) };
  } catch (error) {
    return {
      page: null,
      error: error instanceof ConfigurationError ? "configuration" : "api",
    };
  }
}

function idempotencyKey(): string {
  return crypto.randomUUID();
}

export type UploadDocumentRole =
  | "TENDER_REQUIREMENTS"
  | "SUPPLIER_QUOTE"
  | "APPLICATION_ATTACHMENT";

export type UploadedDocument = {
  document_id: string;
  original_filename: string;
  document_role: UploadDocumentRole;
  sha256: string;
  extraction: { status: "PASS" | "FAIL" | "UNKNOWN"; reasons: string[] };
};

export function uploadDocument(file: File, role: UploadDocumentRole): Promise<UploadedDocument> {
  const body = new FormData();
  body.append("file", file, file.name);
  body.append("document_role", role);
  return request("/v1/documents", {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey() },
    body,
    signal: AbortSignal.timeout(60_000),
  });
}

export function createCase(payload: unknown): Promise<ProcurementCase> {
  return request("/v1/cases", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey(),
    },
    body: JSON.stringify(payload),
  });
}

export type CaseFromEvidencePayload = {
  case: unknown;
  binding_id: string;
  manifest_evidence_sha256: string;
  decision_sha256: string;
  other_checks: unknown[];
};

export function createCaseFromEvidence(payload: CaseFromEvidencePayload): Promise<ProcurementCase> {
  return request("/v1/cases/from-evidence", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey(),
    },
    body: JSON.stringify(payload),
  });
}

export function createEvaluation(
  caseId: string,
  version: string,
  effectiveAt: string,
): Promise<EvaluationRecord> {
  const path = `/v1/cases/${encodeURIComponent(caseId)}/versions/${encodeURIComponent(version)}/evaluations`;
  return request(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey(),
    },
    body: JSON.stringify({ effective_at: effectiveAt }),
  });
}

export function runServerSourcing(
  caseId: string,
  version: string,
  query: string,
): Promise<SourcingRunRecord> {
  const path = `/v1/cases/${encodeURIComponent(caseId)}/versions/${encodeURIComponent(version)}/sourcing-runs`;
  return request(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey(),
    },
    body: JSON.stringify({ query }),
    signal: AbortSignal.timeout(30_000),
  });
}

export function previewRequirementSetMaterialization(
  documentId: string,
  sourceDocumentSha256: string,
  expectedEntryCount: number,
): Promise<RequirementSetMaterializationPreview> {
  return request(
    `/v1/documents/${encodeURIComponent(documentId)}/reviewed-requirement-set-preview`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_document_sha256: sourceDocumentSha256,
        expected_entry_count: expectedEntryCount,
      }),
    },
  );
}

export function materializeReviewedRequirementSet(
  documentId: string,
  payload: {
    source_document_sha256: string;
    expected_entry_count: number;
    preview_sha256: string;
    declared_scope: string;
    selections: ExecutableRequirementSelection[];
  },
): Promise<ReviewedRequirementSetRecord> {
  return request(
    `/v1/documents/${encodeURIComponent(documentId)}/reviewed-requirement-set-materializations`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey(),
      },
      body: JSON.stringify(payload),
    },
  );
}

function reviewedRequirementSetPath(setId: string, suffix = ""): string {
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/.test(setId)) {
    throw new Error("Invalid reviewed requirement-set ID");
  }
  return `/v1/reviewed-requirement-sets/${encodeURIComponent(setId)}${suffix}`;
}

export function loadReviewedRequirementSetForReview(
  setId: string,
): Promise<ReviewedRequirementSetRecord> {
  return requirementSetReviewRequest(reviewedRequirementSetPath(setId));
}

export function decideReviewedRequirementSet(
  setId: string,
  payload: {
    proposal_sha256: string;
    coverage_assessment: RequirementSetCoverageAssessment;
    normalization_assessment: RequirementSetNormalizationAssessment;
    status: "PASS" | "FAIL" | "UNKNOWN";
    reason: string;
  },
): Promise<ReviewedRequirementSetRecord> {
  return requirementSetReviewRequest(reviewedRequirementSetPath(setId, "/decision"), {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey() },
    body: JSON.stringify(payload),
  });
}

export function loadReviewedRequirementSet(
  setId: string,
): Promise<ReviewedRequirementSetRecord> {
  return request(reviewedRequirementSetPath(setId));
}

export function bindReviewedRequirementSet(payload: {
  case_id: string;
  case_version: number;
  set_id: string;
  proposal_sha256: string;
  decision_sha256: string;
}): Promise<CaseRequirementSetBinding> {
  return request("/v1/case-requirement-set-bindings", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey() },
    body: JSON.stringify(payload),
  });
}

export function createServerOfferProposal(
  caseId: string,
  caseVersion: number,
  payload: {
    requirement_set_binding_id: string;
    requirement_set_binding_sha256: string;
    sourcing_run_id: string;
    lead_id: string;
    source_document_id: string;
    source_document_sha256: string;
    bom_lines: ServerOfferBomLineInput[];
    commercial_terms: ServerOfferCommercialTermsInput;
  },
): Promise<ServerOfferProposal> {
  return request(
    `/v1/cases/${encodeURIComponent(caseId)}/versions/${caseVersion}/server-offer-proposals`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey() },
      body: JSON.stringify(payload),
    },
  );
}

export function loadServerOfferProposal(offerId: string): Promise<ServerOfferProposal> {
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/.test(offerId)) {
    throw new Error("Invalid server-offer proposal ID");
  }
  return request(`/v1/server-offer-proposals/${encodeURIComponent(offerId)}`);
}

function serverOfferReviewPath(offerId: string, suffix = ""): string {
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/.test(offerId)) {
    throw new Error("Invalid server-offer proposal ID");
  }
  return `/v1/server-offer-proposals/${encodeURIComponent(offerId)}${suffix}`;
}

export function loadServerOfferReview(offerId: string): Promise<ServerOfferReviewRecord> {
  return serverOfferReviewRequest(serverOfferReviewPath(offerId, "/review"));
}

export function decideServerOfferReview(
  offerId: string,
  payload: {
    proposal_sha256: string;
    requirement_decisions: ServerOfferRequirementDecision[];
    bom_scope_assessment: ServerOfferBomScopeAssessment;
    commercial_terms_assessment: ServerOfferCommercialAssessment;
    reason: string;
  },
): Promise<ServerOfferReviewDecision> {
  return serverOfferReviewRequest(serverOfferReviewPath(offerId, "/review-decision"), {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey() },
    body: JSON.stringify(payload),
  });
}

function serverOfferEconomicsPath(caseId: string, version: number, offerId?: string): string {
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/.test(caseId) || version < 1) {
    throw new Error("Invalid case identity");
  }
  const base = `/v1/cases/${encodeURIComponent(caseId)}/versions/${version}/server-offer-economics`;
  return offerId ? `${base}?offer_id=${encodeURIComponent(offerId)}` : base;
}

export function loadServerOfferEconomics(
  caseId: string, version: number, offerId: string,
): Promise<ServerOfferEconomicsRecord> {
  return request(serverOfferEconomicsPath(caseId, version, offerId));
}

export function createServerOfferEconomics(
  caseId: string,
  version: number,
  payload: {
    offer_id: string;
    offer_proposal_sha256: string;
    offer_review_decision_sha256: string;
    scenarios: ServerOfferScenarioInput[];
  },
): Promise<ServerOfferEconomicsPackage> {
  return request(serverOfferEconomicsPath(caseId, version), {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey() },
    body: JSON.stringify(payload),
  });
}

export function materializeServerOfferEconomicsCase(
  caseId: string,
  version: number,
  payload: { offer_id: string; economics_id: string; package_sha256: string },
): Promise<ProcurementCase> {
  return request(`${serverOfferEconomicsPath(caseId, version)}/materialize`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey() },
    body: JSON.stringify(payload),
  });
}

function hardGateAssessmentPath(caseId: string, version: number, suffix: string): string {
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/.test(caseId) || version < 1) {
    throw new Error("Invalid case identity");
  }
  return `/v1/cases/${encodeURIComponent(caseId)}/versions/${version}/hard-gate-assessments/${suffix}`;
}

export function loadCaseHardGateAssessmentEvidence(
  caseId: string,
  version: number,
): Promise<CaseHardGateAssessmentEvidence> {
  return request(hardGateAssessmentPath(caseId, version, "evidence"));
}

export function materializeCaseHardGateAssessment(
  caseId: string,
  version: number,
  payload: {
    source_case_input_sha256: string;
    document_binding_id: string;
    manifest_evidence_sha256: string;
    document_decision_sha256: string;
    decisions: CaseHardGateDecisionInput[];
  },
): Promise<ProcurementCase> {
  return request(hardGateAssessmentPath(caseId, version, "materialize"), {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey() },
    body: JSON.stringify(payload),
  });
}

export async function loadCompletenessReviews(): Promise<CompletenessReviewsData> {
  try {
    const response = await request<unknown>("/v1/completeness-reviews?limit=100");
    const items = Array.isArray(response) ? response : arrayAt(asRecord(response).items);
    return { reviews: items.map(normalizeCompletenessReview) };
  } catch (error) {
    return {
      reviews: [],
      error: error instanceof ConfigurationError ? "configuration" : "api",
    };
  }
}

export async function createCompletenessReviewDecision(
  reviewId: string,
  payload: {
    evidence_sha256: string;
    status: CompletenessStatus;
    scope: string;
    reason: string;
    unmapped_reviews: Array<{
      block_index: number;
      disposition: UnmappedDisposition;
      rationale: string;
    }>;
  },
): Promise<CompletenessReviewDecision> {
  const { unmapped_reviews, ...decisionFields } = payload;
  const response = await request<unknown>(`/v1/completeness-reviews/${encodeURIComponent(reviewId)}/decision`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey(),
    },
    // The current FastAPI model calls these `block_decisions`/`unmapped_index`.
    // Keep the BFF input semantic and translate this minor wire-name difference here.
    body: JSON.stringify({
      ...decisionFields,
      block_decisions: unmapped_reviews.map((item) => ({
        unmapped_index: item.block_index,
        disposition: item.disposition,
        rationale: item.rationale,
      })),
    }),
  });
  const decision = normalizeCompletenessReview(response).decision;
  if (!decision) throw new Error("API response omitted the persisted completeness decision");
  return decision;
}

function normalizeCompletenessReview(value: unknown): CompletenessReview {
  const record = asRecord(value);
  const snapshot = asRecord(record.snapshot);
  const mapping = asRecord(snapshot.mapping);
  const source = asRecord(snapshot.source_document ?? snapshot.source ?? snapshot.document);
  const extraction = asRecord(snapshot.extraction);
  const requirements = arrayAt(
    snapshot.mapped_requirements ?? snapshot.requirements ?? mapping.requirements,
  );
  const unmapped = arrayAt(
    snapshot.unmapped_blocks ?? snapshot.unmapped ?? mapping.unmapped_blocks ?? mapping.unmapped,
  );
  const decision = asRecord(record.decision);
  const evidenceSha = stringAt(snapshot.evidence_sha256 ?? record.evidence_sha256 ?? source.evidence_sha256);

  return {
    review_id: stringAt(record.review_id ?? snapshot.review_id ?? record.id),
    snapshot: {
      evidence_sha256: evidenceSha,
      source: {
        filename: stringAt(source.filename ?? source.file_name ?? source.source_filename ?? snapshot.source_filename),
        document_id: stringAt(source.document_id ?? source.source_document_id ?? snapshot.source_document_id ?? source.id),
        sha256: stringAt(source.sha256 ?? source.source_document_sha256 ?? snapshot.source_document_sha256 ?? evidenceSha),
        role: stringAt(source.role ?? source.document_role ?? mapping.document_role),
      },
      extraction: {
        status: stringAt(extraction.status ?? snapshot.extraction_status),
        reasons: arrayAt(extraction.reasons ?? snapshot.extraction_reasons)
          .map((item) => stringAt(item))
          .filter(Boolean),
      },
      mapped_requirements: requirements.map((item, index) => {
        const requirement = asRecord(item);
        return {
          requirement_id: stringAt(
            requirement.requirement_id ?? requirement.id ?? `requirement-${index + 1}`,
          ),
          text: stringAt(
            requirement.text ?? requirement.raw_text ?? requirement.description ?? requirement.label ?? requirement.property,
          ),
          status: typeof requirement.mandatory === "boolean"
            ? (requirement.mandatory ? "MANDATORY" : "OPTIONAL")
            : stringAt(requirement.status),
          provenance: normalizeProvenance(requirement.provenance ?? requirement.source),
        };
      }),
      unmapped_blocks: unmapped.map((item, index) => {
        const block = asRecord(item);
        return {
          block_index: integerAt(block.block_index ?? block.index, index),
          text: stringAt(block.text ?? block.block_text ?? block.content),
          reason: stringAt(block.reason ?? block.unmapped_reason),
          provenance: normalizeProvenance(block.provenance ?? block.source),
        };
      }),
    },
    decision: Object.keys(decision).length
      ? {
          evidence_sha256: stringAt(decision.evidence_sha256 ?? evidenceSha),
          status: completenessStatusAt(decision.status),
          scope: stringAt(decision.scope),
          reason: stringAt(decision.reason),
          reviewer_id: stringAt(decision.reviewer_id ?? decision.decided_by ?? decision.reviewed_by ?? decision.reviewer),
          reviewed_at: stringAt(decision.reviewed_at ?? decision.decided_at ?? decision.created_at),
        }
      : null,
  };
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function arrayAt(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function stringAt(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function integerAt(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : fallback;
}

function normalizeProvenance(value: unknown): Provenance | null {
  const provenance = asRecord(value);
  const documentId = stringAt(provenance.document_id);
  const locator = stringAt(provenance.locator);
  if (!documentId && !locator) return null;
  return {
    document_id: documentId,
    locator,
    extractor: typeof provenance.extractor === "string" ? provenance.extractor : null,
    confidence: typeof provenance.confidence === "number" ? provenance.confidence : null,
  };
}

function completenessStatusAt(value: unknown): CompletenessStatus {
  return value === "PASS" || value === "FAIL" || value === "UNKNOWN" ? value : "UNKNOWN";
}

export async function loadAiRequirementReviews(): Promise<AiRequirementReviewData> {
  try {
    return {
      reviews: await aiRequirementsRequest<AiRequirementReviewSummary[]>(
        "/v1/ai-requirement-runs?limit=100",
      ),
    };
  } catch (error) {
    return { reviews: [], error: error instanceof ConfigurationError ? "configuration" : "api" };
  }
}

export async function loadAiRequirementReview(runId: string): Promise<AiRequirementReviewDetail | null> {
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/.test(runId)) return null;
  return aiRequirementsRequest<AiRequirementReviewDetail>(
    `/v1/ai-requirement-runs/${encodeURIComponent(runId)}`,
  );
}

export function decideAiRequirementReview(
  runId: string,
  payload: { evidence_sha256: string; candidate_decisions: AiCandidateDecision[] },
): Promise<AiRequirementReviewDetail> {
  return aiRequirementsRequest(`/v1/ai-requirement-runs/${encodeURIComponent(runId)}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey() },
    body: JSON.stringify(payload),
  });
}

function documentSetManifestPath(manifestId: string, suffix: string): string {
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/.test(manifestId)) {
    throw new Error("Invalid document-set manifest ID");
  }
  return `/v1/document-sets/${encodeURIComponent(manifestId)}/${suffix}`;
}

export function loadDocumentSetReviewEvidence(manifestId: string): Promise<DocumentSetReviewEvidence> {
  return documentSetReviewRequest(documentSetManifestPath(manifestId, "completeness-evidence"));
}

export async function loadDocumentSetReviewDecision(
  manifestId: string,
): Promise<DocumentSetReviewDecision | null> {
  try {
    return await documentSetReviewRequest<DocumentSetReviewDecision>(
      documentSetManifestPath(manifestId, "completeness-decisions"),
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export function createDocumentSetReviewDecision(
  manifestId: string,
  payload: {
    manifest_evidence_sha256: string;
    attestations: DocumentSetMemberAttestation[];
    inventory_assessment: DocumentSetInventoryAssessment;
    inventory_rationale: string;
    cross_document_assessment: DocumentSetCrossAssessment;
    cross_document_rationale: string;
    reviewer_findings: DocumentSetFinding[];
    status: CompletenessStatus;
    reason: string;
  },
): Promise<DocumentSetReviewDecision> {
  return documentSetReviewRequest(documentSetManifestPath(manifestId, "completeness-decisions"), {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey() },
    body: JSON.stringify(payload),
  });
}

async function requestSupplierSearch(payload: SupplierSearchRequest, prepare: boolean, refresh = false): Promise<SavedSupplierSearch> {
  if (!validSupplierSearchRequest(payload)) throw new ApiError(422);
  const { baseUrl, token } = configuration();
  const response = await fetch(`${baseUrl}/v1/tender-discovery/eis-supplier-search/${prepare ? "prepare" : "read"}`, {
    method: "POST", cache: "no-store", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(prepare ? { request: payload, refresh } : { request: payload }), signal: AbortSignal.timeout(70_000),
  });
  if (!response.ok) { await response.body?.cancel(); throw new ApiError(response.status); }
  if (!response.body || response.headers.get("Cache-Control") !== "no-store" ||
    response.headers.get("content-type")?.split(";", 1)[0] !== "application/json") {
    await response.body?.cancel(); throw new ApiError(422);
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = []; let size = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read(); if (done) break;
      size += value.byteLength;
      if (size > 256 * 1024) { await reader.cancel(); throw new ApiError(422); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  let result: unknown;
  try { result = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); }
  catch { throw new ApiError(422); }
  if (!supplierSearchMatches(result, payload, prepare)) throw new ApiError(422);
  return result;
}

export function prepareIndexedSupplierSearch(payload: SupplierSearchRequest, refresh = false): Promise<SavedSupplierSearch> {
  return requestSupplierSearch(payload, true, refresh);
}
export function readIndexedSupplierSearch(payload: SupplierSearchRequest): Promise<SavedSupplierSearch> {
  return requestSupplierSearch(payload, false);
}

async function positionAssociationResponse(payload: AssociationRequest | AssociationListRequest | AssociationDetailRequest,
  operation: "save" | "read" | "list" | "detail"): Promise<unknown> {
  const body = JSON.stringify({ request: payload });
  if (new TextEncoder().encode(body).length > 4096) throw new ApiError(413);
  const { baseUrl, token } = configuration();
  const response = await fetch(`${baseUrl}/v1/tender-discovery/eis-position-association/${operation}`, {
    method: "POST", cache: "no-store", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body, signal: AbortSignal.timeout(20_000),
  });
  if (!response.ok) { await response.body?.cancel(); throw new ApiError(response.status); }
  if (!response.body || response.headers.get("Cache-Control") !== "no-store" ||
    response.headers.get("content-type")?.split(";", 1)[0] !== "application/json") {
    await response.body?.cancel(); throw new ApiError(422);
  }
  const reader = response.body.getReader(), chunks: Uint8Array[] = []; let size = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read(); if (done) break;
      size += value.byteLength;
      if (size > 256 * 1024) { await reader.cancel(); throw new ApiError(422); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  let result: unknown;
  try { result = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); }
  catch { throw new ApiError(422); }
  return result;
}
export async function requestIndexedPositionAssociation(payload: AssociationRequest, save: boolean): Promise<SavedAssociation> {
  if (!validAssociationRequest(payload)) throw new ApiError(422);
  const result = await positionAssociationResponse(payload, save ? "save" : "read");
  if (!associationMatches(result, payload, save)) throw new ApiError(422);
  return result;
}
export async function listIndexedPositionAssociations(payload: AssociationListRequest): Promise<AssociationListResult> {
  if (!validAssociationListRequest(payload)) throw new ApiError(422);
  const result = await positionAssociationResponse(payload, "list");
  if (!associationListMatches(result, payload)) throw new ApiError(422);
  return result;
}
export async function readIndexedPositionAssociationDetail(payload: AssociationDetailRequest): Promise<SavedAssociation> {
  if (!validAssociationDetailRequest(payload)) throw new ApiError(422);
  const result = await positionAssociationResponse(payload, "detail");
  if (!associationDetailMatches(result, payload)) throw new ApiError(422);
  return result;
}

async function requestSupplierSerp(payload: SupplierSearchRequest, prepare: boolean, refresh = false): Promise<SavedSupplierSerp> {
  if (!validSupplierSearchRequest(payload) || typeof refresh !== "boolean") throw new ApiError(422);
  const { baseUrl, token } = configuration();
  const response = await fetch(`${baseUrl}/v1/tender-discovery/eis-supplier-serp/${prepare ? "prepare" : "read"}`, {
    method: "POST", cache: "no-store", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(prepare ? { request: payload, refresh } : { request: payload }), signal: AbortSignal.timeout(95_000),
  });
  if (!response.ok) { await response.body?.cancel(); throw new ApiError(response.status); }
  if (!response.body || response.headers.get("Cache-Control") !== "no-store" ||
    response.headers.get("content-type")?.split(";", 1)[0] !== "application/json") {
    await response.body?.cancel(); throw new ApiError(422);
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = []; let size = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read(); if (done) break;
      size += value.byteLength;
      if (size > 256 * 1024) { await reader.cancel(); throw new ApiError(422); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  let result: unknown;
  try { result = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); }
  catch { throw new ApiError(422); }
  if (!supplierSerpMatches(result, payload, prepare)) throw new ApiError(422);
  return result;
}

export function prepareIndexedSupplierSerp(payload: SupplierSearchRequest, refresh = false): Promise<SavedSupplierSerp> {
  return requestSupplierSerp(payload, true, refresh);
}
export function readIndexedSupplierSerp(payload: SupplierSearchRequest): Promise<SavedSupplierSerp> {
  return requestSupplierSerp(payload, false);
}


async function requestSupplierPage(payload: SupplierPageRequest, prepare: boolean, refresh = false): Promise<SavedSupplierPage> {
  if (!validSupplierPageRequest(payload) || typeof refresh !== "boolean") throw new ApiError(422);
  const { baseUrl, token } = configuration();
  const response = await fetch(`${baseUrl}/v1/tender-discovery/eis-supplier-page/${prepare ? "prepare" : "read"}`, {
    method: "POST", cache: "no-store", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(prepare ? { request: payload, refresh } : { request: payload }), signal: AbortSignal.timeout(50_000),
  });
  if (!response.ok) { await response.body?.cancel(); throw new ApiError(response.status); }
  if (!response.body || response.headers.get("Cache-Control") !== "no-store" ||
    response.headers.get("content-type")?.split(";", 1)[0] !== "application/json") {
    await response.body?.cancel(); throw new ApiError(422);
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = []; let size = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read(); if (done) break;
      size += value.byteLength;
      if (size > 256 * 1024) { await reader.cancel(); throw new ApiError(422); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  let result: unknown;
  try { result = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); }
  catch { throw new ApiError(422); }
  if (!supplierPageMatches(result, payload, prepare)) throw new ApiError(422);
  return result;
}

export function prepareIndexedSupplierPage(payload: SupplierPageRequest, refresh = false): Promise<SavedSupplierPage> {
  return requestSupplierPage(payload, true, refresh);
}
export function readIndexedSupplierPage(payload: SupplierPageRequest): Promise<SavedSupplierPage> {
  return requestSupplierPage(payload, false);
}


async function requestSupplierCatalog(payload: SupplierCatalogRequest, prepare: boolean, refresh = false): Promise<SavedSupplierCatalog> {
  if (!validSupplierCatalogRequest(payload) || typeof refresh !== "boolean") throw new ApiError(422);
  const { baseUrl, token } = configuration();
  const response = await fetch(`${baseUrl}/v1/tender-discovery/eis-supplier-catalog/${prepare ? "prepare" : "read"}`, {
    method: "POST", cache: "no-store", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(prepare ? { request: payload, refresh } : { request: payload }), signal: AbortSignal.timeout(50_000),
  });
  if (!response.ok) { await response.body?.cancel(); throw new ApiError(response.status); }
  if (!response.body || response.headers.get("Cache-Control") !== "no-store" ||
    response.headers.get("content-type")?.split(";", 1)[0] !== "application/json") {
    await response.body?.cancel(); throw new ApiError(422);
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = []; let size = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read(); if (done) break;
      size += value.byteLength;
      if (size > 256 * 1024) { await reader.cancel(); throw new ApiError(422); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  let result: unknown;
  try { result = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); }
  catch { throw new ApiError(422); }
  if (!supplierCatalogMatches(result, payload, prepare)) throw new ApiError(422);
  return result;
}

export function prepareIndexedSupplierCatalog(payload: SupplierCatalogRequest, refresh = false): Promise<SavedSupplierCatalog> {
  return requestSupplierCatalog(payload, true, refresh);
}
export function readIndexedSupplierCatalog(payload: SupplierCatalogRequest): Promise<SavedSupplierCatalog> {
  return requestSupplierCatalog(payload, false);
}


async function requestSupplierProduct(payload: SupplierProductRequest, prepare: boolean): Promise<SavedSupplierProduct> {
  if (!validSupplierProductRequest(payload)) throw new ApiError(422);
  const { baseUrl, token } = configuration();
  const response = await fetch(`${baseUrl}/v1/tender-discovery/eis-supplier-product/${prepare ? "prepare" : "read"}`, {
    method: "POST", cache: "no-store", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ request: payload }), signal: AbortSignal.timeout(30_000),
  });
  if (!response.ok) { await response.body?.cancel(); throw new ApiError(response.status); }
  if (!response.body || response.headers.get("Cache-Control") !== "no-store" ||
    response.headers.get("content-type")?.split(";", 1)[0] !== "application/json") {
    await response.body?.cancel(); throw new ApiError(422);
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = []; let size = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read(); if (done) break;
      size += value.byteLength;
      if (size > 256 * 1024) { await reader.cancel(); throw new ApiError(422); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  let result: unknown;
  try { result = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); }
  catch { throw new ApiError(422); }
  if (!supplierProductMatches(result, payload, prepare)) throw new ApiError(422);
  return result;
}

export function prepareIndexedSupplierProduct(payload: SupplierProductRequest): Promise<SavedSupplierProduct> {
  return requestSupplierProduct(payload, true);
}
export function readIndexedSupplierProduct(payload: SupplierProductRequest): Promise<SavedSupplierProduct> {
  return requestSupplierProduct(payload, false);
}

export async function readIndexedRequirementPreview(payload: RequirementPreviewRequest): Promise<RequirementPreview> {
  if (!validRequirementPreviewRequest(payload)) throw new ApiError(422);
  const { baseUrl, token } = configuration();
  const response = await fetch(`${baseUrl}/v1/tender-discovery/eis-requirement-preview/preview`, {
    method: "POST", cache: "no-store", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ request: payload }), signal: AbortSignal.timeout(30_000),
  });
  if (!response.ok) { await response.body?.cancel(); throw new ApiError(response.status); }
  if (!response.body || response.headers.get("Cache-Control") !== "no-store" || response.headers.get("content-type")?.split(";", 1)[0] !== "application/json") { await response.body?.cancel(); throw new ApiError(422); }
  const reader = response.body.getReader(), chunks: Uint8Array[] = []; let size = 0;
  try { while (true) { const { value, done } = await reader.read(); if (done) break; size += value.byteLength; if (size > 256 * 1024) { await reader.cancel(); throw new ApiError(422); } chunks.push(value); } }
  finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0; for (const c of chunks) { bytes.set(c, offset); offset += c.byteLength; }
  let result: unknown; try { result = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); } catch { throw new ApiError(422); }
  if (!requirementPreviewMatches(result, payload)) throw new ApiError(422);
  return result;
}

async function requestRequirementReview(path: string, payload: unknown): Promise<unknown> {
  const body = JSON.stringify(payload);
  if (new TextEncoder().encode(body).length > 4096) throw new ApiError(413);
  const { baseUrl, token } = configuration();
  const response = await fetch(`${baseUrl}/v1/tender-discovery/eis/index/requirement-review/${path}`, {
    method: "POST", cache: "no-store", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body, signal: AbortSignal.timeout(30_000),
  });
  if (!response.ok) { await response.body?.cancel(); throw new ApiError(response.status); }
  if (!response.body || response.headers.get("Cache-Control") !== "no-store" || response.headers.get("content-type")?.split(";",1)[0] !== "application/json") { await response.body?.cancel(); throw new ApiError(422); }
  const reader = response.body.getReader(), chunks: Uint8Array[] = []; let size = 0;
  try { for (;;) { const {done,value} = await reader.read(); if (done) break; size += value.byteLength; if (size > 384 * 1024) { await reader.cancel(); throw new ApiError(422); } chunks.push(value); } }
  finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0; for (const c of chunks) { bytes.set(c,offset); offset += c.byteLength; }
  try { return JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(bytes)); } catch { throw new ApiError(422); }
}
export async function createIndexedRequirementProposal(payload: ProposalRequest): Promise<SavedRequirementProposal> {
  if (!validProposalRequest(payload)) throw new ApiError(422);
  const result = await requestRequirementReview("proposals",payload);
  if (!savedProposalMatches(result,payload)) throw new ApiError(422); return result;
}
export async function readIndexedRequirementProposal(proposal_id: string): Promise<SavedRequirementProposal> {
  if (!validReviewId(proposal_id)) throw new ApiError(422);
  const result = await requestRequirementReview("proposals/read",{proposal_id});
  if (!savedProposalMatches(result) || result.created || result.proposal.proposal_id !== proposal_id) throw new ApiError(422); return result;
}
export async function createIndexedRequirementDecision(payload: DecisionRequest, proposal: RequirementProposal): Promise<SavedRequirementDecision> {
  if (!validDecisionRequest(payload) || payload.proposal_id !== proposal.proposal_id || payload.expected_proposal_sha256 !== proposal.proposal_sha256) throw new ApiError(422);
  const result = await requestRequirementReview("decisions",payload);
  if (!savedDecisionMatches(result,proposal)) throw new ApiError(422); return result;
}

import {
  manufacturerDossierMatches,
  manufacturerSearchSummariesMatch,
  savedManufacturerSearchMatches,
  validManufacturerSearchRequest,
  type ManufacturerDossier,
  type ManufacturerSearchReport,
  type ManufacturerSearchRequest,
  type ManufacturerSearchSummary,
  type SavedManufacturerSearch,
} from "./manufacturer-search";

export async function createManufacturerSearch(payload: ManufacturerSearchRequest): Promise<SavedManufacturerSearch> {
  if (!validManufacturerSearchRequest(payload)) throw new ApiError(422);
  const result = await request<unknown>("/v1/manufacturer-search", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), signal: AbortSignal.timeout(60_000),
  });
  if (!savedManufacturerSearchMatches(result, payload, true)) throw new ApiError(422);
  return result;
}

export async function listManufacturerSearches(): Promise<ManufacturerSearchSummary[]> {
  const result = await request<unknown>("/v1/manufacturer-search?limit=20", { signal: AbortSignal.timeout(60_000) });
  if (!manufacturerSearchSummariesMatch(result)) throw new ApiError(422);
  return result;
}

export async function readManufacturerSearch(runId: string): Promise<ManufacturerSearchReport> {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(runId)) throw new ApiError(422);
  const result = await request<unknown>(`/v1/manufacturer-search/${encodeURIComponent(runId)}`, { signal: AbortSignal.timeout(60_000) });
  if (!savedManufacturerSearchMatches(result) || result.report.run_id !== runId) throw new ApiError(422);
  return result.report;
}

export async function readManufacturerDossier(runId: string, recordId: string): Promise<ManufacturerDossier> {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(runId) || !/^[0-9a-f]{24}$/.test(recordId)) throw new ApiError(422);
  const result = await request<unknown>(`/v1/manufacturer-search/${encodeURIComponent(runId)}/candidates/${encodeURIComponent(recordId)}`, { signal: AbortSignal.timeout(60_000) });
  if (!manufacturerDossierMatches(result, runId, recordId)) throw new ApiError(422);
  return result;
}
export async function readIndexedRequirementComparison(proposal: RequirementProposal): Promise<RequirementComparison> {
  if (!validReviewId(proposal.proposal_id)) throw new ApiError(422);
  const result = await requestRequirementReview("comparison",{proposal_id:proposal.proposal_id});
  if (!comparisonMatches(result,proposal)) throw new ApiError(422); return result;
}

import { artifactMatches, proposalSummariesMatch, savedDecisionMatches as savedManufacturerDecisionMatches, savedProposalMatches as savedManufacturerProposalMatches, validArtifactCommand, validDecisionCommand, validProposalCommand, UUID_PATTERN, type ArtifactCommand, type DecisionCommand, type ManufacturerArtifact, type ManufacturerProposal, type ManufacturerProposalSummary, type ProposalCommand, type SavedManufacturerDecision, type SavedManufacturerProposal } from "./manufacturer-review";

function manufacturerReviewerConfiguration(): { baseUrl: string; token: string } {
  const { PROCUREMENT_API_URL: url, PROCUREMENT_MANUFACTURER_REVIEWER_TOKEN: token } = process.env;
  if (!url || !token) throw new ConfigurationError("Manufacturer reviewer API is not configured");
  return { baseUrl: url.replace(/\/$/, ""), token };
}
async function manufacturerReviewerRequest(path: string, init: RequestInit = {}): Promise<unknown> {
  const { baseUrl, token } = manufacturerReviewerConfiguration();
  const headers = new Headers(init.headers); headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${baseUrl}${path}`, { ...init, cache: "no-store", headers, signal: init.signal ?? AbortSignal.timeout(60_000) });
  if (!response.ok) throw new ApiError(response.status); return response.json() as Promise<unknown>;
}
export async function uploadManufacturerArtifact(payload: ArtifactCommand): Promise<ManufacturerArtifact> { if (!validArtifactCommand(payload)) throw new ApiError(422); const value = await request<unknown>("/v1/manufacturer-review/artifacts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), signal: AbortSignal.timeout(60_000) }); if (!artifactMatches(value) || value.command_id !== payload.command_id || value.source_title !== payload.source_title || value.source_url !== payload.source_url || value.original_filename !== payload.original_filename) throw new ApiError(422); return value; }
export async function createManufacturerProposal(payload: ProposalCommand): Promise<SavedManufacturerProposal> { if (!validProposalCommand(payload)) throw new ApiError(422); const value = await request<unknown>("/v1/manufacturer-review/proposals", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), signal: AbortSignal.timeout(60_000) }); if (!savedManufacturerProposalMatches(value, payload)) throw new ApiError(422); return value; }
export async function listManufacturerProposals(): Promise<ManufacturerProposalSummary[]> { const value = await request<unknown>("/v1/manufacturer-review/proposals?limit=20"); if (!proposalSummariesMatch(value)) throw new ApiError(422); return value; }
export async function readManufacturerProposal(id: string): Promise<ManufacturerProposal> { if (!UUID_PATTERN.test(id)) throw new ApiError(422); const value = await request<unknown>(`/v1/manufacturer-review/proposals/${encodeURIComponent(id)}`); if (!savedManufacturerProposalMatches(value) || value.proposal.proposal_id !== id) throw new ApiError(422); return value.proposal; }
export async function decideManufacturerProposal(id: string, payload: DecisionCommand, proposal: ManufacturerProposal): Promise<SavedManufacturerDecision> { if (id !== proposal.proposal_id || !validDecisionCommand(payload, proposal)) throw new ApiError(422); const artifactIds = [...new Set(proposal.citations.map(citation => citation.artifact_id))]; const artifacts = await Promise.all(artifactIds.map(artifactId => readManufacturerArtifactMetadata(id, artifactId, proposal.citations.find(citation => citation.artifact_id === artifactId)?.artifact_sha256))); const value = await manufacturerReviewerRequest(`/v1/manufacturer-review/proposals/${encodeURIComponent(id)}/decision`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }); if (!savedManufacturerDecisionMatches(value, proposal, payload, artifacts)) throw new ApiError(422); return value; }
export async function readManufacturerDecision(id: string, proposal: ManufacturerProposal): Promise<SavedManufacturerDecision> { if (id !== proposal.proposal_id || !UUID_PATTERN.test(id)) throw new ApiError(422); const value = await request<unknown>(`/v1/manufacturer-review/proposals/${encodeURIComponent(id)}/decision`); if (!savedManufacturerDecisionMatches(value, proposal)) throw new ApiError(422); return value; }
export async function readManufacturerArtifactMetadata(proposalId: string, artifactId: string, expectedSha256?: string): Promise<ManufacturerArtifact> { if (!UUID_PATTERN.test(proposalId) || !UUID_PATTERN.test(artifactId)) throw new ApiError(422); const value = await manufacturerReviewerRequest(`/v1/manufacturer-review/proposals/${encodeURIComponent(proposalId)}/artifacts/${encodeURIComponent(artifactId)}/metadata`); if (!artifactMatches(value) || value.artifact_id !== artifactId || (expectedSha256 !== undefined && value.sha256 !== expectedSha256)) throw new ApiError(422); return value; }
export async function downloadManufacturerArtifact(proposalId: string, artifactId: string): Promise<{ bytes: Uint8Array; sha256: string }> { if (!UUID_PATTERN.test(proposalId) || !UUID_PATTERN.test(artifactId)) throw new ApiError(422); const { baseUrl, token } = manufacturerReviewerConfiguration(); const response = await fetch(`${baseUrl}/v1/manufacturer-review/proposals/${encodeURIComponent(proposalId)}/artifacts/${encodeURIComponent(artifactId)}`, { cache: "no-store", headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(60_000) }); if (!response.ok) throw new ApiError(response.status); const sha256 = response.headers.get("x-content-sha256"); const contentType = response.headers.get("content-type")?.split(";")[0]; const bytes = new Uint8Array(await response.arrayBuffer()); if (!sha256 || !/^[0-9a-f]{64}$/.test(sha256) || contentType !== "application/pdf" || bytes.length < 1 || bytes.length > 2 * 1024 * 1024) throw new ApiError(422); return { bytes, sha256 }; }



export function readIndexedPublicUnitPrice(requestValue: import("./eis-supplier-product").SupplierProductRequest): Promise<import("./public-unit-price").PublicUnitPriceReport> {
  return request("/v1/tender-discovery/eis-public-unit-price/read", {
    method: "POST", body: JSON.stringify({ request: requestValue }),
  });
}

export async function readTenderNavigation(ref: MixedNoticeRef): Promise<import("./tender-workspace").TenderNavigation> {
  return request("/v1/tender-discovery/eis-navigation/read", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ request: ref }), signal: AbortSignal.timeout(30_000),
  });
}


export type GlobalPriceResult = {
  query: string; law: "all" | "44" | "223"; delivery_region: string; include_unknown_region: boolean;
  result44: EisIndexedSearchResult | null; result223: Eis223SearchResult | null;
  navigation: Record<string, import("./tender-workspace").TenderNavigation>;
  matched_count: number; unknown_region_count: number; next_cursor: string | null;
  page_snapshot_sha256: string; snapshot_at: string;
};
export function searchGlobalPrice(query: string, law: "all" | "44" | "223", region: string, includeUnknown: boolean, cursor?: string): Promise<GlobalPriceResult> {
  const params = new URLSearchParams({ query, law, delivery_region: region, include_unknown_region: String(includeUnknown), page_size: "100" });
  if (cursor) params.set("cursor", cursor);
  return request<GlobalPriceResult>(`/v1/tender-discovery/global-price?${params}`, { signal: AbortSignal.timeout(60_000) });
}

export type GosplanLaw = "44" | "223";
export type GosplanSearchItem = {
  law: GosplanLaw; number: string; title: string; purchase_type: string;
  price: string | null; currency: string | null; deadline_raw: string | null;
  deadline_status: "UNKNOWN"; submission_status: "UNKNOWN"; source_sha256: string;
};
export type GosplanSearchPage = {
  law: GosplanLaw; query: string; observed_at: string; response_sha256: string;
  items: GosplanSearchItem[]; may_have_more: boolean; coverage: "UNKNOWN";
};
export type GosplanDetail = {
  law: GosplanLaw; number: string; observed_at: string; response_sha256: string;
  eis_url: string | null; eis_url_origin: "PROVIDER" | "NUMBER_DERIVED" | null; platform_url: string | null;
  documents: { name: string; url: string; source_sha256: string }[];
  documents_truncated: boolean; submission_status: "UNKNOWN";
};
export async function searchGosplan(query: string, law: GosplanLaw, offset = 0): Promise<GosplanSearchPage> {
  const params = new URLSearchParams({ query, law, offset: String(offset) });
  return request<GosplanSearchPage>(`/v1/tender-discovery/gosplan/search?${params}`, { signal: AbortSignal.timeout(30_000) });
}
export async function readGosplanDetail(law: GosplanLaw, number: string): Promise<GosplanDetail> {
  return request<GosplanDetail>(`/v1/tender-discovery/gosplan/detail/${law}/${encodeURIComponent(number)}`, { signal: AbortSignal.timeout(30_000) });
}
