"use server";

import {
  ApiError,
  ConfigurationError,
  createCaseFromEvidence,
} from "@/lib/procurement-api";

export type CaseFromEvidenceFormState = {
  error?: string;
  success?: string;
  caseId?: string;
  version?: number;
  documentStatus?: string;
};

const SHA256 = /^[0-9a-f]{64}$/;
const BINDING_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const SINGLETON_FIELDS = new Set([
  "binding-id",
  "manifest-evidence-sha256",
  "decision-sha256",
  "case-json",
  "other-checks",
]);
const MAX_CASE_JSON = 200_000;
const MAX_OTHER_CHECKS_JSON = 20_000;
const NON_DOCUMENT_KINDS = new Set([
  "legal",
  "participant",
  "technical",
  "company_policy",
  "logistics",
]);
const GATE_STATUSES = new Set(["PASS", "FAIL", "UNKNOWN"]);

export async function submitCaseFromEvidence(
  _: CaseFromEvidenceFormState,
  form: FormData,
): Promise<CaseFromEvidenceFormState> {
  const parsed = parse(form);
  if (!("payload" in parsed)) return parsed;

  try {
    const created = await createCaseFromEvidence(parsed.payload);
    const checks = created.assessment?.checks ?? [];
    const documentCheck = checks.find((check) => check.kind === "document");
    if (!documentCheck) {
      return { error: "API вернул кейс без server-derived DOCUMENT-проверки." };
    }
    return {
      success: "Кейс создан из exact привязки с server-derived DOCUMENT-проверкой.",
      caseId: created.case_id,
      version: created.version,
      documentStatus: documentCheck.status,
    };
  } catch (error) {
    return { error: safeError(error) };
  }
}

function parse(
  form: FormData,
):
  | { payload: Parameters<typeof createCaseFromEvidence>[0] }
  | CaseFromEvidenceFormState {
  const counts = new Map<string, number>();
  for (const [name, value] of form.entries()) {
    if (name.startsWith("$ACTION_")) continue;
    if (!SINGLETON_FIELDS.has(name) || typeof value !== "string") {
      return { error: "Форма содержит недопустимое поле." };
    }
    counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  if ([...SINGLETON_FIELDS].some((name) => name !== "other-checks" && counts.get(name) !== 1)) {
    return { error: "Заполните привязку и JSON драфта кейса ровно один раз." };
  }
  if ((counts.get("other-checks") ?? 0) > 1) {
    return { error: "Поле дополнительных проверок повторяется." };
  }
  const single = (name: string): string => String(form.get(name) ?? "");

  const bindingId = single("binding-id").trim();
  const manifestEvidence = single("manifest-evidence-sha256").trim();
  const decisionSha = single("decision-sha256").trim();
  if (!BINDING_ID.test(bindingId) || !SHA256.test(manifestEvidence) || !SHA256.test(decisionSha)) {
    return { error: "Binding ID или evidence digest некорректны." };
  }

  const caseJson = single("case-json");
  if (!caseJson.trim() || caseJson.length > MAX_CASE_JSON) {
    return { error: "JSON драфта кейса пуст или превышает 200 000 символов." };
  }
  let draft: unknown;
  try {
    draft = JSON.parse(caseJson) as unknown;
  } catch {
    return { error: "JSON драфта кейса не разбирается." };
  }
  if (typeof draft !== "object" || draft === null || Array.isArray(draft)) {
    return { error: "Драфт кейса должен быть JSON-объектом." };
  }
  if (Object.prototype.hasOwnProperty.call(draft, "assessment")) {
    return { error: "Assessment выводится сервером из привязки — уберите его из драфта." };
  }

  const otherChecksRaw = single("other-checks").trim();
  let otherChecks: unknown[] = [];
  if (otherChecksRaw) {
    if (otherChecksRaw.length > MAX_OTHER_CHECKS_JSON) {
      return { error: "JSON дополнительных проверок превышает 20 000 символов." };
    }
    try {
      otherChecks = JSON.parse(otherChecksRaw) as unknown[];
    } catch {
      return { error: "JSON дополнительных проверок не разбирается." };
    }
    if (!Array.isArray(otherChecks) || otherChecks.length > 5) {
      return { error: "Дополнительных проверок должно быть от 0 до 5 в массиве." };
    }
    for (const check of otherChecks) {
      if (
        typeof check !== "object" || check === null || Array.isArray(check)
        || !NON_DOCUMENT_KINDS.has(String((check as Record<string, unknown>).kind))
        || !GATE_STATUSES.has(String((check as Record<string, unknown>).status))
        || typeof (check as Record<string, unknown>).reason !== "string"
        || !(check as Record<string, unknown>).reason
        || !Array.isArray((check as Record<string, unknown>).evidence)
      ) {
        return { error: "Каждая проверка: kind кроме document, статус, основание и evidence-массив." };
      }
    }
  }

  return {
    payload: {
      case: draft,
      binding_id: bindingId,
      manifest_evidence_sha256: manifestEvidence,
      decision_sha256: decisionSha,
      other_checks: otherChecks,
    },
  };
}

function safeError(error: unknown): string {
  if (error instanceof ApiError) {
    return {
      401: "Не удалось подтвердить доступ оператора к API.",
      403: "Нужна роль OPERATOR в tenant кейса.",
      404: "Привязка недоступна в текущем tenant.",
      409: "Кейс с таким ID и версией уже существует.",
      413: "Запрос превышает лимит API.",
      422: "API отклонил связку: проверьте exact digest, драфт и проверки.",
    }[error.status] ?? "Сервис временно недоступен.";
  }
  if (error instanceof ConfigurationError) return "Server-only operator token не настроен.";
  return "Сервис временно недоступен.";
}
