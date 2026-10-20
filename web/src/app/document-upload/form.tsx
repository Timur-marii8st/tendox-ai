"use client";

import Link from "next/link";
import { useActionState } from "react";

import {
  uploadApplicationAttachment,
  uploadSupplierQuote,
  uploadTenderDocument,
  type UploadState,
} from "./actions";

type Role = "tender" | "quote" | "application";

function UploadSlot({ role }: { role: Role }) {
  const tender = role === "tender";
  const application = role === "application";
  const [state, action, pending] = useActionState(
    tender
      ? uploadTenderDocument
      : application
        ? uploadApplicationAttachment
        : uploadSupplierQuote,
    {} as UploadState,
  );
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-xl font-black text-slate-950">
        {tender
          ? "Документ заказчика"
          : application
            ? "Документ будущей заявки"
            : "Коммерческое предложение поставщика"}
      </h2>
      <p className="mt-2 text-sm leading-6 text-slate-600">
        {tender
          ? "Загрузите ТЗ или приложение с требованиями. Этот документ можно использовать при проверке требований после человеческого review."
          : application
            ? "Загрузите подготовленную форму, декларацию или подтверждающий документ. Загрузка сама по себе не включает файл в заявку."
            : "Загрузите КП. Оно сохранится как предложение поставщика и не станет источником требований заказчика."}
      </p>
      <form action={action} className="mt-4 grid gap-3">
        <label className="grid gap-1 text-sm font-bold text-slate-900">
          Файл PDF, DOCX или XLSX (до 20 МиБ)
          <input
            accept=".pdf,.docx,.xlsx"
            className="rounded-lg border border-slate-300 p-2 text-sm"
            disabled={pending}
            name="file"
            required
            type="file"
          />
        </label>
        <button
          className="w-fit rounded-lg bg-slate-900 px-4 py-2 font-bold text-white disabled:opacity-50"
          disabled={pending}
          type="submit"
        >
          {pending ? "Загрузка…" : "Загрузить документ"}
        </button>
      </form>
      {state.error && <p className="mt-4 text-sm font-bold text-red-800" role="alert">{state.error}</p>}
      {state.documentId && (
        <div className="mt-4 rounded-lg bg-slate-50 p-3 text-sm" role="status">
          <p className="font-bold">Сохранён: {state.filename}</p>
          <p className="mt-1 break-all">ID: {state.documentId}</p>
          <p className="mt-1 break-all">SHA-256: {state.sha256}</p>
          <p className="mt-1 font-bold">Извлечение текста: {state.extractionStatus}</p>
          {!!state.extractionReasons?.length && (
            <p className="mt-1">Причины: {state.extractionReasons.join(", ")}</p>
          )}
          {tender && state.sha256 && (
            <div className="flex flex-wrap gap-5">
              <Link
                className="mt-3 inline-block font-bold text-blue-700 hover:underline"
                href={`/requirement-set-materialization?document_id=${encodeURIComponent(state.documentId)}&sha256=${encodeURIComponent(state.sha256)}`}
              >
                Проверить таблицу требований
              </Link>
              <Link
                className="mt-3 inline-block font-bold text-blue-700 hover:underline"
                href={`/supplier-discovery?document_id=${encodeURIComponent(state.documentId)}`}
              >
                Подготовить поиск поставщиков по ТЗ
              </Link>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

export function DocumentUploadForm() {
  return (
    <div className="mt-6 grid gap-5 lg:grid-cols-3">
      <UploadSlot role="tender" />
      <UploadSlot role="quote" />
      <UploadSlot role="application" />
    </div>
  );
}
