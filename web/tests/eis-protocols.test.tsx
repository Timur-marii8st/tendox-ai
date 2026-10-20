import assert from "node:assert/strict";
import test from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { HistoricalProtocolReportView } from "../src/app/tender-discovery/historical-protocol-report";
import { loadProtocolForCard, protocolReportMatches, sameProtocolRef, validProtocolRef,
  type HistoricalProtocolReport, type ProtocolFact, type ProtocolNoticeRef } from "../src/lib/eis-protocols";

const ref: ProtocolNoticeRef = { purchase_number: "0".repeat(19), version_number: 1, notice_xml_sha256: "a".repeat(64) };
const evidence = { xml_sha256: "b".repeat(64), source_member: "protocol.xml",
  document_type: "fcsProposalsResult", locator: "applications/application[1]/price", namespace: "urn:test" };
function known<T>(value: T): ProtocolFact<T> { return { value, status: "PASS", reason: null, evidence }; }
function missing<T>(reason = "NOT_RECORDED"): ProtocolFact<T> {
  return { value: null, status: "UNKNOWN", reason, evidence };
}
function report(): HistoricalProtocolReport {
  return {
    company_id: "test-tenant", notice: ref, checked_at: "2026-10-05T12:00:00Z",
    linkage_scope: "PURCHASE_NUMBER_ONLY", notice_version_link: "UNKNOWN",
    application_status: "FAIL", reasons: ["DEADLINE_EXPIRED"], metadata_documents: 1,
    uninterpreted_document_types: [], source_requests: 0, coverage: "UNKNOWN",
    source_freshness: "UNKNOWN", profit: "UNKNOWN", participation: "UNKNOWN",
    documents: [{ parser_version: "eis-protocol-facts-v1", source: evidence, purchase_number: ref.purchase_number,
      document_kind: "PROPOSALS_DISTRIBUTION", published_at: null,
      protocol_number: missing(), foundation_protocol_number: missing(), lot_number: missing(),
      observed_rows: known(2), represented_applications: missing("APPLICATION_IDS_MISSING_OR_REPEATED"),
      count_scope: "APPLICATIONS_REPRESENTED_IN_THIS_DOCUMENT", notice_version_link: "UNKNOWN",
      current_stage: "UNKNOWN", signed_contract: "UNKNOWN", competition_prediction: "UNKNOWN",
      applications: [1, 2].map(row_number => ({ row_number, application_id: known("repeated-id"),
        admission: missing(), rank: known(1), result_code: known("CC"), supplier_identity: "UNKNOWN",
        proposal: { amount: known("12345678901234567890.12345678901"), source_kind: "PROPOSAL",
          right_to_conclude_contract: missing(), currency: "UNKNOWN", tax_basis: "UNKNOWN" } })) }],
  };
}
function html(value = report()) { return renderToStaticMarkup(<HistoricalProtocolReportView report={value} />); }

test("only exact valid 44-FZ refs accepted, including no caller tenant", () => {
  assert.equal(validProtocolRef(ref), true);
  for (const invalid of [null, [], {}, { ...ref, company_id: "another-tenant" },
    { ...ref, purchase_number: "1".repeat(11) }, { ...ref, version_number: 1.5 },
    { ...ref, version_number: Number.MAX_SAFE_INTEGER + 1 }, { ...ref, notice_xml_sha256: "A".repeat(64) }]) {
    assert.equal(validProtocolRef(invalid), false);
  }
});
test("different notice, version, SHA or document purchase is rejected", () => {
  assert.equal(protocolReportMatches(report(), ref), true);
  for (const changed of [{ ...ref, purchase_number: "1".repeat(19) }, { ...ref, version_number: 2 },
    { ...ref, notice_xml_sha256: "c".repeat(64) }]) {
    assert.equal(sameProtocolRef(ref, changed), false);
    assert.equal(protocolReportMatches(report(), changed), false);
  }
  const value = report(); value.documents[0].purchase_number = "1".repeat(19);
  assert.equal(protocolReportMatches(value, ref), false);
});
test("duplicate rows retain UNKNOWN counts and explicit per-document scope", () => {
  const rendered = html();
  assert.match(rendered, /Идентификаторы заявок отсутствуют или повторяются/);
  assert.match(rendered, /не являются общим числом конкурентов/);
  assert.match(rendered, /Личности поставщиков: UNKNOWN/);
  assert.match(rendered, /Строки не складываются с другими протоколами/);
  assert.equal((rendered.match(/repeated-id/g) ?? []).length, 2);
});
test("Decimal wire strings retain all digits without invented currency or tax", () => {
  const rendered = html();
  assert.equal((rendered.match(/12345678901234567890\.12345678901/g) ?? []).length, 2);
  assert.match(rendered, /Валюта: UNKNOWN; налоги: UNKNOWN/);
  assert.doesNotMatch(rendered, /₽|RUB|руб\./);
  const value = report(); value.documents[0].applications[0].proposal.amount = known("-0.00000000001");
  value.documents[0].applications[0].proposal.right_to_conclude_contract = known(true);
  assert.match(html(value), /-0\.00000000001/);
});
test("FAIL and UNKNOWN remain visible, rank1/CC do not become contract or recommendation", () => {
  const rendered = html();
  assert.match(rendered, /Подача заявки: FAIL\. Участие: UNKNOWN/);
  assert.match(rendered, /Срок подачи заявки истёк/);
  assert.match(rendered, /Применимость к выбранной версии: UNKNOWN/);
  assert.match(rendered, /Ранг и код результата не подтверждают подписанный контракт/);
  assert.doesNotMatch(rendered, /Победитель|PARTICIPATE|вероятность победы|соответствие:.*%/);
});
test("empty documents or application list do not claim zero competitors", () => {
  const value = report(); value.documents = [];
  assert.match(html(value), /отсутствие протоколов не означает отсутствие конкурентов/);
  const empty = report(); empty.documents[0].applications = [];
  empty.documents[0].observed_rows = missing("APPLICATION_LIST_ABSENT_OR_EMPTY");
  assert.match(html(empty), /число конкурентов UNKNOWN/);
  assert.doesNotMatch(html(value), /конкурентов: 0/);
});
test("XML strings are escaped and every fact retains source locator and SHA", () => {
  const value = report(); value.documents[0].applications[0].application_id = known('<script>alert("x")</script>');
  const rendered = html(value);
  assert.doesNotMatch(rendered, /<script>/);
  assert.match(rendered, /&lt;script&gt;/);
  assert.match(rendered, /applications\/application\[1\]\/price/);
  assert.match(rendered, new RegExp("b".repeat(64)));
  assert.match(rendered, /protocol\.xml/);
});

test("transport failure and mismatched action response stay local and retryable", async () => {
  const failed = await loadProtocolForCard(ref, async () => { throw new Error("private transport details"); });
  assert.equal(failed.result, undefined);
  assert.match(failed.error!, /Проверьте соединение/);
  assert.doesNotMatch(failed.error!, /private/);
  const wrong = report(); wrong.notice = { ...ref, version_number: 2 };
  const mismatch = await loadProtocolForCard(ref, async () => ({ result: wrong }));
  assert.equal(mismatch.result, undefined);
  assert.match(mismatch.error!, /не соответствует/);
  assert.deepEqual(await loadProtocolForCard(ref, async () => ({ error: "Не прочитано" })), { error: "Не прочитано" });
  assert.ok((await loadProtocolForCard(ref, async () => ({ result: report() }))).result);
});
