"use server";

import { cookies } from "next/headers";
import { optionalProfile, profileCookie, readCapabilities, readProfile, readProfileSelection } from "@/lib/company-profile-api";
import { noticeReportMatches, type NoticeProfileContext, type NoticeProfileReport } from "@/lib/notice-profile-comparison";
import type { MixedNoticeRef } from "@/lib/procurement-api";

export async function loadNoticeProfileContext(): Promise<{ context?: NoticeProfileContext; error?: string }> {
  try {
    const caps = await readCapabilities();
    if (!caps.can_edit) return { error: "Сравнение доступно оператору компании." };
    const selection = await optionalProfile(() => readProfileSelection());
    if (!selection) return { error: "Сохраните профиль компании и выберите его версию для сравнения." };
    const snapshot = await readProfile(selection.profile_ref.version);
    if (snapshot.snapshot_sha256 !== selection.profile_ref.snapshot_sha256) return { error: "Выберите версию профиля заново." };
    return { context: { company_id: caps.company_id, actor_id: caps.actor_id, selection_id: selection.selection_id,
      profile_ref: { version: selection.profile_ref.version, snapshot_sha256: selection.profile_ref.snapshot_sha256 }, profile_name: snapshot.facts["identity.name"].knowledge === "KNOWN" ? String(snapshot.facts["identity.name"].value) : "Название не указано" } };
  } catch { return { error: "Подключите персональный доступ на странице профиля компании." }; }
}

export async function compareNoticeProfile(context: NoticeProfileContext, notices: MixedNoticeRef[]): Promise<{ report?: NoticeProfileReport; error?: string }> {
  if (notices.length < 2 || notices.length > 5 || new Set(notices.map(n => `${n.law}:${n.purchase_number}`)).size !== notices.length) return { error: "Выберите от 2 до 5 разных закупок." };
  const token = (await cookies()).get(profileCookie)?.value;
  const base = process.env.PROCUREMENT_API_URL;
  if (!token || !base) return { error: "Подключите персональный доступ на странице профиля компании." };
  try {
    const response = await fetch(`${base.replace(/\/$/, "")}/v1/procurement-comparison/notices`, {
      method: "POST", cache: "no-store", signal: AbortSignal.timeout(30_000),
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ selection_id: context.selection_id, profile_ref: context.profile_ref, notices }),
    });
    if (!response.ok) return { error: ({ 401: "Персональная сессия истекла. Подключитесь снова.", 403: "Нет права запускать сравнение.",
      404: "Выбранная версия профиля или закупки недоступна вашей компании.", 409: "Сохранённые версии изменились или не согласованы. Повторите поиск и выбор профиля.", 422: "Проверьте выбранные закупки." } as Record<number, string>)[response.status] ?? "Не удалось выполнить сравнение. Повторите запрос." };
    const report = await response.json() as NoticeProfileReport;
    if (!noticeReportMatches(report, context, notices)) return { error: "Ответ не соответствует выбранным версиям. Повторите запрос." };
    return { report };
  } catch { return { error: "Сервис сравнения не ответил вовремя. Выбранные карточки сохранены на странице; повторите запрос." }; }
}
