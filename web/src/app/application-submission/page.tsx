import type { Metadata } from "next";
import Link from "next/link";
import { PrepareForm } from "./prepare-form";
import {
  ApiError, ConfigurationError, loadApplicationSubmission,
  type ApplicationSubmissionRecord,
} from "@/lib/procurement-api";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Команда подачи заявки — Syurai Procurement" };
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;

export default async function ApplicationSubmissionPage({ searchParams }: {
  searchParams: Promise<{ package_id?: string | string[] }>;
}) {
  const requested = (await searchParams).package_id;
  const packageId = typeof requested === "string" && ID.test(requested) ? requested : null;
  let record: ApplicationSubmissionRecord | null = null;
  let error: string | null = null;
  if (packageId) {
    try { record = await loadApplicationSubmission(packageId); }
    catch (caught) {
      error = caught instanceof ConfigurationError ? "Не настроен token оператора."
        : caught instanceof ApiError && caught.status === 403 ? "Нужна роль OPERATOR."
          : "Проверенный пакет недоступен или нарушена целостность evidence.";
    }
  }
  const packageValue = record?.evidence.evidence.package;
  const review = record?.evidence.decision;
  const intent = record?.intent;
  return <main className="min-h-screen bg-slate-50 text-slate-950"><div className="mx-auto w-[min(1000px,calc(100%-2rem))] py-10">
    <header className="border-b border-slate-200 pb-6"><p className="text-xs font-black uppercase tracking-widest text-blue-700">S95 · exact submission intent</p><h1 className="text-3xl font-black">Команда подачи заявки</h1><p className="text-sm text-slate-600">Команда сохраняет адрес, цену и точные SHA-256 файлов после независимой проверки. Подписи и отправки здесь нет.</p><nav className="flex gap-4 text-sm font-bold text-blue-700"><Link href="/application-package-review">Проверка пакета</Link><Link href="/application-submission-approval">Согласование</Link></nav></header>
    {!packageId && <form action="/application-submission" className="mt-6 flex gap-3 rounded-xl bg-white p-5" method="get"><input className="min-w-0 flex-1 rounded-lg border border-slate-300 p-2" name="package_id" placeholder="Package ID" required /><button className="rounded-lg bg-slate-950 px-4 py-2 font-bold text-white">Открыть</button></form>}
    {error && <p className="mt-6 rounded-xl bg-red-50 p-4 font-bold text-red-900" role="alert">{error}</p>}
    {packageValue && review && <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-5"><h2 className="m-0 text-xl font-black">Проверенный пакет: {review.status}</h2><p>Цена: <strong>{packageValue.proposed_price_ex_vat} RUB без НДС</strong></p><p className="break-all text-xs">Package SHA-256: {packageValue.package_sha256}<br />Review SHA-256: {review.decision_sha256}</p><ul>{packageValue.attachments.map((item) => <li className="break-all text-sm" key={item.ordinal}>{item.submission_filename} · {item.document_sha256}</li>)}</ul></section>}
    {record && packageValue && review?.status === "PASS" && !intent && <PrepareForm packageId={packageValue.package_id} packageSha={packageValue.package_sha256} reviewSha={review.decision_sha256} />}
    {intent && <section className="mt-6 rounded-2xl border border-blue-200 bg-blue-50 p-5"><h2 className="m-0 text-xl font-black">Команда сохранена</h2><p>Назначение: <span className="break-all font-mono">{intent.request.payload.destination}</span></p><p>Цена: {intent.request.payload.price_ex_vat} RUB без НДС · файлов: {intent.request.payload.attachments.length}</p><p className="break-all font-mono text-xs">Action ID: {intent.request.action_id}<br />Payload SHA-256: {intent.request.payload_sha256}</p><p>Согласование: {record?.decision?.status ?? "ожидается"}</p><Link className="font-bold text-blue-700" href={`/application-submission-approval?package_id=${encodeURIComponent(intent.package_id)}`}>Открыть отдельное согласование →</Link></section>}
  </div></main>;
}
