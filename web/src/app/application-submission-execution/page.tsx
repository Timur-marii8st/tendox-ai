import type { Metadata } from "next";
import Link from "next/link";
import { ClaimForm } from "./claim-form";
import {
  ApiError, ConfigurationError, loadApplicationSubmissionExecution,
  type ApplicationSubmissionExecutionRecord,
} from "@/lib/procurement-api";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Admission заявки — Tendox" };
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;

export default async function ApplicationSubmissionExecutionPage({ searchParams }: {
  searchParams: Promise<{ package_id?: string | string[] }>;
}) {
  const requested = (await searchParams).package_id;
  const packageId = typeof requested === "string" && ID.test(requested) ? requested : null;
  let record: ApplicationSubmissionExecutionRecord | null = null;
  let error: string | null = null;
  if (packageId) {
    try { record = await loadApplicationSubmissionExecution(packageId); }
    catch (caught) {
      error = caught instanceof ConfigurationError ? "Не настроен PROCUREMENT_APPLICATION_SUBMISSION_EXECUTOR_TOKEN."
        : caught instanceof ApiError && caught.status === 403 ? "Нужна роль APPLICATION_SUBMISSION_EXECUTOR."
          : "Exact команда или admission недоступны.";
    }
  }
  const submission = record?.submission;
  const intent = submission?.intent;
  const decision = submission?.decision;
  const admission = record?.admission;
  const expiresAt = decision?.approval?.expires_at;
  return <main className="min-h-screen bg-slate-50 text-slate-950"><div className="mx-auto w-[min(1000px,calc(100%-2rem))] py-10">
    <header className="border-b border-slate-200 pb-6"><p className="text-xs font-black uppercase tracking-widest text-blue-700">S96 · no-dispatch admission</p><h1 className="text-3xl font-black">Проверка перед исполнением</h1><p className="text-sm text-slate-600">Отдельная роль исполнителя однократно использует exact approval и проверяет все исходные байты. Этот этап не отправляет заявку на ЭТП.</p><nav className="flex gap-4 text-sm font-bold text-blue-700"><Link href="/application-submission">Команда</Link><Link href="/application-submission-approval">Согласование</Link></nav></header>
    {!packageId && <form action="/application-submission-execution" className="mt-6 flex gap-3 rounded-xl bg-white p-5" method="get"><input className="min-w-0 flex-1 rounded-lg border border-slate-300 p-2" name="package_id" placeholder="Package ID" required /><button className="rounded-lg bg-slate-950 px-4 py-2 font-bold text-white">Открыть</button></form>}
    {error && <p className="mt-6 rounded-xl bg-red-50 p-4 font-bold text-red-900" role="alert">{error}</p>}
    {intent && <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-5"><h2 className="m-0 text-xl font-black">Exact команда</h2><p className="break-all text-sm">Адрес: {intent.request.payload.destination}<br />Цена: {intent.request.payload.price_ex_vat} RUB без НДС<br />Action: {intent.request.action_id}</p><p className="break-all font-mono text-xs">Payload SHA-256: {intent.request.payload_sha256}<br />Approval decision SHA-256: {decision?.decision_sha256 ?? "—"}</p><p>Решение: {decision?.status ?? "ожидается"} · действительно до {expiresAt ?? "—"}</p><ul>{intent.request.payload.attachments.map((item) => <li className="break-all text-sm" key={item.ordinal}>{item.submission_filename} · {item.document_sha256}</li>)}</ul></section>}
    {admission && <section className="mt-6 rounded-2xl border border-emerald-200 bg-emerald-50 p-5"><h2 className="m-0 text-xl font-black">{admission.status}</h2><p>Проверено файлов: {admission.attachments.length}. Один approval зарезервирован.</p><p className="break-all font-mono text-xs">Admission ID: {admission.admission_id}<br />SHA-256: {admission.admission_sha256}</p><ul>{admission.attachments.map((item) => <li className="break-all text-sm" key={item.ordinal}>{item.submission_filename} · {item.byte_size} bytes · {item.sha256}</li>)}</ul><p className="font-bold">Внешнее действие не выполнялось.</p></section>}
    {intent && decision?.status === "APPROVED" && !admission && <section className="mt-6 rounded-2xl border border-blue-200 bg-blue-50 p-5"><h2 className="m-0 text-xl font-black">Ручная передача пакета</h2><p className="text-sm">Архив содержит только утверждённые оригиналы и проверяемый манифест. Скачивание доступно лишь пока действует согласование и текущие условия заявки, до одноразового admission. Подача на ЭТП и получение её квитанции остаются действиями человека.</p><a className="font-bold text-blue-700" href={`/application-submission-execution/handoff?package_id=${encodeURIComponent(intent.package_id)}`}>Скачать проверенный архив ZIP</a></section>}
    {intent && decision?.status === "APPROVED" && !admission && <ClaimForm intent={intent} decision={decision} />}
  </div></main>;
}
