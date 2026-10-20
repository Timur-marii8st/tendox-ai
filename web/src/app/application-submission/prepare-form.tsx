"use client";

import { useActionState } from "react";
import { prepareSubmission, type SubmissionFormState } from "./actions";

export function PrepareForm({ packageId, packageSha, reviewSha }: {
  packageId: string; packageSha: string; reviewSha: string;
}) {
  const [state, action, pending] = useActionState<SubmissionFormState, FormData>(prepareSubmission, {});
  return <form action={action} className="mt-6 grid gap-4 rounded-2xl border border-slate-200 bg-white p-5">
    <input name="package-id" type="hidden" value={packageId} />
    <input name="package-sha" type="hidden" value={packageSha} />
    <input name="review-sha" type="hidden" value={reviewSha} />
    <h2 className="m-0 text-xl font-black">Подготовить exact команду</h2>
    <p className="m-0 text-sm">Укажите точный HTTPS адрес площадки, который согласующий сверит с заявкой. Сервер добавит цену и файлы из проверенного пакета.</p>
    <label className="grid gap-1 text-sm font-bold">Адрес назначения
      <input className="rounded-lg border border-slate-300 p-3 font-normal" maxLength={2000} name="destination" placeholder="https://…" required type="url" />
    </label>
    <button className="rounded-lg bg-slate-950 px-4 py-3 font-black text-white disabled:opacity-50" disabled={pending} type="submit">{pending ? "Сохраняем…" : "Сохранить команду"}</button>
    {state.error && <p className="font-bold text-red-700" role="alert">{state.error}</p>}
    {state.success && <p className="font-bold text-emerald-700" role="status">{state.success}</p>}
  </form>;
}
