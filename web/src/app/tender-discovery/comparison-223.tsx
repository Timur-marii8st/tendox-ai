"use client";

import type { Comparison223Result, Eis223DocumentType, Eis223SourcePriceKind } from "@/lib/procurement-api";
import { Rejection223State } from "./rejection223-state";
import { LotCancellation223State } from "./lot-cancellation223-state";

type Notice223 = Comparison223Result["rows"][number]["notice"];
export const family223Labels: Record<Eis223DocumentType, string> = {
  purchaseNoticeAESMBO: "Электронный аукцион для МСП",
  purchaseNoticeZKESMBO: "Электронные котировки для МСП",
  purchaseNotice: "Иной способ — ограничения участия проверяются по лоту",
};
export const price223Labels: Record<Eis223SourcePriceKind, string> = {
  INITIAL_SUM: "Начальная сумма",
  MAX_CONTRACT_PRICE: "Максимальная цена договора",
  TEXT_ONLY: "Цена описана текстом",
  UNKNOWN: "Тип цены UNKNOWN",
};
export function deadline223(notice: Notice223) {
  if (notice.document_type !== "purchaseNotice") return notice.selected_deadline ?? notice.deadline;
  return notice.selected_deadline ?? { ...notice.deadline, value: null, status: "UNKNOWN" as const };
}
export function sourcePrice223(lot: Notice223["lots"][number], generic: boolean) {
  const kind = lot.source_price_kind ?? (generic ? "UNKNOWN" : "INITIAL_SUM");
  return { kind, label: price223Labels[kind],
    amount: kind === "TEXT_ONLY" ? null : (lot.source_price_kind ? lot.source_amount?.value : generic ? null : lot.initial_sum.value),
    currency: lot.source_currency_status === "UNKNOWN" ? "UNKNOWN" : lot.currency_letter_code?.value ?? lot.currency.value ?? "UNKNOWN",
    locator: lot.source_price_kind ? lot.source_amount?.provenance.locator : generic ? undefined : lot.initial_sum.provenance.locator };
}
export function Source223Limits({ notice }: { notice: Notice223 }) {
  const generic = notice.document_type === "purchaseNotice";
  const refs = notice.manifest_references ?? [];
  const hidden = notice.attachments.filter(d => ["true", "1"].includes(d.not_placement_raw?.value ?? ""));
  return <div className="mt-2 text-sm text-amber-900">
    {generic && <p>Сокрытие закупки: {notice.hide_purchase_raw?.value ?? "UNKNOWN"}.
      Сроки по лотам: {notice.is_lot_oriented_raw?.value ?? "UNKNOWN"}. Доступность и ограничения участия требуют проверки.</p>}
    {generic && <p>Показ только аккредитованным участникам по XML: {notice.hide_purchase_customer_accredited_raw?.value ?? "UNKNOWN (значение не подтверждено)"}.</p>}
    <p>Только МСП — признак извещения: {notice.for_small_or_middle_raw?.value ?? "UNKNOWN (значение не подтверждено)"}.
      Признаки каждого лота указаны отдельно; право участия требует проверки.</p>
    <p>Перечень документов: {notice.manifest_status}. Дополнительные файлы: {notice.manifest_additional_count?.value ?? "UNKNOWN"}.
      Неразрешённые ссылки: {refs.length}. Полнота комплекта: UNKNOWN.</p>
    {hidden.length > 0 && <p>Скрытые вложения: {hidden.length}. Их наличие не разрешает скачивание.</p>}
    {generic && <p>Флаг сокрытия вложений отсутствует или неизвестен у {notice.attachments.filter(d => d.not_placement_raw?.value == null).length} файлов.</p>}
    {refs.length > 0 && <details><summary>Ссылки на дополнительные и прежние документы</summary>
      <ul className="list-disc pl-4">{refs.map((ref, i) => <li key={i}>
        {ref.kind === "DOCUMENT_FS" ? "Файл в хранилище" : "Документ прежней редакции"}: {ref.content_uid.value ?? ref.guid.value ?? "UNKNOWN"}
        <p className="break-all text-xs">{ref.provenance.locator}</p>
      </li>)}</ul>
    </details>}
  </div>;
}

export function Comparison223({ result }: { result: Comparison223Result }) {
  return <section aria-label="Сравнение закупок 223-ФЗ" className="mt-4 rounded-xl border border-blue-300 bg-blue-50 p-4">
    <h3 className="text-lg font-bold">Сравнение выбранных закупок 223-ФЗ</h3>
    <p className="text-sm">Проверено {result.checked_at}. Порядок — по выбору пользователя.
      Рейтинг прибыли, полнота ЕИС и допуск: UNKNOWN.</p>
    <div className={`mt-3 grid gap-4 ${result.rows.length === 2 ? "lg:grid-cols-2" : "lg:grid-cols-3"}`}>{result.rows.map(row => <Comparison223Card key={row.notice.purchase_number} row={row} />)}</div>
  </section>;
}

export function Comparison223Card({ row }: { row: Comparison223Result["rows"][number] }) {
  const deadline = deadline223(row.notice);
  return <article
      className="min-w-0 rounded-lg border bg-white p-3">
      <h4 className="font-bold">№ {row.notice.purchase_number} · версия {row.notice.version_number}</h4>
      <p>{row.notice.title.value ?? "Название UNKNOWN"}</p>
      <p className="text-sm">{family223Labels[row.notice.document_type]}</p>
      <p className="mt-2 font-bold">Готовность: {row.readiness_status}</p>
      <Rejection223State state={row.cancellation_state} />
      <LotCancellation223State state={row.lot_cancellation_state} />
      {row.blocking_reasons.length > 0 && <p className="font-bold text-red-800">{row.blocking_reasons.join("; ")}</p>}
      <p>Срок: {deadline.value ?? `${deadline.raw ?? "нет данных"} — применимость срока / часовой пояс UNKNOWN`}</p>
      <details className="text-xs text-slate-600"><summary>Источник срока</summary>
        <p className="break-all">{deadline.provenance.locator}</p>
      </details>
      <p className={row.source_schema_status === "FAIL" ? "font-bold text-amber-800" : ""}>Официальная XSD: {row.source_schema_status}</p>
      <h5 className="mt-3 font-bold">Лоты и позиции</h5>
      {row.notice.lots.map((lot, i) => { const price = sourcePrice223(lot, row.notice.document_type === "purchaseNotice"); return <div key={i} className="mt-2 border-t pt-2 text-sm">
        <p>Лот {lot.ordinal.value ?? "UNKNOWN"}: {lot.subject.value ?? "Предмет UNKNOWN"}</p>
        <p className="font-bold">{price.label}: {price.amount ?? "UNKNOWN"} {price.currency}</p>
        {lot.source_price_text?.raw && <p>Описание цены: {lot.source_price_text.raw}</p>}
        {lot.source_price_formula?.raw && <p>Формула цены: {lot.source_price_formula.raw}</p>}
        {price.kind !== "INITIAL_SUM" && <p className="text-amber-900">Этот вид цены не подтверждает выручку и не заменяет начальную сумму для расчёта.</p>}
        {lot.source_currency_status === "UNKNOWN" && <p className="text-amber-900">Валюта неоднозначна: код {lot.currency.raw ?? "нет"}, буквенный код {lot.currency_letter_code?.raw ?? "нет"}. Пересчёт не выполняется.</p>}
        <p>Отмена лота по XML: {lot.cancelled_raw.value ?? "UNKNOWN"}. Текущая стадия требует проверки.</p>
        <p>Только МСП — признак этого лота: {lot.for_small_or_middle_raw?.value ?? "UNKNOWN (значение не подтверждено)"}. Допуск поставщика: UNKNOWN.</p>
        {lot.for_small_or_middle_raw && <details className="text-xs text-slate-600"><summary>Источник признака МСП лота</summary>
          <p className="break-all">{lot.for_small_or_middle_raw.provenance.locator}</p>
        </details>}
        <details className="text-xs text-slate-600"><summary>Источники цены, валюты и отмены</summary>
          <p className="break-all">{price.locator ?? "Источник числовой цены UNKNOWN"} · {lot.currency_letter_code?.value ? lot.currency_letter_code.provenance.locator : lot.currency.provenance.locator} · {lot.cancelled_raw.provenance.locator}</p>
        </details>
        <ul className="list-disc pl-4">{lot.items.map((item, j) => <li key={j}>
          {item.description.value ?? "Описание UNKNOWN"} · {item.quantity.value ?? "Количество UNKNOWN"} {item.unit_name.value ?? "Единица UNKNOWN"}
          <details className="text-xs text-slate-600"><summary>Источник позиции</summary>
            <p className="break-all">{item.description.provenance.locator} · {item.quantity.provenance.locator} · {item.unit_name.provenance.locator}</p>
          </details>
        </li>)}</ul>
      </div>; })}
      <h5 className="mt-3 font-bold">Документы и условия</h5>
      <Source223Limits notice={row.notice} />
      <p className="text-sm">Получено {row.documents.filter(d => d.received).length} из {row.documents.length}.
        Загрузка: {row.download_status}. Очередь: {row.queue_status}.</p>
      {row.documents.map((doc, i) => <details key={i} className="mt-2 rounded border p-2 text-sm">
        <summary>{doc.filename ?? "Имя UNKNOWN"} · {doc.received ? "получен" : "не скачан"}</summary>
        <p>Извлечение: {doc.extraction_status}. Роль и проверка требований: UNKNOWN.</p>
        <p className="break-all text-xs">UID {doc.content_uid ?? "UNKNOWN"} · {doc.source_locator}<br />SHA-256: {doc.sha256 ?? "UNKNOWN"}</p>
        <p>{doc.reasons.join("; ")}</p>
        <p>Показано {doc.snippets.length} из {doc.snippets_total} фрагментов.
          {doc.preview_truncated && " Превью сокращено; полный извлечённый текст сохранён на сервере."}</p>
        <ul className="list-disc pl-4">{doc.snippets.map((snippet, j) => <li key={j}>
          <strong>{snippet.kind}:</strong> {snippet.text}
          <p className="break-all text-xs text-slate-600">{snippet.provenance.document_id} · {snippet.provenance.locator}</p>
        </li>)}</ul>
      </details>)}
      <ul className="mt-3 list-disc pl-4 text-sm">{row.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>
      <details className="mt-3 text-xs"><summary>Источники карточки и проверки XSD</summary>
        <p className="break-all">XML: {row.notice.xml_sha256}<br />Архив: {row.archive_sha256}<br />
          Ответ источника: {row.source_response_sha256}<br />Окно: {row.source_window}</p>
        {row.source_schema_checks.map((check, i) => <div key={i} className="mt-2 break-all">
          XSD {check.schema_release}: {check.status} · {check.checked_at} · {check.tree_sha256}
          <ul>{check.diagnostics.map((d, j) => <li key={j}>Строка {d.line} · {d.path} · {d.type_name}: {d.message}</li>)}</ul>
        </div>)}
      </details>
    </article>;
}
