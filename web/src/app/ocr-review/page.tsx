import type { Metadata } from "next";
import Link from "next/link";

import { OcrReviewWorkspace } from "./review-workspace";

export const metadata: Metadata = {
  title: "Проверка OCR-разметки — Syurai Procurement",
  description: "Локальное человеческое подтверждение эталонной OCR-разметки",
};

export default function OcrReviewPage() {
  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <div className="mx-auto w-[min(1600px,calc(100%-1rem))] py-5 sm:w-[min(1600px,calc(100%-2rem))] sm:py-8">
        <header className="mb-5 flex flex-col gap-4 border-b border-slate-200 pb-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="m-0 text-xs font-black uppercase tracking-[.16em] text-blue-700">
              S4 · локальная проверка
            </p>
            <h1 className="mt-2 text-3xl font-black tracking-tight sm:text-5xl">
              Подтверждение OCR-разметки
            </h1>
          </div>
          <div className="max-w-2xl text-sm leading-6 text-slate-600">
            <p className="m-0">
              DOCX и JSON читаются только вашим браузером и не отправляются в API.
              Скачивание создаёт новый evidence-файл, исходная AI-разметка не меняется.
            </p>
            <Link className="mt-2 inline-block font-bold text-blue-700 hover:underline" href="/">
              ← Вернуться к делам
            </Link>
            <Link className="ml-5 mt-2 inline-block font-bold text-blue-700 hover:underline" href="/document-search">
              Поиск по документам →
            </Link>
            <Link className="ml-5 mt-2 inline-block font-bold text-blue-700 hover:underline" href="/completeness-review">
              Проверка полноты →
            </Link>
          </div>
        </header>
        <OcrReviewWorkspace />
      </div>
    </main>
  );
}
