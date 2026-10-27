"use server";

import { randomUUID } from "node:crypto";
import { cookies } from "next/headers";
import { profileCookie, readProfile, readProfileSelection } from "@/lib/company-profile-api";
import { betaHistoryMatches, betaReportMatches, type BetaHistoryReport, type BetaQuoteRef, type BetaQuoteInput, type BetaQuoteReport, type BetaShortlist } from "@/lib/beta-procurement";

async function betaRequest<T>(path: string, payload: unknown): Promise<T> {
  const token = (await cookies()).get(profileCookie)?.value;
  const base = process.env.PROCUREMENT_API_URL;
  if (!token || !base) throw new Error("Подключите персональный доступ на странице профиля компании.");
  const response = await fetch(`${base.replace(/\/$/, "")}/v1/beta-procurement/${path}`, {
    method: "POST", cache: "no-store", signal: AbortSignal.timeout(60_000),
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(response.status === 422 ? "Проверьте КП, даты, НДС и расходы. Денежные значения вводите через точку." : response.status === 409
    ? "Версия закупки или условия изменились. Повторите поиск и проверьте КП." : response.status === 401
    ? "Персональная сессия истекла. Подключитесь снова." : "Не удалось прочитать или сохранить расчёт. Повторите запрос.");
  return response.json() as Promise<T>;
}
export async function readBetaQuote(ref: BetaQuoteRef): Promise<{ report?: BetaQuoteReport; error?: string; nextRecordId?: string }> {
  try {
    const report = await betaRequest<BetaQuoteReport>("quote/read", ref);
    if (!betaReportMatches(report, ref)) throw new Error("Ответ не соответствует выбранной закупке.");
    return { report, nextRecordId: randomUUID() };
  } catch (error) { return { error: error instanceof Error ? error.message : "Расчёт недоступен." }; }
}
export async function readBetaHistory(ref: BetaQuoteRef): Promise<{ report?: BetaHistoryReport; error?: string }> {
  try {
    const report = await betaRequest<unknown>("history/read", ref);
    if (!betaHistoryMatches(report, ref)) throw new Error("История не соответствует выбранной закупке или её данные не подтверждены.");
    return { report };
  } catch (error) { return { error: error instanceof Error ? error.message : "История контрактов недоступна." }; }
}
export async function saveBetaQuote(ref: BetaQuoteRef, recordId: string, quote: BetaQuoteInput): Promise<{ report?: BetaQuoteReport; error?: string; nextRecordId?: string }> {
  try {
    const report = await betaRequest<BetaQuoteReport>("quote/save", { ...ref, record_id: recordId, quote });
    if (!betaReportMatches(report, ref)) throw new Error("Ответ не соответствует выбранной закупке.");
    return { report, nextRecordId: randomUUID() };
  } catch (error) { return { error: error instanceof Error ? error.message : "Расчёт не сохранён." }; }
}
export async function readBetaShortlist(notices: BetaQuoteRef[], region: string, ranking: "TOTAL_PROFIT" | "UNIT_PROFIT" = "UNIT_PROFIT"): Promise<{ report?: BetaShortlist; error?: string }> {
  try {
    if (!notices.length || notices.length > 20) throw new Error("Для сравнения выберите до 20 лотов.");
    return { report: await betaRequest<BetaShortlist>("shortlist", { notices, region, ranking }) };
  } catch (error) { return { error: error instanceof Error ? error.message : "Сравнение недоступно." }; }
}
export async function betaProfileSearch(): Promise<{ terms?: string[]; error?: string }> {
  try {
    const selection = await readProfileSelection();
    const profile = await readProfile(selection.profile_ref.version);
    if (profile.snapshot_sha256 !== selection.profile_ref.snapshot_sha256) throw new Error();
    const terms = ["supplied_goods", "performed_works", "provided_services"].flatMap(path => {
      const fact = profile.facts[path];
      return fact.knowledge === "KNOWN" && Array.isArray(fact.value) ? fact.value.filter((v): v is string => typeof v === "string" && v.length <= 120) : [];
    });
    return terms.length ? { terms } : { error: "Заполните товары, работы или услуги в профиле компании." };
  } catch { return { error: "Сохраните профиль, выберите его версию и подключите персональный доступ." }; }
}
