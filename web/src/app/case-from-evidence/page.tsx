import type { Metadata } from "next";
import Link from "next/link";

import { CaseFromEvidenceForm } from "./form";

export const metadata: Metadata = {
  title: "Кейс из привязки — Syurai Procurement",
  description: "Создание версии кейса с server-derived DOCUMENT-проверкой из exact привязки",
};

export default function CaseFromEvidencePage() {
  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <div className="mx-auto w-[min(1120px,calc(100%-1rem))] py-6 sm:w-[min(1120px,calc(100%-2rem))] sm:py-10">
        <header className="border-b border-slate-200 pb-6">
          <p className="m-0 text-xs font-black uppercase tracking-[.16em] text-blue-700">S4 · case ingestion</p>
          <h1 className="mt-2 text-3xl font-black tracking-tight sm:text-5xl">Кейс из привязки</h1>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">
            Создаёт версию кейса, чья DOCUMENT-проверка выводится сервером из точной terminal
            привязки. Assessment и DOCUMENT оператор не вводит: они принадлежат серверу.
            Экономика, КП и остальные проверки по-прежнему оцениваются case evaluator.
          </p>
          <nav aria-label="Разделы пилота" className="mt-4 flex flex-wrap gap-4 text-sm font-bold">
            <Link className="text-blue-700 hover:underline" href="/">Дела</Link>
            <Link className="text-blue-700 hover:underline" href="/document-set-review">Проверка комплекта</Link>
            <Link className="text-blue-700 hover:underline" href="/document-search">Поиск документов</Link>
          </nav>
        </header>

        <CaseFromEvidenceForm />
      </div>
    </main>
  );
}
