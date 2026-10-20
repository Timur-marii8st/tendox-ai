"use client";

import { useActionState, useState } from "react";

import { submitApplicationPackage, type ApplicationPackageState } from "./actions";

const initial: ApplicationPackageState = {};

export function ApplicationPackageForm({
  decisionId,
  decisionSha256,
  minimumBidPrice,
  nmck,
}: {
  decisionId: string;
  decisionSha256: string;
  minimumBidPrice: string;
  nmck: string;
}) {
  const [state, action, pending] = useActionState(submitApplicationPackage, initial);
  const [requirementCount, setRequirementCount] = useState(1);
  const [attachmentCount, setAttachmentCount] = useState(1);
  return <form action={action} className="mt-6 grid gap-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
    <input name="decision-id" type="hidden" value={decisionId} />
    <input name="decision-sha256" type="hidden" value={decisionSha256} />
    <input name="requirement-count" type="hidden" value={requirementCount} />
    <input name="attachment-count" type="hidden" value={attachmentCount} />
    <section>
      <h2 className="m-0 text-xl font-black">Цена заявки</h2>
      <p className="text-sm text-slate-600">Допустимый коридор на момент подготовки: от {minimumBidPrice} до {nmck} RUB без НДС. Сервер пересчитает floor и deadline.</p>
      <label className="grid max-w-sm gap-1 text-sm font-bold">Цена без НДС, RUB
        <input className="rounded-lg border border-slate-300 p-2 font-mono" defaultValue={minimumBidPrice} inputMode="decimal" name="proposed-price-ex-vat" pattern="(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,2})?" required />
      </label>
    </section>
    <section className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="m-0 text-xl font-black">Что требует документация</h2><p className="mb-0 text-sm text-slate-600">Каждая строка ссылается на immutable документ заказчика и точный locator.</p></div><div className="flex gap-2"><button className="rounded-lg border px-3 py-2 text-sm font-bold" disabled={pending || requirementCount === 1} onClick={() => setRequirementCount((value) => value - 1)} type="button">Убрать последнюю</button><button className="rounded-lg border px-3 py-2 text-sm font-bold" disabled={pending || requirementCount === 50} onClick={() => setRequirementCount((value) => value + 1)} type="button">Добавить</button></div></div>
      {Array.from({ length: requirementCount }, (_, index) => index + 1).map((ordinal) => <fieldset className="grid gap-3 rounded-xl border border-slate-200 p-4" key={ordinal}><legend className="px-2 font-black">Требование №{ordinal}</legend><label className="grid gap-1 text-sm font-bold">Вид<select className="rounded-lg border border-slate-300 p-2" defaultValue="FORM" name={`requirement-${ordinal}-kind`}><option value="FORM">Форма</option><option value="DECLARATION">Декларация</option><option value="ELIGIBILITY">Право участия</option><option value="CERTIFICATE">Сертификат</option><option value="AUTHORITY">Полномочия</option><option value="TECHNICAL_PROPOSAL">Техническое предложение</option><option value="PRICE_PROPOSAL">Ценовое предложение</option><option value="OTHER">Другое</option></select></label><label className="grid gap-1 text-sm font-bold">Название<input className="rounded-lg border border-slate-300 p-2" maxLength={1000} name={`requirement-${ordinal}-title`} required /></label><div className="grid gap-3 sm:grid-cols-2"><label className="grid gap-1 text-sm font-bold">ID документа заказчика<input className="rounded-lg border border-slate-300 p-2 font-mono text-xs" name={`requirement-${ordinal}-source-id`} pattern="[A-Za-z0-9][A-Za-z0-9._:-]{0,199}" required /></label><label className="grid gap-1 text-sm font-bold">SHA-256 документа<input className="rounded-lg border border-slate-300 p-2 font-mono text-xs" name={`requirement-${ordinal}-source-sha256`} pattern="[0-9a-f]{64}" required /></label></div><label className="grid gap-1 text-sm font-bold">Точное место в документе<input className="rounded-lg border border-slate-300 p-2" maxLength={1000} name={`requirement-${ordinal}-locator`} placeholder="Раздел 4, форма 1" required /></label></fieldset>)}
    </section>
    <section className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="m-0 text-xl font-black">Файлы заявки</h2><p className="mb-0 text-sm text-slate-600">Используйте ID и SHA-256 файлов с ролью APPLICATION_ATTACHMENT.</p></div><div className="flex gap-2"><button className="rounded-lg border px-3 py-2 text-sm font-bold" disabled={pending || attachmentCount === 1} onClick={() => setAttachmentCount((value) => value - 1)} type="button">Убрать последний</button><button className="rounded-lg border px-3 py-2 text-sm font-bold" disabled={pending || attachmentCount === 50} onClick={() => setAttachmentCount((value) => value + 1)} type="button">Добавить</button></div></div>
      {Array.from({ length: attachmentCount }, (_, index) => index + 1).map((ordinal) => <fieldset className="grid gap-3 rounded-xl border border-slate-200 p-4" key={ordinal}><legend className="px-2 font-black">Файл №{ordinal}</legend><label className="grid gap-1 text-sm font-bold">Номера покрываемых требований<input className="rounded-lg border border-slate-300 p-2" name={`attachment-${ordinal}-requirements`} pattern="[1-9][0-9]*(?:,[1-9][0-9]*)*" placeholder="1,2" required /><span className="font-normal text-slate-500">По возрастанию, без повторов и пробелов.</span></label><div className="grid gap-3 sm:grid-cols-2"><label className="grid gap-1 text-sm font-bold">ID загруженного файла<input className="rounded-lg border border-slate-300 p-2 font-mono text-xs" name={`attachment-${ordinal}-document-id`} pattern="[A-Za-z0-9][A-Za-z0-9._:-]{0,199}" required /></label><label className="grid gap-1 text-sm font-bold">SHA-256 файла<input className="rounded-lg border border-slate-300 p-2 font-mono text-xs" name={`attachment-${ordinal}-document-sha256`} pattern="[0-9a-f]{64}" required /></label></div><label className="grid gap-1 text-sm font-bold">Имя при подаче<input className="rounded-lg border border-slate-300 p-2" maxLength={255} name={`attachment-${ordinal}-filename`} placeholder="application.pdf" required /></label></fieldset>)}
    </section>
    <p className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">Сохранение создаёт только immutable proposal со статусами <strong>PENDING_REVIEW / UNKNOWN</strong>. Оно не подписывает и не отправляет заявку.</p>
    <button className="rounded-lg bg-slate-950 px-4 py-3 font-black text-white disabled:opacity-50" disabled={pending} type="submit">{pending ? "Проверяем и сохраняем…" : "Сохранить пакет для review"}</button>
    {state.error && <p className="font-bold text-red-700" role="alert">{state.error}</p>}
    {state.success && <p className="font-bold text-emerald-700" role="status">{state.success}</p>}
    {state.packageSha256 && <code className="break-all text-xs">{state.packageSha256}</code>}
  </form>;
}
