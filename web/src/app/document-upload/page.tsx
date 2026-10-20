import type { Metadata } from "next";
import Link from "next/link";

import { DocumentUploadForm } from "./form";

export const metadata: Metadata = {
  title: "Загрузка документов — Syurai Procurement",
  description: "Отдельная загрузка документов заказчика и КП поставщика",
};

export default function DocumentUploadPage() {
  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <div className="mx-auto w-[min(1100px,calc(100%-2rem))] py-8">
        <header className="border-b border-slate-200 pb-5">
          <p className="text-xs font-black uppercase tracking-[.16em] text-blue-700">Внутренний пилот</p>
          <h1 className="mt-2 text-3xl font-black sm:text-5xl">Загрузка документов</h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">
            Выберите назначение документа до загрузки. Результат извлечения показывает, удалось ли
            прочитать текст; он не является решением о соответствии закупке.
          </p>
          <nav aria-label="Разделы пилота" className="mt-4 flex gap-5 text-sm font-bold text-blue-700">
            <Link href="/">Дела</Link>
            <Link href="/document-search">Поиск по документам</Link>
          </nav>
        </header>
        <DocumentUploadForm />
      </div>
    </main>
  );
}
