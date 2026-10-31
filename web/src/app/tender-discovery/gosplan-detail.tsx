import type { GosplanDetail } from "../../lib/procurement-api";

export function GosplanDetailContent({ detail }: { detail: GosplanDetail }) {
  return <>
    <p>Источник: ГосПлан, получено {detail.observed_at}. Актуальность проверяйте в ЕИС.</p>
    {detail.eis_url && <p><a href={detail.eis_url} target="_blank" rel="noopener noreferrer">{detail.eis_url_origin === "NUMBER_DERIVED" ? "Найти карточку ЕИС по номеру" : "Открыть в ЕИС"} ↗</a></p>}
    {!detail.eis_url && <p>Ссылка на карточку ЕИС не подтверждена.</p>}
    {detail.platform_url && <p><a href={detail.platform_url} target="_blank" rel="noopener noreferrer">Открыть на площадке ↗</a></p>}
    {!detail.platform_url && <p>Ссылка на площадку не найдена.</p>}
    <h3>Документы</h3>
    <p>Ссылки могут относиться к разным версиям извещения; актуальную версию проверьте в ЕИС.</p>
    {detail.documents.length ? <ul>{detail.documents.map(doc => <li key={doc.url}><a href={doc.url} target="_blank" rel="noopener noreferrer">{doc.name} ↗</a></li>)}</ul> : <p>Доступные ссылки на документы не найдены.</p>}
    {detail.documents_truncated && <p>Показаны первые 50 ссылок. Полный перечень проверяйте в источнике.</p>}
  </>;
}
