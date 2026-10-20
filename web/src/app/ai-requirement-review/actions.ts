"use server";

import { revalidatePath } from "next/cache";

import {
  ApiError,
  ConfigurationError,
  decideAiRequirementReview,
  type AiCandidateDecision,
} from "@/lib/procurement-api";

export type AiReviewFormState = { error?: string; success?: string };

const SHA256 = /^[0-9a-f]{64}$/;
const RUN_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const FIELD =
  /^candidate-(REQUIREMENT|PROCUREMENT_ITEM)-(ai-(?:req|item)-[0-9a-f]{16})-(disposition|reason)$/;
const DISPOSITIONS = new Set<AiCandidateDecision["disposition"]>([
  "ACCEPTED",
  "REJECTED",
  "NEEDS_CLARIFICATION",
]);

export async function submitAiRequirementReview(
  _: AiReviewFormState,
  form: FormData,
): Promise<AiReviewFormState> {
  const runId = single(form, "run-id");
  const digest = single(form, "evidence-sha256");
  const candidateCountText = single(form, "candidate-count");
  const candidateCount = candidateCountText === null ? Number.NaN : Number(candidateCountText);
  if (
    !runId ||
    !RUN_ID.test(runId) ||
    !digest ||
    !SHA256.test(digest) ||
    !Number.isSafeInteger(candidateCount) ||
    candidateCount < 0 ||
    candidateCount > 10_000
  ) {
    return { error: "Идентификатор запуска, evidence digest или число кандидатов некорректны." };
  }

  const grouped = new Map<string, Partial<AiCandidateDecision>>();
  const seenFields = new Set<string>();
  for (const [name, value] of form.entries()) {
    if (["run-id", "evidence-sha256", "candidate-count"].includes(name) || name.startsWith("$ACTION_")) {
      continue;
    }
    const match = FIELD.exec(name);
    if (!match || typeof value !== "string" || seenFields.has(name)) {
      return { error: "Форма содержит недопустимое или повторяющееся поле." };
    }
    seenFields.add(name);
    const key = `${match[1]}:${match[2]}`;
    const current = grouped.get(key) ?? {
      candidate_kind: match[1] as AiCandidateDecision["candidate_kind"],
      candidate_id: match[2],
    };
    if (match[3] === "disposition") {
      current.disposition = value as AiCandidateDecision["disposition"];
    } else {
      current.reason = value;
    }
    grouped.set(key, current);
  }
  if (grouped.size !== candidateCount) {
    return { error: "Нужны решения по точному набору кандидатов этого запуска." };
  }

  const decisions: AiCandidateDecision[] = [];
  for (const candidate of grouped.values()) {
    const reason = candidate.reason?.trim();
    if (
      !candidate.candidate_kind ||
      !candidate.candidate_id ||
      !candidate.disposition ||
      !DISPOSITIONS.has(candidate.disposition) ||
      !reason ||
      reason.length > 4_000
    ) {
      return { error: "Для каждого кандидата выберите disposition и укажите основание." };
    }
    decisions.push({
      candidate_kind: candidate.candidate_kind,
      candidate_id: candidate.candidate_id,
      disposition: candidate.disposition,
      reason,
    });
  }

  try {
    await decideAiRequirementReview(runId, {
      evidence_sha256: digest,
      candidate_decisions: decisions,
    });
    revalidatePath("/ai-requirement-review");
    return { success: "Терминальная проверка сохранена. Полнота остаётся UNKNOWN." };
  } catch (error) {
    if (error instanceof ApiError) {
      const message = {
        403: "Нужна роль AI_REQUIREMENTS_REVIEWER.",
        404: "Запуск недоступен в текущем tenant.",
        409: "Evidence устарел, проверка уже завершена или конфликтует с replay.",
        422: "API отклонил проверку точного набора evidence.",
      }[error.status];
      return { error: message ?? "Сервис временно недоступен." };
    }
    return {
      error:
        error instanceof ConfigurationError
          ? "Reviewer API token не настроен на сервере."
          : "Сервис временно недоступен.",
    };
  }
}

function single(form: FormData, name: string): string | null {
  const values = form.getAll(name);
  return values.length === 1 && typeof values[0] === "string" ? values[0] : null;
}
