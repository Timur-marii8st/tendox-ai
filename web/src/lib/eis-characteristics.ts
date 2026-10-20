// Public wire contract. Domain matching remains in the Python service.
import { sameProtocolRef, validProtocolRef, type ProtocolNoticeRef } from "./eis-protocols";

export type PositionSelection = { notice: ProtocolNoticeRef; source_index: number };
export type CharacteristicPairRequest = { target: PositionSelection; candidate: PositionSelection };
export type SourceProvenance = {
  document_id: string; locator: string;
  extractor: "native_pdf" | "native_docx" | "native_xlsx" | "native_xls" |
    "legacy_doc_text" | "ocr" | "llm" | "api" | "manual";
  confidence: number;
};
export type TextFact = { value: string | null; raw: string | null; provenance: SourceProvenance };
export type DecimalFact = { value: string | null; raw: string | null; provenance: SourceProvenance };
export type CharacteristicNumberFact = DecimalFact & { raw_truncated: boolean };
export type CharacteristicValueEvidence = {
  description: TextFact; minimum: CharacteristicNumberFact; minimum_operator: TextFact;
  maximum: CharacteristicNumberFact; maximum_operator: TextFact; unit: TextFact;
  concrete_values: CharacteristicNumberFact[]; concrete_values_total: number;
  concrete_values_truncated: boolean;
  range_source_complete?: boolean;
};
export type CharacteristicEvidence = {
  name: TextFact; instruction_code: TextFact; values: CharacteristicValueEvidence[];
  values_total: number; truncated: boolean; review_status: "UNKNOWN";
};
export type PositionEvidence = {
  source_index: number; lot_index: number | null; lot_ordinal: TextFact | null;
  name: TextFact; quantity: DecimalFact; unit: TextFact; classification_code: TextFact;
  ktru_code: TextFact; unit_price: DecimalFact; line_sum: DecimalFact; currency: TextFact;
  characteristics: CharacteristicEvidence[]; characteristics_total: number;
  characteristics_truncated: boolean; characteristics_status: "SOURCE_VALUES" | "UNKNOWN";
  provenance: SourceProvenance; review_status: "UNKNOWN";
};
export type SavedPosition = {
  selection: PositionSelection; position: PositionEvidence;
  storage_kind: "SAVED_NOTICE_FIELDS" | "SAVED_PROJECTION"; legacy_values_unknown: boolean;
};
export type CharacteristicPairRow = {
  name: string; target_indices: number[]; candidate_indices: number[];
  target_values: CharacteristicValueEvidence[]; candidate_values: CharacteristicValueEvidence[];
  observation: "SAME" | "DIFFERENT" | "UNKNOWN"; reason: string;
  target_provenance: SourceProvenance; candidate_provenance: SourceProvenance;
};
export type CharacteristicPairReport = {
  request: CharacteristicPairRequest; checked_at: string;
  policy_version: "eis-characteristic-observation-v1" | "eis-characteristic-observation-v2";
  scope: "SELECTED_SAVED_POSITION_PAIR"; target: SavedPosition; candidate: SavedPosition;
  rows: CharacteristicPairRow[]; row_count: number; same_count: number;
  different_count: number; unknown_count: number; source_requests: 0;
  technical: "UNKNOWN"; delivery_region: "UNKNOWN"; comparability: "UNKNOWN";
  participation: "UNKNOWN"; profit: "UNKNOWN"; coverage: "UNKNOWN";
};
export type CharacteristicReadState = { result?: CharacteristicPairReport; error?: string };

const extractors = new Set(["native_pdf", "native_docx", "native_xlsx", "native_xls",
  "legacy_doc_text", "ocr", "llm", "api", "manual"]);
const observations = new Set(["SAME", "DIFFERENT", "UNKNOWN"]);
type CharacteristicPolicy = CharacteristicPairReport["policy_version"];
const record = (v: unknown): v is Record<string, unknown> =>
  !!v && typeof v === "object" && !Array.isArray(v);
const exact = (v: Record<string, unknown>, keys: readonly string[]) =>
  Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));
const integer = (v: unknown, min: number, max = Number.MAX_SAFE_INTEGER): v is number =>
  typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max;
const text = (v: unknown, max = 4096): v is string =>
  typeof v === "string" && [...v].length <= max;
const nullableText = (v: unknown, max = 4096): v is string | null => v === null || text(v, max);
const awareTime = (v: unknown): v is string => typeof v === "string" &&
  /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
const pythonWhitespace = /[\u0009-\u000d\u001c-\u001f\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/u;
const pythonWords = (value: string) => value.split(pythonWhitespace).filter(Boolean);
const coherent = (total: unknown, length: number, truncated: unknown) =>
  integer(total, 0) && typeof truncated === "boolean" && (truncated ? total > length : total === length);
const sameSelection = (a: PositionSelection, b: PositionSelection) =>
  a.source_index === b.source_index && sameProtocolRef(a.notice, b.notice);

export function validCharacteristicRequest(v: unknown): v is CharacteristicPairRequest {
  const selection = (item: unknown): item is PositionSelection => record(item) &&
    exact(item, ["notice", "source_index"]) && validProtocolRef(item.notice) &&
    integer(item.source_index, 1, 25);
  return record(v) && exact(v, ["target", "candidate"]) && selection(v.target) &&
    selection(v.candidate);
}

export function characteristicRequestKey(v: CharacteristicPairRequest): string {
  const key = (s: PositionSelection) => [s.notice.purchase_number, s.notice.version_number,
    s.notice.notice_xml_sha256, s.source_index];
  return JSON.stringify([key(v.target), key(v.candidate)]);
}

function provenance(v: unknown, sha: string): v is SourceProvenance {
  return record(v) && exact(v, ["document_id", "locator", "extractor", "confidence"]) &&
    v.document_id === sha && text(v.locator, 4096) && v.locator.length > 0 &&
    typeof v.extractor === "string" && extractors.has(v.extractor) &&
    typeof v.confidence === "number" && Number.isFinite(v.confidence) &&
    v.confidence >= 0 && v.confidence <= 1;
}

function decimalString(v: unknown): v is string {
  if (typeof v !== "string" || v.length > 64) return false;
  const match = /^([+-]?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d+))?$/.exec(v);
  if (!match) return false;
  const digits = `${match[2]}${match[3] ?? ""}`.replace(/^0+/, "") || "0";
  const exponent = Number(match[4] ?? 0) - (match[3]?.length ?? 0);
  const adjusted = exponent + digits.length - 1;
  return digits.length <= 30 && Number.isSafeInteger(exponent) && Math.abs(exponent) <= 12 &&
    Math.abs(adjusted) <= 12;
}

const factKeys = ["value", "raw", "provenance"] as const;
function sourceFact(v: unknown, sha: string, numeric = false): v is TextFact | DecimalFact {
  return record(v) && exact(v, factKeys) && nullableText(v.raw) && provenance(v.provenance, sha) &&
    (numeric ? v.value === null || decimalString(v.value) : nullableText(v.value));
}
function numberFact(v: unknown, sha: string): v is CharacteristicNumberFact {
  return record(v) && exact(v, [...factKeys, "raw_truncated"]) && sourceFact(
    { value: v.value, raw: v.raw, provenance: v.provenance }, sha, true,
  ) && typeof v.raw_truncated === "boolean" && nullableText(v.raw, 400);
}
function characteristicValue(
  v: unknown, sha: string, policy: CharacteristicPolicy,
): v is CharacteristicValueEvidence {
  const keys = ["description", "minimum", "minimum_operator", "maximum", "maximum_operator",
    "unit", "concrete_values", "concrete_values_total", "concrete_values_truncated"];
  if (!record(v)) return false;
  const hasRangeMarker = Object.hasOwn(v, "range_source_complete");
  const exactKeys = hasRangeMarker ? [...keys, "range_source_complete"] : keys;
  if (!exact(v, exactKeys) || (hasRangeMarker && typeof v.range_source_complete !== "boolean") ||
    (policy === "eis-characteristic-observation-v2" && !hasRangeMarker) ||
    (policy === "eis-characteristic-observation-v1" && v.range_source_complete === true) ||
    !sourceFact(v.description, sha) ||
    !numberFact(v.minimum, sha) || !sourceFact(v.minimum_operator, sha) ||
    !numberFact(v.maximum, sha) || !sourceFact(v.maximum_operator, sha) ||
    !sourceFact(v.unit, sha) || !Array.isArray(v.concrete_values) ||
    v.concrete_values.length > 8 || !v.concrete_values.every(x => numberFact(x, sha))) return false;
  return coherent(v.concrete_values_total, v.concrete_values.length, v.concrete_values_truncated);
}
function characteristic(
  v: unknown, sha: string, policy: CharacteristicPolicy,
): v is CharacteristicEvidence {
  const keys = ["name", "instruction_code", "values", "values_total", "truncated", "review_status"];
  if (!record(v) || !exact(v, keys) || !sourceFact(v.name, sha) ||
    !sourceFact(v.instruction_code, sha) || !Array.isArray(v.values) || v.values.length > 8 ||
    !v.values.every(x => characteristicValue(x, sha, policy)) ||
    v.review_status !== "UNKNOWN") return false;
  return coherent(v.values_total, v.values.length, v.truncated);
}
function position(
  v: unknown, selection: PositionSelection, policy: CharacteristicPolicy,
): v is PositionEvidence {
  const keys = ["source_index", "lot_index", "lot_ordinal", "name", "quantity", "unit",
    "classification_code", "ktru_code", "unit_price", "line_sum", "currency", "characteristics",
    "characteristics_total", "characteristics_truncated", "characteristics_status", "provenance",
    "review_status"];
  if (!record(v) || !exact(v, keys) || v.source_index !== selection.source_index ||
    !(v.lot_index === null || integer(v.lot_index, 1)) ||
    !(v.lot_ordinal === null || sourceFact(v.lot_ordinal, selection.notice.notice_xml_sha256)) ||
    !Array.isArray(v.characteristics) || v.characteristics.length > 24 ||
    !v.characteristics.every(x => characteristic(x, selection.notice.notice_xml_sha256, policy)) ||
    typeof v.characteristics_status !== "string" ||
    !["SOURCE_VALUES", "UNKNOWN"].includes(v.characteristics_status) ||
    v.review_status !== "UNKNOWN") return false;
  const sha = selection.notice.notice_xml_sha256;
  if (![v.name, v.unit, v.classification_code, v.ktru_code, v.currency]
    .every(x => sourceFact(x, sha)) || ![v.quantity, v.unit_price, v.line_sum]
    .every(x => sourceFact(x, sha, true)) || !provenance(v.provenance, sha)) return false;
  return coherent(v.characteristics_total, v.characteristics.length, v.characteristics_truncated);
}
function saved(
  v: unknown, selection: PositionSelection, policy: CharacteristicPolicy,
): v is SavedPosition {
  if (!record(v) || !exact(v, ["selection", "position", "storage_kind", "legacy_values_unknown"]) ||
    !validCharacteristicRequest({ target: v.selection, candidate: v.selection })) return false;
  const actual = v.selection as PositionSelection;
  return sameSelection(actual, selection) && position(v.position, actual, policy) &&
    typeof v.storage_kind === "string" &&
    ["SAVED_NOTICE_FIELDS", "SAVED_PROJECTION"].includes(v.storage_kind) &&
    typeof v.legacy_values_unknown === "boolean";
}
const jsonEqual = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

export function savedPositionMatches(v: unknown, selection: PositionSelection): v is SavedPosition {
  return saved(v, selection, "eis-characteristic-observation-v2");
}

function row(
  v: unknown, target: SavedPosition, candidate: SavedPosition, policy: CharacteristicPolicy,
): v is CharacteristicPairRow {
  const keys = ["name", "target_indices", "candidate_indices", "target_values", "candidate_values",
    "observation", "reason", "target_provenance", "candidate_provenance"];
  if (!record(v) || !exact(v, keys) || !text(v.name, 4096) || !text(v.reason, 4096) ||
    v.reason.length === 0 || typeof v.observation !== "string" || !observations.has(v.observation) ||
    !Array.isArray(v.target_indices) || !Array.isArray(v.candidate_indices) ||
    !Array.isArray(v.target_values) || !Array.isArray(v.candidate_values) ||
    v.target_values.length > 8 || v.candidate_values.length > 8) return false;
  const indices = (value: unknown[], max: number) => value.every(i => integer(i, 1, max)) &&
    new Set(value).size === value.length;
  if (!indices(v.target_indices, target.position.characteristics.length) ||
    !indices(v.candidate_indices, candidate.position.characteristics.length)) return false;
  if (!v.target_values.every(item => characteristicValue(
    item, target.selection.notice.notice_xml_sha256, policy,
  )) || !v.candidate_values.every(item => characteristicValue(
    item, candidate.selection.notice.notice_xml_sha256, policy,
  ))) return false;
  if (v.target_indices.length + v.candidate_indices.length === 0) return false;
  const indexedCharacteristics = [
    ...v.target_indices.map(i => target.position.characteristics[i - 1]),
    ...v.candidate_indices.map(i => candidate.position.characteristics[i - 1]),
  ];
  const sourceName = indexedCharacteristics.find(item =>
    item.name.value !== null && pythonWords(item.name.value).length > 0)?.name.value;
  const displayName = sourceName === null || sourceName === undefined ? "" :
    pythonWords(sourceName).join(" ");
  if (v.name !== displayName) return false;
  const expected = (savedPosition: SavedPosition, rawIndices: unknown[]) =>
    rawIndices.flatMap(i => savedPosition.position.characteristics[(i as number) - 1].values).slice(0, 8);
  if (!jsonEqual(v.target_values, expected(target, v.target_indices)) ||
    !jsonEqual(v.candidate_values, expected(candidate, v.candidate_indices))) return false;
  const expectedProvenance = (savedPosition: SavedPosition, rawIndices: unknown[]) => {
    if (!rawIndices.length) return savedPosition.position.provenance;
    const item = savedPosition.position.characteristics[(rawIndices[0] as number) - 1];
    return item.name.value ? item.name.provenance : savedPosition.position.provenance;
  };
  return provenance(v.target_provenance, target.selection.notice.notice_xml_sha256) &&
    provenance(v.candidate_provenance, candidate.selection.notice.notice_xml_sha256) &&
    jsonEqual(v.target_provenance, expectedProvenance(target, v.target_indices)) &&
    jsonEqual(v.candidate_provenance, expectedProvenance(candidate, v.candidate_indices)) &&
    (v.observation === "UNKNOWN" || (v.target_indices.length === 1 && v.candidate_indices.length === 1));
}

export function characteristicReportMatches(
  v: unknown, request: CharacteristicPairRequest,
): v is CharacteristicPairReport {
  const keys = ["request", "checked_at", "policy_version", "scope", "target", "candidate", "rows",
    "row_count", "same_count", "different_count", "unknown_count", "source_requests", "technical",
    "delivery_region", "comparability", "participation", "profit", "coverage"];
  if (!validCharacteristicRequest(request) || !record(v) || !exact(v, keys) ||
    !validCharacteristicRequest(v.request) ||
    characteristicRequestKey(v.request) !== characteristicRequestKey(request) || !awareTime(v.checked_at) ||
    typeof v.policy_version !== "string" ||
    !["eis-characteristic-observation-v1", "eis-characteristic-observation-v2"]
      .includes(v.policy_version) ||
    v.scope !== "SELECTED_SAVED_POSITION_PAIR" || v.source_requests !== 0 ||
    !["technical", "delivery_region", "comparability", "participation", "profit", "coverage"]
      .every(k => v[k] === "UNKNOWN") || !Array.isArray(v.rows) || v.rows.length > 48) return false;
  const policy = v.policy_version as CharacteristicPolicy;
  if (!saved(v.target, request.target, policy) || !saved(v.candidate, request.candidate, policy)) return false;
  const target = v.target as SavedPosition; const candidate = v.candidate as SavedPosition;
  if (!v.rows.every(item => row(item, target, candidate, policy))) return false;
  const rows = v.rows as CharacteristicPairRow[];
  const targetIndices = rows.flatMap(item => item.target_indices);
  const candidateIndices = rows.flatMap(item => item.candidate_indices);
  const complete = (indices: number[], count: number) => {
    const sorted = [...indices].sort((a, b) => a - b);
    return sorted.length === count && new Set(sorted).size === count &&
      sorted.every((item, index) => item === index + 1);
  };
  const count = (observation: CharacteristicPairRow["observation"]) =>
    rows.filter(item => item.observation === observation).length;
  return complete(targetIndices, target.position.characteristics.length) &&
    complete(candidateIndices, candidate.position.characteristics.length) &&
    v.row_count === rows.length && v.same_count === count("SAME") &&
    v.different_count === count("DIFFERENT") && v.unknown_count === count("UNKNOWN");
}

export function createCharacteristicReadSession() {
  let revision = 0;
  return {
    invalidate() { revision++; },
    async read(request: CharacteristicPairRequest,
      read: (request: CharacteristicPairRequest) => Promise<CharacteristicReadState>) {
      const current = ++revision;
      if (!validCharacteristicRequest(request)) return current === revision ?
        { error: "Выберите две сохранённые позиции 1–25." } : undefined;
      const snapshot = structuredClone(request);
      try {
        const response = await read(snapshot);
        const state = response.result && !characteristicReportMatches(response.result, snapshot) ?
          { error: "Ответ не соответствует выбранным позициям или сохранённым источникам." } :
          response.result ? response : { error: response.error ?? "Сравнение характеристик недоступно." };
        return current === revision ? state : undefined;
      } catch {
        return current === revision ? { error: "Не удалось прочитать сравнение характеристик." } : undefined;
      }
    },
  };
}
