import type { MixedComparisonResult, MixedNoticeRef, Provenance } from "./procurement-api";
import type { ProfileRef } from "./procurement-comparison";

export type NoticeProfileCheck = {
  check_id: string; label: string; mandatory: boolean; status: "PASS" | "FAIL" | "UNKNOWN";
  reason_code: string; reason: string; missing: string[];
  profile_sources: Array<{ provenance: Provenance; recorded_at: string; recorded_by: string }>;
  case_sources: Provenance[];
};
export type NoticeProfileReport = {
  schema_version: "selected-profile-notice-comparison-v1";
  company_id: string; selection_id: string; profile_ref: ProfileRef;
  profile_name: string; compared_at: string; input_sha256: string;
  comparison_kind: "PRELIMINARY"; persistence: "EPHEMERAL";
  source: MixedComparisonResult;
  rows: Array<{ notice_ref: MixedNoticeRef; subject: string; overall_status: "FAIL" | "UNKNOWN"; checks: NoticeProfileCheck[] }>;
};
export type NoticeProfileContext = {
  company_id: string; actor_id: string; selection_id: string; profile_ref: ProfileRef; profile_name: string;
};
export function sameNotice(a: MixedNoticeRef, b: MixedNoticeRef): boolean {
  return a.law === b.law && a.purchase_number === b.purchase_number && a.version_number === b.version_number && a.notice_xml_sha256 === b.notice_xml_sha256;
}
export function noticeReportMatches(report: NoticeProfileReport, context: NoticeProfileContext, notices: MixedNoticeRef[]): boolean {
  return report.schema_version === "selected-profile-notice-comparison-v1" && report.company_id === context.company_id &&
    report.selection_id === context.selection_id && report.profile_ref.version === context.profile_ref.version &&
    report.profile_ref.snapshot_sha256 === context.profile_ref.snapshot_sha256 && report.persistence === "EPHEMERAL" &&
    notices.length >= 2 && notices.length <= 5 && report.rows.length === notices.length &&
    /^[a-f0-9]{64}$/.test(report.input_sha256) && report.source.rows.length === notices.length &&
    report.source.rows.every((row, i) => sameNotice(row.law === "44" ? { law: row.law, ...row.evidence.notice } : {
      law: row.law, purchase_number: row.notice.purchase_number, version_number: row.notice.version_number, notice_xml_sha256: row.notice.xml_sha256,
    }, notices[i])) &&
    report.rows.every((row, i) => sameNotice(row.notice_ref, notices[i]) &&
      row.overall_status === (row.checks.some(check => check.mandatory && check.status === "FAIL") ? "FAIL" : "UNKNOWN") &&
      row.checks.length > 0 && row.checks.every(check => ["PASS", "FAIL", "UNKNOWN"].includes(check.status) &&
        (check.status !== "UNKNOWN" || check.missing.length > 0)));
}
