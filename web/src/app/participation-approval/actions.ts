"use server";

import { revalidatePath } from "next/cache";

import {
  ApiError,
  ConfigurationError,
  decideParticipation,
  loadParticipationDecision,
  type ParticipationDecisionStatus,
} from "@/lib/procurement-api";

export type ParticipationApprovalState = {
  error?: string;
  success?: string;
  decisionSha256?: string;
};

const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const FIELDS = new Set(["evaluation-id", "evidence-sha256", "status", "reason"]);

function one(form: FormData, name: string): string | null {
  const values = form.getAll(name);
  return values.length === 1 && typeof values[0] === "string" ? values[0].trim() : null;
}

function failure(error: unknown): string {
  if (error instanceof ConfigurationError) {
    return "Не настроен отдельный server-only token согласующего участие.";
  }
  if (error instanceof ApiError) {
    if (error.status === 403) return "Token не имеет роли PARTICIPATION_APPROVER.";
    if (error.status === 404) return "Exact evaluation не найдена в текущем tenant.";
    if (error.status === 409) return "Terminal decision уже сохранено. Обновите страницу.";
    if (error.status === 422) return "Оценка устарела или exact evidence не прошло проверку.";
  }
  return "Решение не сохранено. Проверьте API и повторите запрос.";
}

export async function submitParticipationDecision(
  _: ParticipationApprovalState,
  form: FormData,
): Promise<ParticipationApprovalState> {
  for (const [name, value] of form.entries()) {
    if (name.startsWith("$ACTION_")) continue;
    if (!FIELDS.has(name) || typeof value !== "string" || form.getAll(name).length !== 1) {
      return { error: "Форма содержит неизвестное или повторяющееся поле." };
    }
  }
  if ([...FIELDS].some((name) => form.getAll(name).length !== 1)) {
    return { error: "Exact evaluation и решение заполнены не полностью." };
  }
  const evaluationId = one(form, "evaluation-id");
  const evidenceSha = one(form, "evidence-sha256");
  const status = one(form, "status");
  const reason = one(form, "reason") ?? "";
  if (
    !evaluationId || !ID.test(evaluationId) || !evidenceSha || !SHA256.test(evidenceSha)
    || (status !== "APPROVED" && status !== "REJECTED")
    || !reason || reason.length > 4_000
  ) {
    return { error: "Проверьте exact evaluation, решение и основание." };
  }

  try {
    const fresh = await loadParticipationDecision(evaluationId);
    if (
      fresh.decision !== null
      || fresh.evidence.evidence_sha256 !== evidenceSha
      || fresh.evidence.recommendation.decision !== "participate"
    ) {
      return { error: "Evaluation изменилась, уже решена или больше не допускает согласование." };
    }
    const decision = await decideParticipation(evaluationId, {
      evaluation_evidence_sha256: evidenceSha,
      status: status as ParticipationDecisionStatus,
      reason,
    });
    revalidatePath(`/participation-approval?evaluation_id=${encodeURIComponent(evaluationId)}`);
    return {
      success: `${decision.status} сохранено. Внешнее действие не разрешено.`,
      decisionSha256: decision.decision_sha256,
    };
  } catch (error) {
    return { error: failure(error) };
  }
}
