import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { TenderDocuments } from "../src/app/tender-discovery/tender-documents";
import type { Eis223SearchResult, EisIndexedLead, EisIndexedSearchResult } from "../src/lib/procurement-api";
import { sortTenderRows, filterDeliveryRegion, formatMoneyString, formatTenderDeadline, rowsFromResult, type WorkspaceResult } from "../src/lib/tender-workspace";

const provenance = { document_id: "synthetic-xml", locator: "/notice/field" };
const fact = (value: string | null) => ({ value, raw: value, provenance });
const lead44: EisIndexedLead = {
  document_type: "epNotificationEF2020", purchase_number: "0000000000000000001", version_number: 1,
  title: "Синтетическая бумага", notice_url: "https://example.invalid/notice", nmck_rub: "9007199254740993.0100",
  deadline: "2099-10-20T12:00:00+03:00", application_status: "UNKNOWN", economic_status: "UNKNOWN",
  match_quality: "STRONG", matched_terms: ["бумага"], match_locator: "/notice/title", reasons: ["ТЗ не проверено"],
  source_window: "getDocsIP/PRIZ/16/day", source_member: "notice.xml", xml_sha256: "a".repeat(64),
  lot_items: [{ name: "Бумага", ktru_code: null, okpd2_code: null, quantity: "10", unit: "упаковка", locator: "/notice/item" }], attachments: [],
};
const lead223: Eis223SearchResult["matched"][number] = {
  notice: {
    law: "223", document_type: "purchaseNotice", purchase_number: "00000000001", version_number: 1,
    xml_sha256: "b".repeat(64), source_member: "notice223.xml", title: fact("Бумага"), method_name: fact("Иной способ"),
    deadline: { ...fact("2099-10-20T12:00:00+03:00"), status: "AWARE" },
    publication: { ...fact(null), status: "UNKNOWN" }, status_raw: fact(null),
    application_status: "UNKNOWN", economics_status: "UNKNOWN", lot_review_status: "UNKNOWN",
    manifest_status: "UNKNOWN", manifest_count: fact(null), attachments: [],
    lots: [{ ordinal: fact("1"), subject: fact("Бумага"), initial_sum: fact("100.00"), currency: fact("RUB"),
      initial_sum_rub: null, provenance, cancelled_raw: fact(null), items: [{ description: fact("Бумага"), quantity: fact("10"), unit_name: fact("пачка"), provenance }] }],
  },
  source_window: "getDocsIP/RI223/77/day", source_response_sha256: "c".repeat(64), archive_sha256: "d".repeat(64),
  match_quality: "STRONG", matched_terms: ["бумага"], term_evidence: [{ term: "бумага", source_value: "Бумага", locator: "/title", value_kind: "title" }],
  matched_lot_ordinal: "1", application_status: "UNKNOWN", reasons: [], source_schema_status: "PASS", source_schema_checks: [],
};
function result44(leads = [lead44]): EisIndexedSearchResult {
  return { query: "бумага", search_scope: "NOT_EXPIRED_OR_UNKNOWN", total_current_notices: leads.length,
    excluded_expired_current_notices: 0, inspected_current_notices: leads.length, matched_count: leads.length,
    indexed_windows: 1, latest_ingested_at: null, corpus_coverage: "UNKNOWN", comparison_kind: "PRELIMINARY",
    planned_windows: 1, pending_windows: 0, requested_region_codes: 1, evaluated_candidate_notices: leads.length,
    unindexed_versions: 0, latest_source_publication: null, source_freshness: "UNKNOWN", compared_at: null,
    search_elapsed_ms: 0, matched: leads };
}
function result223(leads = [lead223]): Eis223SearchResult {
  return { query: "бумага", checked_at: "2026-10-15T00:00:00Z", indexed_current_notices: leads.length,
    indexed_windows: 1, evaluated_candidates: leads.length, matched_count: leads.length, latest_ingested_at: null,
    law: "223", document_types: ["purchaseNotice"], coverage: "UNKNOWN", freshness: "UNKNOWN", economics_status: "UNKNOWN", matched: leads };
}
const rows = (lead: typeof lead223) => rowsFromResult({ query: "бумага", law: "223", result223: result223([lead]) });

test("money preserves Decimal precision, trailing zeros and source currency", () => {
  assert.equal(formatMoneyString("9007199254740993.0100"), "9 007 199 254 740 993,0100 ₽");
  assert.equal(formatMoneyString("0.00000000000000000001", "USD"), "0,00000000000000000001 USD");
  assert.equal(formatMoneyString("-1000.00", "RUR"), "-1 000,00 ₽");
  assert.equal(formatMoneyString("0"), "0 ₽");
  assert.match(formatMoneyString("100", "UNKNOWN"), /валюта не подтверждена/);
  for (const value of [null, "NaN", "1,23", "Infinity", ""]) assert.equal(formatMoneyString(value), "Не подтверждено");
});

test("only valid aware deadlines are displayed and expired source cannot appear open", () => {
  for (const value of [null, "2026-10-20T12:00:00", "2026-02-30T12:00:00Z", "2026-10-20", "bad", "2026-10-20T24:00:00Z"]) {
    assert.equal(formatTenderDeadline(value), "Срок не подтверждён");
    const row = rowsFromResult({ query: "бумага", law: "44", result44: result44([{ ...lead44, deadline: value }]) })[0];
    assert.equal(row.deadline, null);
    assert.match(row.statusLabel, /UNKNOWN/);
  }
  assert.match(formatTenderDeadline("2024-02-29T10:00:00Z"), /29\.02\.2024.*13:00:00 МСК/);
  const expired = rowsFromResult({ query: "бумага", law: "44", result44: result44([{ ...lead44, deadline: "2000-01-01T00:00:00Z" }]) })[0];
  assert.equal(expired.blocked, true);
  assert.match(expired.statusLabel, /Срок истёк.*FAIL/);
});

test("generic 223 deadline and price need their selected typed source", () => {
  const unknown = rows(lead223)[0];
  assert.equal(unknown.deadline, null);
  assert.equal(unknown.deadlineRaw, lead223.notice.deadline.raw);
  assert.match(unknown.priceLabel, /не подтверждён/);
  assert.equal(unknown.priceValue, "Не подтверждено");
  assert.match(unknown.statusLabel, /UNKNOWN/);
  const selected = { ...lead223, notice: { ...lead223.notice, selected_deadline: lead223.notice.deadline,
    lots: [{ ...lead223.notice.lots[0], source_price_kind: "MAX_CONTRACT_PRICE" as const,
      source_amount: fact("9007199254740993.01"), source_currency_status: "CONSISTENT" as const }] } };
  const known = rows(selected)[0];
  assert.equal(known.deadline, lead223.notice.deadline.value);
  assert.match(known.priceLabel, /Максимальная цена договора по лоту/);
  assert.equal(known.priceValue, "9 007 199 254 740 993,01 ₽");
  assert.ok(!known.priceLabel.includes("НМЦК"));
  assert.equal(rows({ ...selected, notice: { ...selected.notice, selected_deadline: { ...lead223.notice.deadline, status: "UNKNOWN" } } })[0].deadline, null);
});

test("223 legacy specialized notice, text prices and multiple lots retain distinct meaning", () => {
  const specialized = rows({ ...lead223, notice: { ...lead223.notice, document_type: "purchaseNoticeAESMBO" } })[0];
  assert.equal(specialized.deadline, lead223.notice.deadline.value);
  assert.equal(specialized.priceValue, "100,00 ₽");
  const lot = { ...lead223.notice.lots[0], source_price_kind: "TEXT_ONLY" as const, source_price_text: fact("По формуле заказчика") };
  assert.equal(rows({ ...lead223, notice: { ...lead223.notice, lots: [lot] } })[0].priceValue, "По формуле заказчика");
  const multiple = rows({ ...lead223, notice: { ...lead223.notice, lots: [lot, { ...lot, ordinal: fact("2") }] } })[0];
  assert.equal(multiple.priceLabel, "Цены по лотам (2)");
  assert.equal(multiple.priceValue, "См. условия каждого лота");
  assert.equal(multiple.evidence.filter(item => item.label.startsWith("Лот ")).length, 2);
});

test("FAIL, cancellation holds and schema failures survive mapping independently of word match", () => {
  assert.equal(rows({ ...lead223, application_status: "FAIL" })[0].blocked, true);
  const held = { ...lead223, lot_cancellation_state: { purchase_number: lead223.notice.purchase_number,
    checked_at: "2026-10-15T00:00:00Z", evidence_status: "UNKNOWN" as const, application_status: "UNKNOWN" as const,
    current_procedure_status: "UNKNOWN" as const, source_schema_status: "UNKNOWN" as const,
    operation_hold: true, reason_codes: ["LOT_ASSOCIATION_UNKNOWN"], events: [] } };
  assert.equal(rows(held)[0].blocked, true);
  assert.match(rows(held)[0].statusLabel, /приостановлены.*UNKNOWN/);
  assert.ok(rows(held)[0].reasons.includes("LOT_ASSOCIATION_UNKNOWN"));
  assert.equal(rows({ ...lead223, source_schema_status: "FAIL" })[0].blocked, true);
  assert.match(rows({ ...lead223, source_schema_status: "PASS" })[0].statusLabel, /UNKNOWN/);
  const expired = rows({ ...lead223, notice: { ...lead223.notice, selected_deadline: { ...fact("2000-01-01T00:00:00Z"), status: "AWARE" } } })[0];
  assert.equal(expired.blocked, true);
});

test("unification respects law, exact identity and keeps evidence without inferring delivery", () => {
  const result: WorkspaceResult = { query: "бумага", law: "all", result44: result44([lead44, lead44, { ...lead44, version_number: 2 }]), result223: result223() };
  const combined = rowsFromResult(result);
  assert.equal(combined.length, 3);
  assert.deepEqual(combined.map(row => row.law), ["44", "44", "223"]);
  assert.equal(combined[0].raw44, lead44);
  assert.equal(combined[2].raw223, lead223);
  assert.equal(combined[0].positions[0].locator, "/notice/item");
  assert.ok(combined[0].evidence.some(item => item.value === lead44.source_window && item.label === "Окно загрузки источника"));
  assert.ok(!combined[0].evidence.some(item => /достав|постав|заказчик/i.test(item.label)));
  assert.equal(rowsFromResult({ ...result, law: "223" }).length, 1);
  assert.equal(rowsFromResult({ query: "бумага", law: "all", error44: "Недоступен", result223: result223() }).length, 1);
  assert.equal(rowsFromResult({ query: "бумага", law: "all", error: "Недоступен" }).length, 0);
});

test("notice links accept only credential-free HTTPS official hosts", () => {
  const urlFor = (notice_url: string) => rowsFromResult({ query: "бумага", law: "44",
    result44: result44([{ ...lead44, notice_url }]) })[0].noticeUrl;
  for (const url of ["https://zakupki.gov.ru/notice?id=1", "https://test.zakupki.gov.ru/notice"]) {
    assert.equal(urlFor(url), url);
  }
  for (const url of ["javascript:alert(1)", "http://zakupki.gov.ru/notice", "https://zakupki.gov.ru.evil.test/notice",
    "https://evilzakupki.gov.ru/notice", "https://zakupki.gov.ru@evil.test/notice", "https://operator@zakupki.gov.ru/notice",
    "https://operator:secret@zakupki.gov.ru/notice", "https://example.invalid/notice", "/notice", "invalid"])
    assert.equal(urlFor(url), null, url);
});

test("workspace exposes original 44 documents with exact source provenance", () => {
  const attachment = { filename: "Описание объекта закупки.pdf", url: "https://zakupki.gov.ru/44/document.pdf", locator: "/attachments/document[1]" };
  const row = rowsFromResult({ query: "бумага", law: "44", result44: result44([{ ...lead44, attachments: [attachment] }]) })[0];
  assert.deepEqual(row.documents, [{ ...attachment, available: true }]);
});

test("223 document links never fall back to raw URL or reveal restricted attachments", () => {
  const url = "https://zakupki.gov.ru/223/filestore/public/1.0/download/fz223/file.html?uid=" + "A".repeat(32);
  const document = { filename: fact("Техническое задание.docx"), content_uid: fact("A".repeat(32)), url: fact(url), not_placement_raw: fact("false") };
  const map = (attachments: typeof lead223.notice.attachments, extra = {}) => rows({ ...lead223, notice: { ...lead223.notice, ...extra, attachments } })[0].documents;
  assert.equal(map([document])[0].url, url);
  assert.equal(map([{ ...document, url: { ...fact(null), raw: url } }])[0].url, null);
  assert.equal(map([{ ...document, not_placement_raw: fact("true") }])[0].url, null);
  assert.equal(map([document], { hide_purchase_raw: fact("true") })[0].url, null);
  assert.equal(map([document], { hide_purchase_customer_accredited_raw: fact("1") })[0].url, null);
  for (const invalid of ["javascript:alert(1)", "https://operator@zakupki.gov.ru/file", "https://evil.test/file", "http://zakupki.gov.ru/file"]) {
    assert.equal(map([{ ...document, url: fact(invalid) }])[0].url, null);
  }
});


test("document section renders source links and escapes filenames without asserting complete TZ", () => {
  const attachment = { filename: "<script>ТЗ</script>.pdf", url: "https://zakupki.gov.ru/44/document.pdf", locator: "/attachments/document[1]" };
  const row = rowsFromResult({ query: "бумага", law: "44", result44: result44([{ ...lead44, attachments: [attachment] }]) })[0];
  const html = renderToStaticMarkup(createElement(TenderDocuments, { row }));
  assert.ok(html.includes('href="https://zakupki.gov.ru/44/document.pdf"'));
  assert.ok(html.includes("&lt;script&gt;ТЗ&lt;/script&gt;.pdf"));
  assert.ok(html.includes(row.xmlSha256));
  assert.match(html, /полнота комплекта требуют проверки/);
});

test("unavailable attachments and absent manifests never become downloadable or complete", () => {
  const attachment = { filename: fact("ТЗ.pdf"), content_uid: fact("A".repeat(32)),
    url: { ...fact(null), raw: "https://zakupki.gov.ru/restricted-document" } };
  const row = rows({ ...lead223, notice: { ...lead223.notice, attachments: [attachment] } })[0];
  const html = renderToStaticMarkup(createElement(TenderDocuments, { row }));
  assert.ok(!html.includes("restricted-document"));
  assert.ok(!html.includes("href="));
  assert.match(html, /доступ ограничен/);
  const empty = renderToStaticMarkup(createElement(TenderDocuments, { row: rows(lead223)[0] }));
  assert.match(empty, /не означает отсутствие ТЗ/);
});


test("delivery filtering uses only source-bound regions and explicit unknown policy", () => {
  const base = rowsFromResult({ query: "бумага", law: "44", result44: result44() });
  const nav = { law: "44" as const, purchase_number: lead44.purchase_number, version_number: 1,
    xml_sha256: lead44.xml_sha256, delivery_regions: [{ value: "Республика Татарстан", provenance: { document_id: lead44.xml_sha256, locator: "/delivery/region" } }],
    delivery_coverage: "UNKNOWN" as const, eis_url: null, platform_url: null, platform_name: null };
  const rows = rowsFromResult({ query: "бумага", law: "44", result44: result44(), navigation: { [base[0].id]: nav } });
  assert.equal(filterDeliveryRegion(rows, "Республика Татарстан", false).length, 1);
  assert.equal(filterDeliveryRegion(rows, "Москва", false).length, 0);
  assert.equal(filterDeliveryRegion(base, "Москва", false).length, 0);
  assert.equal(filterDeliveryRegion(base, "Москва", true).length, 1);
  const wrong = rowsFromResult({ query: "бумага", law: "44", result44: result44(), navigation: { [base[0].id]: { ...nav, xml_sha256: "f".repeat(64) } } });
  assert.equal(wrong[0].deliveryRegions, undefined);
});


test("expensive ordering compares exact Decimal digits and keeps equal prices stable", () => {
  const make = (price: string, digit: string) => ({ ...lead44, purchase_number: digit.repeat(19), nmck_rub: price });
  const original = rowsFromResult({ query: "бумага", law: "44", result44: result44([
    make("9007199254740993.0100", "1"), make("9007199254740993.0101", "2"),
    make("09007199254740993.01", "3"), make("0.00000000000000000001", "4"),
  ]) });
  const sorted = sortTenderRows(original, "price_desc");
  assert.deepEqual(sorted.map(row => row.purchaseNumber[0]), ["2", "1", "3", "4"]);
  assert.deepEqual(original.map(row => row.purchaseNumber[0]), ["1", "2", "3", "4"]);
  assert.deepEqual(sortTenderRows(original, "search"), original);
});

test("expensive ordering never converts currencies or invents an amount for text and multi-lot prices", () => {
  const make = (number: string, currency: string, amount: string) => {
    const lead = structuredClone(lead223); lead.notice.purchase_number = number.repeat(11);
    Object.assign(lead.notice.lots[0], { source_price_kind: "INITIAL_SUM", source_amount: fact(amount),
      currency: fact(currency), source_currency_status: "CONSISTENT" });
    return lead;
  };
  const rub = make("1", "RUR", "150.00"); const foreign = make("2", "USD", "999999999");
  const text = make("3", "RUB", "999999999"); text.notice.lots[0].source_price_kind = "TEXT_ONLY";
  const multi = make("4", "RUB", "999999999"); multi.notice.lots.push(structuredClone(multi.notice.lots[0]));
  const unknown = make("5", "RUB", "999999999"); unknown.notice.lots[0].source_currency_status = "UNKNOWN";
  const values = rowsFromResult({ query: "бумага", law: "all", result44: result44([{ ...lead44, nmck_rub: "100" }]), result223: result223([foreign, text, multi, unknown, rub]) });
  assert.deepEqual(sortTenderRows(values, "price_desc").map(row => row.purchaseNumber[0]), ["1", "0", "2", "3", "4", "5"]);
});

test("price sorting never promotes a hard-blocked source or clears FAIL", () => {
  const values = rowsFromResult({ query: "бумага", law: "44", result44: result44([
    { ...lead44, purchase_number: "1".repeat(19), nmck_rub: "9000000", application_status: "FAIL" },
    { ...lead44, purchase_number: "2".repeat(19), nmck_rub: "100" },
    { ...lead44, purchase_number: "3".repeat(19), nmck_rub: null },
  ]) });
  const sorted = sortTenderRows(values, "price_desc");
  assert.deepEqual(sorted.map(row => row.purchaseNumber[0]), ["2", "3", "1"]);
  assert.equal(sorted[2].blocked, true); assert.match(sorted[2].statusLabel, /FAIL/);
});

test("region filtering and appended pages retain descending price order without admitting unknown regions", () => {
  const values = rowsFromResult({ query: "бумага", law: "44", result44: result44([
    { ...lead44, purchase_number: "1".repeat(19), nmck_rub: "100" },
    { ...lead44, purchase_number: "2".repeat(19), nmck_rub: "200" },
    { ...lead44, purchase_number: "3".repeat(19), nmck_rub: "900" },
  ]) }).map((row, index) => ({ ...row, deliveryRegions: index === 2 ? [] : [{ value: "Московская обл", provenance }] }));
  const appended = { ...values[0], id: "appended", purchaseNumber: "4".repeat(19), sortAmountRub: "300" };
  const selected = filterDeliveryRegion([...values, appended], "Московская область", false);
  assert.deepEqual(sortTenderRows(selected, "price_desc").map(row => row.purchaseNumber[0]), ["4", "2", "1"]);
  assert.equal(sortTenderRows(filterDeliveryRegion(values, "Московская область", true), "price_desc")[0].purchaseNumber[0], "3");
});
