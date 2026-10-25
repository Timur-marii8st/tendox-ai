import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { betaReportMatches, financialQuoteCurrent, type BetaQuoteReport } from "../src/lib/beta-procurement";

const saved = JSON.parse(readFileSync("tests/fixtures/beta-quote.json", "utf8")) as BetaQuoteReport;
const now = Date.parse("2026-10-21T00:00:00Z");
const deadline = "2026-10-23T00:00:00Z";

test("source-bound calculation remains current only inside both validity windows", () => {
  assert.equal(betaReportMatches(saved, saved.ref), true);
  assert.equal(financialQuoteCurrent(saved, deadline, false, now), true);
  assert.equal(financialQuoteCurrent(saved, deadline, false, Date.parse(deadline)), false);
  assert.equal(financialQuoteCurrent(saved, "2030-01-01T00:00:00Z", false, Date.parse(saved.input!.valid_until)), false);
});

test("a cached CALCULATED report cannot override a current source block", () => {
  assert.equal(financialQuoteCurrent(saved, deadline, true, now), false);
  assert.equal(saved.calculation!.status, "CALCULATED");
  assert.equal(financialQuoteCurrent(saved, null, false, now), false);
});

test("unknown and naive validity dates cannot become current financial results", () => {
  assert.equal(financialQuoteCurrent(saved, "2026-10-23T00:00:00", false, now), false);
  const report = structuredClone(saved);
  report.input!.valid_until = "2026-10-31T00:00:00";
  assert.equal(financialQuoteCurrent(report, deadline, false, now), false);
  assert.equal(financialQuoteCurrent(saved, deadline, false, Number.NaN), false);
});

test("not-yet-issued, incomplete or unknown quote calculations stay outside current results", () => {
  const report = structuredClone(saved);
  report.input!.issued_at = "2026-10-22T00:00:00Z";
  assert.equal(financialQuoteCurrent(report, deadline, false, now), false);
  report.input = saved.input;
  report.calculation!.status = "UNKNOWN";
  assert.equal(financialQuoteCurrent(report, deadline, false, now), false);
  report.calculation!.status = "CALCULATED";
  report.input = { ...saved.input!, covers_full_scope: false };
  assert.equal(financialQuoteCurrent(report, deadline, false, now), false);
});

test("different XML or version cannot reuse another procurement's quote report", () => {
  const other = structuredClone(saved.ref);
  other.notice.version_number++;
  assert.equal(betaReportMatches(saved, other), false);
  other.notice.version_number--;
  other.notice.notice_xml_sha256 = "f".repeat(64);
  assert.equal(betaReportMatches(saved, other), false);
});
