import type { ReactNode } from "react";
import type { SavedSupplierSerp, SearchEngine, SerpLink } from "@/lib/eis-supplier-serp";

const statusText: Record<string, string> = {
  COMPLETED: "Выдача прочитана", EMPTY: "Поисковик сообщил об отсутствии результатов",
  BLOCKED: "Проверка робота: поиск остановлен", RATE_LIMITED: "Лимит поисковика",
  TIMEOUT: "Время ожидания истекло", SOURCE_CHANGED: "Структура выдачи не подтверждена",
  SOURCE_ERROR: "Ошибка источника", BROWSER_UNAVAILABLE: "Браузер недоступен",
  COOLDOWN: "Пауза после отказа поисковика",
};
const engineText: Record<SearchEngine, string> = { BING: "Bing", BRAVE: "Brave Search", DUCKDUCKGO: "DuckDuckGo", MOJEEK: "Mojeek", YANDEX: "Яндекс", GOOGLE: "Google" };
export function SupplierSerpReportView({ result, renderPage }: { result: SavedSupplierSerp; renderPage?: (engine: SearchEngine, link: SerpLink) => ReactNode }) {
  const r = result.report;
  return <section className="mt-3 rounded border p-3" data-supplier-serp-report={r.run_id}>
    <h4 className="font-semibold">Сайты для проверки предложения</h4>
    <p>Позиция: {r.position_name.value ?? "Наименование не установлено"}</p>
    <p>Запрос: {r.query ?? "Не сформирован"}</p>
    <p>Попытка сохранена: {r.created_at}. Новых переходов к поисковикам: {result.source_requests}.</p>
    <p className="text-sm">Цена, роль производителя или поставщика, наличие, доставка и соответствие закупке пока не подтверждены. Полный охват рынка неизвестен.</p>
    {r.policy_version === "eis-position-supplier-serp-v2" && <p className="text-sm font-semibold text-amber-800">Это архивная выдача по отозванному методу шести поисковиков. Brave Search, DuckDuckGo и Mojeek больше не используются; обновление создаст активную выдачу только Bing, Яндекс и Google.</p>}
    {r.status === "STARTED" && <p role="status">Попытка начата; итог ещё не сохранён. Откройте сохранённый поиск позже.</p>}
    {r.status === "QUERY_NOT_COVERED" && <p>Наименование позиции не подходит для публичного запроса.</p>}
    {r.status === "PARTIAL" && <p>Доступна часть источников. Отказы других поисковиков показаны ниже.</p>}
    {r.status === "UNAVAILABLE" && <p>Выдача поисковиков недоступна. Это не означает отсутствие поставщиков.</p>}
    {r.batch?.attempts.map(a => <section key={a.engine} className="mt-3 border-t pt-2" data-search-engine={a.engine}>
      <h5 className="font-semibold">{engineText[a.engine]}: {statusText[a.status]}</h5>
      <p className="text-xs">{a.observed_at} · {a.elapsed_ms} мс · ссылок: {a.returned_count}{a.truncated ? " · выдача ограничена" : ""}</p>
      <a className="underline" href={a.source_url} target="_blank" rel="noopener noreferrer">Открыть этот запрос в поисковике</a>
      <ol className="mt-2 space-y-2">{a.links.map(link => <li key={link.url}>
        <p>{link.rank}. <a className="underline" href={link.url} target="_blank" rel="noopener noreferrer">{link.title}</a></p>
        <p className="text-xs break-all">{new URL(link.url).hostname}</p>
        {link.snippet && <p>{link.snippet}</p>}
        <p className="text-xs">Непроверенная ссылка из выдачи. Цена и соответствие: неизвестны.</p>
        <details className="text-xs"><summary>Источник наблюдения</summary><p className="break-all">DOM SHA256: {link.dom_sha256}</p><p>{link.locator}</p></details>
        {renderPage?.(a.engine, link)}
      </li>)}</ol>
    </section>)}
  </section>;
}
