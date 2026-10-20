"use client";

import { useActionState, useState } from "react";

import { submitServerOfferReview, type ServerOfferReviewState } from "./actions";
import type { ServerOfferReviewRecord } from "@/lib/procurement-api";

const initialState: ServerOfferReviewState = {};

export function ServerOfferReviewForm({ record }: { record: ServerOfferReviewRecord }) {
  const [state, action, pending] = useActionState(submitServerOfferReview, initialState);
  const [bomScope, setBomScope] = useState("");
  const [commercial, setCommercial] = useState("");
  const proposal = record.evidence.proposal;
  const requirements = record.evidence.requirement_set.proposal.entries;
  return (
    <form action={action} className="mt-6 grid gap-5" noValidate>
      <input name="offer-id" type="hidden" value={proposal.offer_id} />
      <input name="proposal-sha256" type="hidden" value={proposal.proposal_sha256} />
      <input name="requirement-count" type="hidden" value={requirements.length} />
      <section className="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="m-0 text-xl font-black">Построчное техническое решение</h2>
        <p className="m-0 text-sm leading-6 text-slate-600">
          Для каждой строки выберите verdict, напишите основание и укажите одну или несколько
          строк BOM либо коммерческие условия. UNKNOWN может оставаться без evidence.
        </p>
        {requirements.map((entry) => (
          <fieldset className="grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4" key={entry.ordinal}>
            <legend className="px-1 text-sm font-black">Требование {entry.ordinal}: {entry.raw_name}</legend>
            <p className="m-0 whitespace-pre-wrap text-sm"><strong>ТЗ:</strong> {entry.raw_value}</p>
            <p className="m-0 font-mono text-xs text-slate-500">{entry.provenance.document_id} · {entry.provenance.locator}</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="grid gap-1 text-sm font-bold">Verdict
                <select defaultValue="" disabled={pending} name={`requirement-${entry.ordinal}-status`} required>
                  <option value="">Выберите явно</option><option value="PASS">PASS</option>
                  <option value="FAIL">FAIL</option><option value="UNKNOWN">UNKNOWN</option>
                </select>
              </label>
              <label className="grid gap-1 text-sm font-bold">Evidence (Ctrl/Cmd для нескольких)
                <select disabled={pending} multiple name={`requirement-${entry.ordinal}-evidence`} size={Math.min(proposal.bom_lines.length + 1, 6)}>
                  {proposal.bom_lines.map((line) => <option key={line.ordinal} value={`BOM_LINE:${line.ordinal}`}>BOM {line.ordinal} · {line.sku}</option>)}
                  <option value="COMMERCIAL_TERMS">Коммерческие условия</option>
                </select>
              </label>
            </div>
            <label className="grid gap-1 text-sm font-bold">Основание строки
              <textarea disabled={pending} maxLength={2000} name={`requirement-${entry.ordinal}-reason`} required rows={3} />
            </label>
          </fieldset>
        ))}
      </section>
      <section className="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="m-0 text-xl font-black">Итоговые attestations</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="grid gap-1 text-sm font-bold">Полнота BOM
            <select disabled={pending} name="bom-scope-assessment" onChange={(event) => setBomScope(event.target.value)} required value={bomScope}>
              <option value="">Выберите явно</option><option value="CONFIRMED_COMPLETE">CONFIRMED_COMPLETE</option>
              <option value="CONFIRMED_INCOMPLETE">CONFIRMED_INCOMPLETE</option><option value="UNRESOLVED">UNRESOLVED</option>
            </select>
          </label>
          <label className="grid gap-1 text-sm font-bold">Коммерческие условия
            <select disabled={pending} name="commercial-terms-assessment" onChange={(event) => setCommercial(event.target.value)} required value={commercial}>
              <option value="">Выберите явно</option><option value="CONFIRMED">CONFIRMED</option>
              <option value="REJECTED">REJECTED</option><option value="UNRESOLVED">UNRESOLVED</option>
            </select>
          </label>
        </div>
        <label className="grid gap-1 text-sm font-bold">Общее основание
          <textarea disabled={pending} maxLength={4000} name="reason" required rows={5} />
        </label>
        <p className="m-0 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm leading-6 text-blue-950">
          Итоговый PASS, FAIL или UNKNOWN вычисляет API. Подтверждённый FAIL блокирует предложение;
          PASS возможен только при PASS каждой строки, полном BOM и действующем полном КП.
        </p>
        {state.error && <p className="m-0 text-sm font-bold text-red-800" role="alert">{state.error}</p>}
        {state.success && <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950" role="status"><p className="m-0 font-black">{state.success}</p><p className="mb-0 mt-2 break-all font-mono text-xs">Decision SHA-256: {state.decisionSha256}</p></div>}
        <button className="w-fit rounded-xl bg-blue-700 px-5 py-3 text-sm font-black text-white disabled:opacity-50" disabled={pending || !bomScope || !commercial} type="submit">{pending ? "Сохраняю…" : "Сохранить terminal review"}</button>
      </section>
    </form>
  );
}
