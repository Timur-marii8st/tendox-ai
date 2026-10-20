import type { Eis223LotCancellation, Eis223LotCancellationState, Eis223SelectedLotCancellationState } from "@/lib/procurement-api";

const reasons: Record<string, string> = {
  NO_LOT_CANCELLATION_EVENT_EVIDENCE: "События отмены лотов не найдены в проверенных данных; полнота UNKNOWN",
  LOT_CANCELLATION_REVIEW_REQUIRED: "Сведения об отмене лотов требуют проверки",
  LOT_CANCELLATION_DOCUMENT_REVIEW_REQUIRED: "Сбор документов приостановлен до проверки отмены лотов",
  LOT_CANCELLATION_IDENTITY_UNRESOLVED: "Связь события с лотом и версией извещения не установлена",
  LOT_EVENT_GUID_VARIANTS: "Найдены разные XML одного GUID события",
  LOT_EVENT_GUID_TARGET_CONFLICT: "GUID события связан с противоречивыми целями",
  EVENT_EVIDENCE_LIMIT: "Достигнут предел проверки событий",
  LOT_CANCELLATION_SCHEMA_INCOMPLETE: "Проверка схемы событий неполна",
  LOT_CANCELLATION_TIME_UNRESOLVED: "Время события требует проверки",
  LOT_CANCELLATION_DECISION_INCOMPLETE: "Дата или основание решения неполны",
};

type Fact = Eis223LotCancellation["event_guid"];
function SourceFact({ label, fact }: { label: string; fact: Fact | null }) {
  return <div className="mt-1 break-all"><p>{label}: {fact?.raw ?? fact?.value ?? "UNKNOWN"}</p>
    {fact && <p className="text-xs text-slate-500">{fact.provenance.document_id} · {fact.provenance.locator}</p>}
  </div>;
}
function SourceDate({ label, fact }: { label: string; fact: Eis223LotCancellation["common_cancellation_date"] }) {
  return <div><SourceFact label={label} fact={fact} />
    <p className="text-xs">Точность: {fact.status}; только дата, время UNKNOWN. Смещение источника: {fact.timezone_raw ?? "UNKNOWN"}.</p>
  </div>;
}
function ReasonList({ codes }: { codes: string[] }) {
  return <ul className="list-disc pl-5">{codes.map((code, i) => <li key={`${code}:${i}`}>{reasons[code] ?? code}</li>)}</ul>;
}

export function LotCancellation223State({ state, selected }: {
  state?: Eis223LotCancellationState | null; selected?: Eis223SelectedLotCancellationState | null;
}) {
  if (!state && !selected) return null;
  const hold = state?.operation_hold || selected?.operation_hold;
  return <section aria-label="Проверка отмены лотов 223-ФЗ" className="my-3 rounded border border-amber-300 bg-amber-50 p-3 text-sm">
    <p className="font-semibold">{hold ? "Сведения об отмене лотов: операции приостановлены до проверки" : "Проверка отмены лотов: UNKNOWN"}</p>
    <p>Связь с актуальным лотом, право участия и текущая стадия закупки: UNKNOWN.</p>
    {state && <>
      <p>Проверено: {state.checked_at}. Схема XML: {state.source_schema_status}. Проверка схемы не подтверждает отмену выбранного лота.</p>
      <ReasonList codes={state.reason_codes} />
      {state.events.length === 0 && <p>В проверенных данных нет событий. Отсутствие отмены: UNKNOWN.</p>}
    </>}
    {selected && <details className="mt-2">
      <summary>Выбранная позиция {selected.selected_index}: связь с событием UNKNOWN</summary>
      <p>Позиция выбора отсчитывается с 1; номер лота берётся отдельно из XML.</p>
      <SourceFact label="Номер лота в XML извещения" fact={selected.lot_ordinal} />
      <SourceFact label="GUID лота в извещении" fact={selected.lot_guid} />
      <p className="break-all">SHA-256 извещения: {selected.notice_xml_sha256}</p>
      <ReasonList codes={selected.reason_codes} />
      <p className="break-all">GUID событий с совпадением реквизитов: {selected.apparent_match_event_guids.join("; ") || "не найдены"}. Совпадение не доказывает тождество лота.</p>
    </details>}
    {state?.events.map((event, i) => <details key={`${event.xml_sha256}:${i}`} className="mt-2 border-t pt-2">
      <summary>Событие {event.event_guid.value ?? "UNKNOWN"} · {event.description_type}</summary>
      <SourceFact label="GUID события (источник)" fact={event.event_guid} />
      <p>Закупка: {event.purchase_number}</p>
      <p className="break-all text-xs text-slate-500">{event.purchase_number_provenance.document_id} · {event.purchase_number_provenance.locator}</p>
      <SourceFact label="GUID закупки" fact={event.purchase_guid} />
      <SourceFact label="Создано" fact={event.created_at} />
      <SourceFact label="Опубликовано" fact={event.publication_at} />
      <p>Время создания: {event.created_at.status}; публикации: {event.publication_at.status}.</p>
      <p>Вид описания: {event.description_type} ({event.description_type === "COMMON" ? "общее решение" : "решения по лотам"})</p>
      <p className="break-all text-xs text-slate-500">{event.description_type_provenance.document_id} · {event.description_type_provenance.locator}</p>
      <SourceDate label="Общая дата решения" fact={event.common_cancellation_date} />
      <SourceFact label="Общее основание" fact={event.common_cancellation_cause} />
      <p>Записей лотов в событии: {event.cancelled_lots.length}.</p>
      {event.cancelled_lots.map((lot, j) => <div key={j} className="my-2 border-l-2 pl-3">
        <SourceFact label="Номер лота в XML события (не позиция в массиве)" fact={lot.ordinal} />
        <SourceFact label="GUID из записи лота события; связь UNKNOWN" fact={lot.lot_guid} />
        <SourceFact label="Предмет" fact={lot.subject} />
        <SourceFact label="Совместный лот (исходное значение)" fact={lot.joint_lot} />
        <SourceDate label="Дата решения по лоту" fact={lot.cancellation_date} />
        <SourceFact label="Основание по лоту" fact={lot.cancellation_cause} />
      </div>)}
      <p className="break-all">SHA-256: {event.xml_sha256}</p>
      <p className="break-all">Файл источника: {event.source_member}</p>
    </details>)}
  </section>;
}
