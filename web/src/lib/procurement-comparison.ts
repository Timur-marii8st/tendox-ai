export type Status = "PASS" | "FAIL" | "UNKNOWN";
export type ProfileRef = { version: number; snapshot_sha256: string };
export type CaseRef = { case_id: string; version: number; input_sha256: string };
export type CompareCommand = { profile_ref: ProfileRef; case_refs: CaseRef[]; selection_id?: string };
export type Source = { document_id: string; locator: string; extractor: string; confidence: number };
export type ProfileSource = { company_id?: string | null; provenance: Source; kind: string; source_sha256: string;
  recorded_at: string; recorded_by: string; source_url: string | null };
export type Check = { check_id: string; label: string; mandatory: boolean; status: Status;
  reason_code: string; reason: string; profile_field_paths: string[];
  profile_sources: ProfileSource[]; case_sources: Source[]; missing: string[] };
export type Scenario = { kind: "base" | "realistic" | "conservative"; revenue_ex_vat: string;
  costs_ex_vat: string; profit_ex_vat: string; nds_rate: string; taxes: string;
  assumptions: string[]; sources: Source[] };
export type ComparisonReport = { schema_version: "selected-company-comparison-v1";
  company_id: string; comparison_id: string; profile_ref: ProfileRef; compared_at: string;
  comparison_policy_version: string; input_sha256: string; profile_name: string;
  profile_created_at: string; persistence: "LOCAL_DEMO_EPHEMERAL" | "EPHEMERAL"; audit_event_id: null;
  rows: { case_ref: CaseRef; case_snapshot_sha256: string; subject: string; deadline: string;
    nmck_ex_vat: string; overall_status: Status; checks: Check[]; economics: Scenario[] }[] };
export type ComparisonCatalog = { mode: "LOCAL_DEMO_SYNTHETIC" | "SAVED_CASES"; selection_id?: string; next_cursor?: string | null; company_id: string;
  compared_at: string; profiles: { ref: ProfileRef; name: string; created_at: string }[];
  cases: { ref: CaseRef; subject: string; nmck_ex_vat: string; deadline: string }[] };

const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === "string" && v.trim().length > 0;
const hash = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every(text);
const amount = (v: unknown): v is string => typeof v === "string" && /^-?\d+(\.\d+)?$/.test(v);
const aware = (v: unknown): v is string => text(v) && /(Z|[+-]\d\d:\d\d)$/.test(v) && Number.isFinite(Date.parse(v));
const status = (v: unknown): v is Status => v === "PASS" || v === "FAIL" || v === "UNKNOWN";
const version = (v: unknown): v is number => Number.isSafeInteger(v) && (v as number) > 0;
const source = (v: unknown): v is Source => object(v) && text(v.document_id) && text(v.locator) &&
  text(v.extractor) && typeof v.confidence === "number" && v.confidence >= 0 && v.confidence <= 1;
const profileRef = (v: unknown): v is ProfileRef => object(v) && version(v.version) && hash(v.snapshot_sha256);
const caseRef = (v: unknown): v is CaseRef => object(v) && text(v.case_id) && version(v.version) && hash(v.input_sha256);
export const sameProfile = (a: ProfileRef, b: ProfileRef) => a.version === b.version && a.snapshot_sha256 === b.snapshot_sha256;
export const sameCase = (a: CaseRef, b: CaseRef) => a.case_id === b.case_id && a.version === b.version && a.input_sha256 === b.input_sha256;

export function commandValid(value: unknown): value is CompareCommand {
  return object(value) && profileRef(value.profile_ref) && Array.isArray(value.case_refs) &&
    value.case_refs.length >= 2 && value.case_refs.length <= 5 && value.case_refs.every(caseRef) &&
    new Set(value.case_refs.map(ref => ref.case_id)).size === value.case_refs.length;
}

export function catalogValid(value: unknown): value is ComparisonCatalog {
  return object(value) && (value.mode === "LOCAL_DEMO_SYNTHETIC" || value.mode === "SAVED_CASES" && text(value.selection_id)) && text(value.company_id) &&
    aware(value.compared_at) && Array.isArray(value.profiles) && value.profiles.every(p => object(p) &&
      profileRef(p.ref) && text(p.name) && aware(p.created_at)) && Array.isArray(value.cases) &&
    value.cases.every(c => object(c) && caseRef(c.ref) && text(c.subject) && amount(c.nmck_ex_vat) && aware(c.deadline));
}

function checkValid(value: unknown): value is Check {
  return object(value) && text(value.check_id) && text(value.label) && typeof value.mandatory === "boolean" &&
    status(value.status) && text(value.reason_code) && text(value.reason) && strings(value.profile_field_paths) &&
    Array.isArray(value.profile_sources) && value.profile_sources.every(p => object(p) && source(p.provenance) &&
      text(p.kind) && hash(p.source_sha256) && aware(p.recorded_at) && text(p.recorded_by) &&
      (p.source_url === null || text(p.source_url))) && Array.isArray(value.case_sources) && value.case_sources.every(source) &&
    strings(value.missing) && (value.status !== "UNKNOWN" || value.missing.length > 0) &&
    (value.status === "UNKNOWN" || value.case_sources.length + value.profile_sources.length > 0);
}

function scenarioValid(value: unknown): value is Scenario {
  return object(value) && ["base", "realistic", "conservative"].includes(value.kind as string) &&
    [value.revenue_ex_vat, value.costs_ex_vat, value.profit_ex_vat, value.nds_rate, value.taxes].every(amount) &&
    strings(value.assumptions) && value.assumptions.length > 0 && Array.isArray(value.sources) &&
    value.sources.length > 0 && value.sources.every(source);
}

export function reportMatches(value: unknown, command: CompareCommand, companyId: string): value is ComparisonReport {
  if (!object(value) || value.schema_version !== "selected-company-comparison-v1" || value.company_id !== companyId ||
      !text(value.comparison_id) || !profileRef(value.profile_ref) || !sameProfile(value.profile_ref, command.profile_ref) ||
      !aware(value.compared_at) || !text(value.comparison_policy_version) || !hash(value.input_sha256) ||
      !text(value.profile_name) || !aware(value.profile_created_at) || !["LOCAL_DEMO_EPHEMERAL", "EPHEMERAL"].includes(value.persistence as string) ||
      value.audit_event_id !== null || !Array.isArray(value.rows) || value.rows.length !== command.case_refs.length) return false;
  return value.rows.every((row, index) => {
    if (!object(row) || !caseRef(row.case_ref) || !sameCase(row.case_ref, command.case_refs[index]) ||
        !hash(row.case_snapshot_sha256) || !text(row.subject) || !aware(row.deadline) || !amount(row.nmck_ex_vat) ||
        !status(row.overall_status) || !Array.isArray(row.checks) || row.checks.length === 0 || !row.checks.every(checkValid) ||
        !Array.isArray(row.economics) || !row.economics.every(scenarioValid)) return false;
    if (value.persistence === "EPHEMERAL" && row.checks.some(c => c.profile_sources.some(p => p.company_id !== companyId))) return false;
    const expected: Status = row.checks.some(c => c.mandatory && c.status === "FAIL") ? "FAIL" :
      row.checks.some(c => c.mandatory && c.status === "UNKNOWN") ? "UNKNOWN" : "PASS";
    return row.overall_status === expected && new Set(row.checks.map(c => c.check_id)).size === row.checks.length &&
      (row.economics.length === 0 || row.economics.length === 3 && new Set(row.economics.map(s => s.kind)).size === 3);
  });
}

// Деньги остаются строками: без Number, float и валютного округления в UI.
export function rub(value: string): string {
  if (!amount(value)) return "UNKNOWN";
  const [integer, fraction] = value.split(".");
  return integer.replace(/\B(?=(\d{3})+(?!\d))/g, "\u00a0") + (fraction ? "," + fraction : "") + " ₽";
}
