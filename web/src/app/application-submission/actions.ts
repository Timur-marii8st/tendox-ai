"use server";

import { revalidatePath } from "next/cache";
import {
  ApiError, ConfigurationError, loadApplicationSubmission,
  prepareApplicationSubmission,
} from "@/lib/procurement-api";

export type SubmissionFormState = { error?: string; success?: string };

const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const SHA = /^[0-9a-f]{64}$/;
function one(form: FormData, name: string): string | null {
  const values = form.getAll(name);
  return values.length === 1 && typeof values[0] === "string" ? values[0].trim() : null;
}

export async function prepareSubmission(
  _: SubmissionFormState, form: FormData,
): Promise<SubmissionFormState> {
  const packageId = one(form, "package-id");
  const packageSha = one(form, "package-sha");
  const reviewSha = one(form, "review-sha");
  const destination = one(form, "destination");
  if (
    !packageId || !ID.test(packageId) || !packageSha || !SHA.test(packageSha)
    || !reviewSha || !SHA.test(reviewSha) || !destination || destination.length > 2000
    || !/^https:\/\/[^\s/#?]+/.test(destination)
  ) return { error: "Проверьте идентификаторы и точный HTTPS адрес." };
  try {
    const fresh = await loadApplicationSubmission(packageId);
    if (
      fresh.intent || fresh.evidence.decision?.status !== "PASS"
      || fresh.evidence.evidence.package?.package_sha256 !== packageSha
      || fresh.evidence.decision.decision_sha256 !== reviewSha
    ) return { error: "Пакет уже имеет команду или review больше не соответствует." };
    await prepareApplicationSubmission(packageId, {
      package_sha256: packageSha,
      review_decision_sha256: reviewSha,
      destination,
    });
    revalidatePath(`/application-submission?package_id=${encodeURIComponent(packageId)}`);
    return { success: "Команда сохранена. Попросите отдельного согласующего проверить exact payload." };
  } catch (error) {
    if (error instanceof ConfigurationError) return { error: "Не настроен token оператора." };
    if (error instanceof ApiError) {
      if (error.status === 403) return { error: "Нужна роль OPERATOR." };
      if (error.status === 409) return { error: "Команда уже существует; обновите страницу." };
      if (error.status === 422) return { error: "Текущие deadline, участие или цена не позволяют подготовку." };
    }
    return { error: "Команда не сохранена. Проверьте соединение с API." };
  }
}
