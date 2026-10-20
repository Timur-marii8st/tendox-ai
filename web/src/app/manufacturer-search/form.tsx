"use client";

import { useActionState } from "react";

import { startManufacturerSearch, type ManufacturerSearchFormState } from "./actions";

const initial: ManufacturerSearchFormState = {};

export function ManufacturerSearchForm({ commandId }: { commandId: string }) {
  const [state, action, pending] = useActionState(startManufacturerSearch, initial);
  return <section className="mt-6 rounded-2xl border border-blue-200 bg-white p-5 shadow-sm">
    <h2 className="m-0 text-xl font-black">Новый поиск</h2>
    <p className="mt-2 text-sm leading-6 text-slate-600">Запуск сохранит отдельный snapshot ответа официального реестра. Повторное отображение страницы поиск не запускает.</p>
    <form action={action} className="mt-4 grid gap-3">
      <input name="command-id" type="hidden" value={commandId} />
      <label className="grid gap-2 text-sm font-bold" htmlFor="manufacturer-query">Товар, модель или артикул
        <input className="rounded-lg border border-slate-300 p-3 font-normal" id="manufacturer-query" maxLength={80} name="query" placeholder="Например, промышленный насос" required />
      </label>
      <button className="w-fit rounded-lg bg-slate-950 px-5 py-2 font-bold text-white disabled:opacity-50" disabled={pending} type="submit">{pending ? "Сохраняю поиск…" : "Искать в реестре ЕАЭС"}</button>
    </form>
    {state.error && <p className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-900" role="alert">{state.error}</p>}
    {state.report && <p className="mt-4 rounded-lg bg-blue-50 p-3 text-sm text-blue-950" role="status">Поиск сохранён: {state.report.run_id}. Статус: {state.report.status}.</p>}
  </section>;
}
