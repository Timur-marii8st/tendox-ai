import type { Metadata } from "next";
import Link from "next/link";

import { TenderDiscoveryForm } from "./form";
import { MixedComparisonProvider } from "./mixed-comparison";
import { IndexedSearch } from "./indexed-search";
import { Indexed223Search } from "./indexed-223-search";
import { TenderDiscoveryWorkflow } from "./workflow";
import { loadEis223RegionalCoverage } from "./actions";
import { RegionalCoverage } from "./regional-coverage";

export const metadata: Metadata = { title: "Поиск закупок ЕИС — Syurai Procurement" };
export const dynamic = "force-dynamic";

export default async function TenderDiscoveryPage() {
  const regionalCoverage = await loadEis223RegionalCoverage();
  return <main className="min-h-screen bg-slate-50 text-slate-950">
    <div className="mx-auto w-[min(1100px,calc(100%-2rem))] py-8">
      <Link className="text-sm font-bold text-blue-700" href="/">← Дела</Link>
      <h1 className="mt-4 text-3xl font-black sm:text-5xl">Найти и разобрать закупку</h1>
      <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">
        Поиск использует загруженную часть ЕИС. Полный каталог и свежесть не подтверждены.
        Уточняйте товар: «бумага А4» сужает запрос «бумага». Совпадение слов ещё не означает соответствие ТЗ.
      </p>
      <ol aria-label="От поиска к решению" className="mt-6 grid gap-3 sm:grid-cols-4">
        {[
          ["1", "Обзор", "Сколько найдено, какие способы закупки, что не показано"],
          ["2", "Отбор", "Откройте условия и выберите 2–3 закупки для сравнения"],
          ["3", "Проверка ТЗ", "Получите документы и подтвердите полный набор требований"],
          ["4", "КП и экономика", "Действующее полное КП, три сценария, затем решение"],
        ].map(([step, title, description]) => <li key={step} className="rounded-xl border border-slate-200 bg-white p-4">
          <span className="text-xs font-bold text-blue-700">ШАГ {step} →</span>
          <p className="mt-1 font-bold">{title}</p><p className="mt-2 text-xs leading-5 text-slate-600">{description}</p>
        </li>)}
      </ol>
      <MixedComparisonProvider>
        <IndexedSearch />
        <Indexed223Search />
      </MixedComparisonProvider>
      <details className="mt-8 rounded-2xl border border-slate-200 bg-white p-5">
        <summary className="cursor-pointer text-lg font-bold">Состояние загрузки каталога · 223-ФЗ</summary>
        <RegionalCoverage initial={regionalCoverage} />
      </details>
      <details className="mt-8 rounded-2xl border border-slate-200 bg-white p-5">
        <summary className="cursor-pointer text-lg font-bold">Расширенный поиск по публичной выдаче ЕИС</summary>
        <TenderDiscoveryWorkflow />
      </details>
      <details className="mt-8 rounded-2xl border border-slate-200 bg-white p-5">
        <summary className="cursor-pointer text-lg font-black">Разовый поиск и XML/ZIP-выгрузка</summary>
        <p className="mt-2 text-sm text-slate-600">Резервный режим для одной страницы ЕИС или заранее сохранённой выгрузки без сессии.</p>
        <TenderDiscoveryForm />
      </details>
    </div>
  </main>;
}
