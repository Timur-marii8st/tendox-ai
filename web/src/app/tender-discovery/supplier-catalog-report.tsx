import type { ReactNode } from "react";
import type { CatalogLink, SavedSupplierCatalog } from "@/lib/eis-supplier-catalog";
import { SupplierPageReportView } from "./supplier-page-report";
export function SupplierCatalogReportView({ result, renderProduct }: { result: SavedSupplierCatalog; renderProduct?: (link: CatalogLink) => ReactNode }) {
  const r = result.report;
  return <section className="mt-2 rounded border p-3" data-supplier-catalog-report={r.run_id}>
    <h5 className="font-semibold">{r.stage === "SEARCH" ? "Товары на сайте поставщика" : "Выбранная товарная карточка"}</h5>
    {r.search_spec && <p>Поиск на сайте по позиции: {r.search_spec.query}.</p>}
    {r.selected_link && <p>Выбрано из сохранённого поиска: {r.selected_link.title}.</p>}
    {r.stage === "SEARCH" && <>
      {r.status === "STARTED" && <p role="status">Поиск начат; исход ещё не сохранён.</p>}
      <p>Сохранено {r.created_at}. Новых попыток HTTP-чтения: {result.source_requests}.</p>
      {r.observation && <p>Исход чтения: {r.observation.status}, HTTP {r.observation.http_status ?? "не получен"}.</p>}
      {r.links && <>
        <p>Найдено ссылок в этом снимке: {r.links.returned_count}. {r.links.truncated && "Показана ограниченная часть; полный охват неизвестен."}</p>
        {r.links.status === "EMPTY" && <p>Поддержанные товарные ссылки не найдены.</p>}
        {["UNSUPPORTED", "LIMIT_EXCEEDED"].includes(r.links.status) && <p>Структура ответа не разобрана полностью; результат неизвестен.</p>}
        <ol>{r.links.links.map(link => <li key={link.index} className="mt-2 border-t pt-2">
          <a href={link.url} target="_blank" rel="noopener noreferrer" className="underline">{link.title}</a>
          <p className="text-xs">Кандидат из каталога. Цена и соответствие пока не проверены.</p>
          <details className="text-xs"><summary>Источник ссылки</summary><p>{link.locator}</p><p className="break-all">HTML SHA256: {link.html_sha256}</p></details>
          {renderProduct?.(link)}
        </li>)}</ol>
      </>}
    </>}
    {r.stage === "PRODUCT" && <SupplierPageReportView result={result} />}
    <p className="mt-2 text-sm">Порядок ссылок на сайте не означает выгодность. Условия партии, НДС, доставка, соответствие ТЗ и полное КП требуют проверки.</p>
  </section>;
}
