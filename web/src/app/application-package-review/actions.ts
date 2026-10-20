"use server";

import { revalidatePath } from "next/cache";

import {
  ApiError,
  ConfigurationError,
  decideApplicationReview,
  loadApplicationReview,
  type ApplicationAttachmentReview,
  type ApplicationInventoryAssessment,
  type ApplicationPriceAssessment,
  type ApplicationRequirementReview,
} from "@/lib/procurement-api";

export type ApplicationReviewState = {
  error?: string;
  success?: string;
  decisionSha256?: string;
};

const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const STATUSES = new Set(["PASS", "FAIL", "UNKNOWN"]);
const INVENTORY = new Set<ApplicationInventoryAssessment>([
  "CONFIRMED_COMPLETE", "CONFIRMED_MISSING", "UNRESOLVED",
]);
const PRICE = new Set<ApplicationPriceAssessment>(["CONFIRMED", "REJECTED", "UNRESOLVED"]);

function one(form: FormData, name: string): string | null {
  const values = form.getAll(name);
  return values.length === 1 && typeof values[0] === "string" ? values[0].trim() : null;
}

function failure(error: unknown): string {
  if (error instanceof ConfigurationError) return "Не настроен отдельный server-only token проверяющего.";
  if (error instanceof ApiError) {
    if (error.status === 403) return "Token не имеет роли APPLICATION_REVIEWER.";
    if (error.status === 404) return "Exact пакет не найден в текущем tenant.";
    if (error.status === 409) return "Terminal review уже сохранён. Обновите страницу.";
    if (error.status === 422) return "Review не прошёл exact-evidence или current-time проверку.";
  }
  return "Решение не сохранено. Проверьте API и повторите запрос.";
}

export async function submitApplicationReview(
  _: ApplicationReviewState,
  form: FormData,
): Promise<ApplicationReviewState> {
  const packageId = one(form, "package-id");
  const packageSha = one(form, "package-sha256");
  if (!packageId || !ID.test(packageId) || !packageSha || !SHA256.test(packageSha)) {
    return { error: "Проверьте exact package ID и SHA-256." };
  }
  try {
    const fresh = await loadApplicationReview(packageId);
    const packageValue = fresh.evidence.package;
    if (!packageValue || packageValue.package_sha256 !== packageSha || fresh.decision !== null) {
      return { error: "Пакет изменился, не найден или уже проверен." };
    }
    const expected = new Set([
      "package-id", "package-sha256", "inventory-assessment", "inventory-reason",
      "price-assessment", "price-reason", "reason",
    ]);
    const repeatable = new Set<string>();
    repeatable.add("inventory-source");
    for (const item of packageValue.requirements) {
      expected.add(`requirement-${item.ordinal}-status`);
      expected.add(`requirement-${item.ordinal}-reason`);
      repeatable.add(`requirement-${item.ordinal}-attachment`);
    }
    for (const item of packageValue.attachments) {
      expected.add(`attachment-${item.ordinal}-status`);
      expected.add(`attachment-${item.ordinal}-reason`);
    }
    for (const [name, value] of form.entries()) {
      if (name.startsWith("$ACTION_")) continue;
      if (
        typeof value !== "string" || (!expected.has(name) && !repeatable.has(name))
        || (expected.has(name) && form.getAll(name).length !== 1)
      ) return { error: "Форма содержит неизвестное или повторяющееся поле." };
    }
    if ([...expected].some((name) => form.getAll(name).length !== 1)) {
      return { error: "Review заполнен не полностью." };
    }
    const inventory = one(form, "inventory-assessment") as ApplicationInventoryAssessment | null;
    const inventoryReason = one(form, "inventory-reason") ?? "";
    const price = one(form, "price-assessment") as ApplicationPriceAssessment | null;
    const priceReason = one(form, "price-reason") ?? "";
    const reason = one(form, "reason") ?? "";
    if (
      !inventory || !INVENTORY.has(inventory) || !inventoryReason || inventoryReason.length > 4_000
      || !price || !PRICE.has(price) || !priceReason || priceReason.length > 4_000
      || !reason || reason.length > 4_000
    ) return { error: "Проверьте оценку полного перечня, цены и основания." };
    const sourceIds = [...new Set(packageValue.requirements.map((item) => item.source_document_id))].sort();
    const rawSourceIds = form.getAll("inventory-source");
    const reviewedSourceIds = rawSourceIds.filter((value): value is string => typeof value === "string").sort();
    if (
      reviewedSourceIds.length !== rawSourceIds.length || reviewedSourceIds.length === 0
      || new Set(reviewedSourceIds).size !== reviewedSourceIds.length
      || reviewedSourceIds.some((value) => !sourceIds.includes(value))
      || (inventory === "CONFIRMED_COMPLETE" && reviewedSourceIds.length !== sourceIds.length)
    ) return { error: "Отметьте exact документы заказчика, которые проверены для оценки перечня." };

    const requirementReviews: ApplicationRequirementReview[] = [];
    for (const item of packageValue.requirements) {
      const status = one(form, `requirement-${item.ordinal}-status`);
      const rowReason = one(form, `requirement-${item.ordinal}-reason`) ?? "";
      const raw = form.getAll(`requirement-${item.ordinal}-attachment`);
      const refs = raw.map((value) => typeof value === "string" ? Number(value) : NaN);
      const allowed = packageValue.attachments.filter((attachment) =>
        attachment.requirement_ordinals.includes(item.ordinal)).map((attachment) => attachment.ordinal);
      if (
        !status || !STATUSES.has(status) || !rowReason || rowReason.length > 2_000
        || refs.some((ref) => !Number.isInteger(ref) || !allowed.includes(ref))
        || new Set(refs).size !== refs.length
        || (status !== "UNKNOWN" && refs.length === 0)
        || (status === "PASS" && refs.length !== allowed.length)
      ) return { error: `Проверьте verdict и exact файлы требования №${item.ordinal}.` };
      requirementReviews.push({
        requirement_ordinal: item.ordinal,
        status: status as "PASS" | "FAIL" | "UNKNOWN",
        reason: rowReason,
        attachment_ordinals: refs.sort((left, right) => left - right),
      });
    }
    const attachmentReviews: ApplicationAttachmentReview[] = [];
    for (const item of packageValue.attachments) {
      const status = one(form, `attachment-${item.ordinal}-status`);
      const rowReason = one(form, `attachment-${item.ordinal}-reason`) ?? "";
      if (!status || !STATUSES.has(status) || !rowReason || rowReason.length > 2_000) {
        return { error: `Проверьте verdict и основание файла №${item.ordinal}.` };
      }
      attachmentReviews.push({
        attachment_ordinal: item.ordinal,
        status: status as "PASS" | "FAIL" | "UNKNOWN",
        reason: rowReason,
      });
    }
    const decision = await decideApplicationReview(packageId, {
      package_sha256: packageSha,
      requirement_reviews: requirementReviews,
      attachment_reviews: attachmentReviews,
      inventory_assessment: inventory,
      inventory_source_document_ids: reviewedSourceIds,
      inventory_reason: inventoryReason,
      price_assessment: price,
      price_reason: priceReason,
      reason,
    });
    revalidatePath(`/application-package-review?package_id=${encodeURIComponent(packageId)}`);
    return {
      success: `${decision.status} вычислен сервером и сохранён. Внешняя подача не разрешена.`,
      decisionSha256: decision.decision_sha256,
    };
  } catch (error) {
    return { error: failure(error) };
  }
}
