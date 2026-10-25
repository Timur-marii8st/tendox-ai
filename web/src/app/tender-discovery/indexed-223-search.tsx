"use client";

import { useActionState, useState, useTransition } from "react";
import { compareIndexed223, loadIndexed223Documents, searchIndexed223, type Indexed223State } from "./actions";
import type { Comparison223Result, Eis223SearchResult, Document223Status, NoticeDocumentRef, Eis223RejectionState, Eis223LotCancellationState } from "@/lib/procurement-api";

import { AddToMixedComparison } from "./mixed-comparison";
import { Comparison223, deadline223, family223Labels, sourcePrice223, Source223Limits } from "./comparison-223";
import { Rejection223State } from "./rejection223-state";
import { LotCancellation223State } from "./lot-cancellation223-state";
import { ResultExplorer, ResultRow } from "./result-explorer";
import { PagedResults } from "./paged-results";
import { loadIndexed223SearchPage } from "./actions";

function Documents223({ notice, cancellationState, lotCancellationState }: { notice: NoticeDocumentRef; cancellationState?: Eis223RejectionState | null; lotCancellationState?: Eis223LotCancellationState | null }) {
  const [state, setState] = useState<{ result?: Document223Status; error?: string }>({});
  const [pending, start] = useTransition();
  const result = state.result;
  return <section aria-label={`Документы закупки ${notice.purchase_number}`} className="mt-3 border-t pt-3 text-sm">
    <button disabled={pending} className="rounded border px-3 py-2 font-semibold disabled:opacity-50"
      onClick={() => start(async () => setState(await loadIndexed223Documents(notice)))}>
      {pending ? "Загрузка…" : "Показать сохранённые документы 223-ФЗ"}
    </button>
    <button disabled={pending || result?.requested || Boolean(result?.blocked_reasons.length) || cancellationState?.operation_hold || result?.cancellation_state?.operation_hold || lotCancellationState?.operation_hold || result?.lot_cancellation_state?.operation_hold}
      className="ml-2 rounded bg-blue-700 px-3 py-2 font-semibold text-white disabled:opacity-50"
      onClick={() => start(async () => setState(await loadIndexed223Documents(notice, true)))}>
      {result?.requested ? "Сбор заказан" : "Собрать документы на сервере"}
    </button>
    <p className="mt-1 text-slate-600">Сервер собирает по одному файлу за проход. Обновите сохранённые документы для проверки прогресса.</p>
    {state.error && <p role="alert">{state.error}</p>}
    <Rejection223State state={result?.cancellation_state} />
    <LotCancellation223State state={result?.lot_cancellation_state} />
    {result && <div className="mt-2">
      <p>Версия: {result.version_status}. Получено {result.documents.filter(d => d.received).length} из {result.documents.length} перечисленных файлов.
        Статус загрузки: {result.download_status}. Полнота ТЗ, роль документов и прибыль: UNKNOWN.</p>
      <p>Очередь: {result.queue_status}.</p>
      {result.blocked_reasons.length > 0 && <p className="text-amber-800">{result.blocked_reasons.join("; ")}</p>}
      {result.manifest.reasons.length > 0 && <p className="text-amber-800">{result.manifest.reasons.join("; ")}</p>}
      {result.documents.map((document) => <details key={document.reference.ordinal} className="mt-2 rounded border p-2">
        <summary>{document.reference.filename ?? "Название UNKNOWN"} · {document.received ? "получен" : "не скачан"}</summary>
        <p className="break-all">UID: {document.reference.content_uid ?? "UNKNOWN"} · Источник: {document.reference.source_locator}</p>
        <p>Размер в XML: UNKNOWN. {document.reference.reasons.join("; ")}</p>
        {document.last_failure && <p className="text-amber-800">Последняя ошибка: {document.last_failure}. Попыток: {document.attempt_count} из 5.</p>}
        {document.analysis && <div>
          <p>Получено {document.analysis.byte_count} байт. Извлечение текста: {document.analysis.status}.
            Роль документа: UNKNOWN. {document.analysis.reasons.join("; ")}</p>
          <p className="break-all">SHA-256 файла: {document.analysis.sha256}</p>
          <p>Фрагменты условий: показано {Math.min(18, document.analysis.snippets.length)} из {document.analysis.snippets.length}. Требуют проверки.</p>
          <ul className="list-disc pl-5">{document.analysis.snippets.slice(0, 18).map((snippet, i) => <li key={i}>
            <strong>{snippet.kind}:</strong> {snippet.text.slice(0, 600)}{snippet.text.length > 600 ? "… (фрагмент сокращён)" : ""}
            <p className="break-all text-slate-500">{snippet.provenance.document_id} · {snippet.provenance.locator}</p>
          </li>)}</ul>
        </div>}
      </details>)}
    </div>}
  </section>;
}

export function Indexed223Search() {
  const [state, action, pending] = useActionState<Indexed223State, FormData>(searchIndexed223, {});
  const result = state.result;
  return <section aria-label="Поиск закупок 223-ФЗ" className="mt-8 rounded-2xl border border-slate-200 bg-white p-5">
    <h2 className="text-xl font-black">Закупки 223-ФЗ</h2>
    <p className="mt-2 text-sm text-slate-600">Поиск по сохранённым извещениям: аукционы и котировки для МСП, иной способ.
      Охват и свежесть ЕИС: UNKNOWN. Лоты сравниваются отдельно, прибыль и право участия требуют проверки.</p>
    <form action={action} className="mt-4 flex flex-wrap gap-3">
      <label className="flex-1">Товар или полный регистрационный номер 223-ФЗ
        <input name="query" required maxLength={120} placeholder="Краны шаровые или 32616445250"
          className="mt-1 block w-full rounded-lg border p-2" />
      </label>
      <button disabled={pending} className="self-end rounded-lg bg-blue-700 px-4 py-2 font-bold text-white disabled:opacity-50">
        {pending ? "Поиск…" : "Искать в 223-ФЗ"}
      </button>
    </form>
    {state.error && <p role="alert" className="mt-3 text-red-700">{state.error}</p>}
    {result && <PagedResults key={result.checked_at} initial={result}
      loadPage={cursor => loadIndexed223SearchPage(result.query, cursor)} identity={lead => lead.notice.purchase_number}>
      {(loaded, canLoad) => <Results223 result={loaded} searching={pending} canLoad={canLoad} />}
    </PagedResults>}
  </section>;
}

function Results223({ result, searching, canLoad }: { result: Eis223SearchResult; searching: boolean; canLoad: boolean }) {
  const [selected, setSelected] = useState<NoticeDocumentRef[]>([]);
  const [comparison, setComparison] = useState<{ result?: Comparison223Result; error?: string }>({});
  const [comparing, start] = useTransition();
  return <div className="mt-4">
    <div className="rounded border p-3 text-sm">
      <p>Выберите 2–3 закупки для сравнения цен, позиций и сохранённых условий. Выбрано: {selected.length} из 3.</p>
      <button disabled={comparing || selected.length < 2} className="mt-2 rounded bg-blue-700 px-3 py-2 font-bold text-white disabled:opacity-50"
        onClick={() => start(async () => setComparison(await compareIndexed223(selected)))}>
        {comparing ? "Сравнение…" : "Сравнить выбранные 223-ФЗ"}
      </button>
      {comparison.error && <p role="alert">{comparison.error}</p>}
    </div>
    {comparison.result && <Comparison223 result={comparison.result} />}

      <p className="text-sm">В индексе: {result.indexed_current_notices} актуальных сохранённых версий;
        окон: {result.indexed_windows}; кандидатов проверено: {result.evaluated_candidates};
        найдено: {result.matched_count}. Показано: {result.matched.length}.</p>
      <p className="text-sm text-slate-600">Проверено {result.checked_at}. Последняя загрузка: {result.latest_ingested_at ?? "нет данных"}.
        Полнота: UNKNOWN · Свежесть: UNKNOWN · Экономика: UNKNOWN.</p>
      {result.matched_count === 0 && <p className="mt-3">Совпадений в сохранённой части 223-ФЗ нет. Это не доказывает отсутствие закупок в ЕИС.</p>}
      <ResultExplorer canLoad={canLoad} total={result.matched_count} entries={result.matched.map(lead => ({
        id: lead.notice.purchase_number, quality: lead.match_quality, application: lead.application_status,
        method: family223Labels[lead.notice.document_type] ?? "Способ закупки UNKNOWN",
      }))}>
      {visible => result.matched.filter(lead => visible.has(lead.notice.purchase_number)).map((lead) => <ResultRow
        key={lead.notice.purchase_number} title={lead.notice.title.value ?? "Название не подтверждено"}
        number={lead.notice.purchase_number} quality={lead.match_quality} application={lead.application_status}
        price={`Лотов: ${lead.notice.lots.length} · цены внутри`}
        deadline={deadline223(lead.notice).value ?? null}>
        <AddToMixedComparison disabled={searching} notice={{ law: "223", purchase_number: lead.notice.purchase_number,
          version_number: lead.notice.version_number, notice_xml_sha256: lead.notice.xml_sha256, title: lead.notice.title.value ?? "Название UNKNOWN" }} />
        <label className="mb-2 block text-sm">
          <input type="checkbox" aria-label={`Сравнить закупку ${lead.notice.purchase_number}`}
            checked={selected.some(n => n.purchase_number === lead.notice.purchase_number)}
            disabled={comparing || (selected.length >= 3 && !selected.some(n => n.purchase_number === lead.notice.purchase_number))}
            onChange={event => {
              setComparison({});
              setSelected(event.target.checked
                ? [...selected, { purchase_number: lead.notice.purchase_number, version_number: lead.notice.version_number, notice_xml_sha256: lead.notice.xml_sha256 }]
                : selected.filter(n => n.purchase_number !== lead.notice.purchase_number));
            }} /> В сравнение
        </label>
        <h3 className="font-bold">№ {lead.notice.purchase_number} · версия {lead.notice.version_number} · 223-ФЗ</h3>
        <p>{lead.notice.title.value ?? "Название UNKNOWN"}</p>
        <p className="text-sm">{family223Labels[lead.notice.document_type] ?? "Способ закупки UNKNOWN"}
          {lead.notice.method_name.value && ` · ${lead.notice.method_name.value}`}</p>
        <p className="mt-2 text-sm">{lead.match_quality === "STRONG" ? "Все слова запроса найдены" : "Частичное совпадение слов"}.
          Участие: {lead.application_status}. {lead.matched_lot_ordinal && `Совпадение в лоте ${lead.matched_lot_ordinal}.`}</p>
        <Rejection223State state={lead.cancellation_state} />
        <LotCancellation223State state={lead.lot_cancellation_state} />
        <p className="text-sm">Срок подачи: {deadline223(lead.notice).value ?? `${deadline223(lead.notice).raw ?? "нет данных"} — применимость срока / часовой пояс UNKNOWN`}.</p>
        <p className={`text-sm ${lead.source_schema_status === "FAIL" ? "font-bold text-amber-800" : "text-slate-600"}`}>
          Проверка XML по официальной схеме: {lead.source_schema_status}. Право участия и соответствие ТЗ проверяются отдельно.</p>
        <ul className="mt-2 list-disc pl-5 text-sm">{lead.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
        <div className="mt-3 overflow-x-auto"><table className="w-full text-left text-sm">
          <caption className="text-left font-bold">Лоты и исходные цены</caption>
          <thead><tr><th>Лот</th><th>Предмет</th><th>Цена</th><th>Валюта</th><th>Позиции</th></tr></thead>
          <tbody>{lead.notice.lots.map((lot, i) => { const price = sourcePrice223(lot, lead.notice.document_type === "purchaseNotice"); return <tr key={i} className="border-t">
            <td className="p-2">{lot.ordinal.value ?? "UNKNOWN"}
              <p>Только МСП (лот): {lot.for_small_or_middle_raw?.value ?? "UNKNOWN"}.</p></td><td className="p-2">{lot.subject.value ?? "UNKNOWN"}</td>
            <td className="p-2">{price.label}: {price.amount ?? "UNKNOWN"}
              {lot.source_price_text?.raw && <p>{lot.source_price_text.raw}</p>}
              {price.kind !== "INITIAL_SUM" && <p className="text-amber-900">Выручка и применимость в расчёте UNKNOWN.</p>}</td>
            <td className="p-2">{price.currency}{lot.source_currency_status === "UNKNOWN" && <p className="text-amber-900">Коды валюты требуют проверки.</p>}</td>
            <td className="p-2">{lot.items.map((item) => item.description.value ?? "Описание UNKNOWN").join("; ") || "UNKNOWN"}</td>
          </tr>; })}</tbody>
        </table></div>
        <Source223Limits notice={lead.notice} />
        <details className="mt-3 text-sm"><summary>Почему найдено и источники</summary>
          <ul className="list-disc pl-5">{lead.term_evidence.map((e, i) => <li key={i}>
            {e.term}: {e.source_value} · {e.locator}
          </li>)}</ul>
          <p className="break-all">XML SHA-256: {lead.notice.xml_sha256}<br />Архив: {lead.archive_sha256}<br />
            Ответ источника: {lead.source_response_sha256}<br />Окно: {lead.source_window}</p>
          {lead.source_schema_checks.map((check) => <div key={`${check.schema_release}:${check.validator_version}`} className="mt-2 break-all">
            <p>XSD {check.schema_release}: {check.status} · {check.checked_at} · схема SHA-256: {check.tree_sha256}</p>
            <ul>{check.diagnostics.map((d, i) => <li key={i}>Строка {d.line} · {d.path} · {d.type_name}: {d.message}</li>)}</ul>
          </div>)}
          <p>В XML {lead.notice.attachments.length} ссылок на документы. Комплект и требования ещё не проверены.</p>
        </details>
        <Documents223 key={`${lead.notice.version_number}:${lead.notice.xml_sha256}`} cancellationState={lead.cancellation_state} lotCancellationState={lead.lot_cancellation_state} notice={{
          purchase_number: lead.notice.purchase_number, version_number: lead.notice.version_number,
          notice_xml_sha256: lead.notice.xml_sha256,
        }} />
      </ResultRow>)}
      </ResultExplorer>
  </div>;
}
