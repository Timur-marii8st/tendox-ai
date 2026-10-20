"use client";

import { useActionState } from "react";
import { claimSubmission, type AdmissionFormState } from "./actions";
import type { ApplicationSubmissionIntent, ApplicationSubmissionApproval } from "@/lib/procurement-api";

export function ClaimForm({ intent, decision }: {
  intent: ApplicationSubmissionIntent;
  decision: ApplicationSubmissionApproval;
}) {
  const [state, action, pending] = useActionState<AdmissionFormState, FormData>(claimSubmission, {});
  return <form action={action} className="mt-6 grid gap-4 rounded-2xl border border-amber-300 bg-amber-50 p-5">
    <input name="package-id" type="hidden" value={intent.package_id} />
    <input name="action-id" type="hidden" value={intent.request.action_id} />
    <input name="payload-sha" type="hidden" value={intent.request.payload_sha256} />
    <input name="approval-sha" type="hidden" value={decision.decision_sha256} />
    <h2 className="m-0 text-xl font-black">Однократный admission</h2>
    <p className="m-0 text-sm">Сервер ещё раз проверит действительность approval, deadline, участие, floor и оригинальные байты каждого файла. Затем навсегда зарезервирует единственную попытку исполнения.</p>
    <label className="flex gap-2 text-sm"><input name="acknowledged" required type="checkbox" value="yes" />Понимаю, что approval будет использован один раз, но заявка сейчас не подписывается и не отправляется.</label>
    <button className="rounded-lg bg-slate-950 px-4 py-3 font-black text-white disabled:opacity-50" disabled={pending} type="submit">{pending ? "Проверяем и сохраняем…" : "Зарезервировать попытку"}</button>
    {state.error && <p className="font-bold text-red-700" role="alert">{state.error}</p>}
    {state.success && <p className="font-bold text-emerald-700" role="status">{state.success}</p>}
  </form>;
}
