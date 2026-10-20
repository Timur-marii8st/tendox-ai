"use server";

import { revalidatePath } from "next/cache";

import {
  ApiError,
  ConfigurationError,
  decideServerOfferReview,
  loadServerOfferReview,
  type ServerOfferBomScopeAssessment,
  type ServerOfferCommercialAssessment,
  type ServerOfferEvidenceRef,
  type ServerOfferRequirementDecision,
} from "@/lib/procurement-api";

export type ServerOfferReviewState = {
  error?: string;
  success?: string;
  decisionSha256?: string;
};

const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const ROW_FIELD = /^requirement-(\d{1,3})-(status|reason|evidence)$/;
const STATUSES = new Set(["PASS", "FAIL", "UNKNOWN"] as const);
const BOM_SCOPE = new Set<ServerOfferBomScopeAssessment>([
  "CONFIRMED_COMPLETE", "CONFIRMED_INCOMPLETE", "UNRESOLVED",
]);
const COMMERCIAL = new Set<ServerOfferCommercialAssessment>([
  "CONFIRMED", "REJECTED", "UNRESOLVED",
]);
const SINGLETONS = new Set([
  "offer-id", "proposal-sha256", "requirement-count", "bom-scope-assessment",
  "commercial-terms-assessment", "reason",
]);

function one(form: FormData, name: string): string | null {
  const values = form.getAll(name);
  return values.length === 1 && typeof values[0] === "string" ? values[0].trim() : null;
}

function failure(error: unknown): string {
  if (error instanceof ConfigurationError) {
    return "Не настроен отдельный server-only token проверки предложения.";
  }
  if (error instanceof ApiError) {
    if (error.status === 403) return "Token не имеет роли COMPLETENESS_REVIEWER.";
    if (error.status === 404) return "Exact offer proposal не найден в текущем tenant.";
    if (error.status === 409) return "Terminal review уже сохранён. Обновите страницу.";
    if (error.status === 422) return "Решение не прошло серверные exact-evidence проверки.";
  }
  return "Решение не сохранено. Проверьте API и повторите запрос.";
}

function evidenceRef(value: string, maxBomOrdinal: number): ServerOfferEvidenceRef | null {
  if (value === "COMMERCIAL_TERMS") return { kind: "COMMERCIAL_TERMS", bom_line_ordinal: null };
  const match = /^BOM_LINE:(\d{1,3})$/.exec(value);
  const ordinal = match ? Number(match[1]) : 0;
  return ordinal >= 1 && ordinal <= maxBomOrdinal
    ? { kind: "BOM_LINE", bom_line_ordinal: ordinal }
    : null;
}

export async function submitServerOfferReview(
  _: ServerOfferReviewState,
  form: FormData,
): Promise<ServerOfferReviewState> {
  const singletonCounts = new Map<string, number>();
  const rowOrdinals = new Set<number>();
  for (const [name, value] of form.entries()) {
    if (name.startsWith("$ACTION_")) continue;
    if (typeof value !== "string") return { error: "Форма содержит недопустимое поле." };
    if (SINGLETONS.has(name)) {
      singletonCounts.set(name, (singletonCounts.get(name) ?? 0) + 1);
    } else {
      const match = ROW_FIELD.exec(name);
      if (!match) return { error: "Форма содержит неизвестное поле." };
      rowOrdinals.add(Number(match[1]));
    }
  }
  if ([...SINGLETONS].some((name) => singletonCounts.get(name) !== 1)) {
    return { error: "Exact references или итоговые assessment заполнены не полностью." };
  }
  const offerId = one(form, "offer-id");
  const proposalSha = one(form, "proposal-sha256");
  const countText = one(form, "requirement-count");
  const bomScope = one(form, "bom-scope-assessment");
  const commercial = one(form, "commercial-terms-assessment");
  const reason = one(form, "reason") ?? "";
  const count = countText && /^\d{1,3}$/.test(countText) ? Number(countText) : 0;
  if (
    !offerId || !ID.test(offerId) || !proposalSha || !SHA256.test(proposalSha)
    || count < 1 || count > 500
    || !bomScope || !BOM_SCOPE.has(bomScope as ServerOfferBomScopeAssessment)
    || !commercial || !COMMERCIAL.has(commercial as ServerOfferCommercialAssessment)
    || !reason || reason.length > 4_000
  ) return { error: "Проверьте exact proposal, assessments и основание." };
  if ([...rowOrdinals].some((ordinal) => ordinal < 1 || ordinal > count)) {
    return { error: "Форма содержит строку вне exact requirement scope." };
  }

  try {
    const fresh = await loadServerOfferReview(offerId);
    const proposal = fresh.evidence.proposal;
    const expected = fresh.evidence.requirement_set.proposal.expected_entry_count;
    if (
      fresh.decision !== null || proposal.proposal_sha256 !== proposalSha
      || expected !== count
    ) return { error: "Proposal устарел, изменил scope или уже получил terminal review." };
    const decisions: ServerOfferRequirementDecision[] = [];
    for (let ordinal = 1; ordinal <= count; ordinal += 1) {
      const status = one(form, `requirement-${ordinal}-status`);
      const rowReason = one(form, `requirement-${ordinal}-reason`) ?? "";
      const rawEvidence = form.getAll(`requirement-${ordinal}-evidence`);
      const evidence = rawEvidence.map((value) =>
        typeof value === "string" ? evidenceRef(value, proposal.bom_lines.length) : null
      );
      if (
        !status || !STATUSES.has(status as "PASS" | "FAIL" | "UNKNOWN")
        || !rowReason || rowReason.length > 2_000 || evidence.some((item) => item === null)
        || new Set(rawEvidence).size !== rawEvidence.length
        || (status !== "UNKNOWN" && evidence.length === 0)
      ) return { error: `Проверьте verdict, reason и evidence для строки ${ordinal}.` };
      decisions.push({
        requirement_ordinal: ordinal,
        status: status as "PASS" | "FAIL" | "UNKNOWN",
        reason: rowReason,
        evidence: evidence as ServerOfferEvidenceRef[],
      });
    }
    const decision = await decideServerOfferReview(offerId, {
      proposal_sha256: proposalSha,
      requirement_decisions: decisions,
      bom_scope_assessment: bomScope as ServerOfferBomScopeAssessment,
      commercial_terms_assessment: commercial as ServerOfferCommercialAssessment,
      reason,
    });
    revalidatePath(`/server-offer-review?offer_id=${encodeURIComponent(offerId)}`);
    return {
      success: `${decision.status} вычислен сервером и сохранён для exact proposal.`,
      decisionSha256: decision.decision_sha256,
    };
  } catch (error) {
    return { error: failure(error) };
  }
}
