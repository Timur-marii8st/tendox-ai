import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  betaHistoryMatches, betaRefMatches, betaReportMatches, financialQuoteCurrent, historyDecimal,
  historyFraction, historyDateOnly, historyScopeLabel, betaReason, quoteDiscountMode, type BetaHistoryReport, type BetaQuoteReport, type HistoryFact,
} from "../src/lib/beta-procurement";

const saved = JSON.parse(readFileSync("tests/fixtures/beta-quote.json", "utf8")) as BetaQuoteReport;
const source = { document_id: "a".repeat(64), locator: "contract/price" };
const fact = <T>(value: T | null): HistoryFact<T> => ({ value, source, supporting_sources: [] });
function history(): BetaHistoryReport {
  return {
    ref: structuredClone(saved.ref), source_reasons: [],
    history: {
      policy: "regional-discount-v2", checked_at: "2026-10-21T00:00:00Z", coverage: "UNKNOWN", status: "PASS", sample_size: 5, required_sample: 5,
      realistic_discount: "0.100000", conservative_discount: "0.200000", reasons: [],
      cohort: { law: saved.ref.notice.law, target_id: `${saved.ref.notice.law}:${saved.ref.notice.purchase_number}:${saved.ref.lot_index ?? 0}`,
        region: "Москва", product_key: "synthetic", procedure: "auction", unit: "шт", quantity: "10",
        period_start: "2026-09-01T00:00:00Z", period_end: "2026-10-20T00:00:00Z", source },
      evaluated: Array.from({ length: 5 }, (_, n) => ({
        status: "PASS", reasons: [], discount: "0.100000",
        observation: { purchase_number: `012345678902600000${n}`, law: saved.ref.notice.law,
          initial: fact("100000.00"), final: fact("90000.00"), quantity: fact("10"), region: fact("Москва"),
          product_key: fact("synthetic"), procedure: fact("auction"), unit: fact("шт"), concluded_at: fact("2026-10-01T00:00:00Z"),
          concluded_date: null, qualification_reasons: [], price_basis: "RUB_NOMINAL_DECLARED_SIGNED_TOTALS",
          notice_lot_volume_link: fact(true), rub_nominal_totals: fact(true), concluded_contract: fact(true), current_result: fact(true) },
      })),
    },
  };
}

test("new forms choose regional explicitly while absent legacy mode remains manual", () => {
  assert.equal(quoteDiscountMode(undefined), "REGIONAL");
  assert.equal(quoteDiscountMode(null), "REGIONAL");
  assert.equal(quoteDiscountMode(saved.input), "MANUAL");
  assert.equal(quoteDiscountMode({ ...saved.input!, discount_mode: "MANUAL" }), "MANUAL");
  assert.equal(quoteDiscountMode({ ...saved.input!, discount_mode: "REGIONAL" }), "REGIONAL");
});

test("history and quote binding reject a different lot, law, version, XML or purchase", () => {
  const response = history();
  assert.equal(betaHistoryMatches(response, saved.ref), true);
  for (const change of [
    { ...saved.ref, lot_index: saved.ref.lot_index === null ? 0 : saved.ref.lot_index + 1 },
    ...[
      { law: saved.ref.notice.law === "44" ? "223" as const : "44" as const },
      { version_number: saved.ref.notice.version_number + 1 },
      { notice_xml_sha256: "f".repeat(64) }, { purchase_number: "0999999999926000001" },
    ].map(notice => ({ ...saved.ref, notice: { ...saved.ref.notice, ...notice } })),
  ]) {
    assert.equal(betaRefMatches(response.ref, change), false);
    assert.equal(betaHistoryMatches(response, change), false);
    assert.equal(betaReportMatches(saved, change), false);
  }
  for (const malformed of [null, {}, { notice: null }, { notice: [] }]) assert.equal(betaRefMatches(malformed, saved.ref), false);
});

test("matching outer ref does not authorize another cohort target", () => {
  const response = history();
  response.history.cohort.target_id += "1";
  assert.equal(betaHistoryMatches(response, saved.ref), false);
});

test("nominal price history does not inherit the old gross-price interpretation", () => {
  const response = history();
  assert.equal(betaHistoryMatches({ ...response, history: { ...response.history, policy: "regional-discount-v1" } }, saved.ref), false);
  const entry = response.history.evaluated[0];
  const changed = { ...response, history: { ...response.history, evaluated: [{ ...entry,
    observation: { ...entry.observation, price_basis: "GROSS_INCLUDING_VAT" } }, ...response.history.evaluated.slice(1)] } };
  assert.equal(betaHistoryMatches(changed, saved.ref), false);
});

test("UNKNOWN history remains readable but cannot carry inferred rates", () => {
  const response = history();
  Object.assign(response.history, { status: "UNKNOWN", sample_size: 0, evaluated: [], realistic_discount: null,
    conservative_discount: null, reasons: ["INSUFFICIENT_VERIFIED_COMPARABLE_RESULTS"] });
  assert.equal(betaHistoryMatches(response, saved.ref), true);
  response.history.realistic_discount = "0";
  assert.equal(betaHistoryMatches(response, saved.ref), false);
});

test("sample counts cannot promote four observations or contradictory coverage to PASS", () => {
  const response = history();
  response.history.evaluated.pop();
  assert.equal(betaHistoryMatches(response, saved.ref), false);
  response.history.sample_size = 4;
  assert.equal(betaHistoryMatches(response, saved.ref), false);
  assert.equal(betaHistoryMatches({ ...history(), history: { ...history().history, coverage: "PASS" } }, saved.ref), false);
});

test("history rejects nonfinite, numeric, oversized and missing-source monetary values", () => {
  for (const value of ["NaN", "Infinity", "1e999999", 100, "1".repeat(10000)]) {
    const response = history();
    const invalid = { ...response, history: { ...response.history, evaluated: [{ ...response.history.evaluated[0],
      observation: { ...response.history.evaluated[0].observation, initial: fact(value) } }, ...response.history.evaluated.slice(1)] } };
    assert.equal(betaHistoryMatches(invalid, saved.ref), false);
  }
  const response = history();
  response.history.evaluated[0].observation.initial.source = { document_id: "", locator: "" };
  assert.equal(betaHistoryMatches(response, saved.ref), false);
});

test("history time windows cannot be naive, reversed or later than the check", () => {
  for (const period_end of ["2026-10-20T00:00:00", "2026-08-01T00:00:00Z", "2027-01-01T00:00:00Z"]) {
    const response = history(); response.history.cohort.period_end = period_end;
    assert.equal(betaHistoryMatches(response, saved.ref), false);
  }
});

test("calendar-only contract dates do not acquire invented time or timezone", () => {
  const response = history();
  response.history.evaluated[0].observation.concluded_at = fact<string>(null);
  response.history.evaluated[0].observation.concluded_date = fact("2026-10-01");
  assert.equal(betaHistoryMatches(response, saved.ref), true);
  assert.equal(response.history.evaluated[0].observation.concluded_at.value, null);
  for (const value of ["2026-02-29", "2026-10-01T00:00:00Z", "2026-13-01"]) assert.equal(historyDateOnly(value), false);
  response.history.evaluated[0].observation.concluded_date.value = "2026-02-29";
  assert.equal(betaHistoryMatches(response, saved.ref), false);
});

test("fraction display retains exact decimal digits without money float conversion", () => {
  assert.equal(historyFraction("0.123456000001"), "0.123456000001");
  assert.equal(historyDecimal("9007199254740993.01"), true);
  for (const value of [null, "1", "-0.1", "Infinity", "0.1234567890123", 0.1]) assert.equal(historyFraction(value), "UNKNOWN");
});

test("regional quote never silently reuses a manual or UNKNOWN calculation", () => {
  const report = structuredClone(saved);
  report.input!.discount_mode = "REGIONAL";
  const current = () => financialQuoteCurrent(report, "2026-10-23T00:00:00Z", false, Date.parse("2026-10-21T00:00:00Z"));
  assert.equal(current(), false);
  report.calculation!.discount_basis = "REGIONAL_HISTORY";
  report.calculation!.regional_discount = history().history;
  assert.equal(current(), true);
  report.calculation!.regional_discount.status = "UNKNOWN";
  assert.equal(current(), false);
  report.input!.discount_mode = "MANUAL";
  assert.equal(current(), false); // A regional UNKNOWN result cannot be relabelled manual.
  report.calculation!.discount_basis = "MANUAL";
  report.calculation!.regional_discount = null;
  assert.equal(current(), true);
});

test("legacy missing scope stays whole notice and joint scope names the complete customer contract", () => {
  const response = history();
  assert.equal(betaHistoryMatches(response, saved.ref), true);
  assert.equal(historyScopeLabel(response.history.evaluated[0].observation), "Полный объём извещения");
  const observation = response.history.evaluated[0].observation;
  observation.price_scope = "WHOLE_CUSTOMER_CONTRACT";
  observation.customer = fact("01000000001");
  observation.initial = fact("221758.25");
  assert.equal(betaHistoryMatches(response, saved.ref), true);
  assert.equal(historyScopeLabel(observation), "Полный контракт заказчика в совместной закупке");
  assert.equal(observation.initial.value, "221758.25");
  assert.equal(observation.customer.source, source);
});

test("customer-scoped PASS requires an eleven-digit EIS customer with provenance", () => {
  for (const customer of [undefined, null, fact(null), fact("123"), fact("company-id"), fact(10000000001),
    { value: "01000000001", source: { document_id: "", locator: "" }, supporting_sources: [] }]) {
    const response = history();
    const entry = response.history.evaluated[0];
    const changed = { ...response, history: { ...response.history, evaluated: [{ ...entry,
      observation: { ...entry.observation, price_scope: "WHOLE_CUSTOMER_CONTRACT", customer } },
      ...response.history.evaluated.slice(1)] } };
    assert.equal(betaHistoryMatches(changed, saved.ref), false);
  }
});

test("UNKNOWN customer scope remains readable when identity is not yet confirmed", () => {
  const response = history();
  const entry = response.history.evaluated[0];
  entry.status = "UNKNOWN";
  entry.discount = null;
  entry.reasons = ["CUSTOMER_SCOPE_IDENTITY_NOT_CONFIRMED"];
  entry.observation.price_scope = "WHOLE_CUSTOMER_CONTRACT";
  entry.observation.customer = fact<string>(null);
  Object.assign(response.history, { status: "UNKNOWN", sample_size: 4, realistic_discount: null,
    conservative_discount: null, reasons: ["INSUFFICIENT_VERIFIED_COMPARABLE_RESULTS"] });
  assert.equal(betaHistoryMatches(response, saved.ref), true);
  entry.observation.customer = null;
  assert.equal(betaHistoryMatches(response, saved.ref), true);
});

test("unknown or malformed price scopes are never interpreted as whole notice", () => {
  for (const price_scope of ["PARTIAL_CUSTOMER", "whole_notice", "", null, true, 1]) {
    const response = history();
    const entry = response.history.evaluated[0];
    const changed = { ...response, history: { ...response.history, evaluated: [{ ...entry,
      observation: { ...entry.observation, price_scope } }, ...response.history.evaluated.slice(1)] } };
    assert.equal(betaHistoryMatches(changed, saved.ref), false);
  }
});

test("source and customer exclusions are Russian explanations without raw implementation codes", () => {
  for (const reason of ["CUSTOMER_SCOPE_IDENTITY_NOT_CONFIRMED", "CUSTOMER_IDENTITY_REQUIRED",
    "CUSTOMER_PARTITION_QUANTITY_CONFLICT", "CUSTOMER_PARTITION_BUYER_TOTAL_CONFLICT",
    "CUSTOMER_PARTITION_GLOBAL_TOTAL_CONFLICT", "CUSTOMER_CURRENCY_SCOPE_UNSUPPORTED",
    "CARD_CACHED_RESPONSE", "CARD_RESPONSE_DATE_UNCONFIRMED", "CARD_RESPONSE_DATE_OUTSIDE_CAPTURE",
    "CARD_CONTENT_TYPE_UNCONFIRMED", "CARD_CACHE_AGE_UNCONFIRMED", "SOURCE_CURRENT_CARD_MISMATCH"]) {
    assert.match(betaReason(reason), /[А-Яа-я]/);
    assert.equal(betaReason(reason).includes(reason), false);
  }
  const unknown = "FUTURE_UNVERIFIED_SOURCE_RULE";
  assert.match(betaReason(unknown), /Источник не подтвердил данные/);
  assert.equal(betaReason(unknown).includes(unknown), false);
});
