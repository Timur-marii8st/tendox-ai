"use client";

import { useActionState } from "react";
import { decideSubmission, type ApprovalFormState } from "./actions";
import type { ApplicationSubmissionIntent } from "@/lib/procurement-api";

export function ApprovalForm({ intent }: { intent: ApplicationSubmissionIntent }) {
  const [state, action, pending] = useActionState<ApprovalFormState, FormData>(decideSubmission, {});
  return <form action={action} className="mt-6 grid gap-4 rounded-2xl border border-slate-200 bg-white p-5">
    <input name="package-id" type="hidden" value={intent.package_id} />
    <input name="action-id" type="hidden" value={intent.request.action_id} />
    <input name="payload-sha" type="hidden" value={intent.request.payload_sha256} />
    <h2 className="m-0 text-xl font-black">Решение по exact payload</h2>
    <label className="grid gap-1 text-sm font-bold">Решение<select className="rounded-lg border border-slate-300 p-2" defaultValue="" name="status" required><option disabled value="">Выберите</option><option value="APPROVED">APPROVED — подтверждаю</option><option value="REJECTED">REJECTED — отклоняю</option></select></label>
    <label className="grid gap-1 text-sm font-bold">Основание<textarea className="min-h-24 rounded-lg border border-slate-300 p-2 font-normal" maxLength={4000} name="reason" required /></label>
    <label className="flex gap-2 text-sm"><input name="acknowledged" type="checkbox" value="yes" />Я сверил адрес назначения, цену и каждый файл с exact пакетом и его SHA-256.</label>
    <p className="m-0 text-sm text-amber-900">Положительное решение действительно не более 15 минут и не позже deadline или срока КП. Этот экран не подписывает и не отправляет заявку.</p>
    <button className="rounded-lg bg-slate-950 px-4 py-3 font-black text-white disabled:opacity-50" disabled={pending} type="submit">{pending ? "Сохраняем…" : "Сохранить решение"}</button>
    {state.error && <p className="font-bold text-red-700" role="alert">{state.error}</p>}
    {state.success && <p className="font-bold text-emerald-700" role="status">{state.success}</p>}
  </form>;
}
