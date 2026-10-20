"use server";

import { revalidatePath } from "next/cache";

import {
  ApiError,
  ConfigurationError,
  decideReviewedRequirementSet,
  loadReviewedRequirementSetForReview,
  type RequirementSetCoverageAssessment,
  type RequirementSetNormalizationAssessment,
} from "@/lib/procurement-api";

export type RequirementSetReviewState = {
  error?: string;
  success?: string;
  decisionSha256?: string;
};

const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const COVERAGE = new Set<RequirementSetCoverageAssessment>(["CONFIRMED", "UNRESOLVED"]);
const NORMALIZATION = new Set<RequirementSetNormalizationAssessment>(["REVIEWED", "UNRESOLVED"]);
const STATUSES = new Set(["PASS", "FAIL", "UNKNOWN"] as const);
const FIELDS = new Set([
  "set-id",
  "proposal-sha256",
  "coverage-assessment",
  "normalization-assessment",
  "status",
  "reason",
]);

function one(form: FormData, name: string): string | null {
  const values = form.getAll(name);
  return values.length === 1 && typeof values[0] === "string" ? values[0] : null;
}

function failure(error: unknown): string {
  if (error instanceof ConfigurationError) {
    return "Не настроен отдельный server-only token reviewer deployment.";
  }
  if (error instanceof ApiError) {
    if (error.status === 403) return "Token не имеет роли COMPLETENESS_REVIEWER.";
    if (error.status === 404) return "Exact proposal не найден в текущем tenant.";
    if (error.status === 409) return "Proposal уже решён или его digest изменился. Обновите страницу.";
    if (error.status === 422) return "Решение нарушает requirement-set invariants.";
  }
  return "Решение не сохранено. Проверьте API и повторите запрос.";
}

export async function submitRequirementSetReview(
  _: RequirementSetReviewState,
  form: FormData,
): Promise<RequirementSetReviewState> {
  for (const [name, value] of form.entries()) {
    if (name.startsWith("$ACTION_")) continue;
    if (!FIELDS.has(name) || typeof value !== "string") {
      return { error: "Форма содержит недопустимое поле." };
    }
  }

  const setId = one(form, "set-id");
  const proposalSha256 = one(form, "proposal-sha256");
  const coverage = one(form, "coverage-assessment");
  const normalization = one(form, "normalization-assessment");
  const status = one(form, "status");
  const reason = one(form, "reason")?.trim() ?? "";
  if (
    !setId || !ID.test(setId) || !proposalSha256 || !SHA256.test(proposalSha256)
    || !coverage || !COVERAGE.has(coverage as RequirementSetCoverageAssessment)
    || !normalization || !NORMALIZATION.has(normalization as RequirementSetNormalizationAssessment)
    || !status || !STATUSES.has(status as "PASS" | "FAIL" | "UNKNOWN")
    || !reason || reason.length > 4_000
  ) {
    return { error: "Заполните exact proposal, оба assessment, статус и основание." };
  }
  if (status === "PASS" && (coverage !== "CONFIRMED" || normalization !== "REVIEWED")) {
    return { error: "PASS требует CONFIRMED coverage и REVIEWED normalization." };
  }

  try {
    const fresh = await loadReviewedRequirementSetForReview(setId);
    if (fresh.proposal.proposal_sha256 !== proposalSha256 || fresh.decision !== null) {
      return { error: "Proposal digest устарел или terminal decision уже сохранено. Обновите страницу." };
    }
    const decided = await decideReviewedRequirementSet(setId, {
      proposal_sha256: proposalSha256,
      coverage_assessment: coverage as RequirementSetCoverageAssessment,
      normalization_assessment: normalization as RequirementSetNormalizationAssessment,
      status: status as "PASS" | "FAIL" | "UNKNOWN",
      reason,
    });
    if (!decided.decision) return { error: "API не вернул terminal decision." };
    revalidatePath(`/requirement-set-review?set_id=${encodeURIComponent(setId)}`);
    return {
      success: `${decided.decision.status} сохранён для exact proposal.`,
      decisionSha256: decided.decision.decision_sha256,
    };
  } catch (error) {
    return { error: failure(error) };
  }
}
