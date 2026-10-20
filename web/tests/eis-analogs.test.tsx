import assert from "node:assert/strict";
import test from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { HistoricalAnalogReportView } from "../src/app/tender-discovery/historical-analog-report";
import { analogDimensions, analogReportMatches, analogUnknownFields, createAnalogReadSession,
  loadAnalogsForRequest, validAnalogRequest, type AnalogFact, type AnalogNotice, type AnalogReadState,
  type AnalogReport, type AnalogRequest } from "../src/lib/eis-analogs";

const target = { purchase_number: "0".repeat(19), version_number: 1, notice_xml_sha256: "a".repeat(64) };
const request: AnalogRequest = { target, source_index: 1, query: "бумага", lookback_days: 365 };
const source = (sha: string) => ({ document_id: sha, locator: "notice.xml :: position[1]/name", extractor: "api" as const, confidence: 1 });
const fact = (value: string | null, sha: string): AnalogFact => ({ value, provenance: source(sha) });
function notice(number: string, sha: string): AnalogNotice {
  return { notice: { ...target, purchase_number: number, notice_xml_sha256: sha },
    source_member: "notice.xml", document_type: "epNotificationEF2020", lot_parse_status: "PARSED",
    published_at: fact("2026-09-01T12:00:00+03:00", sha), deadline: fact("2026-09-10T12:00:00+03:00", sha),
    positions_total: 1, positions: [{ source_index: 1, name: fact("Бумага", sha), ktru: fact(null, sha),
      okpd2: fact("17.12", sha), quantity: fact("123456789012345678.123456789012", sha), unit: fact("пачка", sha) }] };
}
function report(): AnalogReport {
  const candidate = notice("1".repeat(19), "b".repeat(64));
  return { ...Object.fromEntries(analogUnknownFields.map(k => [k, "UNKNOWN"])) as Record<typeof analogUnknownFields[number], "UNKNOWN">,
    request: structuredClone(request), checked_at: "2026-10-05T15:00:00Z", policy_version: "eis-analog-retrieval-v1",
    scope: "BOUNDED_SAVED_HISTORICAL_TOKEN_PREFILTER", source_requests: 0,
    target: notice(target.purchase_number, target.notice_xml_sha256), candidates: [candidate],
    period_start: "2025-09-01T09:00:00Z", period_end: "2026-09-01T09:00:00Z",
    selected_notices: 1, evaluated_positions: 1, excluded_rows: 1, review_rows: 0,
    selection_truncated: true, uninspected_positions: 0,
    reasons: ["EXPIRED_DEADLINE_IS_NOT_COMPLETED_CONTRACT", "VOLUME_FILTER_IS_NOT_UNIT_OR_TECHNICAL_EQUIVALENCE"],
    rows: [{ notice: candidate.notice, source_index: 1, disposition: "EXCLUDED", comparability: "FAIL",
      criteria: analogDimensions.map(dimension => ({ dimension,
        status: dimension === "SUBJECT" ? "FAIL" : "UNKNOWN",
        reason: dimension === "SUBJECT" ? "KTRU_CONFLICT" : "SPECIFICATION_NOT_REVIEWED",
        target_value: null, candidate_value: null, evidence: [source(target.notice_xml_sha256), source(candidate.notice.notice_xml_sha256)] })) }],
  };
}
const html = (value = report()) => renderToStaticMarkup(<HistoricalAnalogReportView report={value} />);
test("strict request rejects caller tenant, invalid refs, position and period", () => {
  assert.equal(validAnalogRequest(request), true);
  for (const invalid of [null, [], { ...request, company_id: "other" }, { ...request, target: { ...target, company_id: "other" } },
    { ...request, target: { ...target, version_number: 1.5 } }, { ...request, target: { ...target, notice_xml_sha256: "A".repeat(64) } },
    ...[0, 26, 1.5, "1"].map(source_index => ({ ...request, source_index })),
    ...[0, 731, 1.1, "365"].map(lookback_days => ({ ...request, lookback_days })),
    ...[" ", "a".repeat(121)].map(query => ({ ...request, query }))]) assert.equal(validAnalogRequest(invalid), false);
});

function reportWithOmission(): AnalogReport {
  return { ...report(), policy_version: "eis-analog-retrieval-v2", omitted_candidates: [{
    notice: { purchase_number: "2".repeat(19), version_number: 2, notice_xml_sha256: "c".repeat(64) },
    reason: "CANDIDATE_NOTICE_PAYLOAD_LIMIT", payload_bytes: 300000, limit_bytes: 256 * 1024,
    measurement_source: "SAVED_NOTICE_LOT_ITEMS_JSONB_OCTET_LENGTH",
  }] };
}
test("v1/v2 compatibility requires honest typed disjoint omissions", () => {
  assert.equal(analogReportMatches(report(), request), true);
  assert.equal(analogReportMatches({ ...report(), omitted_candidates: [] }, request), true);
  assert.equal(analogReportMatches({ ...report(), policy_version: "eis-analog-retrieval-v2", omitted_candidates: [] }, request), true);
  assert.equal(analogReportMatches(reportWithOmission(), request), true);
  assert.equal(analogReportMatches({ ...report(), policy_version: "eis-analog-retrieval-v2" }, request), false);
  for (const omitted_candidates of [null, true, {}, "", [null]]) {
    assert.equal(analogReportMatches({ ...reportWithOmission(), omitted_candidates }, request), false);
  }
  const value = reportWithOmission(); const omission = value.omitted_candidates![0];
  for (const change of [
    { payload_bytes: "300000" }, { payload_bytes: true }, { payload_bytes: 300000.5 },
    { payload_bytes: omission.limit_bytes }, { limit_bytes: -1 }, { limit_bytes: "262144" },
    { reason: "FAIL" }, { reason: ["CANDIDATE_NOTICE_PAYLOAD_LIMIT"] },
    { measurement_source: "XML_BYTES" }, { company_id: "foreign" },
    { notice: request.target }, { notice: value.candidates[0].notice },
    { notice: { ...omission.notice, notice_xml_sha256: "C".repeat(64) } },
  ]) assert.equal(analogReportMatches({ ...value, omitted_candidates: [{ ...omission, ...change }] }, request), false);
  assert.equal(analogReportMatches({ ...value, policy_version: "eis-analog-retrieval-v1" }, request), false);
  assert.equal(analogReportMatches({ ...value, omitted_candidates: [omission, omission] }, request), false);
  assert.equal(analogReportMatches({ ...value, omitted_candidates: Array.from({ length: 20 }, (_, i) => ({ ...omission,
    notice: { ...omission.notice, purchase_number: String(i + 2).padStart(19, "0") } })) }, request), false);
  const total = { ...omission, reason: "CANDIDATE_TOTAL_PAYLOAD_LIMIT", payload_bytes: 20000, limit_bytes: 10000 };
  assert.equal(analogReportMatches({ ...value, omitted_candidates: [total] }, request), true);
  assert.equal(analogReportMatches({ ...value, omitted_candidates: [{ ...total, limit_bytes: 0 }] }, request), true);
  assert.equal(analogReportMatches({ ...value, omitted_candidates: [{ ...total, payload_bytes: 300000 }] }, request), false);
});
test("omissions show source refs and UNKNOWN, without invented exclusion or empty search", () => {
  const value = reportWithOmission(); const rendered = html(value);
  for (const expected of ["Не разобрано карточек из-за размера: 1", "не исключены по требованиям", "сопоставимость: UNKNOWN",
    "карточка превышает лимит разбора", "2".repeat(19), "c".repeat(64)]) assert.ok(rendered.includes(expected), expected);
  assert.equal(value.excluded_rows, 1);
  value.candidates = []; value.rows = []; value.selected_notices = value.evaluated_positions = value.excluded_rows = value.review_rows = 0;
  assert.equal(analogReportMatches(value, request), true);
  const empty = html(value);
  assert.ok(empty.includes("Карточки найдены, но не рассмотрены из-за ограничения размера"));
  assert.ok(empty.includes("не подтверждает отсутствие аналогов или конкурентов"));
  assert.ok(!empty.includes("В сохранённой выборке кандидатов нет"));
  assert.doesNotMatch(empty, /PARTICIPATE|вероятность победы|конкурентов: 0/);
});
test("all request fields bind response, with malformed response handled safely", async () => {
  assert.equal(analogReportMatches(report(), request), true);
  for (const changed of [{ ...request, source_index: 2 }, { ...request, query: "сервер" }, { ...request, lookback_days: 30 },
    { ...request, target: { ...target, version_number: 2 } }, { ...request, target: { ...target, notice_xml_sha256: "c".repeat(64) } }]) {
    assert.equal(analogReportMatches(report(), changed), false);
    assert.ok((await loadAnalogsForRequest(changed, async () => ({ result: report() }))).error);
  }
  for (const malformed of [null, {}, { ...report(), rows: [null] }, { ...report(), target: {} }]) {
    assert.equal(analogReportMatches(malformed, request), false);
  }
});
test("no invented PASS, source calls, counts, missing provenance or different row refs", () => {
  const mutations: Array<(r: AnalogReport) => void> = [
    r => { r.rows[0].disposition = "NEEDS_REVIEW"; r.rows[0].comparability = "UNKNOWN"; },
    r => { r.rows[0].criteria[4].status = "PASS"; }, r => { r.rows[0].criteria[5].status = "PASS"; },
    r => { r.rows[0].criteria[0].evidence = [source(target.notice_xml_sha256)]; },
    r => { r.rows[0].notice = { ...r.rows[0].notice, version_number: 2 }; },
    r => { r.candidates[0].positions[0].quantity.provenance = source("c".repeat(64)); },
    r => { r.selected_notices++; }, r => { r.excluded_rows++; }, r => { r.uninspected_positions++; },
    r => { r.rows.push(r.rows[0]); }, r => { r.rows[0].criteria[1] = r.rows[0].criteria[0]; },
    r => { r.checked_at = "2026-10-05T15:00:00"; }, r => { r.target.deadline.value = "2026-10-05"; },
    r => { r.candidates[0].positions[0].quantity.value = "NaN"; },
  ];
  for (const mutate of mutations) { const value = report(); mutate(value); assert.equal(analogReportMatches(value, request), false); }
  assert.equal(analogReportMatches({ ...report(), coverage: "PASS" }, request), false);
  assert.equal(analogReportMatches({ ...report(), source_requests: 1 }, request), false);
  assert.equal(analogReportMatches({ ...report(), candidates: Array(21).fill(report().candidates[0]) }, request), false);
  const invalid = report(); invalid.rows[0].criteria[0].status = ["FAIL"] as unknown as "FAIL";
  invalid.rows[0].disposition = "NEEDS_REVIEW"; invalid.rows[0].comparability = "UNKNOWN";
  invalid.excluded_rows = 0; invalid.review_rows = 1;
  assert.equal(analogReportMatches(invalid, request), false);
  invalid.rows[0].criteria[0].status = "UNKNOWN";
  invalid.target.lot_parse_status = ["PARSED"] as unknown as "PARSED";
  assert.equal(analogReportMatches(invalid, request), false);
});
test("FAIL exclusions, UNKNOWN review, truncation and both XML sources visible", () => {
  const value = report(); const rendered = html(value);
  for (const expected of ["сопоставимость FAIL", "КТРУ различается", "Выборка обрезана", "регион поставки: UNKNOWN",
    "прибыль: UNKNOWN", "участие: UNKNOWN", "не подтверждает завершение контракта", "физическая и техническая эквивалентность неизвестна",
    target.notice_xml_sha256, "b".repeat(64), "notice.xml :: position[1]/name"]) assert.ok(rendered.includes(expected), expected);
  assert.doesNotMatch(rendered, /PARTICIPATE|соответствие.*%|вероятность победы/);
  value.rows[0].criteria[0].status = "PASS";
  value.rows[0].disposition = "NEEDS_REVIEW"; value.rows[0].comparability = "UNKNOWN";
  value.excluded_rows = 0; value.review_rows = 1;
  assert.equal(analogReportMatches(value, request), true);
  assert.match(html(value), /Требуют проверки: 1 · сопоставимость UNKNOWN/);
});
test("Decimal strings and aware dates remain exact, external text escaped", () => {
  const value = report(); value.candidates[0].positions[0].name.value = '<img src=x onerror="alert(1)">';
  value.rows[0].criteria[0].reason = "<script>steal()</script>";
  const rendered = html(value);
  assert.ok(rendered.includes("123456789012345678.123456789012"));
  assert.ok(rendered.includes("2026-09-01T12:00:00+03:00"));
  assert.ok(rendered.includes("&lt;img")); assert.ok(rendered.includes("&lt;script&gt;"));
  assert.doesNotMatch(rendered, /<img|<script>|₽|RUB/);
});
test("empty, missing positions and truncation do not invent zero competition or completeness", () => {
  const empty = report(); empty.candidates = []; empty.rows = [];
  empty.selected_notices = empty.evaluated_positions = empty.excluded_rows = 0; empty.selection_truncated = false;
  assert.equal(analogReportMatches(empty, request), true);
  assert.match(html(empty), /не подтверждает отсутствие аналогов или конкурентов/);
  assert.match(html(empty), /полнота всей ЕИС остаётся UNKNOWN/);
  const missing = report(); missing.candidates[0].positions = []; missing.candidates[0].positions_total = 3;
  missing.evaluated_positions = 0; missing.uninspected_positions = 3; missing.rows[0].source_index = null;
  assert.equal(analogReportMatches(missing, request), true);
  assert.match(html(missing), /позиция UNKNOWN/);
  assert.doesNotMatch(html(empty), /конкурентов: 0/);
});
test("official links reflect the procedure family; full limit does not claim fewer results", () => {
  for (const [kind, page] of [["epNotificationEF2020", "ea20"], ["epNotificationEZK2020", "zk20"], ["epNotificationEOK2020", "ok20"]]) {
    const value = report(); value.candidates[0].document_type = kind;
    assert.ok(html(value).includes(`/notice/${page}/view/common-info.html`));
  }
  const unknown = report(); unknown.candidates[0].document_type = "constructor";
  unknown.rows[0].criteria[0].reason = "constructor"; unknown.reasons = ["constructor"];
  assert.doesNotMatch(html(unknown), /<a /);
  assert.match(html(unknown), /constructor/);
  const value = report(); value.selection_truncated = false;
  const rendered = html(value);
  assert.match(rendered, /Дополнительные карточки за пределами лимита не обнаружены/);
  assert.doesNotMatch(rendered, /Лимит карточек не достигнут/);
});
test("transport failure and API error become visible errors with no report", async () => {
  assert.ok((await loadAnalogsForRequest(request, async () => { throw Error("transport"); })).error?.includes("соединение"));
  assert.deepEqual(await loadAnalogsForRequest(request, async () => ({ error: "source unavailable" })), { error: "source unavailable" });
  assert.ok((await loadAnalogsForRequest(request, async () => ({}))).error);
});
test("input changes and later requests invalidate pending successes and errors", async () => {
  const session = createAnalogReadSession();
  let resolve!: (v: AnalogReadState) => void;
  const read = () => new Promise<AnalogReadState>(r => { resolve = r; });
  const pending = session.read(request, read); session.invalidate(); resolve({ result: report() });
  assert.equal(await pending, undefined);
  const old = session.read(request, read);
  const current = await session.read(request, async () => ({ result: report() }));
  assert.ok(current?.result); resolve({ error: "obsolete error" }); assert.equal(await old, undefined);
});
