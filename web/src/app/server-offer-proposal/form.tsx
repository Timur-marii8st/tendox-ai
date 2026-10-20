"use client";

import { useActionState, useState } from "react";
import Link from "next/link";

import { submitServerOfferProposal, type ServerOfferFormState } from "./actions";

const initialState: ServerOfferFormState = {};
const kinds = ["CHASSIS", "CPU", "MEMORY", "STORAGE", "RAID_CONTROLLER", "NETWORK", "PSU", "COOLING", "RAILS", "CABLE", "LICENSE", "SERVICE", "OTHER"];

export function ServerOfferProposalForm({ defaults }: { defaults: Record<string, string> }) {
  const [state, action, pending] = useActionState(submitServerOfferProposal, initialState);
  const [lineCount, setLineCount] = useState(1);
  return (
    <form action={action} className="mt-6 grid gap-5" noValidate>
      <section className="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="m-0 text-xl font-black">1. Exact references</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          {[
            ["case-id", "Case ID", defaults.case_id], ["case-version", "Версия", defaults.version || "1"],
            ["binding-id", "Requirement binding ID", defaults.binding_id], ["binding-sha256", "Binding SHA-256", defaults.binding_sha256],
            ["sourcing-run-id", "Sourcing run ID", defaults.run_id], ["lead-id", "Lead ID", defaults.lead_id],
            ["source-document-id", "КП document ID", defaults.document_id], ["source-document-sha256", "КП SHA-256", defaults.document_sha256],
          ].map(([name, label, value]) => <label className="grid gap-1 text-sm font-bold" key={name}>{label}<input className="rounded-lg border border-slate-300 p-2 font-mono text-sm" defaultValue={value} name={name} required /></label>)}
        </div>
      </section>
      <section className="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="m-0 text-xl font-black">2. Полный BOM из КП</h2><p className="mb-0 mt-2 text-sm text-slate-600">Каждая строка получает locator в exact КП-документе.</p></div><button className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-bold" disabled={pending || lineCount >= 500} onClick={() => setLineCount((value) => value + 1)} type="button">Добавить строку</button></div>
        {Array.from({ length: lineCount }, (_, index) => index + 1).map((ordinal) => (
          <fieldset className="grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4" key={ordinal}>
            <legend className="px-1 text-sm font-black">Строка {ordinal}</legend>
            <div className="grid gap-3 sm:grid-cols-3">
              <label className="grid gap-1 text-xs font-bold">Тип<select defaultValue="" name={`line-${ordinal}-kind`} required><option value="">Выберите</option>{kinds.map((kind) => <option key={kind} value={kind}>{kind}</option>)}</select></label>
              <label className="grid gap-1 text-xs font-bold">Производитель<input name={`line-${ordinal}-manufacturer`} /></label>
              <label className="grid gap-1 text-xs font-bold">SKU<input name={`line-${ordinal}-sku`} required /></label>
              <label className="grid gap-1 text-xs font-bold sm:col-span-2">Описание<input name={`line-${ordinal}-description`} required /></label>
              <label className="grid gap-1 text-xs font-bold">Количество<input inputMode="decimal" name={`line-${ordinal}-quantity`} required /></label>
              <label className="grid gap-1 text-xs font-bold">Единица<input defaultValue="шт" name={`line-${ordinal}-unit`} required /></label>
              <label className="grid gap-1 text-xs font-bold">Цена единицы без НДС<input inputMode="decimal" name={`line-${ordinal}-unit-price`} /></label>
              <label className="grid gap-1 text-xs font-bold">Сумма строки без НДС<input inputMode="decimal" name={`line-${ordinal}-line-total`} /></label>
              <label className="grid gap-1 text-xs font-bold sm:col-span-3">Source locator<input className="font-mono" name={`line-${ordinal}-locator`} placeholder="page 1 table 1 row 2" required /></label>
            </div>
          </fieldset>
        ))}
      </section>
      <section className="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="m-0 text-xl font-black">3. Коммерческие условия</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="grid gap-1 text-sm font-bold">Номер КП<input name="quote-number" required /></label><label className="grid gap-1 text-sm font-bold">Supplier ID<input name="supplier-id" required /></label>
          <label className="grid gap-1 text-sm font-bold sm:col-span-2">Поставщик<input name="supplier-name" required /></label>
          <label className="grid gap-1 text-sm font-bold">Сумма без НДС, RUB<input inputMode="decimal" name="amount-ex-vat" required /></label><label className="grid gap-1 text-sm font-bold">Ставка НДС, доля<input inputMode="decimal" name="nds-rate" placeholder="0.20" /></label>
          <label className="grid gap-1 text-sm font-bold">Выдано, ISO с timezone<input name="issued-at" placeholder="2026-09-20T12:00:00+03:00" required /></label><label className="grid gap-1 text-sm font-bold">Действует до, ISO с timezone<input name="valid-until" placeholder="2026-10-20T12:00:00+03:00" required /></label>
          <label className="grid gap-1 text-sm font-bold">Покрывает весь scope<select defaultValue="" name="covers-full-scope" required><option value="">Выберите явно</option><option value="true">Да</option><option value="false">Нет</option><option value="unknown">Не подтверждено</option></select></label>
          <label className="grid gap-1 text-sm font-bold">Наличие<input name="availability-terms" /></label><label className="grid gap-1 text-sm font-bold">Поставка<input name="delivery-terms" /></label><label className="grid gap-1 text-sm font-bold">Оплата<input name="payment-terms" /></label>
          <label className="grid gap-1 text-sm font-bold sm:col-span-2">Locator коммерческих условий<input className="font-mono" name="terms-locator" required /></label>
        </div>
      </section>
      <p className="m-0 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-950">Сохранение создаёт immutable proposal со статусом UNKNOWN / PENDING_REVIEW. Оно не подтверждает совместимость конфигурации, полноту КП или участие.</p>
      {state.error && <p className="m-0 text-sm font-bold text-red-800" role="alert">{state.error}</p>}
      {state.success && <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950" role="status"><p className="m-0 font-black">{state.success}</p><p className="mt-2 break-all">Offer ID: {state.offerId}</p><p className="break-all font-mono text-xs">Proposal SHA-256: {state.proposalSha256}</p>{state.offerId && <Link className="font-black text-blue-700 hover:underline" href={`/server-offer-review?offer_id=${encodeURIComponent(state.offerId)}`}>Открыть независимую проверку →</Link>}</div>}
      <button className="w-fit rounded-xl bg-blue-700 px-5 py-3 text-sm font-black text-white disabled:opacity-50" disabled={pending} type="submit">{pending ? "Сохраняю…" : "Сохранить exact BOM/КП proposal"}</button>
    </form>
  );
}
