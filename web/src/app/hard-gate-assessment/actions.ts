"use server";

import { revalidatePath } from "next/cache";

import {
  ApiError,
  ConfigurationError,
  loadCaseHardGateAssessmentEvidence,
  materializeCaseHardGateAssessment,
  type CaseHardGateDecisionInput,
  type HardGateKind,
} from "@/lib/procurement-api";

export type HardGateState = { error?: string; success?: string; nextVersion?: number };
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const SHA = /^[0-9a-f]{64}$/;
const KINDS: HardGateKind[] = ["legal", "participant", "company_policy", "logistics"];
const SUFFIXES = ["status", "reason", "document-id", "document-sha256", "locator"] as const;

function one(form: FormData, name: string): string | null {
  const values = form.getAll(name);
  return values.length === 1 && typeof values[0] === "string" ? values[0].trim() : null;
}

function failure(error: unknown): string {
  if (error instanceof ConfigurationError) return "Operator API не настроен.";
  if (error instanceof ApiError) {
    if (error.status === 403) return "Требуется роль OPERATOR.";
    if (error.status === 404) return "Case или evidence document не найден.";
    if (error.status === 409) return "Следующая версия кейса уже существует.";
    if (error.status === 422) return "Source lineage или hard-gate evidence не прошли проверку.";
  }
  return "Hard-gate assessment не сохранён.";
}

export async function submitHardGates(
  _: HardGateState,
  form: FormData,
): Promise<HardGateState> {
  const singleton = new Set([
    "case-id", "case-version", "source-case-sha256", "document-binding-id",
    "manifest-evidence-sha256", "document-decision-sha256",
  ]);
  for (const kind of KINDS) for (const suffix of SUFFIXES) singleton.add(`${kind}-${suffix}`);
  const counts = new Map<string, number>();
  for (const [name, value] of form.entries()) {
    if (name.startsWith("$ACTION_")) continue;
    if (!singleton.has(name) || typeof value !== "string") return { error: "Форма содержит неизвестное поле." };
    counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  if ([...singleton].some((name) => counts.get(name) !== 1)) return { error: "Заполните каждое поле ровно один раз." };
  const caseId = one(form, "case-id"); const versionText = one(form, "case-version");
  const sourceSha = one(form, "source-case-sha256");
  const documentBindingId = one(form, "document-binding-id");
  const manifestSha = one(form, "manifest-evidence-sha256");
  const documentDecisionSha = one(form, "document-decision-sha256");
  const version = versionText && /^\d+$/.test(versionText) ? Number(versionText) : 0;
  if (!caseId || !ID.test(caseId) || version < 1 || !sourceSha || !SHA.test(sourceSha)
    || !documentBindingId || !ID.test(documentBindingId) || !manifestSha || !SHA.test(manifestSha)
    || !documentDecisionSha || !SHA.test(documentDecisionSha)) {
    return { error: "Exact case identity недействительна." };
  }
  const decisions: CaseHardGateDecisionInput[] = [];
  for (const kind of KINDS) {
    const status = one(form, `${kind}-status`);
    const reason = one(form, `${kind}-reason`);
    const documentId = one(form, `${kind}-document-id`) ?? "";
    const documentSha = one(form, `${kind}-document-sha256`) ?? "";
    const locator = one(form, `${kind}-locator`) ?? "";
    if (!status || !["PASS", "FAIL", "UNKNOWN"].includes(status) || !reason || reason.length > 4_000) {
      return { error: `Заполните status и основание для ${kind}.` };
    }
    const hasAnyEvidence = Boolean(documentId || documentSha || locator);
    const evidenceRequired = status !== "UNKNOWN";
    if ((hasAnyEvidence || evidenceRequired) && (!ID.test(documentId) || !SHA.test(documentSha) || !locator || locator.length > 1_000)) {
      return { error: `Для ${kind} укажите полный exact document ID, SHA-256 и locator.` };
    }
    decisions.push({
      kind,
      status: status as "PASS" | "FAIL" | "UNKNOWN",
      reason,
      evidence: hasAnyEvidence ? [{ document_id: documentId, document_sha256: documentSha, locator }] : [],
    });
  }
  try {
    const fresh = await loadCaseHardGateAssessmentEvidence(caseId, version);
    if (fresh.source_case_input_sha256 !== sourceSha) return { error: "Case snapshot изменился." };
    const result = await materializeCaseHardGateAssessment(caseId, version, {
      source_case_input_sha256: sourceSha,
      document_binding_id: documentBindingId,
      manifest_evidence_sha256: manifestSha,
      document_decision_sha256: documentDecisionSha,
      decisions,
    });
    revalidatePath("/");
    return {
      success: `Создан case ${result.case_id} v${result.version} с шестью hard gates. Рекомендация ещё не запускалась.`,
      nextVersion: result.version,
    };
  } catch (error) { return { error: failure(error) }; }
}
