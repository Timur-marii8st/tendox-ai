import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { noticeReportMatches, type NoticeProfileContext, type NoticeProfileReport } from "../src/lib/notice-profile-comparison";
import { NoticeProfileReportView } from "../src/app/tender-discovery/profile-comparison-report";
import type { Eis223DocumentType, MixedComparisonResult } from "../src/lib/procurement-api";

const context: NoticeProfileContext = { company_id: "synthetic", actor_id: "operator", selection_id: "selection", profile_name: "Компания", profile_ref: { version: 1, snapshot_sha256: "a".repeat(64) } };
function fixture(count = 2): NoticeProfileReport {
  const rows = Array.from({ length: count }, (_, i) => ({ notice_ref: { law: "44" as const, purchase_number: `000000000000000000${i}`, version_number: 1, notice_xml_sha256: "b".repeat(64) }, subject: "<script>external</script>", overall_status: "UNKNOWN" as const, checks: [{ check_id: "activity", label: "Деятельность", mandatory: true, status: "UNKNOWN" as const, reason_code: "REVIEW_REQUIRED", reason: "Нужно проверить", missing: ["сопоставление"], profile_sources: [], case_sources: [] }] }));
  const source = { rows: rows.map(row => ({ law: "44", evidence: { notice: row.notice_ref, nmck_rub: "123.45", deadline: null, document_type: "epNotificationEF2020" } })) };
  return { schema_version: "selected-profile-notice-comparison-v1", ...context, compared_at: "2026-10-15T10:00:00Z", input_sha256: "c".repeat(64), comparison_kind: "PRELIMINARY", persistence: "EPHEMERAL", rows, source } as unknown as NoticeProfileReport;
}
test("notice report binds tenant, selected profile and exact ordered 2–5 XML refs", () => {
  for (const n of [2, 5]) { const report = fixture(n); assert.ok(noticeReportMatches(report, context, report.rows.map(row => row.notice_ref))); }
  const report = fixture(); const refs = report.rows.map(row => row.notice_ref);
  assert.equal(noticeReportMatches(report, { ...context, company_id: "foreign" }, refs), false);
  assert.equal(noticeReportMatches(report, { ...context, profile_ref: { ...context.profile_ref, version: 2 } }, refs), false);
  assert.equal(noticeReportMatches(report, context, [...refs].reverse()), false);
  assert.equal(noticeReportMatches(fixture(6), context, fixture(6).rows.map(row => row.notice_ref)), false);
});
test("notice report refuses hidden mandatory FAIL or source reference mismatch", () => {
  const report = fixture(); const refs = report.rows.map(row => row.notice_ref);
  report.rows[0].checks[0].status = "FAIL"; report.rows[0].checks[0].missing = [];
  assert.equal(noticeReportMatches(report, context, refs), false);
  report.rows[0].overall_status = "FAIL"; assert.ok(noticeReportMatches(report, context, refs));
  const mismatched = structuredClone(report); mismatched.source.rows.reverse();
  assert.equal(noticeReportMatches(mismatched, context, refs), false);
});
test("notice table preserves source price, unknown deadline, escaped text and incomplete economics", () => {
  const report = fixture(); const html = renderToStaticMarkup(createElement(NoticeProfileReportView, { report }));
  for (const text of ["123.45", "Срок UNKNOWN", "Прибыль не рассчитана", "не сохраняется", "версия 1", "сопоставление"]) assert.ok(html.includes(text), text);
  assert.equal(html.includes("<script>"), false); assert.ok(html.includes("&lt;script&gt;"));
});

test("regular KESMBO renders its method without inventing a timezone or participation approval", () => {
  const report = fixture();
  const documentType: Eis223DocumentType = "purchaseNoticeKESMBO";
  report.source.rows[0] = {
    law: "223",
    notice: {
      document_type: documentType, method_name: { value: null },
      deadline: { value: null, raw: "2026-10-16T10:00:00" }, lots: [],
    },
  } as unknown as MixedComparisonResult["rows"][number];
  const html = renderToStaticMarkup(createElement(NoticeProfileReportView, { report }));
  for (const text of ["Электронный конкурс для МСП", "2026-10-16T10:00:00", "часовой пояс / применимость UNKNOWN", "Прибыль не рассчитана"])
    assert.ok(html.includes(text), text);
  assert.equal(html.includes("PARTICIPATE"), false);
});

test("regular ZPESMBO renders its method without inventing a timezone or participation approval", () => {
  const report = fixture();
  const documentType: Eis223DocumentType = "purchaseNoticeZPESMBO";
  report.source.rows[0] = {
    law: "223",
    notice: {
      document_type: documentType, method_name: { value: null },
      deadline: { value: null, raw: "2026-10-16T10:00:00" }, lots: [],
    },
  } as unknown as MixedComparisonResult["rows"][number];
  const html = renderToStaticMarkup(createElement(NoticeProfileReportView, { report }));
  for (const text of ["Электронный запрос предложений для МСП", "2026-10-16T10:00:00", "часовой пояс / применимость UNKNOWN", "Прибыль не рассчитана"])
    assert.ok(html.includes(text), text);
  assert.equal(html.includes("PARTICIPATE"), false);
});
