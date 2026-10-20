import assert from "node:assert/strict";
import test from "node:test";

import {
  characteristicReportMatches, characteristicRequestKey, createCharacteristicReadSession,
  validCharacteristicRequest, type CharacteristicPairReport, type CharacteristicPairRequest,
  type CharacteristicReadState, type CharacteristicValueEvidence, type SourceProvenance,
} from "../src/lib/eis-characteristics";

const SHA_A = "a".repeat(64); const SHA_B = "b".repeat(64);
const ref = (sha: string) => ({ purchase_number: "0".repeat(19), version_number: 1,
  notice_xml_sha256: sha });
const request: CharacteristicPairRequest = {
  target: { notice: ref(SHA_A), source_index: 1 },
  candidate: { notice: ref(SHA_B), source_index: 2 },
};
const prov = (sha: string, locator = "notice.xml :: item[1]"): SourceProvenance =>
  ({ document_id: sha, locator, extractor: "api", confidence: 1 });
const textFact = (sha: string, value: string | null) =>
  ({ value, raw: value, provenance: prov(sha) });
const numberFact = (sha: string, value: string | null, raw = value) =>
  ({ value, raw, raw_truncated: false, provenance: prov(sha) });
const rangeValue = (sha: string): CharacteristicValueEvidence => ({
  description: textFact(sha, null), minimum: numberFact(sha, "10"),
  minimum_operator: textFact(sha, "greaterOrEqual"), maximum: numberFact(sha, null),
  maximum_operator: textFact(sha, null), unit: textFact(sha, "шт"), concrete_values: [],
  concrete_values_total: 0, concrete_values_truncated: false,
});
const saved = (sha: string, sourceIndex: number) => {
  const unknownText = textFact(sha, null); const unknownNumber = { value: null, raw: null, provenance: prov(sha) };
  const characteristic = { name: textFact(sha, "Размер"), instruction_code: textFact(sha, "2"),
    values: [rangeValue(sha)], values_total: 1, truncated: false, review_status: "UNKNOWN" as const };
  return {
    selection: { notice: ref(sha), source_index: sourceIndex },
    position: { source_index: sourceIndex, lot_index: null, lot_ordinal: null,
      name: textFact(sha, "Товар"), quantity: unknownNumber, unit: unknownText,
      classification_code: unknownText, ktru_code: textFact(sha, "17.12.14.110-00000001"),
      unit_price: unknownNumber, line_sum: unknownNumber, currency: unknownText,
      characteristics: [characteristic], characteristics_total: 1, characteristics_truncated: false,
      characteristics_status: "SOURCE_VALUES" as const, provenance: prov(sha), review_status: "UNKNOWN" as const },
    storage_kind: "SAVED_PROJECTION" as const, legacy_values_unknown: false,
  };
};
function report(): CharacteristicPairReport {
  const target = saved(SHA_A, 1); const candidate = saved(SHA_B, 2);
  return {
    request: structuredClone(request), checked_at: "2026-10-06T10:00:00+03:00",
    policy_version: "eis-characteristic-observation-v1", scope: "SELECTED_SAVED_POSITION_PAIR",
    target, candidate, rows: [{ name: "Размер", target_indices: [1], candidate_indices: [1],
      target_values: target.position.characteristics[0].values,
      candidate_values: candidate.position.characteristics[0].values, observation: "UNKNOWN",
      reason: "UNSUPPORTED_OR_INCOMPLETE_VALUE_SHAPE", target_provenance: target.position.characteristics[0].name.provenance,
      candidate_provenance: candidate.position.characteristics[0].name.provenance }],
    row_count: 1, same_count: 0, different_count: 0, unknown_count: 1, source_requests: 0,
    technical: "UNKNOWN", delivery_region: "UNKNOWN", comparability: "UNKNOWN",
    participation: "UNKNOWN", profit: "UNKNOWN", coverage: "UNKNOWN",
  };
}

function addRangeMarkers(value: CharacteristicPairReport, marker: boolean): void {
  for (const savedPosition of [value.target, value.candidate]) {
    for (const characteristic of savedPosition.position.characteristics) {
      for (const sourceValue of characteristic.values) sourceValue.range_source_complete = marker;
    }
  }
  for (const row of value.rows) {
    for (const sourceValue of [...row.target_values, ...row.candidate_values]) {
      sourceValue.range_source_complete = marker;
    }
  }
}

test("strict request rejects tenant, invalid index, and key binds both exact refs", () => {
  assert.equal(validCharacteristicRequest(request), true);
  assert.notEqual(characteristicRequestKey(request), characteristicRequestKey({ ...request,
    candidate: { ...request.candidate, source_index: 3 } }));
  assert.equal(validCharacteristicRequest({ ...request, company_id: "tenant" }), false);
  assert.equal(validCharacteristicRequest({ ...request, target: { ...request.target, source_index: 0 } }), false);
});

test("accepts exact unknown range report and rejects request/count/verdict binding", () => {
  assert.equal(characteristicReportMatches(report(), request), true);
  const wrongRequest = report(); wrongRequest.request.target.source_index = 2;
  assert.equal(characteristicReportMatches(wrongRequest, request), false);
  const wrongCount = report(); wrongCount.same_count = 1;
  assert.equal(characteristicReportMatches(wrongCount, request), false);
  const wrongVerdict = report(); wrongVerdict.rows[0].observation = "SAME"; wrongVerdict.same_count = 1;
  wrongVerdict.unknown_count = 0; wrongVerdict.rows[0].candidate_indices = [];
  wrongVerdict.rows[0].candidate_values = [];
  assert.equal(characteristicReportMatches(wrongVerdict, request), false);
});

test("dual policy requires strict range completeness markers", () => {
  const legacyMissing = report();
  assert.equal(characteristicReportMatches(legacyMissing, request), true);
  const legacyFalse = report(); addRangeMarkers(legacyFalse, false);
  assert.equal(characteristicReportMatches(legacyFalse, request), true);
  const legacyTrue = report(); addRangeMarkers(legacyTrue, true);
  assert.equal(characteristicReportMatches(legacyTrue, request), false);

  const v2Missing = report(); v2Missing.policy_version = "eis-characteristic-observation-v2";
  assert.equal(characteristicReportMatches(v2Missing, request), false);
  const v2Complete = report(); v2Complete.policy_version = "eis-characteristic-observation-v2";
  addRangeMarkers(v2Complete, true);
  assert.equal(characteristicReportMatches(v2Complete, request), true);
  assert.equal(v2Complete.technical, "UNKNOWN");
  assert.equal(v2Complete.rows[0].observation, "UNKNOWN");
});

test("range completeness marker rejects coercible values in sources and rows", () => {
  for (const malformed of [1, "true", [true]]) {
    const source = report(); source.policy_version = "eis-characteristic-observation-v2";
    addRangeMarkers(source, false);
    Object.assign(source.target.position.characteristics[0].values[0],
      { range_source_complete: malformed });
    assert.doesNotThrow(() => characteristicReportMatches(source, request));
    assert.equal(characteristicReportMatches(source, request), false);

    const row = report(); row.policy_version = "eis-characteristic-observation-v2";
    addRangeMarkers(row, false);
    Object.assign(row.rows[0].candidate_values[0], { range_source_complete: malformed });
    assert.doesNotThrow(() => characteristicReportMatches(row, request));
    assert.equal(characteristicReportMatches(row, request), false);
  }
});

test("candidate characteristic indices may be covered in source-independent row order", () => {
  const value = report();
  const extra = structuredClone(value.candidate.position.characteristics[0]);
  extra.name.value = "Материал"; extra.name.raw = "Материал";
  value.candidate.position.characteristics.unshift(extra);
  value.candidate.position.characteristics_total = 2;
  value.rows[0].candidate_indices = [2];
  value.rows.push({ ...structuredClone(value.rows[0]), name: "Материал", target_indices: [],
    target_values: [], candidate_indices: [1], candidate_values: extra.values,
    target_provenance: value.target.position.provenance, candidate_provenance: extra.name.provenance });
  value.row_count = 2; value.unknown_count = 2;
  assert.equal(characteristicReportMatches(value, request), true);
});

test("rows bind display names and cannot invent an index-free characteristic", () => {
  const unrelated = report(); unrelated.rows[0].name = "Несвязанное имя";
  assert.equal(characteristicReportMatches(unrelated, request), false);

  const empty = report(); empty.rows.push({ ...structuredClone(empty.rows[0]), name: "",
    target_indices: [], candidate_indices: [], target_values: [], candidate_values: [],
    target_provenance: empty.target.position.provenance,
    candidate_provenance: empty.candidate.position.provenance });
  empty.row_count = 2; empty.unknown_count = 2;
  assert.equal(characteristicReportMatches(empty, request), false);

  const blank = report();
  for (const characteristic of [blank.target.position.characteristics[0],
    blank.candidate.position.characteristics[0]]) {
    characteristic.name.value = "   "; characteristic.name.raw = "   ";
  }
  blank.rows[0].name = "";
  assert.equal(characteristicReportMatches(blank, request), true);
});

test("display binding follows Python whitespace for U+0085 and U+FEFF", () => {
  const nextLine = report();
  nextLine.target.position.characteristics[0].name.value = " Размер\u0085пачки ";
  nextLine.target.position.characteristics[0].name.raw = " Размер\u0085пачки ";
  nextLine.rows[0].name = "Размер пачки";
  assert.equal(characteristicReportMatches(nextLine, request), true);

  const byteOrderMark = report();
  byteOrderMark.target.position.characteristics[0].name.value = " \uFEFF ";
  byteOrderMark.target.position.characteristics[0].name.raw = " \uFEFF ";
  byteOrderMark.rows[0].name = "\uFEFF";
  assert.equal(characteristicReportMatches(byteOrderMark, request), true);
});

test("rejects provenance, numeric wire, truncation, index, duplicate row and extra fields", () => {
  const mutations: Array<(value: CharacteristicPairReport) => void> = [
    v => {
      // @ts-expect-error Deliberately malformed wire value.
      v.target.position.quantity.value = 1.5;
    },
    v => {
      // @ts-expect-error Deliberately malformed wire value.
      v.target.position.quantity.value = true;
    },
    v => { v.target.position.quantity.value = "1e13"; },
    v => { v.rows[0].target_provenance.document_id = SHA_B; },
    v => { v.target.position.characteristics_total = 2; },
    v => { v.target.position.characteristics_truncated = true; },
    v => { v.rows[0].target_indices = [2]; },
    v => { v.rows.push(structuredClone(v.rows[0])); v.row_count = 2; v.unknown_count = 2; },
    v => { Object.assign(v.target.position, { tenant_id: "forbidden" }); },
  ];
  for (const mutate of mutations) {
    const value = report(); mutate(value);
    assert.equal(characteristicReportMatches(value, request), false);
  }
});

test("enum boundaries reject objects without coercion or exceptions", () => {
  const values: object[] = [
    { toString: () => "SOURCE_VALUES" },
    { claimed: "SOURCE_VALUES" },
    ["SOURCE_VALUES"],
  ];
  for (const malformed of values) {
    const status = report();
    Object.assign(status.target.position, { characteristics_status: malformed });
    assert.doesNotThrow(() => characteristicReportMatches(status, request));
    assert.equal(characteristicReportMatches(status, request), false);

    const storage = report();
    Object.assign(storage.target, { storage_kind: malformed });
    assert.doesNotThrow(() => characteristicReportMatches(storage, request));
    assert.equal(characteristicReportMatches(storage, request), false);
  }
  const storageArray = report();
  Object.assign(storageArray.target, { storage_kind: ["SAVED_PROJECTION"] });
  assert.doesNotThrow(() => characteristicReportMatches(storageArray, request));
  assert.equal(characteristicReportMatches(storageArray, request), false);
});

test("session drops stale replies and rejects a wrong bound report", async () => {
  const session = createCharacteristicReadSession();
  let resolve!: (state: CharacteristicReadState) => void;
  const pending = session.read(request, () => new Promise(r => { resolve = r; }));
  session.invalidate(); resolve({ result: report() });
  assert.equal(await pending, undefined);

  const changed = structuredClone(report()); changed.request.candidate.source_index = 3;
  const state = await session.read(request, async () => ({ result: changed }));
  assert.match(state?.error ?? "", /не соответствует/);
});
