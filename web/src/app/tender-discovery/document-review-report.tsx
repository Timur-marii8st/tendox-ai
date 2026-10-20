import type { SavedReviewPage } from "@/lib/eis-document-review";

export function DocumentReviewReport({ report }: { report: SavedReviewPage }) {
  const p = report.page;
  return <div className="mt-3 rounded border border-slate-300 bg-white p-3">
    <h5 className="font-bold">Сохранённый текст: {report.filename}</h5>
    <p className="mt-1">Область разбора: параграфы и таблицы тела DOCX. Колонтитулы и другие части документа не покрыты.</p>
    <p className="font-bold text-amber-900">Полнота документа и ТЗ: UNKNOWN. Роль, требования и участие: UNKNOWN.</p>
    <p>Извлечено блоков: {p.blocks_extracted_total ?? "UNKNOWN"}; символов: {p.characters_extracted ?? "UNKNOWN"}.
      Сохранено: {p.retained_total} блоков, {p.retained_characters} символов.</p>
    <p>{p.retained_extracted_text_complete ? "Сохранён весь извлечённый текст тела документа." : "Сохранение извлечённого текста неполно или не подтверждено."}</p>
    {p.retention_truncated && <p className="font-bold text-amber-900">Текст усечён при сохранении: {p.retention_reasons.join(", ")}.</p>}
    <p className="text-xs text-slate-600">Лимиты: файл 4 МиБ, раскрытие DOCX 32 МиБ; сохранение 1000 блоков / 100000 символов.
      На странице до 25 блоков / 16000 символов.</p>
    <p>Извлечение: {p.extraction_status}; {p.extraction_reasons.join(", ") || "ограничения не сообщены"}.</p>
    {p.rejection_code && <p role="alert" className="text-red-800">Документ не разобран: {p.rejection_code}.</p>}
    <p className="mt-1 break-all text-xs">№{report.request.notice.purchase_number}, версия {report.request.notice.version_number};
      XML SHA-256 {report.request.notice.notice_xml_sha256}; UID {report.request.content_uid}.
      Документ SHA-256 {p.sha256}; {report.source_locator}.</p>
    <p className="text-xs">Получен: {report.observed_at}; анализ: {report.analyzed_at}.
      Новых загрузок и заданий ЕИС: 0.</p>
    <p className="mt-2">Страница: блок {p.offset + 1}, смещение {p.character_offset}.
      {p.next_offset === null ? " Конец сохранённого текста." : " Есть следующая страница."}</p>
    {p.page_text_truncated && <p className="text-amber-900">Длинный блок продолжается на другой странице; весь сохранённый текст доступен через навигацию.</p>}
    {!!p.delivery_lead_indices.length && <p className="text-amber-900">Отмечены фрагменты о поставке и соседний контекст. Адреса, сроки и связь с позициями требуют проверки: UNKNOWN.</p>}
    {!p.blocks.length && <p>Сохранённых блоков текста на этой странице нет.</p>}
    {p.blocks.map(b => <blockquote key={`${b.block_index}:${b.character_start}`}
      className={`mt-2 whitespace-pre-wrap border-l-2 pl-2 ${p.delivery_lead_indices.includes(b.block_index) ? "border-amber-500 bg-amber-50" : "border-slate-300"}`}>
      <p>{b.text}</p>
      <p className="break-all text-xs text-slate-600">{b.provenance.locator} · SHA-256 {b.provenance.document_id}
        {b.text_truncated && ` · символы ${b.character_start + 1}–${b.character_end} из ${b.source_character_count}`}</p>
    </blockquote>)}
  </div>;
}
