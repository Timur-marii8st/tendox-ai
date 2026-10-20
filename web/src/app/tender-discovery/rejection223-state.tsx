"use client";

import type { Eis223RejectionState } from "@/lib/procurement-api";

const reasons: Record<string, string> = {
  NO_REJECTION_EVENT_EVIDENCE: "В сохранённых данных нет события отмены; отсутствие отмены не подтверждено.",
  EVENT_EVIDENCE_LIMIT: "Превышен предел проверки событий; требуется дополнительная сверка.",
  EVENT_GUID_TARGET_CONFLICT: "Один идентификатор события связан с разными закупками.",
  EVENT_GUID_VARIANTS: "Для одного идентификатора события получены разные исходные XML.",
  REJECTION_EVIDENCE_INCOMPLETE: "Соответствие схемам не подтверждено либо даты отсутствуют, не имеют часового пояса или находятся в будущем.",
  REJECTION_EVENT_TIME_ORDER_UNRESOLVED: "Дата создания или принятия решения позже публикации события; последовательность дат требует проверки.",
  PURCHASE_REJECTION_CONFIRMED: "Исходное событие отмены подтверждено; участие заблокировано, текущая стадия процедуры остаётся UNKNOWN.",
  PURCHASE_REJECTION_REVIEW_REQUIRED: "Для сведений об отмене требуется дополнительная проверка; операции приостановлены.",
};

export function Rejection223State({ state }: { state?: Eis223RejectionState | null }) {
  if (!state) return null;
  const confirmed = state.evidence_status === "PASS" && state.application_status === "FAIL";
  return <section aria-label={`События отмены закупки ${state.purchase_number}`}
    className={`mt-2 rounded border p-3 text-sm ${confirmed ? "border-red-300 bg-red-50 text-red-900" : state.operation_hold ? "border-amber-300 bg-amber-50 text-amber-900" : "border-slate-200 text-slate-700"}`}>
    <p className="font-bold">{confirmed
      ? "Подтверждено событие отмены закупки. Участие заблокировано: FAIL."
      : state.operation_hold
        ? "Сведения об отмене требуют проверки. Операции приостановлены; участие: UNKNOWN."
        : "Отсутствие отмены не подтверждено: UNKNOWN."}</p>
    <p>Текущая стадия процедуры: {state.current_procedure_status}. Восстановление закупки требует отдельной проверки.</p>
    <p>Оценка прибыли и рекомендация участия из этих сведений не следуют.</p>
    {state.reason_codes.length > 0 && <ul className="mt-1 list-disc pl-4">{state.reason_codes.map((code, i) =>
      <li key={`${code}:${i}`}>{reasons[code] ?? `Требуется проверка источника: ${code}`}</li>)}</ul>}
    <details className="mt-2 text-xs"><summary>Доказательства события и время проверки</summary>
      <p>Проверено: {state.checked_at}. Полнота evidence: {state.evidence_status}. Событий: {state.events.length}.</p>
      {state.events.map(event => <div className="mt-2 break-all" key={`${event.event_guid.value}:${event.xml_sha256}`}>
        <p>Номер в событии: {event.purchase_number}. GUID: {event.event_guid.value ?? "UNKNOWN"}.</p>
        <p>Публикация: {event.publication_at.value ?? `${event.publication_at.raw ?? "нет данных"} — UNKNOWN`}.</p>
        <p>Решение: {event.rejection_at.value ?? `${event.rejection_at.raw ?? "нет данных"} — UNKNOWN`}.</p>
        <p>XML SHA-256: {event.xml_sha256}<br />Файл источника: {event.source_member}</p>
        <p>{event.event_guid.provenance.locator}<br />{event.purchase_number_provenance.locator}</p>
      </div>)}
    </details>
  </section>;
}
