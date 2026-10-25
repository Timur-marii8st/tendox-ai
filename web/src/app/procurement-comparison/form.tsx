"use client";

import { startTransition, useActionState, useState } from "react";
import { rub, sameCase, sameProfile, type ComparisonCatalog } from "../../lib/procurement-comparison";
import { compareAction } from "./actions";
import { ComparisonReportView } from "./report";

export function ComparisonForm({ catalog }: { catalog: ComparisonCatalog }) {
  const [state, action, pending] = useActionState(compareAction, {});
  const [selected, setSelected] = useState<string[]>([]);
  const [profile, setProfile] = useState("");
  const refs = catalog.cases.filter(row => selected.includes(row.ref.case_id)).map(row => row.ref);
  const profileRef = catalog.profiles.find(row => JSON.stringify(row.ref) === profile)?.ref;
  const matches = !!state.report && !!profileRef && sameProfile(state.report.profile_ref, profileRef) &&
    state.report.rows.length === refs.length && state.report.rows.every((row, i) => sameCase(row.case_ref, refs[i]));
  return <>
    <form onSubmit={event => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      startTransition(() => action(form));
    }} className="comparison-selection">
      {catalog.selection_id && <input type="hidden" name="selection_id" value={catalog.selection_id} />}
      <fieldset disabled={pending}><legend>1. Выберите от 2 до 5 закупок</legend>
        <p aria-live="polite">Выбрано: {selected.length} из 5</p>
        <div className="comparison-options">{catalog.cases.map(row => <label key={row.ref.case_id}>
          <input type="checkbox" name="cases" value={JSON.stringify(row.ref)} checked={selected.includes(row.ref.case_id)}
            disabled={selected.length >= 5 && !selected.includes(row.ref.case_id)}
            onChange={event => setSelected(event.target.checked ? [...selected, row.ref.case_id] : selected.filter(id => id !== row.ref.case_id))} />
          <span><b>{row.subject}</b><small>v{row.ref.version} · НМЦК {rub(row.nmck_ex_vat)} без НДС · срок {row.deadline}</small></span>
        </label>)}</div>
      </fieldset>
      <fieldset disabled={pending}><legend>2. Выберите сохранённую версию профиля</legend>
        <label htmlFor="comparison-profile">Версия профиля компании</label>
        <select id="comparison-profile" name="profile" required value={profile} onChange={event => setProfile(event.target.value)}>
          <option value="" disabled>Выберите конкретную версию</option>
          {catalog.profiles.map(row => <option key={row.ref.version} value={JSON.stringify(row.ref)}>
            v{row.ref.version} · {row.name} · {row.created_at}
          </option>)}
        </select>
        <p>Выбранная версия остаётся неизменной. Для другой версии сначала сохраните выбор на странице профиля компании.</p>
      </fieldset>
      <button type="submit" disabled={pending || selected.length < 2 || !profile}>{pending ? "Сравниваем…" : "Сравнить выбранные закупки"}</button>
      {state.error && <p role="alert" className="comparison-error">{state.error}</p>}
    </form>
    {state.report && !matches && <p role="status">Выбор изменён. Нажмите «Сравнить», чтобы получить отчёт для новых входов.</p>}
    {state.report && matches && <ComparisonReportView report={state.report} />}
  </>;
}
