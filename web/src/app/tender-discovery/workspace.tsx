"use client";

import { useEffect, useRef, useState, useTransition, type RefObject } from "react";
import { sortTenderRows, filterDeliveryRegion, formatTenderDeadline, rowsFromResult, type TenderLaw, type TenderLawFilter, type TenderRow, type TenderSort, type WorkspaceResult } from "@/lib/tender-workspace";
import { BetaQuote } from "./beta-quote";
import { BetaFinancialComparison } from "./beta-shortlist";
import { betaProfileSearch } from "./beta-actions";
import { TenderDocuments } from "./tender-documents";
import { IndexedDocuments } from "./indexed-documents";
import { PositionEvidenceView } from "./position-evidence";
import { PositionEvidence223View } from "./position-evidence-223";
import { AddToMixedComparison } from "./mixed-comparison";
import { mergeSearchPage } from "./paged-results";
import { loadWorkspacePage, searchWorkspace, searchGlobalWorkspace } from "./workspace-actions";
import styles from "./workspace.module.css";

type PageState = { pending?: boolean; error?: string; restart?: boolean };

function SearchIcon() {
  return <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none"><circle cx="10.5" cy="10.5" r="6.5" stroke="currentColor" strokeWidth="1.7" /><path d="m16 16 4.5 4.5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" /></svg>;
}

export function TenderWorkspace() {
  const [query, setQuery] = useState("");
  const [profileTerms, setProfileTerms] = useState<string[]>([]);
  const [profileError, setProfileError] = useState<string>();
  const [quoteVersion, setQuoteVersion] = useState(0);
  const [region, setRegion] = useState("");
  const [order, setOrder] = useState<TenderSort>("search");
  const [includeUnknownRegion, setIncludeUnknownRegion] = useState(false);
  const [law, setLaw] = useState<TenderLawFilter>("all");
  const [result, setResult] = useState<WorkspaceResult>();
  const [selectedId, setSelectedId] = useState<string>();
  const [globalPage, setGlobalPage] = useState<PageState>({});
  const [pages, setPages] = useState<Partial<Record<TenderLaw, PageState>>>({});
  const [pending, startSearch] = useTransition();
  const [clock, setClock] = useState(0);
  const generation = useRef(0);
  const loadingPages = useRef(new Set<TenderLaw>());
  const detailHeading = useRef<HTMLHeadingElement>(null);
  const loadedRows = result ? rowsFromResult(result) : [];
  const regionRows = result?.globalPrice ? loadedRows : filterDeliveryRegion(loadedRows, region, includeUnknownRegion);
  const rows = sortTenderRows(result?.globalPrice ? [...regionRows].sort((a, b) => a.law === b.law ? a.purchaseNumber.localeCompare(b.purchaseNumber) : a.law.localeCompare(b.law)) : regionRows, order);
  const regions = [...new Set(loadedRows.flatMap(row => row.deliveryRegions?.map(fact => fact.value) ?? []))].sort();
  const selected = rows.find(row => row.id === selectedId) ?? rows[0];

  useEffect(() => () => { generation.current++; }, []);
  useEffect(() => {
    if (!selectedId) return;
    detailHeading.current?.focus({ preventScroll: true });
    if (window.matchMedia("(max-width: 760px)").matches) detailHeading.current?.scrollIntoView({ block: "start" });
  }, [selectedId]);
  useEffect(() => {
    if (!result) return;
    const now = Date.now();
    const nextDeadline = Math.min(...rowsFromResult(result).flatMap(row => row.deadline && Date.parse(row.deadline) > now ? [Date.parse(row.deadline)] : []));
    if (!Number.isFinite(nextDeadline)) return;
    const timer = window.setTimeout(() => setClock(value => value + 1), Math.min(nextDeadline - now + 1, 2_147_483_647));
    return () => window.clearTimeout(timer);
  }, [result, clock]);

  function runSearch(searchQuery = query, searchLaw = law, searchOrder = order) {
    const cleaned = searchQuery.trim();
    if (!cleaned) return;
    const epoch = ++generation.current;
    loadingPages.current.clear();
    setPages({}); setGlobalPage({}); setSelectedId(undefined); setResult(undefined);
    startSearch(async () => {
      try {
        const next = searchOrder === "price_desc" ? await searchGlobalWorkspace(cleaned, searchLaw, region, includeUnknownRegion) : await searchWorkspace(cleaned, searchLaw);
        if (generation.current === epoch) setResult(next);
      } catch {
        if (generation.current === epoch) setResult({ query: cleaned, law: searchLaw, error: "Поиск временно недоступен. Повторите запрос." });
      }
    });
  }

  async function loadGlobalMore() {
    const current = result;
    const source = current?.globalPrice;
    if (!current || !source?.next_cursor || globalPage.pending || globalPage.restart) return;
    const epoch = generation.current;
    setGlobalPage({ pending: true });
    let next: Awaited<ReturnType<typeof searchGlobalWorkspace>>;
    try {
      next = await searchGlobalWorkspace(current.query, current.law, source.delivery_region, source.include_unknown_region, source.next_cursor);
    } catch {
      if (generation.current === epoch) setGlobalPage({ error: "Не удалось загрузить продолжение. Попробуйте ещё раз." });
      return;
    }
    if (generation.current !== epoch) return;
    if (next.error || !next.globalPrice) {
      setGlobalPage({ error: next.error ?? "Продолжение поиска недоступно.", restart: next.restartRequired }); return;
    }
    if (next.globalPrice.page_snapshot_sha256 !== source.page_snapshot_sha256 || next.globalPrice.snapshot_at !== source.snapshot_at) {
      setGlobalPage({ error: "Состав результатов изменился. Повторите поиск.", restart: true }); return;
    }
    try {
      const merged44 = current.result44 && next.result44 ? mergeSearchPage(current.result44, next.result44, row => row.purchase_number) : next.result44;
      const merged223 = current.result223 && next.result223 ? mergeSearchPage(current.result223, next.result223, row => row.notice.purchase_number) : next.result223;
      setResult({ ...next, result44: merged44, result223: merged223, navigation: { ...current.navigation, ...next.navigation } });
      setGlobalPage({});
    } catch {
      setGlobalPage({ error: "Состав результатов изменился. Повторите поиск.", restart: true });
    }
  }

  function invalidateGlobalFilters() {
    if (order === "price_desc") { generation.current++; setResult(undefined); setGlobalPage({}); }
  }

  async function loadMore(pageLaw: TenderLaw) {
    const current = result;
    const source = pageLaw === "44" ? current?.result44 : current?.result223;
    if (!current || !source?.next_cursor || loadingPages.current.has(pageLaw) || pages[pageLaw]?.restart) return;
    const epoch = generation.current;
    loadingPages.current.add(pageLaw);
    setPages(value => ({ ...value, [pageLaw]: { pending: true } }));
    try {
      const next = await loadWorkspacePage(current.query, pageLaw, source.next_cursor);
      if (generation.current !== epoch) return;
      const error = next.error ?? (pageLaw === "44" ? next.error44 : next.error223);
      if (error || (pageLaw === "44" ? !next.result44 : !next.result223)) {
        setPages(value => ({ ...value, [pageLaw]: { error: error ?? "Продолжение поиска недоступно.", restart: next.restartRequired } }));
        return;
      }
      try {
        if (pageLaw === "44" && current.result44 && next.result44) {
          const merged = mergeSearchPage(current.result44, next.result44, row => row.purchase_number);
          setResult(value => value ? { ...value, result44: merged, navigation: { ...value.navigation, ...next.navigation } } : value);
        } else if (pageLaw === "223" && current.result223 && next.result223) {
          const merged = mergeSearchPage(current.result223, next.result223, row => row.notice.purchase_number);
          setResult(value => value ? { ...value, result223: merged, navigation: { ...value.navigation, ...next.navigation } } : value);
        }
        setPages(value => ({ ...value, [pageLaw]: {} }));
      } catch {
        setPages(value => ({ ...value, [pageLaw]: { restart: true, error: "Состав результатов изменился. Повторите поиск, чтобы получить согласованные страницы." } }));
      }
    } catch {
      if (generation.current === epoch) setPages(value => ({ ...value, [pageLaw]: { error: "Не удалось загрузить продолжение. Попробуйте ещё раз." } }));
    } finally {
      if (generation.current === epoch) loadingPages.current.delete(pageLaw);
    }
  }

  return <section className={styles.workspace} aria-label="Поиск и просмотр закупок">
    <header className={styles.hero}>
      <p className={styles.eyebrow}><span /> ВАШ ТЕНДЕРНЫЙ ОТДЕЛ</p>
      <h1>Что вы хотите <span>поставлять?</span></h1>
      <p className={styles.subtitle}>Найдите закупки на свой товар. Изучите условия и выберите, что проверить дальше.</p>
    </header>
    <form className={styles.searchPanel} onSubmit={event => { event.preventDefault(); runSearch(); }}>
      <div className={styles.searchFields}>
        <label className={styles.productField} htmlFor="tender-product">Товар или номер закупки
          <span className={styles.searchInput}><SearchIcon /><input id="tender-product" name="query" value={query} onChange={event => setQuery(event.target.value)} required maxLength={120} placeholder="Например, бумага А4" autoComplete="off" disabled={pending} /></span>
        </label>
        <label className={styles.regionField} htmlFor="tender-delivery">Место поставки
          <input id="tender-delivery" list="delivery-regions" value={region} onChange={event => { setRegion(event.target.value); invalidateGlobalFilters(); }} placeholder="Все регионы" maxLength={200} aria-describedby="delivery-limitation" /><datalist id="delivery-regions">{regions.map(value => <option key={value} value={value} />)}</datalist>
        </label>
        <button className={styles.searchButton} disabled={pending || !query.trim()} type="submit"><SearchIcon />{pending ? "Ищем закупки…" : "Найти закупки"}</button>
      </div>
      <div className={styles.searchOptions}>
        <fieldset className={styles.lawFilter} disabled={pending}><legend>Закон</legend>
          {([ ["all", "Все закупки"], ["44", "44-ФЗ"], ["223", "223-ФЗ"] ] as const).map(([value, label]) => <label key={value} className={law === value ? styles.lawSelected : ""}><input type="radio" name="law" value={value} checked={law === value} onChange={() => setLaw(value)} /><span>{label}</span></label>)}
        </fieldset>
        <div id="delivery-limitation"><p>Для «Сначала дорогие» регион проверяется по всей сохранённой базе. После выбора нажмите «Найти закупки». Полнота адресов не подтверждена.</p><label><input type="checkbox" checked={includeUnknownRegion} onChange={event => { setIncludeUnknownRegion(event.target.checked); invalidateGlobalFilters(); }} /> Включать закупки с неизвестным регионом</label></div>
      </div>
      {/бумаг/iu.test(query) && <div className={styles.suggestions}><span>Уточнить запрос:</span>{["Бумага А4", "Бумага А3", "Бумага для печати"].map(preset => <button type="button" disabled={pending} key={preset} onClick={() => { setQuery(preset); runSearch(preset); }}>{preset} ↗</button>)}</div>}
    </form>
    <div><button type="button" className={styles.secondaryButton} onClick={() => { void betaProfileSearch().then(next => { setProfileTerms(next.terms ?? []); setProfileError(next.error); }); }}>Подобрать товар из моего профиля</button>{profileError && <p role="alert">{profileError}</p>}{profileTerms.map(term => <button key={term} type="button" disabled={pending} onClick={() => { setQuery(term); runSearch(term); }}>{term}</button>)}</div>
    <div className={styles.coverageNote}><span aria-hidden="true">ⓘ</span><p>Поиск по загруженной части ЕИС. Полнота и свежесть не подтверждены. Совпадение по товару ещё не означает соответствие ТЗ.</p></div>
    <div aria-live="polite" aria-atomic="true" className={styles.searchStatus}>
      {pending && <p>Ищем в сохранённых извещениях ЕИС…</p>}
      {result?.globalPrice && !result.error && <p>{result.query} · Найдено {result.globalPrice.matched_count} по запросу и месту поставки</p>}
      {result && !result.globalPrice && !result.error && <p>{result.query}{" · "}{result.result44 ? `44-ФЗ: ${result.result44.matched_count}` : result.error44 ? "44-ФЗ: результат недоступен" : ""}{result.law === "all" && " · "}{result.result223 ? `223-ФЗ: ${result.result223.matched_count}` : result.error223 ? "223-ФЗ: результат недоступен" : ""}{(result.error44 || result.error223) && " · Частичная выдача"}</p>}
    </div>
    {result?.error && <p className={styles.error} role="alert">{result.error}</p>}
    {result?.error44 && <p className={styles.error} role="alert">44-ФЗ: {result.error44}</p>}
    {result?.error223 && <p className={styles.error} role="alert">223-ФЗ: {result.error223}</p>}
    {!result && !pending && <div className={styles.emptyState}><div className={styles.emptyIcon}><SearchIcon /></div><h2>Начните с вашего товара</h2><p>Введите название или полный номер закупки.<br />Здесь появятся реальные результаты поиска и условия выбранной закупки.</p><div className={styles.steps}><span><b>01</b> Найдите закупку</span><span><b>02</b> Проверьте условия</span><span><b>03</b> Сравните с профилем</span></div></div>}
    {result && (result.result44 || result.result223) && <>
      <div className={styles.resultHeading}><h2>Результаты поиска <span>{rows.length} показано из {loadedRows.length}</span></h2><div className={styles.sortControls} role="group" aria-label="Порядок результатов">
        <button type="button" aria-pressed={order === "search"} disabled={pending || globalPage.pending} onClick={() => { setOrder("search"); runSearch(result.query, result.law, "search"); }}>Порядок поиска</button>
        <button type="button" aria-pressed={order === "price_desc"} disabled={pending || globalPage.pending} onClick={() => { setOrder("price_desc"); runSearch(result.query, result.law, "price_desc"); }}>Сначала дорогие</button>
      </div></div>
      <p className={styles.scopeNote}>{order === "price_desc" ? "По начальной сумме лота в рублях по всему сохранённому корпусу для вашего запроса и региона. Следующие страницы продолжают общий порядок 44-ФЗ и 223-ФЗ. Закупки с блокировкой и без сопоставимой цены — в конце. Это сумма закупки, прибыль здесь не рассчитывается." : "Порядок поиска: сначала 44-ФЗ, затем 223-ФЗ. Чтобы увидеть крупные суммы сверху, нажмите «Сначала дорогие»."}</p>
      <p className={styles.scopeNote}>44-ФЗ: срок не истёк или неизвестен. 223-ФЗ: сохранённые извещения, включая истёкшие. Истёкший срок блокирует дальнейшее действие.</p>
      <BetaFinancialComparison key={`${result.query}:${region}:${regionRows.map(row => row.id).join("|")}:${quoteVersion}:${clock}`} rows={regionRows} region={region} onSelect={setSelectedId} />
      {rows.length ? <div className={styles.resultsGrid}>
        <div className={styles.resultList} aria-label="Найденные закупки">
          {rows.map(row => <button type="button" key={row.id} aria-pressed={selected?.id === row.id} aria-controls="tender-detail" className={`${styles.resultCard} ${selected?.id === row.id ? styles.selectedCard : ""}`} onClick={() => setSelectedId(row.id)}>
            <span className={styles.cardTop}><span className={styles.lawBadge}>{row.law}-ФЗ</span><span>№ {row.purchaseNumber}</span><span aria-hidden="true">↗</span></span>
            <strong className={styles.cardTitle}>{row.title}</strong>
            <span className={styles.cardPrice}>{row.priceValue}</span><span className={styles.priceCaption}>{row.priceLabel}</span>
            <span className={styles.cardDeadline}>Срок подачи · {formatTenderDeadline(row.deadline)}</span>
            <span className={`${styles.statusBadge} ${row.blocked ? styles.blocked : ""}`}>{row.statusLabel}</span>
          </button>)}
        </div>
        {selected && <TenderDetail key={selected.id} row={selected} headingRef={detailHeading} onQuoteSaved={() => setQuoteVersion(value => value + 1)} />}
      </div> : <div className={styles.emptyState}><h2>{result.error44 || result.error223 ? "В доступной части выдачи совпадений нет" : "По вашему запросу совпадений нет"}</h2><p>Попробуйте другое название товара или более короткий запрос. Это результат поиска в сохранённой части базы, а не во всей ЕИС.</p></div>}
      <div className={styles.pagination}>
        {result.globalPrice && <div className={styles.pageLaw}>
          <p>По всему сохранённому корпусу · загружено {loadedRows.length} из {result.globalPrice.matched_count}</p>
          {region && <p>Неизвестный регион у {result.globalPrice.unknown_region_count} совпадений; {result.globalPrice.include_unknown_region ? "включены по вашему выбору" : "не включены"}.</p>}
          {result.globalPrice.next_cursor && !globalPage.restart && <button type="button" className={styles.secondaryButton} disabled={pending || globalPage.pending} onClick={() => void loadGlobalMore()}>{globalPage.pending ? "Загружаем…" : "Загрузить ещё · по цене"}</button>}
          {globalPage.error && <p role="alert" className={styles.error}>{globalPage.error}</p>}
          {globalPage.restart && <button type="button" onClick={() => runSearch(result.query, result.law, "price_desc")}>Повторить поиск</button>}
        </div>}
        {(["44", "223"] as const).map(pageLaw => {
          const source = pageLaw === "44" ? result.result44 : result.result223;
          const page = pages[pageLaw];
          if (!source || result.globalPrice) return null;
          return <div key={pageLaw} className={styles.pageLaw}>
            <p><b>{pageLaw}-ФЗ</b> · загружено {source.matched.length} из {source.matched_count}</p>
            {source.snapshot_at && <p className={styles.muted}>Снимок: {formatTenderDeadline(source.snapshot_at)}. Продолжение доступно 15 минут.</p>}
            {source.next_cursor && !page?.restart && <button type="button" className={styles.secondaryButton} disabled={pending || page?.pending} onClick={() => void loadMore(pageLaw)}>{page?.pending ? "Загружаем…" : `Загрузить ещё · ${pageLaw}-ФЗ`}</button>}
            {page?.error && <p role="alert" className={styles.error}>{page.error}</p>}
            {page?.restart && <button type="button" className={styles.secondaryButton} disabled={pending} onClick={() => { setQuery(result.query); setLaw(result.law); runSearch(result.query, result.law); }}>Повторить поиск</button>}
          </div>;
        })}
      </div>
    </>}
  </section>;
}

function TenderDetail({ row, headingRef, onQuoteSaved }: { row: TenderRow; headingRef: RefObject<HTMLHeadingElement | null>; onQuoteSaved: () => void }) {
  return <article id="tender-detail" className={styles.detail} aria-labelledby="tender-detail-title">
    <div className={styles.detailTop}><span className={styles.eyebrow}>ВЫБРАННАЯ ЗАКУПКА</span><span className={styles.lawBadge}>{row.law}-ФЗ</span></div>
    <p className={styles.noticeNumber}>№ {row.purchaseNumber} · версия {row.version}</p>
    <h2 id="tender-detail-title" ref={headingRef} tabIndex={-1}>{row.title}</h2>
    <span className={`${styles.statusBadge} ${row.blocked ? styles.blocked : ""}`}>{row.statusLabel}</span>
    <div className={styles.facts}><div><p>{row.priceLabel}</p><strong>{row.priceValue}</strong></div><div><p>Окончание подачи</p><strong className={styles.deadlineValue}>{formatTenderDeadline(row.deadline)}</strong></div></div>
    <section className={styles.positions}><h3>Что закупают</h3>{row.raw223?.position_projection ? <PositionEvidence223View projection={row.raw223.position_projection} ordinaryPositions={row.positions} /> : row.positionSet ? <PositionEvidenceView set={row.positionSet} /> : row.positions.length ? <><p className={styles.muted}>Позиции из сохранённого извещения. Полнота ТЗ требует проверки.</p><ul>{row.positions.slice(0, 6).map((item, index) => <li key={`${item.locator}:${index}`}><span>{item.name}</span><strong>{item.quantity} <small>{item.unit}</small></strong></li>)}</ul>{row.positions.length > 6 && <p className={styles.muted}>Показано 6 из {row.positions.length} позиций. Полный список — в источниках ниже.</p>}</> : <p className={styles.muted}>Позиции не подтверждены. Проверьте документы закупки.</p>}</section>
    <section><h3>Место поставки</h3><p>{row.deliveryRegions?.map(fact => fact.value).join("; ") || "Регион поставки не подтверждён"}</p>{row.navigation?.delivery_addresses?.map((fact,index) => <p key={index}>{fact.value}</p>)}<p className={styles.muted}>Полнота мест исполнения требует проверки ТЗ.</p></section>
    <TenderDocuments row={row} />
    <BetaQuote notice={{ law: row.law, purchase_number: row.purchaseNumber, version_number: row.version, notice_xml_sha256: row.xmlSha256 }} lotCount={row.raw223?.notice.lots.length ?? 1} deadline={row.deadline} blocked={row.blocked} onSaved={onQuoteSaved} />
    {row.law === "44" && <details className={styles.sources} key={`documents:${row.id}`}><summary>Открыть сохранённый разбор ТЗ и документов</summary><IndexedDocuments key={row.id} notice={{ purchase_number: row.purchaseNumber, version_number: row.version, notice_xml_sha256: row.xmlSha256 }} /></details>}
    <details className={styles.checks} open={row.blocked} key={row.id}><summary><span className={styles.checkIcon}>!</span> Что нужно проверить</summary><p>{row.statusLabel.includes("FAIL") ? "Допуск: FAIL. Экономика: UNKNOWN." : "Допуск и экономика: UNKNOWN."} Для решения нужны полный комплект требований, действующее КП и три сценария экономики.</p>{row.reasons.length > 0 && <ul>{row.reasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul>}<p>Место поставки и соответствие профилю компании проверяются отдельно.</p></details>
    <div className={styles.detailActions}><AddToMixedComparison notice={{ law: row.law, purchase_number: row.purchaseNumber, version_number: row.version, notice_xml_sha256: row.xmlSha256, title: row.title }} disabled={row.blocked} />{row.blocked && <p className={styles.muted}>Действия по этой карточке заблокированы. Причины указаны выше.</p>}{row.noticeUrl && <a href={row.noticeUrl} target="_blank" rel="noopener noreferrer" className={styles.sourceLink}>Открыть извещение в ЕИС ↗</a>}</div>
    <section><h3>Площадка</h3>{row.platformUrl ? <a href={row.platformUrl} target="_blank" rel="noopener noreferrer">{row.platformName || "Площадка из извещения"} ↗</a> : <p>Ссылка площадки не подтверждена.</p>}{!row.noticeUrl && <p><a href={`https://zakupki.gov.ru/epz/order/extendedsearch/results.html?searchString=${encodeURIComponent(row.purchaseNumber)}`} target="_blank" rel="noopener noreferrer">Найти номер закупки в ЕИС ↗</a> · Прямая публичная ссылка не подтверждена.</p>}</section>
    <details className={styles.sources}><summary>Источники и исходные данные</summary>{row.navigation && [...row.navigation.delivery_regions, row.navigation.eis_url, row.navigation.platform_url, row.navigation.platform_name].filter(item => item !== null).map((fact, index) => <p key={`navigation:${index}`}>{fact.value}<br />{fact.provenance.document_id} · {fact.provenance.locator}{fact.supporting_sources?.map((source, i) => <span key={i}><br />{source.document_id} · {source.locator}</span>)}</p>)}<p>Источник: сохранённое извещение ЕИС. Версия {row.version}. Статус подачи не выводится из совпадения слов.</p>{row.deadlineRaw && <p>Исходный срок: {row.deadlineRaw}</p>}<dl>{row.evidence.map((item, index) => <div key={index}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}</dl>{row.positions.length > 0 && <details><summary>Все исходные позиции · {row.positions.length}</summary>{row.positions.map((item, index) => <p key={index}>{item.name} · {item.quantity} · {item.unit}<br /><span className={styles.muted}>{item.locator}</span></p>)}</details>}</details>
  </article>;
}
