"use server";

import { revalidatePath } from "next/cache";

import {
  ApiError,
  ConfigurationError,
  createServerOfferEconomics,
  loadServerOfferEconomics,
  materializeServerOfferEconomicsCase,
  type ServerOfferOperatingCostsInput,
  type ServerOfferScenarioInput,
} from "@/lib/procurement-api";

export type EconomicsState = { error?: string; success?: string; packageSha256?: string };
export type MaterializationState = { error?: string; success?: string; nextVersion?: number };
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const SHA = /^[0-9a-f]{64}$/;
const MONEY = /^(?:0|[1-9]\d{0,15})(?:\.\d{1,2})?$/;
const KINDS = ["base", "realistic", "conservative"] as const;
const COSTS = ["packaging", "logistics", "loading_unloading", "storage", "installation",
  "payroll_travel", "subcontracting", "insurance", "finance", "bank_guarantee",
  "platform_fees", "taxes", "certification", "warranty", "risk_reserve",
  "penalty_reserve", "other"] as const;
const SINGLETONS = new Set(["case-id", "case-version", "offer-id", "proposal-sha256", "review-sha256"]);
const SCENARIO_FIELD = /^(base|realistic|conservative)-(revenue|assumptions|packaging|logistics|loading_unloading|storage|installation|payroll_travel|subcontracting|insurance|finance|bank_guarantee|platform_fees|taxes|certification|warranty|risk_reserve|penalty_reserve|other)$/;

function one(form: FormData, name: string): string | null {
  const values = form.getAll(name);
  return values.length === 1 && typeof values[0] === "string" ? values[0].trim() : null;
}

function failure(error: unknown): string {
  if (error instanceof ConfigurationError) return "Operator API не настроен.";
  if (error instanceof ApiError) {
    if (error.status === 403) return "Требуется роль OPERATOR.";
    if (error.status === 404) return "Exact case или PASS offer не найден.";
    if (error.status === 409) return "Для версии кейса уже сохранена экономика.";
    if (error.status === 422) return "Сценарии не прошли exact-evidence проверку.";
  }
  return "Экономика не сохранена.";
}

export async function submitEconomics(_: EconomicsState, form: FormData): Promise<EconomicsState> {
  const counts = new Map<string, number>();
  for (const [name, value] of form.entries()) {
    if (name.startsWith("$ACTION_")) continue;
    if (typeof value !== "string" || (!SINGLETONS.has(name) && !SCENARIO_FIELD.test(name))) {
      return { error: "Форма содержит неизвестное поле." };
    }
    counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  const expected = [...SINGLETONS, ...KINDS.flatMap((kind) => [
    `${kind}-revenue`, `${kind}-assumptions`, ...COSTS.map((cost) => `${kind}-${cost}`),
  ])];
  if (expected.some((name) => counts.get(name) !== 1)) return { error: "Заполните все поля и явные нули." };
  const caseId = one(form, "case-id"); const versionText = one(form, "case-version");
  const offerId = one(form, "offer-id"); const proposalSha = one(form, "proposal-sha256");
  const reviewSha = one(form, "review-sha256");
  const version = versionText && /^\d+$/.test(versionText) ? Number(versionText) : 0;
  if (!caseId || !ID.test(caseId) || version < 1 || !offerId || !ID.test(offerId)
    || !proposalSha || !SHA.test(proposalSha) || !reviewSha || !SHA.test(reviewSha)) {
    return { error: "Exact references недействительны." };
  }
  const scenarios: ServerOfferScenarioInput[] = [];
  for (const kind of KINDS) {
    const revenue = one(form, `${kind}-revenue`) ?? "";
    const assumption = one(form, `${kind}-assumptions`) ?? "";
    const values = Object.fromEntries(COSTS.map((cost) => [cost, one(form, `${kind}-${cost}`) ?? ""]));
    if (!MONEY.test(revenue) || !assumption || assumption.length > 2_000
      || Object.values(values).some((value) => !MONEY.test(value))) {
      return { error: `Проверьте все суммы и допущение сценария ${kind}.` };
    }
    scenarios.push({ kind, contract_revenue: revenue,
      costs: values as ServerOfferOperatingCostsInput, assumptions: [assumption] });
  }
  try {
    const fresh = await loadServerOfferEconomics(caseId, version, offerId);
    const review = fresh.evidence.offer_review;
    if (fresh.package !== null || review.evidence.proposal.proposal_sha256 !== proposalSha
      || !review.decision || review.decision.decision_sha256 !== reviewSha
      || review.decision.status !== "PASS") {
      return { error: "Evidence устарел, не PASS или package уже сохранён." };
    }
    const result = await createServerOfferEconomics(caseId, version, {
      offer_id: offerId, offer_proposal_sha256: proposalSha,
      offer_review_decision_sha256: reviewSha, scenarios,
    });
    revalidatePath(`/server-offer-economics?case_id=${encodeURIComponent(caseId)}&version=${version}&offer_id=${encodeURIComponent(offerId)}`);
    return { success: "Три complete-сценария сохранены; recommendation остаётся UNKNOWN.", packageSha256: result.package_sha256 };
  } catch (error) { return { error: failure(error) }; }
}

export async function materializeCase(
  _: MaterializationState,
  form: FormData,
): Promise<MaterializationState> {
  const allowed = new Set(["case-id", "case-version", "offer-id", "economics-id", "package-sha256"]);
  const counts = new Map<string, number>();
  for (const [name, value] of form.entries()) {
    if (name.startsWith("$ACTION_")) continue;
    if (!allowed.has(name) || typeof value !== "string") return { error: "Форма содержит неизвестное поле." };
    counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  if ([...allowed].some((name) => counts.get(name) !== 1)) return { error: "Exact references неполны." };
  const caseId = one(form, "case-id"); const versionText = one(form, "case-version");
  const offerId = one(form, "offer-id"); const economicsId = one(form, "economics-id");
  const packageSha = one(form, "package-sha256");
  const version = versionText && /^\d+$/.test(versionText) ? Number(versionText) : 0;
  if (!caseId || !ID.test(caseId) || version < 1 || !offerId || !ID.test(offerId)
    || !economicsId || !ID.test(economicsId) || !packageSha || !SHA.test(packageSha)) {
    return { error: "Exact references недействительны." };
  }
  try {
    const fresh = await loadServerOfferEconomics(caseId, version, offerId);
    if (!fresh.package || fresh.package.economics_id !== economicsId
      || fresh.package.package_sha256 !== packageSha) {
      return { error: "Economics package изменился или недоступен." };
    }
    const result = await materializeServerOfferEconomicsCase(caseId, version, {
      offer_id: offerId, economics_id: economicsId, package_sha256: packageSha,
    });
    revalidatePath("/");
    return {
      success: `Создан case ${result.case_id} v${result.version}. Остальные hard gates требуют оценки.`,
      nextVersion: result.version,
    };
  } catch (error) { return { error: failure(error) }; }
}
