import type { SavedAssociation } from "@/lib/eis-position-association";
export function PositionAssociationReportView({ result }: { result: SavedAssociation }) {
  const r = result.report;
  return <section className="mt-3 rounded border border-blue-300 bg-white p-3" aria-label="Сохранённая связь позиции с фрагментами">
    <h5 className="font-bold">Фрагменты связаны оператором с позицией {r.request.position.selection.source_index}: {r.position_name.value ?? "UNKNOWN"}</h5>
    <p>Документ: {r.filename}. Выбрано {r.fragments.length} фрагментов / {r.selected_characters} символов из {r.retained_total} сохранённых блоков.</p>
    <p>Это выбранный контекст позиции. Требования ещё не нормализованы и не утверждены. Полнота ТЗ, соответствие товара, КП и участие: UNKNOWN.</p>
    <p>Связал: {r.linked_by}; сохранено: {r.created_at}. {result.created ? "Новая связь." : "Сохранённая связь."} Загрузок и заданий ЕИС: 0.</p>
    <p className="break-all text-xs">XML {r.request.position.selection.notice.notice_xml_sha256} · документ {r.request.document.expected_document_sha256} · UID {r.request.document.content_uid}</p>
    <p className="break-all text-xs">Анализ {r.analysis_sha256} · {r.request.analyzer_version}; позиция {r.position_sha256}</p>
    {r.fragments.map(f => <blockquote key={`${f.selection.block_index}:${f.selection.character_start}`} className="mt-2 whitespace-pre-wrap border-l-2 pl-2">
      <p>{f.text}</p><p className="break-all text-xs">{f.provenance.locator} · {f.provenance.document_id}</p>
    </blockquote>)}
  </section>;
}
