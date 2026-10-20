import type { AssociationListResult } from "@/lib/eis-position-association";
export function PositionAssociationListView({ result, pending = false, onOpen, onNext }:
  { result: AssociationListResult; pending?: boolean; onOpen: (id: string) => void; onNext: () => void }) {
  return <section className="mt-3 rounded border bg-white p-3" aria-label="Сохранённые связи выбранной позиции">
    <h5 className="font-bold">Сохранённые связи этой позиции и документа</h5>
    <p>Показаны связи, проверенные по текущему источнику. Выберите связь для открытия. Повторное выделение строк не требуется. Требования и полнота ТЗ: UNKNOWN.</p>
    {result.items.length === 0 ? <p>Для этой точной позиции и документа сохранённых связей на этой странице нет.</p> : <ul>
      {result.items.map(item => <li key={item.association_id} className="mt-2 rounded border p-2">
        <p>{item.created_at} · {item.linked_by} · {item.fragment_count} фрагментов / {item.selected_characters} символов</p>
        <p className="break-all text-xs">ID {item.association_id}</p>
        <button type="button" disabled={pending} className="underline disabled:opacity-50" onClick={() => onOpen(item.association_id)}>Открыть эту связь</button>
      </li>)}
    </ul>}
    {result.next_cursor && <button type="button" disabled={pending} className="mt-2 underline disabled:opacity-50" onClick={onNext}>Следующая страница сохранённых связей</button>}
    <p className="mt-2 text-xs">До {result.request.limit} связей на странице. Чтение: 0 загрузок, 0 заданий и 0 записей.</p>
  </section>;
}
