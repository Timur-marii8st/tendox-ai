import Link from "next/link";
import { randomUUID } from "node:crypto";
import { optionalProfile, ProfileApiError, readCapabilities, readProfile, readProfileHistory, readProfileSelection } from "@/lib/company-profile-api";
import { CompanyProfileForm, ProfileAccessForm, ProfileSelectionForm } from "./form";
import { disconnectProfile } from "./actions";

export const dynamic = "force-dynamic";
export const metadata = { title: "Профиль компании — Tendox" };

async function loadProfilePage(version?: number, before?: number) {
  try {
    const capabilities = await readCapabilities();
    const [latest, history, selection] = await Promise.all([optionalProfile(() => readProfile()), readProfileHistory(before), optionalProfile(() => readProfileSelection())]);
    const snapshot = version ? await readProfile(version) : latest;
    const current = !snapshot || snapshot.version === latest?.version;
    return { data: { capabilities, latest, history, selection, snapshot, current } };
  } catch (error) { return { error: error instanceof ProfileApiError ? error.status : 503 }; }
}

export default async function CompanyProfilePage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const query = await searchParams;
  const version = typeof query.version === "string" && /^[1-9]\d*$/.test(query.version) && Number.isSafeInteger(Number(query.version)) ? Number(query.version) : undefined;
  const before = typeof query.before === "string" && /^[1-9]\d*$/.test(query.before) ? Number(query.before) : undefined;
  const result = await loadProfilePage(version, before);
  if (result.error !== undefined) {
    const needsAccess = result.error === 401;
    return <main className="min-h-screen bg-slate-50 p-6 text-slate-950"><div className="mx-auto max-w-3xl"><h1 className="mb-5 text-3xl font-semibold">Профиль компании</h1>{needsAccess ? <ProfileAccessForm /> : <><p role="alert" className="mb-4 rounded-lg bg-red-50 p-4 text-red-900">{result.error === 404 ? "Эта версия профиля не найдена." : result.error === 403 ? "Эта роль не даёт доступ к профилю компании." : "Не удалось загрузить сохранённый профиль. Данные на сервере не изменены."}</p><Link href="/company-profile" className="text-blue-800 underline">Открыть актуальную версию</Link><form action={disconnectProfile} className="mt-4"><button className="text-blue-800 underline">Подключить другой доступ</button></form></>}</div></main>;
  }
  const { capabilities, latest, history, selection, snapshot, current } = result.data!;
    return <main className="min-h-screen bg-slate-50 px-4 py-8 text-slate-950 md:px-8">
      <div className="mx-auto max-w-6xl">
        <header className="mb-6 flex flex-wrap items-start justify-between gap-4"><div><nav className="flex gap-4 text-sm text-blue-800 underline"><Link href="/tender-discovery">Поиск и сравнение закупок</Link><Link href="/">Кейсы</Link></nav><h1 className="mt-2 text-3xl font-semibold">Профиль компании</h1><p className="mt-2 text-slate-600">{snapshot ? `${snapshot.facts["identity.name"].knowledge === "KNOWN" ? snapshot.facts["identity.name"].value : "Название не указано"} · версия ${snapshot.version}` : "Создайте профиль и дополните его по мере необходимости"}</p></div><form action={disconnectProfile}><p className="mb-2 text-sm text-slate-600">Доступ: {capabilities.actor_id}{!capabilities.can_edit && " · только просмотр"}</p><button className="text-sm text-blue-800 underline">Отключить доступ</button></form></header>
        {query.saved === "1" && snapshot && <p role="status" className="mb-5 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-emerald-900">Версия {snapshot.version} сохранена. Можно закрыть страницу и открыть её снова.</p>}
        {query.selected === "1" && selection && <p role="status" className="mb-5 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-emerald-900">Версия {selection.profile_ref.version} выбрана для последующего сравнения.</p>}
        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
          <CompanyProfileForm key={`${snapshot?.version ?? 0}-${capabilities.company_id}`} snapshot={snapshot} capabilities={capabilities} current={current} commandKey={randomUUID()} />
          <aside className="space-y-5 lg:sticky lg:top-6">
            <section className="rounded-xl border border-slate-200 bg-white p-5"><h2 className="text-lg font-semibold">Версия для сравнения</h2><p className="mt-2 text-sm text-slate-600">{selection ? <>Выбрана <Link href={`/company-profile?version=${selection.profile_ref.version}`} className="font-medium text-blue-800 underline">версия {selection.profile_ref.version}</Link>. Выбор сохранится после перезагрузки и не изменится при редактировании профиля.</> : snapshot ? "Пока не выбрана. Выберите одну из сохранённых версий." : "Пока не выбрана. Сначала сохраните профиль."}</p><p className="mt-2 text-sm text-slate-500">Выбор версии не означает допуск к участию.</p>{snapshot && capabilities.can_edit && <ProfileSelectionForm key={snapshot.version} snapshot={snapshot} selectionKey={randomUUID()} />}{selection && <Link href="/tender-discovery" className="mt-3 block text-sm font-semibold text-blue-800 underline">Выбрать закупки из поиска и сравнить</Link>}{selection && <Link href="/procurement-comparison" className="mt-3 block text-sm text-blue-800 underline">Сравнить сохранённые кейсы</Link>}{selection && <Link href={`/company-profile/export?selection=${encodeURIComponent(selection.selection_id)}`} className="mt-3 block text-sm text-blue-800 underline">Скачать выбранную версию для интеграции</Link>}</section>
            <section className="rounded-xl border border-slate-200 bg-white p-5"><h2 className="text-lg font-semibold">История профиля</h2>{latest && <Link href="/company-profile" className="mt-3 block text-sm font-medium text-blue-800 underline">Актуальная версия {latest.version}</Link>}<ul className="mt-3 space-y-3">{history.items.map(item => <li key={item.version}><Link href={`/company-profile?version=${item.version}`} className="font-medium text-blue-800 underline" aria-current={snapshot?.version === item.version ? "page" : undefined}>Версия {item.version}</Link><p className="text-xs text-slate-500">{new Date(item.created_at).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" })} (МСК)</p></li>)}</ul>{!history.items.length && <p className="mt-3 text-sm text-slate-500">Сохранённых версий пока нет.</p>}{history.next_before && <Link href={`/company-profile?before=${history.next_before}`} className="mt-3 block text-sm text-blue-800 underline">Предыдущие версии</Link>}</section>
          </aside>
        </div>
      </div>
    </main>;
}
