"use server";

import { revalidatePath } from "next/cache";
import {
  ApiError, ConfigurationError, claimApplicationSubmission,
  loadApplicationSubmissionExecution,
} from "@/lib/procurement-api";

export type AdmissionFormState = { error?: string; success?: string };
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const SHA = /^[0-9a-f]{64}$/;
function one(form: FormData, name: string): string | null {
  const values = form.getAll(name);
  return values.length === 1 && typeof values[0] === "string" ? values[0].trim() : null;
}

export async function claimSubmission(
  _: AdmissionFormState, form: FormData,
): Promise<AdmissionFormState> {
  const packageId = one(form, "package-id");
  const actionId = one(form, "action-id");
  const payloadSha = one(form, "payload-sha");
  const approvalSha = one(form, "approval-sha");
  if (
    !packageId || !ID.test(packageId) || !actionId || !ID.test(actionId)
    || !payloadSha || !SHA.test(payloadSha) || !approvalSha || !SHA.test(approvalSha)
    || one(form, "acknowledged") !== "yes"
  ) return { error: "Подтвердите точную команду и одноразовое использование approval." };
  try {
    const fresh = await loadApplicationSubmissionExecution(packageId);
    if (
      fresh.admission || fresh.submission.decision?.status !== "APPROVED"
      || fresh.submission.intent?.request.action_id !== actionId
      || fresh.submission.intent.request.payload_sha256 !== payloadSha
      || fresh.submission.decision.decision_sha256 !== approvalSha
    ) return { error: "Команда уже заявлена к исполнению или её exact approval изменился." };
    const admission = await claimApplicationSubmission(packageId, {
      action_id: actionId,
      payload_sha256: payloadSha,
      approval_decision_sha256: approvalSha,
    });
    revalidatePath(`/application-submission-execution?package_id=${encodeURIComponent(packageId)}`);
    return { success: `${admission.status}: оригинальные байты проверены, approval использован один раз. Подачи на площадку не было.` };
  } catch (error) {
    if (error instanceof ConfigurationError) return { error: "Не настроен отдельный token исполнителя." };
    if (error instanceof ApiError) {
      if (error.status === 403) return { error: "Нужна роль APPLICATION_SUBMISSION_EXECUTOR." };
      if (error.status === 409) return { error: "Approval уже использован; обновите страницу." };
      if (error.status === 422) return { error: "Approval, текущие условия или оригинальные байты не прошли проверку." };
    }
    return { error: "Admission не сохранён. Проверьте соединение с API." };
  }
}
