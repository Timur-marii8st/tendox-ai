"use client";

import { useActionState } from "react";

import { submitEconomics, type EconomicsState } from "./actions";
import type { ServerOfferEconomicsRecord } from "@/lib/procurement-api";

const initial: EconomicsState = {};
const kinds = ["base", "realistic", "conservative"] as const;
const costs = [
  ["packaging", "Упаковка"], ["logistics", "Логистика"],
  ["loading_unloading", "Погрузка/разгрузка"], ["storage", "Хранение"],
  ["installation", "Монтаж"], ["payroll_travel", "Персонал/командировки"],
  ["subcontracting", "Субподряд"], ["insurance", "Страхование"],
  ["finance", "Финансирование"], ["bank_guarantee", "Банковская гарантия"],
  ["platform_fees", "Комиссии площадки"], ["taxes", "Налоги кроме НДС"],
  ["certification", "Сертификация"], ["warranty", "Гарантия"],
  ["risk_reserve", "Резерв рисков"], ["penalty_reserve", "Резерв штрафов"],
  ["other", "Прочее"],
] as const;

export function EconomicsForm({ record }: { record: ServerOfferEconomicsRecord }) {
  const [state, action, pending] = useActionState(submitEconomics, initial);
  const proposal = record.evidence.offer_review.evidence.proposal;
  const decision = record.evidence.offer_review.decision;
  if (!decision) return null;
  return <form action={action} className="mt-6 grid gap-5" noValidate>
    <input name="case-id" type="hidden" value={record.evidence.case.case_id} />
    <input name="case-version" type="hidden" value={record.evidence.case.version} />
    <input name="offer-id" type="hidden" value={proposal.offer_id} />
    <input name="proposal-sha256" type="hidden" value={proposal.proposal_sha256} />
    <input name="review-sha256" type="hidden" value={decision.decision_sha256} />
    <p className="m-0 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-950">
      Goods и НДС берутся сервером из PASS КП: <strong>{proposal.commercial_terms.amount_ex_vat} RUB</strong>, НДС <strong>{proposal.commercial_terms.nds_rate}</strong>. Каждую другую статью заполните явно; ноль означает подтверждённый нулевой расход.
    </p>
    <div className="grid gap-5 xl:grid-cols-3">{kinds.map((kind) => <fieldset className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" key={kind}>
      <legend className="px-2 text-lg font-black">{kind}</legend>
      <label className="grid gap-1 text-sm font-bold">Выручка без НДС<input inputMode="decimal" name={`${kind}-revenue`} required /></label>
      {costs.map(([name, label]) => <label className="grid gap-1 text-xs font-bold" key={name}>{label}<input inputMode="decimal" name={`${kind}-${name}`} placeholder="введите 0 явно" required /></label>)}
      <label className="grid gap-1 text-sm font-bold">Допущения<textarea maxLength={2000} name={`${kind}-assumptions`} required rows={4} /></label>
    </fieldset>)}</div>
    <p className="m-0 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">Сохранение создаёт immutable economics package. Оно не обновляет кейс и не выдаёт PARTICIPATE.</p>
    {state.error && <p className="m-0 font-bold text-red-800" role="alert">{state.error}</p>}
    {state.success && <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950" role="status"><strong>{state.success}</strong><p className="mb-0 break-all font-mono text-xs">Package SHA-256: {state.packageSha256}</p></div>}
    <button className="w-fit rounded-xl bg-blue-700 px-5 py-3 text-sm font-black text-white disabled:opacity-50" disabled={pending} type="submit">{pending ? "Сохраняю…" : "Сохранить complete economics"}</button>
  </form>;
}
