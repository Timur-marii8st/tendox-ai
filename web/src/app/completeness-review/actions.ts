"use server";

import { revalidatePath } from "next/cache";

import {
  ApiError,
  ConfigurationError,
  createCompletenessReviewDecision,
  type CompletenessStatus,
  type UnmappedDisposition,
} from "@/lib/procurement-api";

export type CompletenessDecisionFormState = { error?: string; success?: string };

const SHA256 = /^[0-9a-f]{64}$/;
const REVIEW_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const DISPOSITIONS = new Set<UnmappedDisposition>([
  "MATERIAL_REQUIREMENT",
  "NON_REQUIREMENT",
  "EXCLUDED_FROM_SCOPE",
]);
const STATUSES = new Set<CompletenessStatus>(["PASS", "FAIL", "UNKNOWN"]);
const UNMAPPED_FIELD = /^unmapped-(\d{1,6})-(disposition|rationale)$/;
const MAX_SCOPE_LENGTH = 4_000;
const MAX_REASON_LENGTH = 4_000;
const MAX_RATIONALE_LENGTH = 2_000;
const MAX_UNMAPPED_REVIEWS = 500;

export async function submitCompletenessDecision(
  _: CompletenessDecisionFormState,
  form: FormData,
): Promise<CompletenessDecisionFormState> {
  const parsed = parseDecisionForm(form);
  if (!("reviewId" in parsed)) return parsed;

  try {
    await createCompletenessReviewDecision(parsed.reviewId, parsed.payload);
    revalidatePath("/completeness-review");
    return { success: "Решение сохранено и привязано к неизменному снимку." };
  } catch (error) {
    return { error: safeApiError(error) };
  }
}

function parseDecisionForm(
  form: FormData,
):
  | {
      reviewId: string;
      payload: {
        evidence_sha256: string;
        status: CompletenessStatus;
        scope: string;
        reason: string;
        unmapped_reviews: Array<{
          block_index: number;
          disposition: UnmappedDisposition;
          rationale: string;
        }>;
      };
    }
  | CompletenessDecisionFormState {
  const singletonNames = new Set([
    "review-id",
    "evidence-sha256",
    "status",
    "scope",
    "reason",
  ]);
  const blocks = new Map<number, Partial<Record<"disposition" | "rationale", string>>>();

  for (const [name, value] of form.entries()) {
    if (name.startsWith("$ACTION_")) continue;
    if (singletonNames.has(name)) continue;
    const match = UNMAPPED_FIELD.exec(name);
    if (!match || typeof value !== "string") {
      return { error: "Форма решения содержит недопустимое поле." };
    }
    const index = Number(match[1]);
    const kind = match[2] as "disposition" | "rationale";
    const current = blocks.get(index) ?? {};
    if (current[kind] !== undefined) {
      return { error: "Форма решения содержит повторяющиеся данные блока." };
    }
    current[kind] = value;
    blocks.set(index, current);
  }

  const reviewId = singleton(form, "review-id");
  const evidenceSha256 = singleton(form, "evidence-sha256");
  const status = singleton(form, "status");
  const scope = singleton(form, "scope");
  const reason = singleton(form, "reason");
  if (!reviewId || !REVIEW_ID.test(reviewId)) {
    return { error: "Идентификатор review некорректен." };
  }
  if (!evidenceSha256 || !SHA256.test(evidenceSha256)) {
    return { error: "Digest снимка некорректен." };
  }
  if (!status || !STATUSES.has(status as CompletenessStatus)) {
    return { error: "Выберите допустимый статус полноты." };
  }
  if (!validText(scope, MAX_SCOPE_LENGTH) || !validText(reason, MAX_REASON_LENGTH)) {
    return { error: "Заполните scope и основание в пределах допустимой длины." };
  }
  if (blocks.size > MAX_UNMAPPED_REVIEWS) {
    return { error: "Слишком много решений по непокрытым блокам." };
  }

  const unmappedReviews: Array<{
    block_index: number;
    disposition: UnmappedDisposition;
    rationale: string;
  }> = [];
  for (const [blockIndex, item] of blocks) {
    const disposition = item.disposition?.trim() ?? "";
    const rationale = item.rationale?.trim() ?? "";
    if (!disposition && !rationale) continue;
    if (!DISPOSITIONS.has(disposition as UnmappedDisposition) || !validText(rationale, MAX_RATIONALE_LENGTH)) {
      return { error: "Для каждого отмеченного блока выберите решение и укажите основание." };
    }
    unmappedReviews.push({
      block_index: blockIndex,
      disposition: disposition as UnmappedDisposition,
      rationale,
    });
  }
  if (status === "PASS" && blocks.size !== unmappedReviews.length) {
    return { error: "Для PASS требуется решение и основание по каждому непокрытому блоку." };
  }

  return {
    reviewId,
    payload: {
      evidence_sha256: evidenceSha256,
      status: status as CompletenessStatus,
      scope: scope.trim(),
      reason: reason.trim(),
      unmapped_reviews: unmappedReviews,
    },
  };
}

function singleton(form: FormData, name: string): string | null {
  const values = form.getAll(name);
  return values.length === 1 && typeof values[0] === "string" ? values[0] : null;
}

function validText(value: string | null, limit: number): value is string {
  return typeof value === "string" && Boolean(value.trim()) && value.trim().length <= limit;
}

function safeApiError(error: unknown): string {
  if (error instanceof ApiError) {
    return (
      {
        401: "Не удалось подтвердить доступ reviewer к API.",
        403: "Для решения нужна роль COMPLETENESS_REVIEWER.",
        404: "Review недоступен в текущем tenant.",
        409: "Для этого review уже есть терминальное решение.",
        422: "API отклонил решение: проверьте снимок и основания по блокам.",
      }[error.status] ?? "Сервис временно недоступен. Повторите попытку позже."
    );
  }
  if (error instanceof ConfigurationError) {
    return "Серверное подключение reviewer к API не настроено.";
  }
  return "Сервис временно недоступен. Повторите попытку позже.";
}
