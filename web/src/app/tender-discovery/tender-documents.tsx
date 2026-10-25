import type { TenderRow } from "../../lib/tender-workspace";

/** Исходные файлы выбранного XML, без догадки о роли или полноте комплекта. */
export function TenderDocuments({ row }: { row: TenderRow }) {
  return <section aria-label="Документы закупки">
    <h3>ТЗ и документы закупки</h3>
    <p>Откройте исходный файл с описанием объекта закупки или техническим заданием.
      Роли файлов и полнота комплекта требуют проверки. Версия {row.version}.</p>
    {row.documents.length === 0 ? <p>В сохранённом извещении нет доступного списка файлов.
      Проверьте комплект в ЕИС. Отсутствие списка не означает отсутствие ТЗ.</p> :
      <ul>{row.documents.map((file, index) => <li key={`${file.locator}:${index}`}>
        {file.available && file.url ? <a href={file.url} target="_blank" rel="noopener noreferrer">{file.filename} ↗</a>
          : <span>{file.filename} · ссылка недоступна или доступ ограничен</span>}
        <details><summary>Источник файла</summary><p>XML {row.xmlSha256} · {file.locator}</p></details>
      </li>)}</ul>}
  </section>;
}
