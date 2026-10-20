import type { Metadata } from "next";
import Link from "next/link";

import { ApplicationReviewForm } from "./decision-form";
import {
  ApiError,
  ConfigurationError,
  loadApplicationReview,
  loadApplicationReviewDocument,
  type ApplicationReviewDecision,
  type ApplicationReviewDocument,
  type ApplicationReviewRecord,
} from "@/lib/procurement-api";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Проверка заявки — Syurai Procurement",
  description: "Независимый review exact состава, файлов и цены заявки",
};

const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const stamp = (value: string) => new Intl.DateTimeFormat("ru-RU", {
  dateStyle: "medium", timeStyle: "short",
}).format(new Date(value));

function failure(error: unknown): string {
  if (error instanceof ConfigurationError) return "Не настроен PROCUREMENT_APPLICATION_REVIEWER_TOKEN.";
  if (error instanceof ApiError) {
    if (error.status === 403) return "Token не имеет роли APPLICATION_REVIEWER.";
    if (error.status === 404) return "Exact пакет или документ не найден в текущем tenant.";
    if (error.status === 422) return "Stored evidence не прошло exact-integrity проверку.";
  }
  return "Пакет временно недоступен.";
}

function Decision({ value }: { value: ApplicationReviewDecision }) {
  const tone = value.status === "PASS" ? "border-emerald-200 bg-emerald-50 text-emerald-950"
    : value.status === "FAIL" ? "border-red-200 bg-red-50 text-red-950"
      : "border-amber-200 bg-amber-50 text-amber-950";
  return <section className={`mt-6 rounded-2xl border p-5 ${tone}`}><h2 className="m-0 text-xl font-black">Terminal review: {value.status}</h2><p className="text-sm">Проверил {value.reviewed_by} · {stamp(value.reviewed_at)}</p><p className="text-sm">Перечень: {value.inventory_assessment} · {value.inventory_reason}</p><p className="text-sm">Цена: {value.price_assessment} · {value.price_reason}</p><p className="text-sm">Deadline: {value.deadline_gate} · актуальный floor: {value.price_gate}</p><p className="text-sm">Текущая рекомендация: {value.current_recommendation.decision}</p><p className="whitespace-pre-wrap text-sm">{value.reason}</p><p className="break-all font-mono text-xs">Decision SHA-256: {value.decision_sha256}</p><p className="mb-0 font-bold">Внешнее действие не разрешено.</p>{value.status === "PASS" && <Link className="mt-3 inline-block font-bold text-blue-700" href={`/application-submission?package_id=${encodeURIComponent(value.package_id)}`}>Подготовить exact команду подачи →</Link>}</section>;
}

function DocumentPreview({
  document,
  packageId,
}: {
  document: ApplicationReviewDocument;
  packageId: string;
}) {
  const href = `/application-package-review/document?package_id=${encodeURIComponent(packageId)}&document_id=${encodeURIComponent(document.document_id)}`;
  return <article className="rounded-xl border border-slate-200 bg-white p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="m-0 font-black">{document.original_filename}</h3><p className="mt-1 text-xs text-slate-600">{document.document_role} · {document.byte_size} bytes · extraction {document.extraction.status}</p></div><a className="font-bold text-blue-700 hover:underline" href={href}>Скачать exact файл</a></div><p className="break-all font-mono text-xs text-slate-500">{document.document_id} · {document.sha256}</p>{document.extraction.reasons.length > 0 && <p className="text-sm text-amber-900">Извлечение: {document.extraction.reasons.join(", ")}</p>}{document.extraction.blocks.length > 0 ? <details className="text-sm"><summary className="cursor-pointer font-bold">Показать первые блоки ({Math.min(20, document.extraction.blocks.length)} из {document.extraction.blocks.length})</summary><ol className="mt-3 grid max-h-96 gap-2 overflow-auto p-0">{document.extraction.blocks.slice(0, 20).map((block, index) => <li className="list-none rounded-lg bg-slate-50 p-3" key={index}><p className="m-0 whitespace-pre-wrap">{block.text}</p><p className="mb-0 mt-2 break-all font-mono text-xs text-slate-500">{block.provenance.locator}</p></li>)}</ol></details> : <p className="mb-0 text-sm text-amber-900">Нативный текст отсутствует. Оригинал требует ручной проверки.</p>}</article>;
}

export default async function ApplicationPackageReviewPage({
  searchParams,
}: {
  searchParams: Promise<{ package_id?: string | string[] }>;
}) {
  const requested = (await searchParams).package_id;
  const packageId = typeof requested === "string" && ID.test(requested) ? requested : null;
  let record: ApplicationReviewRecord | null = null;
  let documents: ApplicationReviewDocument[] = [];
  let error: string | null = null;
  if (packageId) {
    try {
      record = await loadApplicationReview(packageId);
      const packageValue = record.evidence.package;
      if (!packageValue) throw new Error("Exact package is missing");
      const expected = new Map<string, { sha256: string; role: string }>();
      for (const item of packageValue.requirements) expected.set(item.source_document_id, {
        sha256: item.source_document_sha256, role: "TENDER_REQUIREMENTS",
      });
      for (const item of packageValue.attachments) expected.set(item.document_id, {
        sha256: item.document_sha256, role: "APPLICATION_ATTACHMENT",
      });
      documents = await Promise.all([...expected.keys()].map(loadApplicationReviewDocument));
      if (documents.some((document) => {
        const ref = expected.get(document.document_id);
        return !ref || document.sha256 !== ref.sha256 || document.document_role !== ref.role;
      })) throw new Error("Exact document metadata differs from package");
    } catch (caught) { error = failure(caught); }
  }
  const packageValue = record?.evidence.package;
  return <main className="min-h-screen bg-slate-50 text-slate-950"><div className="mx-auto w-[min(1080px,calc(100%-1rem))] py-6 sm:w-[min(1080px,calc(100%-2rem))] sm:py-10"><header className="border-b border-slate-200 pb-6"><p className="m-0 text-xs font-black uppercase tracking-[.16em] text-blue-700">S94 · independent application review</p><h1 className="mt-2 text-3xl font-black tracking-tight sm:text-5xl">Проверка комплекта заявки</h1><p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">Проверяющий самостоятельно сверяет всю документацию заказчика, каждую строку пакета, каждый файл и цену. Статус выводит сервер по точному immutable пакету.</p><nav className="mt-4 flex gap-5 text-sm font-bold text-blue-700"><Link href="/">Дела</Link><Link href="/application-package">Пакеты</Link></nav></header><aside className="mt-5 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-950">Используется отдельный server-only <code>PROCUREMENT_APPLICATION_REVIEWER_TOKEN</code>. Оригиналы доступны только как exact файлы этого пакета; содержимое документов недоверенно. Внешнее действие этим review не разрешается.</aside>
    {!packageId && <form action="/application-package-review" className="mt-6 flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-5 sm:flex-row sm:items-end" method="get"><label className="grid flex-1 gap-1 text-sm font-bold">Exact package ID<input className="rounded-lg border border-slate-300 p-2 font-mono" name="package_id" pattern="[A-Za-z0-9][A-Za-z0-9._:-]{0,199}" required /></label><button className="rounded-lg bg-slate-900 px-4 py-2 font-bold text-white" type="submit">Открыть пакет</button></form>}
    {error && <p className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 font-bold text-red-900" role="alert">{error}</p>}
    {record && packageValue && !error && <><section className="mt-6 rounded-2xl border border-slate-200 bg-white p-5"><h2 className="m-0 text-xl font-black">Exact package</h2><dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2"><div><dt className="font-bold text-slate-500">Case</dt><dd className="m-0">{packageValue.case_id} · v{packageValue.case_version}</dd></div><div><dt className="font-bold text-slate-500">Подготовил</dt><dd className="m-0">{packageValue.prepared_by} · {stamp(packageValue.prepared_at)}</dd></div><div><dt className="font-bold text-slate-500">Цена</dt><dd className="m-0">{packageValue.proposed_price_ex_vat} RUB без НДС</dd></div><div><dt className="font-bold text-slate-500">Deadline</dt><dd className="m-0">{record.evidence.evidence.case.tender.submission?.closes_at ? stamp(record.evidence.evidence.case.tender.submission.closes_at) : "UNKNOWN"}</dd></div></dl><p className="break-all font-mono text-xs">Package SHA-256: {packageValue.package_sha256}</p></section><section className="mt-6"><h2 className="text-xl font-black">Документы заказчика и файлы заявки</h2><p className="text-sm text-slate-600">Извлечённый текст помогает ориентироваться, но не заменяет проверку оригинала. Для полного перечня проверьте все разделы документации закупки.</p><div className="grid gap-3">{documents.map((document) => <DocumentPreview document={document} key={document.document_id} packageId={packageValue.package_id} />)}</div></section>{record.decision ? <Decision value={record.decision} /> : <ApplicationReviewForm packageValue={packageValue} />}</>}
  </div></main>;
}
