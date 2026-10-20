"use server";

import {
  ApiError,
  ConfigurationError,
  bindReviewedRequirementSet,
  loadReviewedRequirementSet,
} from "@/lib/procurement-api";

export type RequirementSetBindingState = {
  error?: string;
  success?: string;
  bindingId?: string;
  bindingSha256?: string;
  caseId?: string;
  caseVersion?: number;
};

const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const FIELDS = new Set(["case-id", "case-version", "set-id", "proposal-sha256", "decision-sha256"]);

function one(form: FormData, name: string): string | null {
  const values = form.getAll(name);
  return values.length === 1 && typeof values[0] === "string" ? values[0] : null;
}

function failure(error: unknown): string {
  if (error instanceof ConfigurationError) return "Серверный доступ к API не настроен.";
  if (error instanceof ApiError) {
    if (error.status === 403) return "Для привязки требуется роль OPERATOR.";
    if (error.status === 404) return "Кейс, версия или exact requirement set не найдены в текущем tenant.";
    if (error.status === 409) return "Для этой версии кейса уже есть binding или exact digests устарели.";
    if (error.status === 422) return "Binding нарушает requirement-set invariants.";
  }
  return "Binding не создан. Проверьте API и повторите запрос.";
}

export async function submitRequirementSetBinding(
  _: RequirementSetBindingState,
  form: FormData,
): Promise<RequirementSetBindingState> {
  for (const [name, value] of form.entries()) {
    if (name.startsWith("$ACTION_")) continue;
    if (!FIELDS.has(name) || typeof value !== "string") return { error: "Форма содержит недопустимое поле." };
  }
  const caseId = one(form, "case-id")?.trim() ?? "";
  const rawVersion = one(form, "case-version");
  const setId = one(form, "set-id");
  const proposalSha256 = one(form, "proposal-sha256");
  const decisionSha256 = one(form, "decision-sha256");
  if (
    !ID.test(caseId) || !rawVersion || !/^\d{1,9}$/.test(rawVersion) || Number(rawVersion) < 1
    || !setId || !ID.test(setId) || !proposalSha256 || !SHA256.test(proposalSha256)
    || !decisionSha256 || !SHA256.test(decisionSha256)
  ) {
    return { error: "Проверьте case ID, версию и exact requirement-set digests." };
  }

  try {
    const fresh = await loadReviewedRequirementSet(setId);
    if (
      fresh.proposal.proposal_sha256 !== proposalSha256
      || fresh.decision?.decision_sha256 !== decisionSha256
      || fresh.decision.status !== "PASS"
    ) {
      return { error: "Привязка разрешена только к свежему exact terminal PASS." };
    }
    const binding = await bindReviewedRequirementSet({
      case_id: caseId,
      case_version: Number(rawVersion),
      set_id: setId,
      proposal_sha256: proposalSha256,
      decision_sha256: decisionSha256,
    });
    return {
      success: `Exact requirement set привязан к ${binding.case_id} v${binding.case_version}.`,
      bindingId: binding.binding_id,
      bindingSha256: binding.binding_sha256,
      caseId: binding.case_id,
      caseVersion: binding.case_version,
    };
  } catch (error) {
    return { error: failure(error) };
  }
}
