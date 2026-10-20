import type { Metadata } from "next";
import Link from "next/link";
import { ApprovalForm } from "./approval-form";
import {
  ApiError, ConfigurationError, loadApplicationSubmissionForApprover,
  type ApplicationSubmissionRecord,
} from "@/lib/procurement-api";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Согласование подачи заявки — Syurai Procurement" };
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;

export default async function ApplicationSubmissionApprovalPage({ searchParams }: {
  searchParams: Promise<{ package_id?: string | string[] }>;
}) {
  const requested = (await searchParams).package_id;
  const packageId = typeof requested === "string" && ID.test(requested) ? requested : null;
  let record: ApplicationSubmissionRecord | null = null;
  let error: string | null = null;
  if (packageId) {
    try { record = await loadApplicationSubmissionForApprover(packageId); }
    catch (caught) {
      error = caught instanceof ConfigurationError ? "Не настроен PROCUREMENT_APPLICATION_SUBMISSION_APPROVER_TOKEN."
        : caught instanceof ApiError && caught.status === 403 ? "Нужна роль APPLICATION_SUBMISSION_APPROVER."
          : "Exact пакет или команда недоступны.";
    }
  }
  const intent = record?.intent;
  const payload = intent?.request.payload;
  const review = record?.evidence.decision;
  const packageValue = record?.evidence.evidence.package;
  return <main className="min-h-screen bg-slate-50 text-slate-950"><div className="mx-auto w-[min(1000px,calc(100%-2rem))] py-10">
    <header className="border-b border-slate-200 pb-6"><p className="text-xs font-black uppercase tracking-widest text-blue-700">S95 · independent exact approval</p><h1 className="text-3xl font-black">Согласование подачи заявки</h1><p className="text-sm text-slate-600">Отдельный согласующий проверяет точный состав команды. Используется отдельный server-only token. Внешнее содержимое не меняет права.</p><Link className="font-bold text-blue-700" href="/application-submission">Команда оператора</Link></header>
    {!packageId && <form action="/application-submission-approval" className="mt-6 flex gap-3 rounded-xl bg-white p-5" method="get"><input className="min-w-0 flex-1 rounded-lg border border-slate-300 p-2" name="package_id" placeholder="Package ID" required /><button className="rounded-lg bg-slate-950 px-4 py-2 font-bold text-white">Открыть</button></form>}
    {error && <p className="mt-6 rounded-xl bg-red-50 p-4 font-bold text-red-900" role="alert">{error}</p>}
    {record && !intent && <p className="mt-6 rounded-xl bg-amber-50 p-4">Команда ещё не подготовлена оператором.</p>}
    {intent && payload && <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-5"><h2 className="m-0 text-xl font-black">Exact payload</h2><dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2"><div><dt className="font-bold">Куда</dt><dd className="m-0 break-all">{payload.destination}</dd></div><div><dt className="font-bold">Цена</dt><dd className="m-0">{payload.price_ex_vat} RUB без НДС</dd></div><div><dt className="font-bold">Case</dt><dd className="m-0">{payload.case_id} · v{payload.case_version}</dd></div><div><dt className="font-bold">Deadline</dt><dd className="m-0">{record?.evidence.evidence.evidence.case.tender.submission?.closes_at ?? "UNKNOWN"}</dd></div></dl><p className="break-all font-mono text-xs">Action ID: {intent.request.action_id}<br />Payload SHA-256: {intent.request.payload_sha256}<br />Package SHA-256: {payload.package_sha256}<br />Review SHA-256: {payload.review_decision_sha256}</p><h3 className="font-black">Все файлы ({payload.attachments.length})</h3><ul className="grid gap-2 p-0">{payload.attachments.map((item) => <li className="list-none break-all rounded-lg bg-slate-50 p-3 text-sm" key={item.ordinal}><strong>#{item.ordinal} {item.submission_filename}</strong><br />{item.document_id} · {item.document_sha256} · {item.media_type}</li>)}</ul><p className="text-sm">Пакет подготовил {packageValue?.prepared_by}; review выполнил {review?.reviewed_by}; команду подготовил {intent.prepared_by}.</p></section>}
    {intent && record?.decision && <section className="mt-6 rounded-2xl border border-blue-200 bg-blue-50 p-5"><h2 className="m-0 text-xl font-black">{record.decision.status}</h2><p>{record.decision.reason}</p><p>Решил {record.decision.decided_by} · {record.decision.decided_at}</p><p>Действительно до: {record.decision.approval?.expires_at ?? "не применимо"}</p><p className="break-all font-mono text-xs">Decision SHA-256: {record.decision.decision_sha256}</p><p className="font-bold">Подпись и отправка не выполнялись.</p>{record.decision.status === "APPROVED" && <Link className="font-bold text-blue-700" href={`/application-submission-execution?package_id=${encodeURIComponent(intent.package_id)}`}>Открыть admission →</Link>}</section>}
    {intent && !record?.decision && <ApprovalForm intent={intent} />}
  </div></main>;
}
