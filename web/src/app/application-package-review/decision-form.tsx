"use client";

import { useActionState } from "react";

import { submitApplicationReview, type ApplicationReviewState } from "./actions";
import type { ApplicationPackage } from "@/lib/procurement-api";

const initial: ApplicationReviewState = {};

function VerdictSelect({ name }: { name: string }) {
  return <select className="rounded-lg border border-slate-300 p-2" defaultValue="" name={name} required><option disabled value="">Выберите verdict</option><option value="PASS">PASS — подтверждено</option><option value="FAIL">FAIL — обнаружено нарушение</option><option value="UNKNOWN">UNKNOWN — не доказано</option></select>;
}

export function ApplicationReviewForm({ packageValue }: { packageValue: ApplicationPackage }) {
  const [state, action, pending] = useActionState(submitApplicationReview, initial);
  return <form action={action} className="mt-6 grid gap-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
    <input name="package-id" type="hidden" value={packageValue.package_id} />
    <input name="package-sha256" type="hidden" value={packageValue.package_sha256} />
    <section className="grid gap-4"><h2 className="m-0 text-xl font-black">Каждое требование</h2>{packageValue.requirements.map((item) => {
      const mapped = packageValue.attachments.filter((attachment) => attachment.requirement_ordinals.includes(item.ordinal));
      return <fieldset className="grid gap-3 rounded-xl border border-slate-200 p-4" key={item.ordinal}><legend className="px-2 font-black">#{item.ordinal} {item.title}</legend><p className="m-0 text-sm text-slate-600">{item.kind} · {item.source_locator}</p><label className="grid gap-1 text-sm font-bold">Вердикт<VerdictSelect name={`requirement-${item.ordinal}-status`} /></label><fieldset className="grid gap-2"><legend className="font-bold">Проверенные exact файлы</legend>{mapped.map((attachment) => <label className="flex gap-2 text-sm" key={attachment.ordinal}><input name={`requirement-${item.ordinal}-attachment`} type="checkbox" value={attachment.ordinal} /> #{attachment.ordinal} {attachment.submission_filename}</label>)}</fieldset><label className="grid gap-1 text-sm font-bold">Основание<textarea className="min-h-20 rounded-lg border border-slate-300 p-2 font-normal" maxLength={2000} name={`requirement-${item.ordinal}-reason`} required /></label></fieldset>;
    })}</section>
    <section className="grid gap-4"><h2 className="m-0 text-xl font-black">Каждый файл</h2>{packageValue.attachments.map((item) => <fieldset className="grid gap-3 rounded-xl border border-slate-200 p-4" key={item.ordinal}><legend className="px-2 font-black">#{item.ordinal} {item.submission_filename}</legend><p className="m-0 break-all font-mono text-xs text-slate-600">{item.document_id} · {item.document_sha256}</p><label className="grid gap-1 text-sm font-bold">Вердикт<VerdictSelect name={`attachment-${item.ordinal}-status`} /></label><label className="grid gap-1 text-sm font-bold">Основание<textarea className="min-h-20 rounded-lg border border-slate-300 p-2 font-normal" maxLength={2000} name={`attachment-${item.ordinal}-reason`} required /></label></fieldset>)}</section>
    <section className="grid gap-4 rounded-xl border border-amber-200 bg-amber-50 p-4"><h2 className="m-0 text-xl font-black">Полнота перечня и цена</h2><p className="m-0 text-sm">Сверьте исходную документацию целиком, включая формы, декларации и подтверждения, с перечнем в пакете. Положительный verdict требует самостоятельного подтверждения, что отсутствующих обязательных документов нет.</p><fieldset className="grid gap-2"><legend className="font-bold">Проверенные документы заказчика</legend>{[...new Set(packageValue.requirements.map((item) => item.source_document_id))].sort().map((sourceId) => <label className="flex gap-2 break-all text-sm" key={sourceId}><input name="inventory-source" type="checkbox" value={sourceId} /> {sourceId}</label>)}</fieldset><label className="grid gap-1 text-sm font-bold">Перечень<select className="rounded-lg border border-slate-300 p-2" defaultValue="" name="inventory-assessment" required><option disabled value="">Выберите оценку</option><option value="CONFIRMED_COMPLETE">Всё обязательное включено</option><option value="CONFIRMED_MISSING">Обнаружен пропуск</option><option value="UNRESOLVED">Не удалось установить</option></select></label><label className="grid gap-1 text-sm font-bold">Основание оценки перечня<textarea className="min-h-24 rounded-lg border border-slate-300 p-2 font-normal" maxLength={4000} name="inventory-reason" required /></label><p className="m-0 text-sm">Цена без НДС: <strong>{packageValue.proposed_price_ex_vat} RUB</strong>. Floor при подготовке: {packageValue.minimum_bid_price} RUB. Сервер заново проверит текущий floor и deadline.</p><label className="grid gap-1 text-sm font-bold">Цена<select className="rounded-lg border border-slate-300 p-2" defaultValue="" name="price-assessment" required><option disabled value="">Выберите оценку</option><option value="CONFIRMED">Подтверждена</option><option value="REJECTED">Неверная цена или база</option><option value="UNRESOLVED">Не удалось установить</option></select></label><label className="grid gap-1 text-sm font-bold">Основание оценки цены<textarea className="min-h-20 rounded-lg border border-slate-300 p-2 font-normal" maxLength={4000} name="price-reason" required /></label></section>
    <label className="grid gap-1 font-bold">Общее основание решения<textarea className="min-h-24 rounded-lg border border-slate-300 p-2 font-normal" maxLength={4000} name="reason" required /></label>
    <p className="m-0 text-sm text-amber-900">Итоговый статус вычисляет сервер. Даже PASS не является exact-payload approval и не разрешает подпись или отправку.</p>
    <button className="rounded-lg bg-slate-950 px-4 py-3 font-black text-white disabled:opacity-50" disabled={pending} type="submit">{pending ? "Проверяем и сохраняем…" : "Сохранить terminal review"}</button>
    {state.error && <p className="font-bold text-red-700" role="alert">{state.error}</p>}
    {state.success && <p className="font-bold text-emerald-700" role="status">{state.success}</p>}
    {state.decisionSha256 && <code className="break-all text-xs">{state.decisionSha256}</code>}
  </form>;
}
