"use client";

import { useActionState, useState } from "react";
import Link from "next/link";
import { changedFacts, factInput, factLabel, profileFields, unknownFact, type FactInput, type ProfileCapabilities, type ProfileField, type ProfileSnapshot } from "@/lib/company-profile";
import { connectProfile, saveProfileAction, selectProfileAction } from "./actions";

const inputClass = "mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-950 focus:border-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50";

export function ProfileAccessForm() {
  const [state, action, pending] = useActionState(connectProfile, {});
  return <form action={action} className="max-w-lg space-y-4 rounded-xl border border-slate-200 bg-white p-6">
    <h2 className="text-xl font-semibold">Подключить персональный доступ</h2>
    <p className="text-sm text-slate-600">Используйте действующий ключ вашей компании. Права и компания проверяются сервером; общий ключ пилота не назначает владельца.</p>
    <label className="block font-medium" htmlFor="credential">Персональный ключ доступа</label>
    <input id="credential" name="credential" type="password" autoComplete="off" required className={inputClass} />
    {state.error && <p role="alert" className="text-red-800">{state.error}</p>}
    <button disabled={pending} className="rounded-lg bg-blue-700 px-4 py-2 font-medium text-white disabled:opacity-50">{pending ? "Проверка доступа…" : "Подключиться"}</button>
  </form>;
}

function SourceNote({ snapshot, field }: { snapshot: ProfileSnapshot | null; field: ProfileField }) {
  const sources = snapshot?.facts[field.path]?.sources;
  if (!sources?.length) return null;
  return <details className="mt-1 text-xs text-slate-500"><summary className="cursor-pointer">Источник сохранённого значения</summary>{sources.map((source, index) => <p key={index}>Ручной ввод: {source.recorded_by}, {new Date(source.recorded_at).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" })} (МСК)</p>)}</details>;
}

export function CompanyProfileForm({ snapshot, capabilities, current, commandKey }: { snapshot: ProfileSnapshot | null; capabilities: ProfileCapabilities; current: boolean; commandKey: string }) {
  const [state, action, pending] = useActionState(saveProfileAction, {});
  const [draft, setDraft] = useState<Record<string, FactInput>>(() => Object.fromEntries(profileFields.map(field => [field.path, factInput(snapshot?.facts[field.path])])));
  const [confirmed, setConfirmed] = useState(false);
  const changes = changedFacts(snapshot, draft, capabilities.blocked_fields);
  const changedPaths = Object.keys(changes);
  const editable = capabilities.can_edit && current;
  const set = (path: string, fact: FactInput) => { setDraft(previous => ({ ...previous, [path]: fact })); setConfirmed(false); };
  const setText = (field: ProfileField, value: string) => {
    if (!value.trim()) return set(field.path, unknownFact());
    const result = field.kind === "list" ? value.split(/\r?\n/).map(item => item.trim()).filter(Boolean) : field.kind === "decimal" ? value.trim().replace(",", ".") : value;
    set(field.path, { knowledge: "KNOWN", value: result, reason: null });
  };
  const groups = ["Реквизиты", "Деятельность", "География поиска", ...(capabilities.critical_settings_editable ? ["Критические настройки"] : [])];
  return <form action={action} onReset={event => event.preventDefault()} className="space-y-6">
    <input type="hidden" name="command-key" value={commandKey} />
    <input type="hidden" name="command" value={JSON.stringify({ schema_version: "company-profile-save-command-v1", expected_version: snapshot?.version ?? 0, changes })} />
    {!current && <p className="rounded-lg border border-amber-200 bg-amber-50 p-4">Открыта предыдущая версия. Она сохранена неизменной. <Link href="/company-profile" className="font-medium text-blue-800 underline">Редактировать актуальную версию</Link></p>}
    {!capabilities.can_edit && <p className="rounded-lg bg-slate-100 p-4">Ваш доступ позволяет только просмотр.</p>}
    {groups.map(group => <section key={group} className="rounded-xl border border-slate-200 bg-white p-5 md:p-6">
      <h2 className="mb-4 text-xl font-semibold">{group}</h2>
      {group === "География поиска" && <p className="mb-4 text-sm text-slate-600">Где вы хотите искать закупки. Эти сведения не подтверждают сроки и возможность доставки.</p>}
      <div className="grid gap-5 md:grid-cols-2">{profileFields.filter(field => field.group === group).map(field => {
        const fact = draft[field.path];
        const id = `profile-${field.path}`;
        const fieldEditable = editable && !capabilities.blocked_fields.includes(field.path);
        return <div key={field.path} className={field.kind === "list" || field.path === "business_description" ? "md:col-span-2" : ""}>
          <label htmlFor={id} className="block font-medium">{field.label}</label>
          {field.hint && <p id={`${id}-hint`} className="mt-1 text-sm text-slate-500">{field.hint}</p>}
          {field.kind === "boolean" ? <select id={id} className={inputClass} disabled={!fieldEditable} value={fact.knowledge === "KNOWN" ? String(fact.value) : "unknown"} onChange={event => set(field.path, event.target.value === "unknown" ? unknownFact() : { knowledge: "KNOWN", value: event.target.value === "true", reason: null })}>
            <option value="unknown">Не указано</option><option value="true">Да</option><option value="false">Нет</option>
          </select> : <>
            {field.optional && <select aria-label={`${field.label}: применимость`} className={inputClass} disabled={!fieldEditable} value={fact.knowledge === "NOT_APPLICABLE" ? "na" : "value"} onChange={event => set(field.path, event.target.value === "na" ? { knowledge: "NOT_APPLICABLE", value: null, reason: "DECLARED_NOT_APPLICABLE" } : unknownFact())}>
              <option value="value">Указать значение или оставить неизвестным</option><option value="na">{field.path === "geography.max_distance_km" ? "Нет ограничения" : "Не применяется"}</option>
            </select>}
            {fact.knowledge !== "NOT_APPLICABLE" && (field.kind === "list" ? <textarea id={id} aria-describedby={field.hint ? `${id}-hint` : undefined} rows={3} disabled={!fieldEditable} className={inputClass} value={Array.isArray(fact.value) ? fact.value.join("\n") : ""} onChange={event => setText(field, event.target.value)} /> : <input id={id} aria-describedby={field.hint ? `${id}-hint` : undefined} type="text" inputMode={field.kind === "decimal" ? "decimal" : undefined} disabled={!fieldEditable} className={inputClass} value={typeof fact.value === "string" ? fact.value : ""} onChange={event => setText(field, event.target.value)} />)}
            {field.kind === "list" && (!fact.value || (Array.isArray(fact.value) && fact.value.length === 0)) && <label className="mt-2 flex items-center gap-2 text-sm text-slate-600"><input type="checkbox" disabled={!fieldEditable} checked={fact.knowledge === "KNOWN"} onChange={event => set(field.path, event.target.checked ? { knowledge: "KNOWN", value: [], reason: null } : unknownFact())} />Подтверждаю, что список пуст</label>}
          </>}
          <SourceNote snapshot={snapshot} field={field} />
        </div>;
      })}</div>
    </section>)}
    <details className="rounded-xl border border-amber-200 bg-amber-50 p-5">
      <summary className="cursor-pointer font-semibold">{capabilities.critical_settings_editable ? "Запреты пока не поддерживаются" : "Финансовые лимиты, разрешения и запреты — недоступны для изменения"}</summary>
      <p className="mt-3 text-sm text-amber-950">{capabilities.critical_settings_editable ? "Юридические и коммерческие запреты остаются неизвестными: их структурированный контракт и источники ещё не реализованы." : "Критические настройки требуют подтверждённого владельца компании. Обычный оператор не получает полномочия владельца."}</p>
      <dl className="mt-4 grid gap-2 text-sm md:grid-cols-2">{profileFields.filter(field => field.group === "Критические настройки").map(field => <div key={field.path}><dt className="font-medium">{field.label}</dt><dd>{factLabel(snapshot?.facts[field.path])}</dd></div>)}</dl>
    </details>
    {editable && <section className="rounded-xl border border-slate-200 bg-white p-5">
      <h2 className="text-xl font-semibold">{snapshot ? "Изменения перед сохранением" : "Первое сохранение"}</h2>
      <p className="mt-2 text-sm text-slate-600">Заполнять всё сразу не нужно. Пустые поля сохранятся как неизвестные. Каждое сохранение создаёт самостоятельную версию и не меняет ранее созданные кейсы.</p>
      {changedPaths.length ? <div className="my-4 overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr className="border-b"><th className="p-2">Поле</th><th className="p-2">Было</th><th className="p-2">Стало</th></tr></thead><tbody>{changedPaths.map(path => <tr key={path} className="border-b border-slate-100"><th className="p-2 font-medium">{profileFields.find(field => field.path === path)?.label}</th><td className="p-2">{factLabel(snapshot?.facts[path])}</td><td className="p-2">{factLabel(changes[path])}</td></tr>)}</tbody></table></div> : <p className="my-4 text-sm text-slate-500">{snapshot ? "Изменений нет." : "Можно сохранить пустой профиль и дополнить его позже."}</p>}
      <label className="flex items-start gap-2"><input name="confirmed" value="yes" type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} className="mt-1" />Я проверил точный список изменений и подтверждаю сохранение</label>
      {state.error && <p role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-red-900">{state.error} <Link href="/company-profile" className="underline">Открыть актуальную версию</Link></p>}
      <button type="submit" disabled={pending || !confirmed || (!!snapshot && changedPaths.length === 0)} className="mt-4 rounded-lg bg-blue-700 px-5 py-2.5 font-semibold text-white disabled:opacity-50">{pending ? "Сохранение…" : snapshot ? "Сохранить новую версию" : "Сохранить профиль"}</button>
    </section>}
  </form>;
}

export function ProfileSelectionForm({ snapshot, selectionKey }: { snapshot: ProfileSnapshot; selectionKey: string }) {
  const [state, action, pending] = useActionState(selectProfileAction, {});
  return <form action={action} className="mt-4">
    <input type="hidden" name="version" value={snapshot.version} />
    <input type="hidden" name="snapshot-sha" value={snapshot.snapshot_sha256} />
    <input type="hidden" name="selection-key" value={selectionKey} />
    <button disabled={pending} className="w-full rounded-lg border border-blue-700 bg-white px-3 py-2 text-sm font-semibold text-blue-800 disabled:opacity-50">{pending ? "Сохранение выбора…" : `Выбрать версию ${snapshot.version} для сравнения`}</button>
    {state.error && <p role="alert" className="mt-2 text-sm text-red-800">{state.error}</p>}
  </form>;
}
