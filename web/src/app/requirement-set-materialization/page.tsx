import type { Metadata } from "next";
import Link from "next/link";

import { RequirementSetMaterializationForm } from "./form";

export const metadata: Metadata = {
  title: "Материализация требований — Syurai Procurement",
  description: "Server-derived proposal из exact таблицы технических характеристик",
};

export default async function RequirementSetMaterializationPage({
  searchParams,
}: {
  searchParams: Promise<{ document_id?: string; sha256?: string }>;
}) {
  const params = await searchParams;
  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <div className="mx-auto w-[min(1180px,calc(100%-1rem))] py-6 sm:w-[min(1180px,calc(100%-2rem))] sm:py-10">
        <header className="border-b border-slate-200 pb-6">
          <p className="m-0 text-xs font-black uppercase tracking-[.16em] text-blue-700">S82 · operator workflow</p>
          <h1 className="mt-2 text-3xl font-black tracking-tight sm:text-5xl">Материализация таблицы требований</h1>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">
            Preview строится из persisted native DOCX extraction и exact SHA-256. Все строки
            сохраняются; числовые подсказки становятся исполнимыми только после явного выбора.
            Proposal ещё не является независимым reviewer decision или допуском товара.
          </p>
          <nav aria-label="Разделы пилота" className="mt-4 flex flex-wrap gap-4 text-sm font-bold">
            <Link className="text-blue-700 hover:underline" href="/">Дела</Link>
            <Link className="text-blue-700 hover:underline" href="/document-upload">Загрузка документов</Link>
          </nav>
        </header>
        <RequirementSetMaterializationForm
          documentId={params.document_id ?? ""}
          sha256={params.sha256 ?? ""}
        />
      </div>
    </main>
  );
}
