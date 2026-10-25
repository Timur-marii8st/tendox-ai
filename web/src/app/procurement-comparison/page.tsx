import { comparisonCatalog } from "../../lib/procurement-comparison-api";
import { ComparisonForm } from "./form";
import "./style.css";

export const dynamic = "force-dynamic";

export default async function Page({ searchParams }: { searchParams: Promise<{ cursor?: string }> }) {
  const { cursor } = await searchParams;
  let catalog;
  let error;
  try { catalog = await comparisonCatalog(cursor); }
  catch (caught) { error = caught instanceof Error ? caught.message : "Локальное API недоступно."; }
  return <main className="shell comparison-page">
    <header><p className="eyebrow">Tendox · Сравнение закупок</p><h1>Закупки и ваш профиль</h1>
      <p>Проверьте выбранные условия рядом: подтверждённые несоответствия, проверенные условия и сведения, которые ещё нужны.</p></header>
    <aside className="demo-banner"><div><b>{catalog?.mode === "LOCAL_DEMO_SYNTHETIC" ? "Демонстрация · синтетические данные" : "Сохранённые версии профиля и кейсов"}</b>
      <p>Результат не является допуском к участию. Отчёт пока не сохраняется в истории или аудите.</p>
      <p><a href="/company-profile">Выбрать версию профиля компании</a></p></div></aside>
    {catalog?.cases.length === 0 && <p>Сохранённых кейсов нет. Результаты поиска ЕИС ещё не являются полными кейсами для сравнения.</p>}
    {catalog?.next_cursor && <p><a href={`/procurement-comparison?cursor=${encodeURIComponent(catalog.next_cursor)}`}>Следующие сохранённые кейсы</a> · <a href="/procurement-comparison">К началу списка</a></p>}
    {catalog ? <ComparisonForm catalog={catalog} /> : <p role="alert" className="load-error">{error}</p>}
  </main>;
}
