"use client";

import { useActionState, useState, useTransition } from "react";
import type { DocumentSelectionResult, EisRefreshStatus } from "@/lib/procurement-api";

import { searchIndexed, type IndexedSearchState } from "./actions";
import { IndexedDocuments } from "./indexed-documents";
import { HistoricalProtocols } from "./historical-protocols";
import { HistoricalAnalogs } from "./historical-analogs";
import { AddToMixedComparison, useMixedBasket } from "./mixed-comparison";
import { IndexedComparison } from "./indexed-comparison";
import { prepareTopIndexedDocuments, loadEisRefresh } from "./actions";
import { ResultExplorer, ResultRow } from "./result-explorer";
import { PagedResults } from "./paged-results";
import { loadIndexedSearchPage } from "./actions";

export function IndexedSearch() {
  const basket = useMixedBasket();
  const [state, action, pending] = useActionState(searchIndexed, {} as IndexedSearchState);
  const [query, setQuery] = useState("");
  const [regions, setRegions] = useState("50,77,78");
  const [refreshRequested, setRefreshRequested] = useState(true);
  const [includeHistory, setIncludeHistory] = useState(false);
  const [selection, setSelection] = useState<DocumentSelectionResult>();
  const [selectionError, setSelectionError] = useState<string>();
  const [preparing, startPreparing] = useTransition();
  const [progress, setProgress] = useState<EisRefreshStatus>();
  const [progressError, setProgressError] = useState<string>();
  const [checking, startChecking] = useTransition();
  const refresh = progress?.request.request_id === state.refresh?.request.request_id ? progress : state.refresh;
  return <section className="mt-8 rounded-2xl border border-blue-200 bg-white p-5 shadow-sm">
    <h2 className="text-xl font-black">Найти закупки · 44-ФЗ</h2>
    <p className="mt-2 text-sm text-slate-600">
      Сравниваются последние версии карточек из уже загруженных окон ЕИС.
      Выгода остаётся неизвестной без закупочных цен и полного КП.
    </p>
    <form action={action} onSubmit={() => basket?.clearLaw("44")} onReset={(event) => event.preventDefault()} className="mt-4 flex flex-wrap gap-3">
      <label className="min-w-64 flex-1 text-sm font-bold">Что вы поставляете
        <input name="query" required maxLength={120} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Офисная бумага или серверное оборудование"
          className="mt-1 w-full rounded-lg border border-slate-300 p-2 font-normal" disabled={pending} />
      </label>
      <label className="text-sm font-bold">Регионы публикации для обновления
        <input name="regions" value={regions} onChange={(event) => setRegions(event.target.value)} maxLength={20} disabled={pending}
          className="mt-1 block w-44 rounded-lg border border-slate-300 p-2 font-normal" />
        <span className="mt-1 block max-w-64 text-xs font-normal text-slate-600">До 3 кодов ЕИС. Это очередь загрузки, поиск идёт по всем сохранённым регионам.</span>
      </label>
      <label className="w-full text-sm text-slate-700">
        <input type="hidden" name="search_scope" value={includeHistory ? "ALL_CACHED" : "NOT_EXPIRED_OR_UNKNOWN"} />
        <input type="checkbox" checked={includeHistory} onChange={(event) => setIncludeHistory(event.target.checked)} disabled={pending} className="mr-2" />
        Включить закупки с истёкшим сроком из сохранённой истории
        <span className="mt-1 block text-xs text-slate-600">По умолчанию: срок не истёк или неизвестен. Это не подтверждает открытость подачи заявки.</span>
      </label>
      <label className="w-full text-sm text-slate-700">
        <input type="checkbox" name="refresh" checked={refreshRequested} onChange={(event) => setRefreshRequested(event.target.checked)} disabled={pending} className="mr-2" />
        Поставить выбранные регионы в очередь обновления. Поиск сейчас использует сохранённые карточки.
      </label>
      <button type="submit" disabled={pending}
        className="self-end rounded-lg bg-blue-700 px-4 py-2 font-bold text-white disabled:opacity-50">
        {pending ? "Сравниваю…" : "Искать в индексе"}
      </button>
    </form>
    {state.error && <p role="alert" className="mt-3 text-sm font-bold text-red-800">{state.error}</p>}
    {state.refreshError && <p role="alert" className="mt-3 text-sm text-amber-900">{state.refreshError}</p>}
    {refresh && <div role="status" className="mt-4 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm">
      <strong>Обновление регионов {refresh.request.payload.regions.join(", ")}: {{
        QUEUED: "в очереди", PARTIAL: "выполнено частично", POLLED: "опрос завершён", EXPIRED: "время запроса истекло",
      }[refresh.status]}.</strong>
      <p className="mt-1">Опрошено окон: {refresh.polled_windows} из {refresh.request.window_keys.length};
        импортировано: {refresh.synced_windows}; без данных: {refresh.no_data_windows};
        ошибок: {refresh.failed_windows}; ещё не подтверждено: {refresh.pending_windows}.</p>
      <p className="mt-1">Обновляем два последних доступных часа текущего дня (когда они доступны) и предыдущие сутки по аукционам,
        котировкам и отменам 44-ФЗ. Данные машинного источника имеют задержку;
        полный охват и свежесть остаются UNKNOWN.</p>
      <p className="mt-1">После обновления повторите поиск: карточки будут заново сравнены по товару.
        Запрос действует до {new Date(refresh.request.expires_at).toLocaleTimeString("ru-RU")}.</p>
      <button type="button" disabled={checking} className="mt-2 rounded border border-blue-700 px-3 py-2 font-bold text-blue-800 disabled:opacity-50"
        onClick={() => startChecking(async () => {
          const result = await loadEisRefresh(refresh.request.request_id);
          setProgress(result.result); setProgressError(result.error);
        })}>{checking ? "Читаю статус…" : "Обновить статус очереди"}</button>
      {progressError && <p role="alert" className="mt-2 text-red-800">{progressError}</p>}
      {!!refresh.failed_windows && <ul className="mt-2 list-disc pl-5">{refresh.windows.filter((item) => item.reason).map((item) =>
        <li key={item.window_key}>{item.window_key}: {item.reason}</li>)}</ul>}
    </div>}
    {state.result && <PagedResults key={`${state.result.compared_at}:${state.result.query}`} initial={state.result}
      loadPage={cursor => loadIndexedSearchPage(state.result!.query, state.result!.search_scope, cursor)}
      identity={lead => `${lead.purchase_number}-${lead.xml_sha256}`}>
      {(result, canLoad) => <div className="mt-5 grid gap-4">
      <details className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm">
        <summary className="cursor-pointer font-bold">Что вошло в поиск · охват и свежесть не подтверждены</summary>
        <strong>Охват всей ЕИС: UNKNOWN.</strong> Загружено окон: {result.indexed_windows};
        последних карточек в сохранённой базе: {result.total_current_notices};
        карточек в выбранном режиме: {result.inspected_current_notices};
        совпадений: {result.matched_count}; показано: {result.matched.length}.
        <p className="mt-1 font-bold">Режим: {result.search_scope === "ALL_CACHED"
          ? "Вся сохранённая история, включая истёкшие сроки"
          : "Срок не истёк или неизвестен"}.
          {result.search_scope !== "ALL_CACHED" && <> Исключено карточек с истёкшим сроком:
            {" "}{result.excluded_expired_current_notices}.</>}</p>
        {result.strong_matched_count != null && <p className="mt-1">Все слова и уточнения запроса найдены:
          {" "}{result.strong_matched_count}; частичное совпадение: {result.partial_matched_count}.
          Это релевантность текста, допуск и соответствие требованиям ещё не подтверждены.</p>}
        <p className="mt-1">Подробно сравнено кандидатов: {result.evaluated_candidate_notices};
          поиск на сервере: {result.search_elapsed_ms} мс.
          {result.unindexed_versions > 0 && <> Ещё без поисковых ключей:
            {" "}{result.unindexed_versions} версий в сохранённой базе.
            Подходящие выбранному режиму карточки проверяются без поисковых ключей.</>}</p>
        <p className="mt-1">В плане: {result.planned_windows} окон;
          ещё не подтверждено: {result.pending_windows};
          запрошено региональных кодов: {result.requested_region_codes}.</p>
        <p className="mt-1">Подтверждённый разбор: аукционы, котировки и электронные открытые конкурсы 44-ФЗ.
          Остальные процедуры, 223-ФЗ и полнота истории событий требуют проверки.</p>
        {result.latest_ingested_at && <p className="mt-1">Последний импорт: {new Date(result.latest_ingested_at).toLocaleString("ru-RU")}.</p>}
        {result.latest_source_publication && <p className="mt-1">Последняя известная публикация:
          {" "}{new Date(result.latest_source_publication).toLocaleString("ru-RU")}.</p>}
        <p className="mt-1 font-bold">Свежесть всей ЕИС: {result.source_freshness}.
          Время импорта не подтверждает отсутствие новых карточек и изменений в источнике.</p>
        <p className="mt-1">Порядок предварительный. Доходность, допуск и полнота документов требуют отдельной проверки.</p>
      </details>
      <details className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm">
        <summary className="cursor-pointer font-bold">Подготовить документы кандидатов</summary>
        <button type="button" disabled={preparing} className="rounded bg-blue-700 px-3 py-2 font-bold text-white disabled:opacity-50"
          onClick={() => startPreparing(async () => {
            const prepared = await prepareTopIndexedDocuments(result.query);
            setSelection(prepared.result); setSelectionError(prepared.error);
          })}>{preparing ? "Выбираю…" : "Подготовить документы первых 3 кандидатов"}</button>
        <p className="mt-1">Выбор по предварительной релевантности среди карточек с документами.
          Отменённые и просроченные кандидаты исключаются; доходность ещё не подтверждена.</p>
        {selectionError && <p role="alert" className="mt-2 text-red-800">{selectionError}</p>}
        {selection && selection.query === result.query && <div role="status" className="mt-2">
          <p>В очереди: {selection.jobs.length}; подходит для сбора документов: {selection.eligible_count}.</p>
          <ul className="list-disc pl-5">{selection.jobs.map((job) => <li key={job.notice.purchase_number}>
            №{job.notice.purchase_number}, версия {job.notice.version_number}: получено {job.received_count} из {job.listed_count}.
          </li>)}</ul>
          {selection.rejected.map((item) => <p key={item.notice.purchase_number} className="text-red-800">
            №{item.notice.purchase_number} не запланирован: {item.reason}.</p>)}
        </div>}
      </details>
      {result.matched.length >= 2 && <details className="rounded-lg border p-3 text-sm">
        <summary className="cursor-pointer font-bold">Сравнить 2–3 закупки 44-ФЗ</summary>
        <IndexedComparison
        leads={result.matched} /></details>}
      <ResultExplorer canLoad={canLoad} total={result.matched_count}
        entries={result.matched.map(lead => ({ id: `${lead.purchase_number}-${lead.xml_sha256}`,
          quality: lead.match_quality, application: lead.application_status,
          method: lead.document_type === "epNotificationEZK2020" ? "Запрос котировок"
            : lead.document_type === "epNotificationEOK2020" ? "Открытый конкурс"
              : lead.document_type === "epNotificationEF2020" ? "Аукцион" : "Способ не подтверждён" }))}>
      {visible => result.matched.filter(lead => visible.has(`${lead.purchase_number}-${lead.xml_sha256}`)).map((lead) => <ResultRow
        key={`${lead.purchase_number}-${lead.xml_sha256}`} title={lead.title} number={lead.purchase_number}
        quality={lead.match_quality} application={lead.application_status}
        price={lead.nmck_rub ? `${lead.nmck_rub} ₽ · НМЦК` : "НМЦК неизвестна"}
        deadline={lead.deadline ? new Date(lead.deadline).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" }) + " МСК" : null}>
        <AddToMixedComparison disabled={pending} notice={{ law: "44", purchase_number: lead.purchase_number,
          version_number: lead.version_number, notice_xml_sha256: lead.xml_sha256, title: lead.title }} />
        <h3 className="text-lg font-black">{lead.title}</h3>
        <p className="mt-1">{lead.document_type === "epNotificationEZK2020"
          ? "Электронный запрос котировок, 44-ФЗ"
          : lead.document_type === "epNotificationEOK2020"
            ? "Электронный открытый конкурс, 44-ФЗ"
            : lead.document_type === "epNotificationEF2020"
              ? "Электронный аукцион, 44-ФЗ" : "Метод закупки: UNKNOWN"} ·
          № {lead.purchase_number} · версия {lead.version_number} ·
          совпадение {lead.match_quality === "STRONG" ? "всех слов" : "части слов"}</p>
        <p className="mt-1">НМЦК: {lead.nmck_rub ? `${lead.nmck_rub} ₽` : "UNKNOWN"} ·
          срок: {lead.deadline ? new Date(lead.deadline).toLocaleString("ru-RU") : "UNKNOWN"}</p>
        <p className="mt-1 font-bold">Подача: {lead.application_status} · экономика: {lead.economic_status}</p>
        {lead.document_type === "epNotificationEOK2020" && <p className="mt-1 text-amber-900">
          Критерии оценки конкурса и требования к квалификации ещё не проверены.
          НМЦК и совпадение запроса не определяют вероятность победы.</p>}
        <p className="mt-1">Совпали слова: {lead.matched_terms.join(", ")} · XML: {lead.match_locator}</p>
        <ul className="mt-2 list-disc pl-5 text-slate-700">
          {lead.reasons.map((reason) => <li key={reason}>{reason}</li>)}
        </ul>
        <a href={lead.notice_url} target="_blank" rel="noreferrer"
          className="mt-2 inline-block font-bold text-blue-700 underline">Официальная карточка ЕИС</a>
        {!!lead.lot_items.length && <details className="mt-3 rounded-lg bg-slate-50 p-3">
          <summary className="cursor-pointer font-bold">Позиции лота ({lead.lot_items.length})</summary>
          <ul className="mt-2 list-disc pl-5">
            {lead.lot_items.map((item) => <li key={item.locator}>
              {item.name}{item.quantity !== null ? ` · ${item.quantity} ${item.unit ?? "ед."}` : ""}
              {item.ktru_code ? ` · КТРУ ${item.ktru_code}` : ""}
            </li>)}
          </ul>
        </details>}
        {!!lead.attachments.length && <details className="mt-3 rounded-lg bg-slate-50 p-3">
          <summary className="cursor-pointer font-bold">Ссылки на документы ({lead.attachments.length})</summary>
          <ul className="mt-2 list-disc pl-5">
            {lead.attachments.map((item) => <li key={item.url}>
              <a href={item.url} target="_blank" rel="noreferrer" className="text-blue-700 underline">{item.filename}</a>
            </li>)}
          </ul>
        </details>}
        <IndexedDocuments notice={{ purchase_number: lead.purchase_number,
          version_number: lead.version_number, notice_xml_sha256: lead.xml_sha256 }} />
        <HistoricalProtocols notice={{ purchase_number: lead.purchase_number,
          version_number: lead.version_number, notice_xml_sha256: lead.xml_sha256 }} />
        <HistoricalAnalogs query={result.query} positions={lead.lot_items} notice={{ purchase_number: lead.purchase_number,
          version_number: lead.version_number, notice_xml_sha256: lead.xml_sha256 }} />
        <p className="mt-3 break-all text-xs text-slate-500">Окно: {lead.source_window} · XML SHA-256: {lead.xml_sha256}</p>
      </ResultRow>)}
      </ResultExplorer>
    </div>}
    </PagedResults>}
  </section>;
}
