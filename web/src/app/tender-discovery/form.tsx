"use client";

import { useActionState, useState, useTransition } from "react";
import { IndexedDocuments } from "./indexed-documents";

import {
  inspectAttachment, listLiveDocuments, searchExport, searchLive,
  verifyLiveNumber,
  type AttachmentState, type DiscoveryState, type LiveDocumentsState, type LiveSearchState,
} from "./actions";

function VerifyOfficialNotice({ number }: { number: string }) {
  const [state, setState] = useState<Awaited<ReturnType<typeof verifyLiveNumber>>>({});
  const [pending, start] = useTransition();
  return <div className="mt-3 rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm">
    <button type="button" disabled={pending} onClick={() => start(async () => setState(await verifyLiveNumber(number)))}
      className="rounded bg-blue-700 px-3 py-2 font-bold text-white disabled:opacity-50">
      {pending ? "Проверяю официальный XML…" : "Проверить XML и поставить документы в очередь"}
    </button>
    {state.error && <p role="alert" className="mt-2 text-red-800">{state.error}</p>}
    {state.result && <div className="mt-2" role="status">
      <p>Машинный сервис ЕИС: <strong>{state.result.source.status}</strong>. Охват: только №{number}; полнота всей ЕИС UNKNOWN.</p>
      {state.result.source.reason && <p>Причина: {state.result.source.reason}</p>}
      {state.result.source.source_response_sha256 && <p className="break-all text-xs">SHA-256 ответа: {state.result.source.source_response_sha256}</p>}
      {state.result.source.latest_version_number && <p>Версия XML: {state.result.source.latest_version_number}; новых версий: {state.result.source.new_versions}.</p>}
      {state.result.document_queue_reason && <p>Очередь документов: {state.result.document_queue_reason}</p>}
      {state.result.document_job && <p>Документы: {state.result.document_job.download_status}; получено {state.result.document_job.received_count} из {state.result.document_job.listed_count} файлов.</p>}
      {state.result.source.latest_version_number && state.result.source.latest_xml_sha256 &&
        <IndexedDocuments notice={{ purchase_number: number,
          version_number: state.result.source.latest_version_number,
          notice_xml_sha256: state.result.source.latest_xml_sha256 }} />}
    </div>}
  </div>;
}

function LiveDocuments({ url }: { url: string }) {
  const [state, action, pending] = useActionState(listLiveDocuments, {} as LiveDocumentsState);
  return <div className="mt-3 rounded-lg border border-slate-200 p-3 text-sm">
    <form action={action}>
      <input type="hidden" name="url" value={url} />
      <button disabled={pending} type="submit"
        className="rounded bg-slate-900 px-3 py-1 font-bold text-white disabled:opacity-50">
        {pending ? "Читаю страницу документов…" : "Показать файлы ЕИС"}
      </button>
    </form>
    {state.error && <p role="alert" className="mt-2 text-red-800">{state.error}</p>}
    {state.result && <div className="mt-2">
      <p>Чтение: {state.result.status} · файлов поддержанных форматов: {state.result.documents.length}</p>
      {state.result.reason && <p>Причина: {state.result.reason}</p>}
      {state.result.retry_at && <p>Повторить после: {new Date(state.result.retry_at).toLocaleString("ru-RU")}</p>}
      {state.result.source_sha256 && <p className="break-all">SHA-256 страницы: {state.result.source_sha256}</p>}
      {state.result.documents.map((item) => <Attachment key={item.url} {...item} />)}
    </div>}
  </div>;
}

function LiveSearch() {
  const [state, action, pending] = useActionState(searchLive, {} as LiveSearchState);
  return <section className="grid gap-4">
    <form action={action} className="grid gap-3 rounded-2xl border border-blue-200 bg-white p-5 shadow-sm">
      <h2 className="text-xl font-black">Живой поиск по публичной выдаче ЕИС</h2>
      <label className="grid gap-1 text-sm font-bold">Что хотите поставлять
        <input name="query" required maxLength={120} placeholder="Бумага или серверное оборудование"
          className="rounded-lg border border-slate-300 p-2 font-normal" disabled={pending} />
      </label>
      <button type="submit" disabled={pending}
        className="w-fit rounded-lg bg-blue-700 px-4 py-2 font-bold text-white disabled:opacity-50">
        {pending ? "Читаю ЕИС…" : "Искать на ЕИС"}
      </button>
      <p className="text-xs text-slate-600">Одна первая страница выдачи, до 100 карточек. Повторный запрос доступен через 60 секунд согласно robots.txt ЕИС.</p>
    </form>
    {state.error && <p role="alert" className="font-bold text-red-800">{state.error}</p>}
    {state.result && <div className="grid gap-4">
      <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm" role="status">
        <strong>Источник: публичная страница ЕИС. Статус: {state.result.status}.</strong>
        {state.result.reason && <p>Причина: {state.result.reason}</p>}
        {state.result.retry_at && <p>Повторить после: {new Date(state.result.retry_at).toLocaleString("ru-RU")}</p>}
        {state.result.scanned_count !== null && <p>Прочитано строк: {state.result.scanned_count}; уникальных закупок: {state.result.unique_scanned_count ?? "не подтверждено"}; найдено по названию: {state.result.leads.length}.</p>}
        {state.result.unparsed_count > 0 && <p>Без проверяемого названия или номера: {state.result.unparsed_count}. Эти карточки не включены в подбор.</p>}
        {state.result.source_result_count_floor !== null && <p>Счётчик ЕИС: {state.result.source_result_count_exact ? "" : "более "}{state.result.source_result_count_floor.toLocaleString("ru-RU")} записей.</p>}
        {state.result.query_exceeds_page_limit && <p>Счётчик ЕИС превышает текущий лимит программы. Доступность всех результатов и корректность переходов между страницами не подтверждены.</p>}
        {state.result.has_more_pages && <p>ЕИС показывает признаки следующих страниц; их содержимое и полнота охвата пока не проверены.</p>}
        {state.result.source_sha256 && <p className="break-all">SHA-256 страницы: {state.result.source_sha256}</p>}
        <a className="font-bold text-blue-700 underline" href={state.result.search_url} target="_blank" rel="noreferrer">Открыть выдачу ЕИС</a>
      </div>
      {state.result.leads.map((lead) => <article key={lead.purchase_number}
        className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="text-xl font-black">{lead.subject}</h3>
        <p className="mt-1 text-sm">№ {lead.purchase_number} · {lead.method}</p>
        {lead.customer && <p className="mt-1 text-sm">Заказчик: {lead.customer}</p>}
        <p className="mt-1 text-sm">Этап: {lead.stage} · НМЦК: {lead.nmck_rub ? `${lead.nmck_rub} ₽` : "не подтверждена"}</p>
        <p className="mt-1 text-sm">Дата окончания: {lead.deadline_date || "не указана"}; точное время и часовой пояс — по карточке.</p>
        <p className="mt-1 text-sm font-bold">Окно подачи: {lead.application_status} · прибыль: {lead.economic_status}</p>
        <p className="mt-2 text-sm">Почему показано: совпали слова «{lead.matched_terms.join(", ")}» в названии объекта закупки.</p>
        <div className="mt-3 flex gap-5 text-sm font-bold text-blue-700">
          <a href={lead.detail_url} target="_blank" rel="noreferrer" className="underline">Карточка ЕИС</a>
          {lead.documents_url && <a href={lead.documents_url} target="_blank" rel="noreferrer" className="underline">Документы ЕИС</a>}
        </div>
        {lead.documents_url?.includes("/epz/order/notice/") &&
          <LiveDocuments url={lead.documents_url} />}
        {lead.law === "44-fz" && /^[0-9]{19,23}$/.test(lead.purchase_number) &&
          <VerifyOfficialNotice number={lead.purchase_number} />}
      </article>)}
    </div>}
  </section>;
}

function Attachment({ url, filename }: { url: string; filename: string }) {
  const [state, action, pending] = useActionState(inspectAttachment, {} as AttachmentState);
  return <div className="mt-3 rounded-lg border border-slate-200 p-3 text-sm">
    <form action={action} className="flex flex-wrap items-center gap-2">
      <input type="hidden" name="url" value={url} />
      <input type="hidden" name="filename" value={filename} />
      <a className="font-bold text-blue-700 underline" href={url} target="_blank" rel="noreferrer">{filename}</a>
      <button className="rounded bg-slate-900 px-3 py-1 font-bold text-white disabled:opacity-50"
        disabled={pending} type="submit">{pending ? "Читаю…" : "Скачать и прочитать"}</button>
    </form>
    {state.error && <p className="mt-2 text-red-800" role="alert">{state.error}</p>}
    {state.result && <div className="mt-2" role="status">
      <p>Извлечение: <strong>{state.result.extraction_status}</strong> · {state.result.byte_count} байт</p>
      <p className="break-all">SHA-256: {state.result.sha256}</p>
      {!!state.result.extraction_reasons.length && <p>Ограничения: {state.result.extraction_reasons.join(", ")}</p>}
      {!!state.result.bundle_members.length && <p>Файлы в архиве: {state.result.bundle_members.join(", ")}</p>}
      <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs">{state.result.text_preview}</pre>
      {state.result.preview_truncated && <p>Показан только первый фрагмент текста.</p>}
    </div>}
  </div>;
}

export function TenderDiscoveryForm() {
  const [state, action, pending] = useActionState(searchExport, {} as DiscoveryState);
  return <div className="mt-7 grid gap-5">
    <LiveSearch />
    <h2 className="mt-4 text-xl font-black">Поиск по сохранённой выгрузке XML/ZIP</h2>
    <form action={action} className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <label className="grid gap-1 text-sm font-bold">Что хотите поставлять
        <input name="query" required maxLength={120} placeholder="Серверное оборудование"
          className="rounded-lg border border-slate-300 p-2 font-normal" disabled={pending} />
      </label>
      <label className="grid gap-1 text-sm font-bold">Выгрузка ЕИС XML или ZIP (до 20 МиБ)
        <input name="file" type="file" accept=".xml,.zip" required
          className="rounded-lg border border-slate-300 p-2 font-normal" disabled={pending} />
      </label>
      <button type="submit" disabled={pending}
        className="w-fit rounded-lg bg-blue-700 px-4 py-2 font-bold text-white disabled:opacity-50">
        {pending ? "Ищу…" : "Найти закупки"}
      </button>
    </form>
    {state.error && <p role="alert" className="font-bold text-red-800">{state.error}</p>}
    {state.result && <section aria-label="Найденные закупки" className="grid gap-4">
      <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm">
        <strong>Покрытие: только загруженный файл; подлинность источника UNKNOWN.</strong> Проверено извещений: {state.result.inspected_notices}.
        Отклонено файлов: {state.result.rejected_members}. Совпадений: {state.result.matched.length}.
        <p className="mt-1 break-all">SHA-256 выгрузки: {state.result.export_sha256}</p>
      </div>
      {state.result.matched.map((lead) => <article key={`${lead.export_member}-${lead.xml_sha256}`}
        className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-xl font-black">{lead.title}</h2>
        <p className="mt-1 text-sm">№ {lead.purchase_number}{lead.customer ? ` · ${lead.customer}` : ""}</p>
        <p className="mt-1 text-sm">НМЦК: {lead.nmck ? `${lead.nmck} ₽` : "не подтверждена"} ·
          срок: {lead.deadline ? new Date(lead.deadline).toLocaleString("ru-RU") : "не подтверждён"}</p>
        <p className="mt-1 text-sm font-bold">Подача: {lead.application_status} · прибыль: {lead.economic_status}</p>
        <p className="mt-1 text-sm">Совпадение: {lead.match_quality === "STRONG" ? "все слова запроса" : "часть слов запроса"} · XML: {lead.match_locator}</p>
        <ul className="mt-3 list-disc pl-5 text-sm text-slate-700">
          {lead.explanation.map((reason) => <li key={reason}>{reason}</li>)}
        </ul>
        <a href={lead.notice_url} target="_blank" rel="noreferrer"
          className="mt-3 inline-block text-sm font-bold text-blue-700 underline">Найти извещение в ЕИС</a>
        <p className="mt-2 break-all text-xs text-slate-500">Источник: {lead.export_member} · XML SHA-256: {lead.xml_sha256}</p>
        {lead.attachments.map((item) => <Attachment key={item.url} {...item} />)}
      </article>)}
    </section>}
  </div>;
}
