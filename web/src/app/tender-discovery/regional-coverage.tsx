"use client";

import { useState, useTransition } from "react";

import {
  loadEis223RegionalCoverage,
  type Eis223RegionalCoverageState,
} from "./actions";

const reasonText: Record<string, string> = {
  OFFICIAL_REGION_CATALOG_MISSING: "Официальный список регионов ещё не загружен.",
  EXACT_PLANNED_SCOPE_ONLY: "Статус относится только к зафиксированному плану ниже.",
};

function date(value: string | null): string {
  return value ? new Intl.DateTimeFormat("ru-RU").format(new Date(`${value}T00:00:00Z`)) : "—";
}

function dateTime(value: string | null): string {
  return value ? new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "—";
}

function officialCatalogUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.hostname === "zakupki.gov.ru" &&
      url.pathname === "/epz/nsi/kladr/chooseRegion.html" ? url.toString() : null;
  } catch {
    return null;
  }
}

export function RegionalCoverage({ initial }: { initial: Eis223RegionalCoverageState }) {
  const [state, setState] = useState(initial);
  const [pending, startTransition] = useTransition();
  const coverage = state.result;
  const missingCatalog = Boolean(coverage && !coverage.catalog_sha256);
  const catalogUrl = officialCatalogUrl(coverage?.catalog_source_url ?? null);
  const scope = coverage?.scope_status === "COMPLETE"
    ? "Зафиксированный план на выбранную пару дат обработан полностью."
    : coverage?.scope_status === "PARTIAL"
      ? "Обработка зафиксированного плана продолжается."
      : "Полнота зафиксированного плана пока не определена.";

  return <section aria-labelledby="regional-coverage-title" className="mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 id="regional-coverage-title" className="text-xl font-black">Охват и обновление 223-ФЗ</h2>
        <p className="mt-1 text-sm text-slate-600">{scope} Свежесть сведений пока не подтверждена.</p>
      </div>
      <button type="button" disabled={pending} onClick={() => startTransition(async () => setState(await loadEis223RegionalCoverage()))}
        className="rounded-lg border border-blue-700 px-3 py-2 text-sm font-bold text-blue-700 disabled:opacity-50">
        {pending ? "Обновление…" : "Обновить данные"}
      </button>
    </div>
    {state.error && <p role="alert" className="mt-3 text-sm text-red-700">{state.error}</p>}
    {missingCatalog && <p className="mt-4 rounded-lg bg-amber-50 p-3 text-sm font-semibold text-amber-900">
      Официальный список регионов ещё не загружен. Общероссийский охват не подтверждён.
    </p>}
    {coverage && !missingCatalog && <>
      {(coverage.catalog_check_status === "FAILED" || coverage.catalog_check_status === "REVIEW_REQUIRED") &&
        <p className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
          {coverage.catalog_check_status === "REVIEW_REQUIRED"
            ? "В новом списке регионов исчезли коды. Сохраняем прежний охват до проверки."
            : "Последняя проверка списка регионов не завершилась успешно. Загрузка использует ранее проверенный список."}
        </p>}
      <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <div><dt className="text-slate-500">Регионов в списке</dt><dd className="text-lg font-black">{coverage.catalog_regions}</dd></div>
        <div><dt className="text-slate-500">Регионов начато</dt><dd className="text-lg font-black">{coverage.regions_attempted}</dd></div>
        <div><dt className="text-slate-500">Регионов завершено</dt><dd className="text-lg font-black">{coverage.regions_terminal}</dd></div>
        <div><dt className="text-slate-500">Отставание даты источника</dt><dd className="text-lg font-black">{coverage.source_day_lag ?? "—"}{coverage.source_day_lag !== null && " дн."}</dd></div>
      </dl>
      <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-100" aria-label={`Обработано ${coverage.attempted} из ${coverage.planned}`}>
        <div className="h-full bg-blue-600" style={{ width: `${coverage.planned ? Math.min(100, coverage.attempted / coverage.planned * 100) : 0}%` }} />
      </div>
      <p className="mt-2 text-sm">Запланировано {coverage.planned}; попыток {coverage.attempted}; завершено {coverage.synced + coverage.no_data} (загружено {coverage.synced}, без данных {coverage.no_data}); ещё не начато {coverage.unattempted}; с ошибкой {coverage.failed}.</p>
      {(coverage.old_gaps > 0 || coverage.failed > 0) && <p className="mt-2 text-sm font-semibold text-amber-900">
        Требуют повторной проверки: {coverage.failed}; прежних пробелов: {coverage.old_gaps}{coverage.oldest_gap_day ? `, самый ранний — ${date(coverage.oldest_gap_day)}` : ""}.
      </p>}
      <details className="mt-4 border-t pt-3 text-sm">
        <summary className="cursor-pointer font-bold">Даты и источник расчёта</summary>
        <dl className="mt-2 grid gap-2 sm:grid-cols-2">
          <div><dt className="text-slate-500">Пара дат плана</dt><dd>{date(coverage.start_day)} — {date(coverage.end_day)}</dd></div>
          <div><dt className="text-slate-500">Проверено</dt><dd>{dateTime(coverage.checked_at)}</dd></div>
          <div><dt className="text-slate-500">Список регионов получен</dt><dd>{dateTime(coverage.catalog_observed_at)}</dd></div>
          <div><dt className="text-slate-500">Список этого плана повторно проверен</dt><dd>{dateTime(coverage.catalog_last_success_at)}</dd></div>
          <div><dt className="text-slate-500">Последний принятый список проверен</dt><dd>{dateTime(coverage.latest_catalog_checked_at)}</dd></div>
          <div><dt className="text-slate-500">Все окна плана наблюдались к</dt><dd>{dateTime(coverage.observation_watermark)}</dd></div>
        </dl>
        {coverage.latest_catalog_sha256 !== coverage.catalog_sha256 &&
          <p className="mt-2 text-slate-600">Обновлённый список регионов будет применён в следующем плане. Текущий план сохраняет свой состав.</p>}
        <p className="mt-2">
          {catalogUrl
            ? <a className="font-semibold text-blue-700 underline" href={catalogUrl} rel="noreferrer" target="_blank">Публичный справочник регионов ЕИС</a>
            : "Источник списка регионов сохранён без публичной ссылки."}
          {coverage.catalog_scope === "PUBLIC_KLADR_SELECTOR" && " · Публичный выбор региона; актуальность записей НСИ не заявлена."}
          {coverage.catalog_scope === "NSI_SUBJECT_RF" && " · Справочник субъектов РФ ЕИС."}
        </p>
        <p className="mt-2 text-slate-600">{reasonText[coverage.reason] ?? "Результат требует проверки по сохранённым данным источника."}</p>
        <p className="mt-1 text-slate-600">Технический статус: охват {coverage.coverage}, свежесть {coverage.freshness}.</p>
      </details>
    </>}
  </section>;
}
