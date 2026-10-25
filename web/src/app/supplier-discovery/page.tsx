import type { Metadata } from "next";
import Link from "next/link";

import {
  loadDocumentSupplierSearchPlan,
  searchEaeuManufacturers,
  searchEaeuRegistry,
  searchDirectCatalog,
  searchYandexBusinessCategory,
  type DocumentSupplierSearchPlan,
} from "@/lib/procurement-api";

import { DocumentSupplierSearch } from "./document-search";

export const metadata: Metadata = {
  title: "Источники поиска поставщиков — Tendox",
};

type Source = {
  name: string;
  url: string;
  purpose: string;
  access: string;
};

const sources: { heading: string; description: string; items: Source[] }[] = [
  {
    heading: "Производители и происхождение",
    description: "Кандидаты на изготовителя и официальные сведения. Карточка сама по себе не подтверждает статус производителя для конкретной поставки.",
    items: [
      { name: "Гравитон · серверы", url: "https://graviton.ru/catalog/servery-i-khranenie-dannykh/servery/", purpose: "Публичный каталог производителя", access: "Автоматический поиск по ТЗ: одна категория серверов, совпадение слов названия" },
      { name: "Гравитон · ноутбуки", url: "https://graviton.ru/catalog/klientskie-ustroystva/noutbuki/", purpose: "Публичный каталог производителя", access: "Автоматический поиск по ТЗ: одна категория ноутбуков, совпадение слов названия" },
      { name: "Гравитон · принтеры и МФУ", url: "https://graviton.ru/catalog/klientskie-ustroystva/printery/", purpose: "Публичный каталог производителя", access: "Автоматический поиск по ТЗ: одна категория печатной техники, совпадение слов названия" },
      { name: "Гравитон · ПК", url: "https://graviton.ru/catalog/klientskie-ustroystva/pk/", purpose: "Публичный каталог производителя", access: "Автоматический поиск по ТЗ: одна категория ПК, совпадение слов названия" },
      { name: "DEPO · серверы", url: "https://www.depo.ru/catalog/servery/", purpose: "Публичный каталог производителя", access: "Автоматический поиск по ТЗ: одна категория серверов, совпадение слов названия" },
      { name: "Реестр промышленных товаров ЕАЭС", url: "https://goszakupki.eaeunion.org/erpt/ru/registers/products/list", purpose: "Промышленная продукция и указанные в реестре изготовители", access: "Автоматический поиск по товару подключён ниже" },
      { name: "Реестр производителей ЕАЭС", url: "https://goszakupki.eaeunion.org/erpt/ru/registers/products/map", purpose: "Названия и идентификационные коды компаний", access: "Автоматический поиск по названию компании подключён ниже" },
      { name: "ГИСП · каталог и реестры", url: "https://gisp.gov.ru/importsub/search/product", purpose: "Российская продукция и аналоги", access: "Ручная проверка; API поиска не подключён" },
      { name: "ГИСП · перечень производителей", url: "https://gisp.gov.ru/pp719v2/pub/org/", purpose: "Производители промышленной продукции", access: "Ручная проверка; реестровая запись сверяется отдельно" },
    ],
  },
  {
    heading: "Оптовые каталоги и B2B",
    description: "Площадки для поиска предложений и контрагентов. Цена, наличие, MOQ и полномочия продавца требуют отдельного подтверждения.",
    items: [
      { name: "Supl.biz · промышленные насосы", url: "https://supl.biz/promyishlennyie-nasosyi-category4240/", purpose: "B2B-каталог предложений поставщиков", access: "Автоматический браузерный просмотр одной категории по ТЗ; общий поиск и API не подключены" },
      { name: "Пульс цен", url: "https://www.pulscen.ru/", purpose: "Товары, компании, запрос КП", access: "Поисковые пути и API закрыты для роботов" },
      { name: "Allbiz", url: "https://all.biz/", purpose: "Товары и поставщики по странам", access: "С текущего сервера HTTP 403; результат неизвестен" },
      { name: "ServerMall · HPE Gen12", url: "https://servermall.ru/sets/servery-hp-proliant-gen12/", purpose: "Серверы из одной публичной категории", access: "Прямой автоматический поиск подключён ниже" },
      { name: "PromPortal", url: "https://promportal.su/", purpose: "Товары и компании", access: "Ручная проверка; автоматическое копирование требует разрешения площадки" },
      { name: "Flagma", url: "https://flagma.ru/companies/", purpose: "Компании, товары и услуги", access: "Условия площадки ограничивают автоматический сбор; поиск закрыт для роботов" },
      { name: "B2B Маркет", url: "https://market.b2b-center.ru/", purpose: "Каталоги продавцов в системе B2B-Center", access: "Поиск закрыт для роботов; с текущего сервера HTTP 403" },
      { name: "Фабрикант Маркет", url: "https://market.fabrikant.ru/", purpose: "Каталог предложений поставщиков", access: "Стабильный публичный контракт поиска не подтверждён" },
      { name: "Торговый портал ЭТП ГПБ", url: "https://new.etpgpb.ru/products/market/portal/", purpose: "Электронный магазин и каталог", access: "Прямой каталог предложений с сервера не получен" },
      { name: "ЕАТ «Берёзка»", url: "https://berezka-tender.ru/documentation.html", purpose: "Каталог и малые закупки", access: "Предложения не подключены; классификатор читается отдельно" },
    ],
  },
  {
    heading: "Маркетплейсы для закупки товара",
    description: "Витрины могут помочь найти товар, но не доказывают право продажи с полки по государственному механизму.",
    items: [
      { name: "Ozon для бизнеса", url: "https://www.ozon.ru/", purpose: "Товары для покупки юридическим лицом", access: "Публичная покупательская выдача с сервера не получена" },
      { name: "Wildberries", url: "https://www.wildberries.ru/", purpose: "Товары, в том числе предложения для юрлиц", access: "С текущего сервера антибот-ответ; покупательский API не подтверждён" },
      { name: "Яндекс Маркет для Бизнеса", url: "https://business.market.yandex.ru/", purpose: "Товары для покупки юридическим лицом", access: "Поиск по словам названия: насосы, ноутбуки, принтеры и МФУ; до двух страниц выбранной категории" },
    ],
  },
  {
    heading: "Международные B2B-каталоги",
    description: "Поиск за рубежом требует отдельной проверки географии закупки, документов и доставки.",
    items: [
      { name: "Alibaba.com", url: "https://www.alibaba.com/", purpose: "Товары и поставщики", access: "Прямой клиент получил антибот-страницу; обход не подключён" },
      { name: "Made-in-China.com", url: "https://www.made-in-china.com/", purpose: "Каталог производителей и продукции", access: "Поисковые пути закрыты для роботов" },
      { name: "Europages", url: "https://www.europages.com/", purpose: "Компании и продукция", access: "robots.txt закрывает обход для обычного клиента" },
    ],
  },
];

export default async function SupplierDiscoveryPage({ searchParams }: {
  searchParams: Promise<{ query?: string | string[]; maker_query?: string | string[]; web_query?: string | string[]; document_id?: string | string[]; mode?: string | string[] }>;
}) {
  const params = await searchParams;
  const input = params.query;
  const query = typeof input === "string" && input.trim().length <= 80
    ? input.trim() : "";
  const makerInput = params.maker_query;
  const makerQuery = typeof makerInput === "string" && makerInput.trim().length <= 80
    ? makerInput.trim() : "";
  const webInput = params.web_query;
  const webQuery = typeof webInput === "string" && webInput.trim().length <= 80
    ? webInput.trim() : "";
  const docInput = params.document_id;
  const documentId = typeof docInput === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/.test(docInput)
    ? docInput : "";
  const [search, manufacturerSearch, webSearch, yandexSearch] = await Promise.all([
    query ? searchEaeuRegistry(query) : null,
    makerQuery ? searchEaeuManufacturers(makerQuery) : null,
    webQuery ? searchDirectCatalog(webQuery) : null,
    query ? searchYandexBusinessCategory(query) : null,
  ]);
  let documentPlan: DocumentSupplierSearchPlan | null = null;
  let documentPlanError = false;
  if (documentId) {
    try {
      const mode = params.mode === "HTTP" || params.mode === "BROWSER" ? params.mode : "AUTO";
      documentPlan = await loadDocumentSupplierSearchPlan(documentId, mode);
    } catch {
      documentPlanError = true;
    }
  }
  return <main className="min-h-screen bg-slate-50 p-5 text-slate-950 sm:p-10">
    <div className="mx-auto max-w-5xl">
      <header className="border-b border-slate-200 pb-6">
        <p className="text-xs font-black uppercase tracking-widest text-blue-700">Поиск источников снабжения</p>
        <h1 className="text-3xl font-black">Где искать производителей и поставщиков</h1>
        <p className="max-w-3xl text-sm leading-6 text-slate-600">По загруженному ТЗ можно подготовить точный запрос и искать в реестре ЕАЭС и подходящей категории: ServerMall для серверов HPE, Гравитон для серверов, ноутбуков, принтеров, МФУ и ПК, DEPO для серверов, Яндекс Маркет для насосов, ноутбуков, принтеров и МФУ, Supl.biz для промышленных насосов через браузер. Широкий автоматический поиск по торговым площадкам пока не подключён. Найденная карточка не подтверждает цену, наличие или соответствие ТЗ.</p>
        <nav className="flex flex-wrap gap-4 text-sm font-bold">
          <Link className="text-blue-700 hover:underline" href="/">Вернуться к кейсам и работающему поиску →</Link>
          <Link className="text-blue-700 hover:underline" href="/manufacturer-search">Сохранённый поиск производителей ЕАЭС</Link>
        </nav>
      </header>
      {documentPlan && <DocumentSupplierSearch key={documentPlan.plan_sha256} plan={documentPlan} />}
      {documentPlanError && <p className="mt-6 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">План поиска для документа недоступен. Проверьте API и права доступа.</p>}
      <form className="mt-6 rounded-xl border border-slate-200 bg-white p-5" method="get">
        <label className="grid gap-2 text-sm font-bold" htmlFor="supplier-query">Название товара, модель или артикул
          <input className="rounded-lg border border-slate-300 p-3 font-normal" defaultValue={query} id="supplier-query" maxLength={80} name="query" placeholder="Например, промышленный насос" />
        </label>
        <button className="mt-3 rounded-lg bg-slate-950 px-5 py-2 font-bold text-white" type="submit">Искать производителей</button>
        {query && <p className="mb-0 text-sm text-slate-600">Запрос для копирования в поиск каждой площадки: <strong className="select-all">{query}</strong></p>}
      </form>
      <form className="mt-4 rounded-xl border border-slate-200 bg-white p-5" method="get">
        <label className="grid gap-2 text-sm font-bold" htmlFor="web-supplier-query">Товар или модель для прямого поиска в каталоге ServerMall
          <input className="rounded-lg border border-slate-300 p-3 font-normal" defaultValue={webQuery} id="web-supplier-query" maxLength={80} name="web_query" placeholder="Например, промышленный насос" />
        </label>
        <button className="mt-3 rounded-lg bg-slate-950 px-5 py-2 font-bold text-white" type="submit">Искать в каталоге</button>
        <p className="mb-0 text-xs text-slate-500">Проверяется только публичная категория HPE ProLiant Gen12; для других товаров отсутствие карточек ничего не означает.</p>
      </form>
      {webQuery && <section className="mt-8 rounded-xl border border-blue-200 bg-white p-5">
        <h2 className="mt-0 text-xl font-black">Прямой поиск · ServerMall</h2>
        {webSearch?.error && <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{webSearch.error === "validation" ? "Введите от одного до пяти слов, не более 80 символов." : "Прямой поиск сейчас недоступен. Результат неизвестен."}</p>}
        {webSearch?.result && <div className="mt-5 border-t border-slate-200 pt-4">
          {(() => { const attempt = webSearch.result; return <>
          <h3 className="m-0 text-lg font-bold">{attempt.site_name}</h3>
          {attempt.fetch_status === "QUERY_NOT_COVERED" && <p className="text-sm text-slate-600">Категория HPE Gen12 не подходит для этого запроса; сетевого обращения не было.</p>}
          {attempt.fetch_status === "SOURCE_ERROR" && <p className="text-sm text-amber-900">Каталог не ответил или изменил формат. Результат неизвестен.</p>}
          {attempt.fetch_status === "COMPLETED" && <>
            <p className="text-sm text-slate-700">Совпадений в одной категории: {attempt.candidates.length}. Другие категории не проверены.</p>
            <div className="grid gap-3">
              {attempt.candidates.map((item) => <article className="rounded-lg border border-slate-200 bg-slate-50 p-4" key={item.url}>
                <a className="font-bold text-blue-700 underline" href={item.url} rel="noopener noreferrer" target="_blank">{item.title} ↗</a>
                <p className="m-0 break-all text-xs text-slate-600">{item.url} · продавец {item.supplier} · соответствие ТЗ: UNKNOWN</p>
              </article>)}
            </div>
            <p className="mt-3 break-all text-xs text-slate-500">Источник: {attempt.catalog_url} · получено {attempt.observed_at} · SHA-256 ответа {attempt.response_sha256}. Результаты не сохранены в кейс.</p>
          </>}
          </>; })()}
        </div>}
      </section>}
      <form className="mt-4 rounded-xl border border-slate-200 bg-white p-5" method="get">
        <label className="grid gap-2 text-sm font-bold" htmlFor="manufacturer-query">Название производителя для проверки в реестре ЕАЭС
          <input className="rounded-lg border border-slate-300 p-3 font-normal" defaultValue={makerQuery} id="manufacturer-query" maxLength={80} name="maker_query" placeholder="Например, Торгмаш" />
        </label>
        <button className="mt-3 rounded-lg bg-slate-950 px-5 py-2 font-bold text-white" type="submit">Проверить компанию</button>
      </form>
      {makerQuery && <section className="mt-8 rounded-xl border border-blue-200 bg-white p-5">
        <h2 className="mt-0 text-xl font-black">Автоматический поиск · производители ЕАЭС</h2>
        {manufacturerSearch?.error && <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{manufacturerSearch.error === "validation" ? "Введите от одного до пяти слов, не более 80 символов." : "Поиск сейчас недоступен. Результат неизвестен; попробуйте позже."}</p>}
        {manufacturerSearch?.result?.fetch_status === "SOURCE_ERROR" && <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">Реестр не ответил или изменил формат. Наличие компании неизвестно.</p>}
        {manufacturerSearch?.result?.fetch_status === "COMPLETED" && <>
          <p className="text-sm text-slate-700">Совпадений по названию: {manufacturerSearch.result.matched_count}. Показаны первые {manufacturerSearch.result.candidates.length} компаний. Запись не подтверждает соответствие конкретного товара или действительность документов.</p>
          <div className="grid gap-3">
            {manufacturerSearch.result.candidates.map((item) => <article className="rounded-lg border border-slate-200 bg-slate-50 p-4" key={item.record_id}>
              <h3 className="m-0 text-base font-bold">{item.manufacturer_name}</h3>
              <p className="m-0 text-xs text-slate-600">Код производителя: {item.identity_code} · код государства ЕАЭС: {item.member_state_code ?? "не указан"} · строка ответа {item.source_record_index} · соответствие ТЗ: UNKNOWN</p>
            </article>)}
          </div>
          <p className="mt-4 break-all text-xs text-slate-500">Источник: <a className="underline" href="https://goszakupki.eaeunion.org/erpt/ru/registers/products/map" rel="noopener noreferrer" target="_blank">карта производителей ЕАЭС</a> · API {manufacturerSearch.result.source_url} · получено {manufacturerSearch.result.observed_at} · SHA-256 ответа {manufacturerSearch.result.response_sha256} · SHA-256 запроса {manufacturerSearch.result.request_sha256}. Ответ не сохранён в кейс.</p>
        </>}
      </section>}
      {query && <section className="mt-8 rounded-xl border border-blue-200 bg-white p-5">
        <h2 className="mt-0 text-xl font-black">Автоматический поиск · реестр ЕАЭС</h2>
        {search?.error && <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
          {search.error === "validation" ? "Введите от одного до пяти слов, не более 80 символов." : "Поиск сейчас недоступен. Результат неизвестен; попробуйте позже."}
        </p>}
        {search?.result?.fetch_status === "SOURCE_ERROR" && <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">Источник не ответил или изменил формат данных. Результат неизвестен, это не означает отсутствия производителей.</p>}
        {search?.result?.fetch_status === "COMPLETED" && <>
          <p className="text-sm text-slate-700">По данным источника совпадений: {search.result.matched_count}. Показаны первые {search.result.candidates.length} записей. Все требуют проверки применимости и актуального документа.</p>
          <div className="grid gap-3">
            {search.result.candidates.map((item) => <article className="rounded-lg border border-slate-200 bg-slate-50 p-4" key={item.record_id}>
              <h3 className="m-0 text-base font-bold"><a className="text-blue-700 underline" href={item.record_url} rel="noopener noreferrer" target="_blank">{item.product_name} ↗</a></h3>
              <p className="my-2 text-sm">Изготовитель в реестре: <strong>{item.manufacturer_name}</strong></p>
              <p className="m-0 text-xs text-slate-600">Запись № {item.registry_number} · документ до {item.document_expires_on ?? "дата неизвестна"} · строка ответа {item.source_record_index} · соответствие ТЗ: UNKNOWN</p>
            </article>)}
          </div>
          <p className="mt-4 break-all text-xs text-slate-500">Источник: <a className="underline" href="https://goszakupki.eaeunion.org/erpt/ru/registers/products/list" rel="noopener noreferrer" target="_blank">публичный реестр ЕАЭС</a> · API {search.result.source_url} · получено {search.result.observed_at} · SHA-256 ответа {search.result.response_sha256} · SHA-256 запроса {search.result.request_sha256}. Это текущий просмотр, ответ не сохранён в кейс.</p>
        </>}
      </section>}
      {query && <section className="mt-8 rounded-xl border border-blue-200 bg-white p-5">
        <h2 className="mt-0 text-xl font-black">Прямой просмотр · Яндекс Маркет для Бизнеса</h2>
        {yandexSearch?.error && <p className="text-sm text-amber-900">Источник недоступен; результат неизвестен.</p>}
        {yandexSearch?.result?.fetch_status === "QUERY_NOT_COVERED" && <p className="text-sm text-slate-600">Для этой товарной группы проверенная категория пока не подключена.</p>}
        {yandexSearch?.result?.fetch_status === "SOURCE_ERROR" && <p className="text-sm text-amber-900">Категория не ответила или изменила формат; результат неизвестен.</p>}
        {(yandexSearch?.result?.fetch_status === "COMPLETED" || yandexSearch?.result?.fetch_status === "PARTIAL") && <>
          <p className="text-sm text-slate-700">{yandexSearch.result.site_name}: {yandexSearch.result.candidates.length} совпадений по словам названия на {yandexSearch.result.pages.filter(p => p.status === "COMPLETED").length} страницах. {yandexSearch.result.fetch_status === "PARTIAL" ? "Продолжение не удалось прочитать; результат частичный." : "Полнота каталога не подтверждена."}</p>
          {yandexSearch.result.candidates.map((item) => <p className="text-sm" key={item.url}>
            <a className="text-blue-700 underline" href={item.url} rel="noopener noreferrer" target="_blank">{item.title}</a> · соответствие ТЗ: UNKNOWN
          </p>)}
          <p className="break-all text-xs text-slate-500">Источник: {yandexSearch.result.category_url} · получено {yandexSearch.result.observed_at} · SHA-256 ответа {yandexSearch.result.response_sha256}</p>
        </>}
      </section>}
      {sources.map((group) => <section className="mt-8" key={group.heading}>
        <h2 className="text-xl font-black">{group.heading}</h2>
        <p className="text-sm text-slate-600">{group.description}</p>
        <div className="grid gap-3 sm:grid-cols-2">
          {group.items.map((source) => <article className="rounded-xl border border-slate-200 bg-white p-4" key={source.name}>
            <h3 className="m-0 font-bold"><a className="text-blue-700 underline" href={source.url} rel="noopener noreferrer" target="_blank">{source.name} ↗</a></h3>
            <p className="my-2 text-sm">{source.purpose}</p>
            <p className="m-0 text-xs font-semibold text-amber-800">{source.access}</p>
          </article>)}
        </div>
      </section>)}
      <p className="mt-8 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm">ЕИС и ЭТП для тендеров служат поиску спроса заказчиков; они не подтверждают изготовителя товара. Никакая найденная карточка не становится КП или техническим PASS без документов и независимой проверки.</p>
    </div>
  </main>;
}
