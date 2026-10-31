"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { readGosplanAction, searchGosplanAction } from "./gosplan-actions";
import { GosplanDetailContent } from "./gosplan-detail";
import { GosplanPagination } from "./gosplan-pagination";
import type { GosplanDetail, GosplanLaw, GosplanSearchPage } from "@/lib/procurement-api";
import styles from "./workspace.module.css";

type Portion = { result?: GosplanSearchPage; error?: string; offset: number };
function showPrice(value: string | null, currency: string | null): string {
  if (value === null) return "Сумма не указана";
  const [integer, fraction] = value.split(".");
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return `${grouped}${fraction ? `,${fraction}` : ""} ${currency === "RUB" ? "₽" : currency ?? ""}`.trim();
}
export function GosplanWorkspace() {
  const [query, setQuery] = useState("");
  const [law, setLaw] = useState<"all" | GosplanLaw>("all");
  const [parts, setParts] = useState<Partial<Record<GosplanLaw, Portion>>>({});
  const [selected, setSelected] = useState<{ law: GosplanLaw; number: string }>();
  const [detail, setDetail] = useState<GosplanDetail>();
  const [detailError, setDetailError] = useState<string>();
  const [pending, start] = useTransition();
  const [detailPending, startDetail] = useTransition();
  const generation = useRef(0);
  const detailRef = useRef<HTMLElement>(null);
  useEffect(() => { if (selected) detailRef.current?.focus(); }, [selected]);

  function search() {
    const text = query.trim(); if (!text) return;
    const request = ++generation.current; setSelected(undefined); setDetail(undefined); setParts({});
    start(async () => {
      const numberLaw = /^\d{19}$/.test(text) ? "44" : /^\d{11}$/.test(text) ? "223" : undefined;
      const laws: GosplanLaw[] = numberLaw ? [numberLaw] : law === "all" ? ["44", "223"] : [law];
      const results = await Promise.all(laws.map(async value => [value, await searchGosplanAction(text, value)] as const));
      if (request !== generation.current) return;
      setParts(Object.fromEntries(results.map(([value, part]) => [value, { ...part, offset: 0 }])));
    });
  }
  function select(value: GosplanLaw, number: string) {
    const request = ++generation.current; setSelected({ law: value, number }); setDetail(undefined); setDetailError(undefined);
    startDetail(async () => { const part = await readGosplanAction(value, number); if (request === generation.current) { setDetail(part.result); setDetailError(part.error); } });
  }
  function more(value: GosplanLaw) {
    const current = parts[value]; if (!current?.result || !current.result.may_have_more) return;
    const offset = current.offset + current.result.items.length; if (offset > 1000) return;
    const request = ++generation.current;
    start(async () => { const part = await searchGosplanAction(current.result!.query, value, offset); if (request === generation.current) setParts(previous => ({ ...previous, [value]: { ...part, offset } })); });
  }
  return <section className={styles.workspace}>
    <div className={styles.hero}><div className={styles.eyebrow}><span />ПОИСК ЗАКУПОК</div><h1>Найдите подходящую <span>закупку</span></h1><p className={styles.subtitle}>Поиск по данным ГосПлана. Перед участием проверьте извещение и сроки в ЕИС.</p></div>
    <form className={styles.searchPanel} onSubmit={event => { event.preventDefault(); search(); }}>
      <div className={styles.searchFields}><label className={styles.productField}>Товар или номер закупки<span className={styles.searchInput}><span aria-hidden="true">⌕</span><input value={query} onChange={event => setQuery(event.target.value)} required maxLength={120} placeholder="Например, бумага А4" /></span></label><button className={styles.searchButton} disabled={pending || !query.trim()}>{pending ? "Ищем…" : "Найти закупки"}</button></div>
      <div className={styles.searchOptions}><fieldset className={styles.lawFilter}><legend>Закон</legend>{([["all", "Все закупки"], ["44", "44-ФЗ"], ["223", "223-ФЗ"]] as const).map(([value, text]) => <label key={value} className={law === value ? styles.lawSelected : ""}><input type="radio" name="gosplan-law" checked={law === value} onChange={() => setLaw(value)} /><span>{text}</span></label>)}</fieldset></div>
    </form>
    <p className={styles.scopeNote}>Данные ГосПлана; полнота и актуальный статус не подтверждены. Даты показаны как в источнике без подтверждённого часового пояса.</p>
    {selected && <article ref={detailRef} tabIndex={-1} className={styles.detail} aria-live="polite"><h2>{selected.law}-ФЗ · № {selected.number}</h2>{detailPending && <p>Загружаем документы и ссылки…</p>}{detailError && <p role="alert">{detailError}</p>}{detail && <GosplanDetailContent detail={detail} />}</article>}
    {(["44", "223"] as const).map(value => { const part = parts[value]; if (!part) return null; return <section key={value}><h2>{value}-ФЗ</h2>{part.error && <p role="alert" className={styles.error}>{part.error}</p>}{part.result && <><p>Страница с позиции {part.offset + 1}; получено {part.result.items.length}. Данные на {part.result.observed_at}.</p>{part.result.items.length === 0 && <p>На этой странице совпадений нет.</p>}<div className={styles.resultList}>{part.result.items.map(row => <button type="button" key={row.number} className={styles.resultCard} onClick={() => select(value, row.number)}><span className={styles.cardTop}>{value}-ФЗ · № {row.number}</span><strong>{row.title}</strong><span>{showPrice(row.price, row.currency)}</span><span>Срок из источника: {row.deadline_raw ?? "не указан"}</span><span>Статус подачи не подтверждён</span></button>)}</div><GosplanPagination law={value} offset={part.offset} count={part.result.items.length} mayHaveMore={part.result.may_have_more} disabled={pending} className={styles.secondaryButton} onNext={() => more(value)} /></>}</section>; })}
  </section>;
}
