"use client";
import { useActionState } from "react";
import { createRfq, type RfqState } from "./actions";

export function ManufacturerRfqForm({ commandId, runId, recordId, proposalId, decisionId }: { commandId: string; runId: string; recordId: string; proposalId: string; decisionId: string }) {
  const [state, action, pending] = useActionState(createRfq, {} as RfqState);
  return <form action={action} className="mt-6 grid gap-3 rounded-xl border bg-white p-5">
    <input type="hidden" name="command_id" value={commandId} /><input type="hidden" name="run_id" value={runId} /><input type="hidden" name="record_id" value={recordId} /><input type="hidden" name="proposal_id" value={proposalId} /><input type="hidden" name="decision_id" value={decisionId} />
    <h2 className="text-xl font-black">Ручные данные черновика</h2>
    <p className="text-sm text-slate-600">Эти поля вводятся оператором и получают manual provenance. Требования ниже не считаются полным ТЗ.</p>
    <label>Количество<input className="mt-1 w-full border p-2" name="quantity" inputMode="decimal" maxLength={100} required /></label>
    <label>Исходная единица количества<input className="mt-1 w-full border p-2" name="unit_raw" maxLength={100} placeholder="упаковка, пачка, лист" required /></label>
    <label>Основание количества<input className="mt-1 w-full border p-2" name="quantity_basis_raw" maxLength={500} placeholder="Из какой позиции и документа взято количество" required /></label>
    <label>Ручные требования, по одному на строку<textarea className="mt-1 min-h-40 w-full border p-2" name="requirements" maxLength={10019} required /></label>
    <label>Адрес поставки<input className="mt-1 w-full border p-2" name="delivery_address_raw" maxLength={1000} required /></label>
    <label>Желаемый срок поставки<input className="mt-1 w-full border p-2" name="desired_delivery_raw" maxLength={500} required /></label>
    <label>Ответить до (МСК, UTC+03:00)<input className="mt-1 w-full border p-2" name="reply_due_at" type="datetime-local" required /></label>
    <button className="rounded bg-blue-700 px-4 py-2 text-white disabled:opacity-50" disabled={pending}>{pending ? "Сохраняю…" : "Сохранить неизменяемый черновик"}</button>
    {state.error && <p role="alert" className="text-red-700">{state.error}</p>}
  </form>;
}
