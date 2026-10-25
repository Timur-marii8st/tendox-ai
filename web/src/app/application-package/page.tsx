import type { Metadata } from "next";
import Link from "next/link";

import { ApplicationPackageForm } from "./package-form";
import {
  ApiError,
  ConfigurationError,
  loadApplicationPackage,
  type ApplicationPackage,
  type ApplicationPackageRecord,
} from "@/lib/procurement-api";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Комплектация заявки — Tendox",
  description: "Immutable пакет документов и цены после APPROVED участия",
};

const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const stamp = (value: string) => new Intl.DateTimeFormat("ru-RU", {
  dateStyle: "medium", timeStyle: "short",
}).format(new Date(value));

function failure(error: unknown): string {
  if (error instanceof ConfigurationError) return "Не настроен PROCUREMENT_API_TOKEN.";
  if (error instanceof ApiError) {
    if (error.status === 403) return "Token не имеет роли OPERATOR или AUDITOR.";
    if (error.status === 404) return "Exact APPROVED participation decision не найдено в текущем tenant.";
    if (error.status === 422) return "Stored evidence не прошло проверку целостности.";
  }
  return "Данные пакета временно недоступны.";
}

function StoredPackage({ value }: { value: ApplicationPackage }) {
  return <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
    <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="m-0 text-xl font-black">Пакет сохранён</h2><strong className="rounded-full bg-amber-100 px-3 py-1 text-amber-950">{value.review_status} · {value.coverage_status}</strong></div>
    <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2"><div><dt className="font-bold text-slate-500">Цена / floor</dt><dd className="m-0">{value.proposed_price_ex_vat} / {value.minimum_bid_price} {value.currency}</dd></div><div><dt className="font-bold text-slate-500">Подготовил</dt><dd className="m-0">{value.prepared_by} · {stamp(value.prepared_at)}</dd></div><div><dt className="font-bold text-slate-500">Требований</dt><dd className="m-0">{value.requirements.length}</dd></div><div><dt className="font-bold text-slate-500">Файлов</dt><dd className="m-0">{value.attachments.length}</dd></div></dl>
    <h3 className="mt-5 font-black">Покрытие proposal</h3><ul className="text-sm">{value.requirements.map((item) => <li key={item.ordinal}><strong>#{item.ordinal} {item.title}</strong> — {item.source_locator}</li>)}</ul>
    <h3 className="mt-5 font-black">Точный payload файлов</h3><ul className="text-sm">{value.attachments.map((item) => <li className="break-all" key={item.ordinal}><strong>{item.submission_filename}</strong> → требования {item.requirement_ordinals.join(", ")} · {item.document_sha256}</li>)}</ul>
    <p className="break-all font-mono text-xs text-slate-500">Package SHA-256: {value.package_sha256}</p>
    <p className="font-bold text-amber-900">Независимая полнота ещё не подтверждена. Внешнее действие не разрешено.</p>
    <Link className="font-bold text-blue-700 hover:underline" href={`/application-package-review?package_id=${encodeURIComponent(value.package_id)}`}>Открыть независимую проверку →</Link>
  </section>;
}

export default async function ApplicationPackagePage({
  searchParams,
}: {
  searchParams: Promise<{ decision_id?: string | string[] }>;
}) {
  const requested = (await searchParams).decision_id;
  const decisionId = typeof requested === "string" && ID.test(requested) ? requested : null;
  let record: ApplicationPackageRecord | null = null;
  let error: string | null = null;
  if (decisionId) {
    try { record = await loadApplicationPackage(decisionId); }
    catch (caught) { error = failure(caught); }
  }
  const decision = record?.evidence.participation.decision ?? null;
  const caseValue = record?.evidence.case;
  return <main className="min-h-screen bg-slate-50 text-slate-950"><div className="mx-auto w-[min(1000px,calc(100%-1rem))] py-6 sm:w-[min(1000px,calc(100%-2rem))] sm:py-10">
    <header className="border-b border-slate-200 pb-6"><p className="m-0 text-xs font-black uppercase tracking-[.16em] text-blue-700">S93 · application builder proposal</p><h1 className="mt-2 text-3xl font-black tracking-tight sm:text-5xl">Комплектация заявки</h1><p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">Оператор связывает минимальный перечень из документации с exact файлами заявки и фиксирует цену. Сервер повторно проверяет APPROVED, deadline, текущий PARTICIPATE и floor.</p><nav className="mt-4 flex gap-5 text-sm font-bold text-blue-700"><Link href="/">Дела</Link><Link href="/document-upload">Загрузить файлы</Link></nav></header>
    {!decisionId && <form action="/application-package" className="mt-6 flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-5 sm:flex-row sm:items-end" method="get"><label className="grid flex-1 gap-1 text-sm font-bold">Participation decision ID<input className="rounded-lg border border-slate-300 p-2 font-mono" name="decision_id" pattern="[A-Za-z0-9][A-Za-z0-9._:-]{0,199}" required /></label><button className="rounded-lg bg-slate-900 px-4 py-2 font-bold text-white" type="submit">Открыть решение</button></form>}
    {error && <p className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 font-bold text-red-900" role="alert">{error}</p>}
    {record && decision && caseValue && <><section className="mt-6 rounded-2xl border border-slate-200 bg-white p-5"><div className="flex flex-wrap items-center justify-between gap-3"><h2 className="m-0 text-xl font-black">APPROVED participation</h2><strong className="rounded-full bg-emerald-100 px-3 py-1 text-emerald-900">{decision.status}</strong></div><dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2"><div><dt className="font-bold text-slate-500">Case</dt><dd className="m-0">{caseValue.case_id} · v{caseValue.version}</dd></div><div><dt className="font-bold text-slate-500">Закупка</dt><dd className="m-0">{caseValue.tender.subject}</dd></div><div><dt className="font-bold text-slate-500">Deadline</dt><dd className="m-0">{caseValue.tender.submission?.closes_at ? stamp(caseValue.tender.submission.closes_at) : "UNKNOWN"}</dd></div><div><dt className="font-bold text-slate-500">Decision</dt><dd className="m-0 break-all">{decision.decision_id}</dd></div></dl><p className="break-all font-mono text-xs text-slate-500">Decision SHA-256: {decision.decision_sha256}</p></section>{record.package ? <StoredPackage value={record.package} /> : <ApplicationPackageForm decisionId={decision.decision_id} decisionSha256={decision.decision_sha256} minimumBidPrice={decision.current_recommendation.minimum_bid_price ?? ""} nmck={caseValue.nmck_ex_vat} />}</>}
    {record && !decision && <p className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-4 font-bold text-amber-950">Participation decision ещё не принято.</p>}
  </div></main>;
}
