// Public wire types only. Authentication remains in the server-only API adapter.
export type ProtocolNoticeRef = {
  purchase_number: string; version_number: number; notice_xml_sha256: string;
};
export type ProtocolEvidence = {
  xml_sha256: string; source_member: string; document_type: string;
  locator: string; namespace: string;
};
export type ProtocolFact<T> = {
  value: T | null; status: "PASS" | "UNKNOWN"; reason: string | null;
  evidence: ProtocolEvidence;
};
export type ProtocolApplication = {
  row_number: number; application_id: ProtocolFact<string>;
  admission: ProtocolFact<boolean>; rank: ProtocolFact<number>;
  result_code: ProtocolFact<string>; supplier_identity: "UNKNOWN";
  proposal: {
    amount: ProtocolFact<string>; source_kind: "FINAL_PROPOSAL" | "PROPOSAL" | "UNKNOWN";
    right_to_conclude_contract: ProtocolFact<boolean>;
    currency: "UNKNOWN"; tax_basis: "UNKNOWN";
  };
};
export type ProtocolDocument = {
  parser_version: "eis-protocol-facts-v1"; source: ProtocolEvidence;
  purchase_number: string;
  document_kind: "FINAL_PROTOCOL" | "PLACEMENT_RESULT" | "PROPOSALS_DISTRIBUTION";
  published_at: string | null;
  protocol_number: ProtocolFact<string>; foundation_protocol_number: ProtocolFact<string>;
  lot_number: ProtocolFact<string>; observed_rows: ProtocolFact<number>;
  represented_applications: ProtocolFact<number>; applications: ProtocolApplication[];
  count_scope: "APPLICATIONS_REPRESENTED_IN_THIS_DOCUMENT";
  notice_version_link: "UNKNOWN"; current_stage: "UNKNOWN";
  signed_contract: "UNKNOWN"; competition_prediction: "UNKNOWN";
};
export type HistoricalProtocolReport = {
  company_id: string; notice: ProtocolNoticeRef; checked_at: string;
  linkage_scope: "PURCHASE_NUMBER_ONLY"; notice_version_link: "UNKNOWN";
  application_status: "FAIL" | "UNKNOWN"; reasons: string[];
  metadata_documents: number; uninterpreted_document_types: string[];
  documents: ProtocolDocument[]; source_requests: 0;
  coverage: "UNKNOWN"; source_freshness: "UNKNOWN";
  profit: "UNKNOWN"; participation: "UNKNOWN";
};

export function validProtocolRef(value: unknown): value is ProtocolNoticeRef {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const ref = value as Record<string, unknown>;
  return Object.keys(ref).length === 3 &&
    typeof ref.purchase_number === "string" && /^[0-9]{19,23}$/.test(ref.purchase_number) &&
    typeof ref.version_number === "number" && Number.isSafeInteger(ref.version_number) && ref.version_number >= 1 &&
    typeof ref.notice_xml_sha256 === "string" && /^[0-9a-f]{64}$/.test(ref.notice_xml_sha256);
}

export function sameProtocolRef(left: ProtocolNoticeRef, right: ProtocolNoticeRef): boolean {
  return left.purchase_number === right.purchase_number && left.version_number === right.version_number &&
    left.notice_xml_sha256 === right.notice_xml_sha256;
}

// The API validates the document schema. The BFF additionally binds its response
// to the selected card, so a different version cannot be shown under that card.
export function protocolReportMatches(report: HistoricalProtocolReport, ref: ProtocolNoticeRef): boolean {
  return !!report && validProtocolRef(report.notice) && sameProtocolRef(report.notice, ref) &&
    report.linkage_scope === "PURCHASE_NUMBER_ONLY" && report.notice_version_link === "UNKNOWN" &&
    report.source_requests === 0 && Array.isArray(report.documents) && report.documents.length <= 12 &&
    report.documents.every(doc => doc.purchase_number === ref.purchase_number &&
      doc.parser_version === "eis-protocol-facts-v1" &&
      doc.count_scope === "APPLICATIONS_REPRESENTED_IN_THIS_DOCUMENT");
}

export type ProtocolReadState = { result?: HistoricalProtocolReport; error?: string };

export async function loadProtocolForCard(ref: ProtocolNoticeRef,
  read: (ref: ProtocolNoticeRef) => Promise<ProtocolReadState>): Promise<ProtocolReadState> {
  try {
    const response = await read(ref);
    if (response.result) return protocolReportMatches(response.result, ref) ? response :
      { error: "Ответ не соответствует выбранной версии карточки. Повторите поиск." };
    return { error: response.error ?? "Сохранённые протоколы сейчас недоступны. Повторите запрос." };
  } catch {
    // Includes browser-to-Next transport failures, which the BFF cannot catch.
    return { error: "Не удалось прочитать протоколы. Проверьте соединение и повторите запрос." };
  }
}
