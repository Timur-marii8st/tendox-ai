"use client";

import { useActionState } from "react";
import Link from "next/link";

import type { BrowserCatalogAttempt, CatalogPageEvidence, DocumentSupplierSearchPlan, SupplierSearchMode } from "@/lib/procurement-api";

import { executeDocumentSearch, type DocumentSearchState } from "./actions";

const statusMessage: Record<Exclude<DocumentSupplierSearchPlan["status"], "READY">, string> = {
  NO_PRODUCT_ANCHOR: "В извлечённом тексте нет явного названия товара после метки «Наименование товара» или «Предмет закупки». Поисковая фраза остаётся неизвестной.",
  AMBIGUOUS: "В ТЗ найдены разные названия товаров. Автоматический запрос не запускается, пока предмет поиска неоднозначен.",
  EXTRACTION_UNAVAILABLE: "Извлечение текста не завершено либо документ не является ТЗ. Автоматический запрос недоступен.",
};

const modes: Record<SupplierSearchMode, string> = {
  AUTO: "Автоматически", HTTP: "Только прямой доступ", BROWSER: "Через браузер",
};

const browserStatus: Record<BrowserCatalogAttempt["status"], string> = {
  COMPLETED: "Категория загружена", BLOCKED: "Площадка ограничила доступ или показала CAPTCHA",
  RATE_LIMITED: "Площадка просит сделать паузу", AUTH_REQUIRED: "Площадка требует входа в аккаунт",
  SOURCE_CHANGED: "Адрес или структура каталога изменились", SOURCE_ERROR: "Не удалось загрузить страницу",
  TIMEOUT: "Площадка не ответила за отведённое время", PROFILE_BUSY: "Для этой компании уже идёт просмотр площадки",
  COOLDOWN: "Пауза перед следующим обращением к площадке", QUERY_NOT_COVERED: "Категория для этого товара не подключена",
  BROWSER_UNAVAILABLE: "Браузер на сервере не установлен или не запускается",
  WORKER_BUSY: "Все браузеры сейчас заняты; повторите поиск позже",
  PARTIAL: "Получена часть страниц; продолжение не удалось проверить",
};

function PageEvidence({ pages, stop }: { pages: CatalogPageEvidence[]; stop: string | null }) {
  return <details className="my-2 text-xs text-slate-600"><summary>Проверенные страницы и границы поиска</summary>
    {pages.map((page) => <p key={page.page_number} className="break-all">
      Страница {page.page_number}: {page.status === "COMPLETED" ? `просмотрено ${page.scanned_count}, совпало по названию ${page.matched_count}` : `ошибка (${page.error_code})`}.
      {" "}<a href={page.source_url} target="_blank" rel="noopener noreferrer" className="underline">Источник</a>
      {page.sha256 && <> · SHA-256 {page.sha256}</>}
      {page.continuation_evidence && <> · продолжение: {page.continuation_evidence === "LINK" ? "ссылка на странице" : page.continuation_evidence === "PAGE_STATE" ? "данные каталога на странице" : "ссылка и данные каталога"}
        {page.continuation === "END_REPORTED" ? " (источник сообщил последнюю страницу)" : " (есть следующая страница)"}</>}
    </p>)}
    <p>{stop === "PAGE_LIMIT" ? "Достигнут лимит страниц; выдача может продолжаться."
      : stop === "NO_NEXT_EVIDENCE" ? "Подтверждение продолжения не найдено. Полнота каталога не подтверждена."
      : stop === "END_REPORTED" ? "Источник сообщил последнюю страницу этой выдачи. Полнота каталога не подтверждена."
      : "Полнота выдачи неизвестна."}</p>
  </details>;
}

function BrowserResult({ attempt }: { attempt: BrowserCatalogAttempt }) {
  return <div className="mt-4 rounded-lg border border-slate-200 p-3">
    <h4 className="m-0 font-bold">{attempt.site === "servermall" ? "ServerMall" : attempt.site === "supl_biz" ? "Supl.biz · промышленные насосы" : "Яндекс Маркет для Бизнеса"} · через браузер</h4>
    <p className="text-sm" role={attempt.status === "COMPLETED" ? undefined : "status"}>
      {browserStatus[attempt.status]}. {attempt.status === "COMPLETED" || attempt.status === "PARTIAL"
        ? `Совпадений по названию: ${attempt.candidates.length}. Просмотрено карточек: ${attempt.scanned_count ?? "не указано"}. Успешно прочитано страниц: ${attempt.pages.filter(p => p.status === "COMPLETED").length}.`
        : "Результат этого источника неизвестен."}
    </p>
    {attempt.query_mode === "CATEGORY_PREVIEW" && <p className="text-xs text-slate-600">Просмотр категории по товарной группе; точное совпадение с запросом не подтверждено.</p>}
    {attempt.candidates.map((item) => <p className="my-2 text-sm" key={item.url}>
      <a className="text-blue-700 underline" href={item.url} target="_blank" rel="noopener noreferrer">{item.title}</a> · соответствие UNKNOWN
      {item.seller_name && item.seller_url && <> · продавец по данным площадки: <a className="text-blue-700 underline" href={item.seller_url} target="_blank" rel="noopener noreferrer">{item.seller_name}</a></>}
      {item.source_page_number && <> · страница {item.source_page_number}</>}
    </p>)}
    {attempt.status !== "COMPLETED" && attempt.retry_at && <p className="text-xs text-slate-600">
      Следующая попытка не раньше {new Date(attempt.retry_at).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" })} (МСК).
    </p>}
    {attempt.status !== "COMPLETED" && <a className="text-sm text-blue-700 underline" href={attempt.source_url} target="_blank" rel="noopener noreferrer">Открыть площадку вручную</a>}
    <details className="mt-2 text-xs text-slate-500"><summary>Источник и проверка</summary>
      <p className="break-all">{attempt.source_url} · {attempt.observed_at}</p>
      <p className="break-all">{attempt.dom_sha256 ? `SHA-256 страницы: ${attempt.dom_sha256}` : `Причина: ${attempt.reason ?? attempt.status}`}</p>
    </details>
    <PageEvidence pages={attempt.pages} stop={attempt.stop_reason} />
  </div>;
}

export function DocumentSupplierSearch({ plan }: { plan: DocumentSupplierSearchPlan }) {
  const [state, action, pending] = useActionState(
    executeDocumentSearch,
    {} as DocumentSearchState,
  );
  return <section className="mt-8 rounded-xl border border-blue-200 bg-white p-5">
    <h2 className="mt-0 text-xl font-black">Поиск по загруженному ТЗ</h2>
    <nav className="mb-3 flex flex-wrap gap-2" aria-label="Способ поиска">
      {(Object.keys(modes) as SupplierSearchMode[]).map((mode) => <Link
        key={mode} aria-current={plan.mode === mode ? "page" : undefined}
        className={`rounded-lg border px-3 py-2 text-sm ${plan.mode === mode ? "bg-slate-950 text-white" : "bg-white text-slate-800"}`}
        href={`/supplier-discovery?document_id=${encodeURIComponent(plan.document_id)}&mode=${mode}`}
      >{modes[mode]}</Link>)}
    </nav>
    <p className="break-all text-xs text-slate-600">Документ {plan.document_id} · SHA-256 {plan.source_document_sha256} · план {plan.plan_sha256}</p>
    {plan.status !== "READY" && <>
      <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{statusMessage[plan.status]}</p>
      {plan.alternative_evidence.map((item) => <p className="text-sm" key={`${item.provenance.locator}-${item.query}`}>
        {item.query} · {item.provenance.locator}
      </p>)}
    </>}
    {plan.status === "READY" && plan.query_evidence && <>
      <p className="text-sm">Запрос из ТЗ: <strong>{plan.query}</strong> · источник: {plan.query_evidence.provenance.locator}.</p>
      <p className="text-sm text-slate-600">Проверьте точные фразы и адреса ниже. Запуск обратится к указанным источникам. Для ServerMall, Яндекс Маркета, Гравитона, DEPO и Supl.biz охват ограничен категориями; результаты не сохраняются в кейс.</p>
      <p className="text-sm text-slate-600">Категория выбирается по товару. В каталогах сравниваются слова запроса с названием карточки; характеристики и роль производителя ещё не подтверждены. Яндекс Маркет: до двух страниц, если ссылка или данные каталога подтверждают продолжение.</p>
      {plan.destinations.length === 1 && <p className="text-sm text-amber-900">Для этого товара торговый каталог пока не выбран. Поиск выполнится только в реестре ЕАЭС.</p>}
      {plan.destinations.some((destination) => destination.browser_loads_page_resources) && <p className="text-sm text-slate-600">
        {plan.mode === "AUTO" ? "Supl.biz откроется через браузер; при ошибке прямого чтения ServerMall или Яндекс Маркета браузер подключится и для них." : "ServerMall, Яндекс Маркет и Supl.biz откроются через браузер. Реестр ЕАЭС, Гравитон и DEPO используют прямой HTTP-доступ."}
        {" "}Браузер загружает страницу и её ресурсы, включая ресурсы других доменов, и сохраняет отдельную сессию вашей компании. Поиск может занять до полутора минут.
      </p>}
      <div className="max-h-56 overflow-y-auto rounded-lg border border-slate-200 p-3">
        {plan.destinations.map((destination) => <p className="my-1 break-all text-xs" key={destination.site_id}>
          <strong>{destination.site_name}</strong>: {destination.exact_query} → {destination.api_url}
          {" · "}{destination.transport === "HTTP" ? "прямой доступ" : destination.transport === "BROWSER" ? "браузер" : "прямой доступ, при ошибке — браузер"}
          {destination.page_urls.length > 0 && <> · до {destination.page_urls.length} стр.: {destination.page_urls.join("; ")}</>}
        </p>)}
      </div>
      <form action={action} className="mt-4">
        <input name="document_id" type="hidden" value={plan.document_id} />
        <input name="plan_sha256" type="hidden" value={plan.plan_sha256} />
        <input name="mode" type="hidden" value={plan.mode} />
        <button className="rounded-lg bg-slate-950 px-5 py-2 font-bold text-white disabled:opacity-50" disabled={pending} type="submit">
          {pending ? "Поиск…" : `Подтвердить и искать по ${plan.destinations.length} источникам`}
        </button>
      </form>
    </>}
    {state.error && <p className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-900" role="alert">{state.error}</p>}
    {state.run && <div className="mt-6 border-t border-slate-200 pt-4">
      <h3 className="text-lg font-bold">Результат по ТЗ</h3>
      <p className="text-sm">Реестр ЕАЭС: {state.run.eaeu_products.fetch_status === "COMPLETED" ? `${state.run.eaeu_products.matched_count} совпадений, показано ${state.run.eaeu_products.candidates.length}` : "ошибка источника; результат неизвестен"}.</p>
      {state.run.eaeu_products.candidates.map((item) => <p className="text-sm" key={item.record_id}>
        <a className="text-blue-700 underline" href={item.record_url} rel="noopener noreferrer" target="_blank">{item.product_name}</a> · {item.manufacturer_name} · соответствие UNKNOWN
      </p>)}
      {state.run.direct_catalog && <div className="mt-4 border-t border-slate-100 pt-2">
        <h4 className="m-0 font-bold">{state.run.direct_catalog.site_name}</h4>
        <p className="m-0 text-sm text-slate-600">{state.run.direct_catalog.fetch_status === "COMPLETED" ? `Карточек в одной категории: ${state.run.direct_catalog.candidates.length}. Другие категории не проверены.` : "Каталог недоступен; результат неизвестен."}</p>
        {state.run.direct_catalog.candidates.map((item) => <p className="my-1 text-sm" key={item.url}>
          <a className="text-blue-700 underline" href={item.url} rel="noopener noreferrer" target="_blank">{item.title}</a> · UNKNOWN
        </p>)}
      </div>}
      {state.run.yandex_business && <div className="mt-4 border-t border-slate-100 pt-2">
        <h4 className="m-0 font-bold">{state.run.yandex_business.site_name}</h4>
        <p className="m-0 text-sm text-slate-600">{state.run.yandex_business.fetch_status === "COMPLETED" || state.run.yandex_business.fetch_status === "PARTIAL" ? `Совпало по словам в названии: ${state.run.yandex_business.candidates.length}. Прочитано страниц: ${state.run.yandex_business.pages.filter(p => p.status === "COMPLETED").length}. ${state.run.yandex_business.fetch_status === "PARTIAL" ? "Следующая страница недоступна; результат частичный." : "Полнота каталога не подтверждена."}` : state.run.yandex_business.fetch_status === "QUERY_NOT_COVERED" ? "Для этой товарной группы категория не подключена." : "Ошибка источника; результат неизвестен."}</p>
        {state.run.yandex_business.candidates.map((item) => <p className="my-1 text-sm" key={item.url}>
          <a className="text-blue-700 underline" href={item.url} rel="noopener noreferrer" target="_blank">{item.title}</a> · UNKNOWN
          {item.source_page_number && <> · страница {item.source_page_number}</>}
        </p>)}
        <PageEvidence pages={state.run.yandex_business.pages} stop={state.run.yandex_business.stop_reason} />
      </div>}
      {state.run.browser_attempts.map((attempt) => <BrowserResult key={attempt.site} attempt={attempt} />)}
      {state.run.graviton_catalog && <div className="mt-4 rounded-lg border border-slate-200 p-3">
        <h4 className="m-0 font-bold">{state.run.graviton_catalog.site_name}</h4>
        <p className="text-sm">{state.run.graviton_catalog.fetch_status === "COMPLETED"
          ? `Просмотрено карточек: ${state.run.graviton_catalog.scanned_count}. Совпадений по названию: ${state.run.graviton_catalog.candidates.length}. Проверена одна страница категории.`
          : "Каталог не удалось проверить; результат неизвестен."}</p>
        <p className="text-xs text-slate-600">Каталог производителя даёт кандидатов. Соответствие ТЗ, реестровая запись, цена и наличие проверяются отдельно.</p>
        {state.run.graviton_catalog.candidates.map((item) => <p className="text-sm" key={item.url}>
          <a href={item.url} target="_blank" rel="noopener noreferrer" className="text-blue-700 underline">{item.title}</a> · соответствие UNKNOWN · карточка {item.source_item_index}
        </p>)}
        <details className="text-xs text-slate-500"><summary>Источник и проверка</summary>
          <p className="break-all"><a href={state.run.graviton_catalog.source_url} target="_blank" rel="noopener noreferrer">Каталог</a> · {state.run.graviton_catalog.observed_at} · SHA-256 {state.run.graviton_catalog.response_sha256 ?? "ответ не получен"}</p>
        </details>
      </div>}
      {state.run.depo_catalog && <div className="mt-4 rounded-lg border border-slate-200 p-3">
        <h4 className="m-0 font-bold">{state.run.depo_catalog.site_name}</h4>
        <p className="text-sm">{state.run.depo_catalog.fetch_status === "COMPLETED"
          ? `Просмотрено карточек: ${state.run.depo_catalog.scanned_count}. Совпадений по названию: ${state.run.depo_catalog.candidates.length}. Проверена одна страница категории.`
          : "Каталог не удалось проверить; результат неизвестен."}</p>
        <p className="text-xs text-slate-600">Карточка производителя не подтверждает комплектацию, соответствие ТЗ, цену, наличие или реестровую запись.</p>
        {state.run.depo_catalog.candidates.map((item) => <p className="text-sm" key={item.url}>
          <a href={item.url} target="_blank" rel="noopener noreferrer" className="text-blue-700 underline">{item.title}</a> · соответствие UNKNOWN · карточка {item.source_item_index}
        </p>)}
        <details className="text-xs text-slate-500"><summary>Источник и проверка</summary>
          <p className="break-all"><a href={state.run.depo_catalog.source_url} target="_blank" rel="noopener noreferrer">Каталог</a> · {state.run.depo_catalog.observed_at} · SHA-256 {state.run.depo_catalog.response_sha256 ?? "ответ не получен"}</p>
        </details>
      </div>}
    </div>}
  </section>;
}
