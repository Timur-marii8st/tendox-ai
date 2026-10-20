"use client";

import { createContext, useContext, useRef, useState, useTransition, type ReactNode } from "react";
import type { Mixed44Row, MixedComparisonResult, MixedNoticeRef } from "@/lib/procurement-api";
import { compareMixed } from "./actions";
import { Comparison223Card } from "./comparison-223";
import { PositionEvidenceView } from "./position-evidence";
import { SourceEstimateForm } from "./source-estimate";

type Chosen = MixedNoticeRef & { title: string };
type Basket = {
  selected: Chosen[]; pending: boolean;
  toggle: (notice: Chosen) => void; clearLaw: (law: "44" | "223") => void;
};
const Context = createContext<Basket | null>(null);
function identity(ref: MixedNoticeRef) { return `${ref.law}:${ref.purchase_number}`; }
export function useMixedBasket() { return useContext(Context); }

export function AddToMixedComparison({ notice, disabled = false }: { notice: Chosen; disabled?: boolean }) {
  const basket = useMixedBasket();
  if (!basket) return null;
  const chosen = basket.selected.some(n => identity(n) === identity(notice));
  return <button type="button" aria-label={`${chosen ? "Убрать" : "Добавить"} ${notice.law}-ФЗ ${notice.purchase_number} в общее сравнение`}
    disabled={disabled || basket.pending || (!chosen && basket.selected.length >= 3)}
    className="mb-2 rounded border border-blue-700 px-3 py-2 text-sm font-semibold text-blue-800 disabled:opacity-50"
    onClick={() => basket.toggle(notice)}>{chosen ? "Убрать из общего сравнения" : "В общее сравнение 44/223"}</button>;
}

export function MixedComparisonProvider({ children }: { children: ReactNode }) {
  const [selected, setSelected] = useState<Chosen[]>([]);
  const [state, setState] = useState<{ result?: MixedComparisonResult; error?: string }>({});
  const [pending, start] = useTransition();
  const generation = useRef(0);
  function toggle(notice: Chosen) {
    generation.current++; setState({});
    setSelected(current => current.some(n => identity(n) === identity(notice))
      ? current.filter(n => identity(n) !== identity(notice))
      : current.length < 3 ? [...current, notice] : current);
  }
  function clearLaw(law: "44" | "223") {
    generation.current++; setState({});
    setSelected(current => current.filter(n => n.law !== law));
  }
  return <Context.Provider value={{ selected, pending, toggle, clearLaw }}>
    <details open={selected.length > 0} aria-label="Общее сравнение 44-ФЗ и 223-ФЗ" className="mt-6 rounded-xl border border-blue-300 bg-blue-50 p-4">
      <summary className="cursor-pointer text-lg font-bold">Сравнение 44-ФЗ и 223-ФЗ · выбрано {selected.length} из 3</summary>
      <p className="mt-1 text-sm">Добавьте 2–3 карточки кнопкой «В общее сравнение» в результатах поиска ниже.
        Выбрано: {selected.length} из 3. Новый поиск убирает выбор только своего закона.</p>
      <ul className="mt-2 text-sm">{selected.map(n => <li key={identity(n)} className="mt-1">
        {n.law}-ФЗ · № {n.purchase_number} · версия {n.version_number} · {n.title}
        <button type="button" disabled={pending} className="ml-2 underline disabled:opacity-50"
          aria-label={`Удалить ${n.law}-ФЗ ${n.purchase_number} из корзины`} onClick={() => toggle(n)}>Убрать</button>
      </li>)}</ul>
      <button disabled={pending || selected.length < 2} className="mt-3 rounded bg-blue-700 px-4 py-2 font-bold text-white disabled:opacity-50"
        onClick={() => {
          const epoch = generation.current;
          const refs = selected.map(({law, purchase_number, version_number, notice_xml_sha256}) => ({law, purchase_number, version_number, notice_xml_sha256}));
          start(async () => {
            const next = await compareMixed(refs);
            if (generation.current === epoch) setState(next);
          });
        }}>{pending ? "Сравнение…" : "Сравнить общую корзину"}</button>
      {state.error && <p role="alert" className="mt-2 text-red-800">{state.error}</p>}
      {state.result && <div className="mt-4">
        <h3 className="font-bold">Выбранные карточки 44-ФЗ и 223-ФЗ</h3>
        <p className="text-sm">Проверено {state.result.checked_at}. Порядок — по выбору пользователя.
          НМЦК 44-ФЗ и цены отдельных лотов 223-ФЗ имеют разный смысл.
          Сопоставимость товаров, полнота ЕИС, допуск и рейтинг прибыли: UNKNOWN.</p>
        <details className="mt-3 rounded border bg-white p-3 text-sm">
          <summary>Предложенные связи между позициями: {state.result.position_links.length}</summary>
          <p>Совпадение имени или кода — повод проверить позиции. Эквивалентность товара и сопоставимость цен: UNKNOWN.</p>
          {!state.result.position_links.length && <p>По именам и кодам связи не предложены. Можно изучить характеристики и таблицы каждой карточки.</p>}
          {state.result.position_links_truncated && <p>Список связей сокращён до 24.</p>}
          {state.result.position_links.map((link,i) => <div key={i} className="mt-2 border-t pt-2">
            <p>Карточка {link.left_row + 1}, позиция {link.left_position} ↔ карточка {link.right_row + 1}, позиция {link.right_position}.</p>
            <p>Совпало: {link.basis === "NAME" ? "название" : link.basis === "KTRU" ? "КТРУ" : "код классификации"}.</p>
            <ul className="list-disc pl-4">{link.differences.map(code => <li key={code}>{differenceLabel(code)}</li>)}</ul>
            <details className="text-xs"><summary>Источники обеих позиций</summary>
              {link.evidence.map((p,j) => <p key={j} className="break-all">{p.document_id} · {p.locator}</p>)}
            </details>
          </div>)}
        </details>
        <div className={`mt-3 grid gap-4 ${state.result.rows.length === 2 ? "lg:grid-cols-2" : "lg:grid-cols-3"}`}>
          {state.result.rows.map(row => <div key={`${row.law}:${row.law === "44" ? row.evidence.notice.purchase_number : row.notice.purchase_number}`}>
            <p className="mb-1 font-bold">{row.law}-ФЗ</p>
            {row.law === "223" ? <><Comparison223Card row={row} /><PositionEvidenceView set={row.position_set} /></> : <Comparison44Card row={row} />}
            <SourceEstimateForm key={`${state.result!.checked_at}:${row.law}:${row.law === "44" ? row.evidence.notice.notice_xml_sha256 : row.notice.xml_sha256}`}
              notice={{ law: row.law, ...(row.law === "44" ? row.evidence.notice : {
                purchase_number: row.notice.purchase_number, version_number: row.notice.version_number, notice_xml_sha256: row.notice.xml_sha256,
              }) }} lots={row.law === "223" ? row.notice.lots.map((lot,i) => ({ index: i + 1,
                title: `Лот ${i + 1} · ${lot.ordinal.value ?? "номер UNKNOWN"} · ${lot.subject.value ?? "предмет UNKNOWN"}` })) : []} />
          </div>)}
        </div>
      </div>}
    </details>
    {children}
  </Context.Provider>;
}

function Comparison44Card({ row }: { row: Mixed44Row }) {
  const e = row.evidence;
  return <article className="min-w-0 rounded-lg border bg-white p-3 text-sm">
    <h4 className="font-bold">№ {e.notice.purchase_number} · версия {e.notice.version_number}</h4>
    <p>{e.title}</p><p className="mt-2 font-bold">Готовность: {row.readiness_status}</p>
    {!!row.blocking_reasons.length && <p className="font-bold text-red-800">{row.blocking_reasons.join("; ")}</p>}
    <p>Срок: {e.deadline ?? "UNKNOWN"}</p>
    {row.deadline_provenance && <details className="text-xs"><summary>Источник срока</summary><p className="break-all">{row.deadline_provenance.locator}</p></details>}
    <p>Полная проверка официальной XSD: UNKNOWN.</p>
    <h5 className="mt-3 font-bold">НМЦК и позиции</h5>
    <p className="font-bold">НМЦК: {e.nmck_rub ?? "UNKNOWN"} {e.nmck_rub !== null ? "RUB" : ""}</p>
    {e.nmck_provenance && <details className="text-xs"><summary>Источник НМЦК</summary><p className="break-all">{e.nmck_provenance.locator}</p></details>}
    <p>Разбор позиций: {e.lot_parse_status}</p>
    <PositionEvidenceView set={e.position_set} />
    {e.document_type === "epNotificationEOK2020" && <p className="mt-2 text-amber-800">Критерии оценки конкурса в этом быстром сравнении UNKNOWN. Нужна отдельная проверка.</p>}
    <h5 className="mt-3 font-bold">Документы и условия</h5>
    <p>Получено {e.collection.received_count} из {e.collection.listed_count}. Загрузка: {e.collection.download_status}.</p>
    <p>Полнота ТЗ, проверка требований и прибыль: UNKNOWN.</p>
    {e.collection.documents.map(doc => {
      const preview = e.documents.find(d => d.content_uid === doc.content_uid);
      return <details key={doc.content_uid} className="mt-2 rounded border p-2">
        <summary>{doc.filename} · {doc.fetch_status === "RECEIVED" ? "получен" : "не получен"}</summary>
        <p>Извлечение: {doc.extraction_status}. Роль и проверка: UNKNOWN.</p>
        <p className="break-all text-xs">UID: {doc.content_uid} · {doc.source_locator}<br />SHA-256: {doc.sha256 ?? "UNKNOWN"}</p>
        <p>{doc.reasons.join("; ")}</p>
        <p>Показано {preview?.conditions.length ?? 0} из {preview?.conditions_total ?? 0} фрагментов.
          {preview?.conditions_truncated && " Превью сокращено; полный извлечённый текст сохранён на сервере."}</p>
        {preview?.conditions.map((c,i) => <blockquote key={i} className="mt-2 border-l-2 pl-2">
          <p><strong>{c.kind}:</strong> {c.excerpt}{c.truncated && "… (сокращено)"}</p>
          <p className="break-all text-xs">{c.provenance.document_id} · {c.provenance.locator}</p>
          {c.context?.map((b,j) => <div key={j} className="mt-1 bg-amber-50 p-2">
            <p>Следующий абзац, связь требует проверки: {b.excerpt}{b.truncated && "…"}</p>
            <p className="break-all text-xs">{b.provenance.document_id} · {b.provenance.locator}</p>
          </div>)}
        </blockquote>)}
      </details>;
    })}
    <ul className="mt-3 list-disc pl-4">{row.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>
    <details className="mt-3 text-xs"><summary>Источники карточки</summary><p className="break-all">
      XML: {e.notice.notice_xml_sha256}<br />Архив: {row.archive_sha256}<br />Ответ источника: {row.source_response_sha256}<br />Окно: {row.source_window}
    </p></details>
  </article>;
}

function differenceLabel(code: string) {
  const labels: Record<string, string> = {
    SOURCE_QUANTITY_DIFFERS: "Количество в источниках различается.",
    SOURCE_UNIT_LABEL_DIFFERS: "Исходные обозначения единиц различаются; преобразование не подтверждено.",
    QUANTITY_UNKNOWN: "Количество одной из позиций UNKNOWN.", UNIT_UNKNOWN: "Единица одной из позиций UNKNOWN.",
    CHARACTERISTICS_UNKNOWN: "Характеристики одной из позиций UNKNOWN.",
    SOURCE_CHARACTERISTIC_VALUES_DIFFER: "Значения одноимённых характеристик различаются.",
    CHARACTERISTIC_SETS_DIFFER: "Наборы названий характеристик различаются.",
    CLASSIFICATION_DOES_NOT_ESTABLISH_EQUIVALENCE: "Общий код классификации не подтверждает одинаковый товар.",
    SOURCE_PREVIEW_TRUNCATED: "Часть исходных позиций или характеристик не вошла в превью.",
  };
  return labels[code] ?? "Различие требует проверки по источнику.";
}
