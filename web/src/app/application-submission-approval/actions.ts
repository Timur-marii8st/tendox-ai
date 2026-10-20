"use server";

import { revalidatePath } from "next/cache";
import {
  ApiError, ConfigurationError, decideApplicationSubmission,
  loadApplicationSubmissionForApprover,
} from "@/lib/procurement-api";

export type ApprovalFormState = { error?: string; success?: string };
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const SHA = /^[0-9a-f]{64}$/;
function one(form: FormData, name: string): string | null {
  const values = form.getAll(name);
  return values.length === 1 && typeof values[0] === "string" ? values[0].trim() : null;
}

export async function decideSubmission(
  _: ApprovalFormState, form: FormData,
): Promise<ApprovalFormState> {
  const packageId = one(form, "package-id");
  const actionId = one(form, "action-id");
  const payloadSha = one(form, "payload-sha");
  const status = one(form, "status");
  const reason = one(form, "reason");
  const acknowledged = one(form, "acknowledged");
  if (
    !packageId || !ID.test(packageId) || !actionId || !ID.test(actionId)
    || !payloadSha || !SHA.test(payloadSha)
    || (status !== "APPROVED" && status !== "REJECTED")
    || !reason || reason.length > 4000
    || (status === "APPROVED" && acknowledged !== "yes")
  ) return { error: "Укажите решение, основание и подтвердите сверку exact payload." };
  try {
    const fresh = await loadApplicationSubmissionForApprover(packageId);
    if (
      fresh.decision || fresh.evidence.decision?.status !== "PASS"
      || fresh.intent?.request.action_id !== actionId
      || fresh.intent.request.payload_sha256 !== payloadSha
    ) return { error: "Команда изменилась, не найдена или уже получила решение." };
    const decision = await decideApplicationSubmission(packageId, {
      action_id: actionId, payload_sha256: payloadSha, status, reason,
    });
    revalidatePath(`/application-submission-approval?package_id=${encodeURIComponent(packageId)}`);
    return { success: `${decision.status} сохранён. Подпись и отправка не выполнялись.` };
  } catch (error) {
    if (error instanceof ConfigurationError) return { error: "Не настроен отдельный token согласующего." };
    if (error instanceof ApiError) {
      if (error.status === 403) return { error: "Нужна роль APPLICATION_SUBMISSION_APPROVER." };
      if (error.status === 409) return { error: "Решение уже принято; обновите страницу." };
      if (error.status === 422) return { error: "Точный payload, независимость или текущие условия не подтверждены." };
    }
    return { error: "Решение не сохранено. Проверьте соединение с API." };
  }
}
