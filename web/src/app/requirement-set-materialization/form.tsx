"use client";

import { useActionState } from "react";

import {
  commitRequirementSet,
  previewRequirementSet,
  type MaterializationState,
  type PreviewState,
} from "./actions";

function SourceFields({
  documentId,
  sha256,
}: {
  documentId: string;
  sha256: string;
}) {
  return (
    <>
      <label className="grid gap-1 text-sm font-bold">
        Document ID
        <input
          className="rounded-lg border border-slate-300 p-2 font-mono text-sm"
          defaultValue={documentId}
          name="document-id"
          pattern="[A-Za-z0-9][A-Za-z0-9._:-]{0,199}"
          required
        />
      </label>
      <label className="grid gap-1 text-sm font-bold">
        Source SHA-256
        <input
          className="rounded-lg border border-slate-300 p-2 font-mono text-sm"
          defaultValue={sha256}
          name="source-sha256"
          pattern="[0-9a-f]{64}"
          required
        />
      </label>
      <label className="grid gap-1 text-sm font-bold">
        Ожидаемое число строк
        <input
          className="rounded-lg border border-slate-300 p-2 text-sm"
          defaultValue="87"
          max="500"
          min="1"
          name="expected-entry-count"
          required
          type="number"
        />
      </label>
    </>
  );
}

export function RequirementSetMaterializationForm({
  documentId,
  sha256,
}: {
  documentId: string;
  sha256: string;
}) {
  const [previewState, previewAction, previewPending] = useActionState(
    previewRequirementSet,
    {} as PreviewState,
  );
  const [commitState, commitAction, commitPending] = useActionState(
    commitRequirementSet,
    {} as MaterializationState,
  );
  const preview = previewState.preview;

  return (
    <div className="mt-6 grid gap-5">
      <form action={previewAction} className="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="m-0 text-xl font-black">1. Построить exact preview</h2>
        <p className="m-0 text-sm leading-6 text-slate-600">
          Сервер выберет только одну полную native DOCX-таблицу с указанным числом строк.
          Текст строк не принимается из браузера.
        </p>
        <SourceFields documentId={documentId} sha256={sha256} />
        <button
          className="w-fit rounded-lg bg-slate-900 px-4 py-2 font-bold text-white disabled:opacity-50"
          disabled={previewPending}
          type="submit"
        >
          {previewPending ? "Проверяем…" : "Показать 87 строк"}
        </button>
        {previewState.error && <p className="text-sm font-bold text-red-800" role="alert">{previewState.error}</p>}
      </form>

      {preview && (
        <form action={commitAction} className="grid gap-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <input name="document-id" type="hidden" value={preview.source_document_id} />
          <input name="source-sha256" type="hidden" value={preview.source_document_sha256} />
          <input name="expected-entry-count" type="hidden" value={preview.expected_entry_count} />
          <input name="preview-sha256" type="hidden" value={preview.preview_sha256} />
          <div>
            <h2 className="m-0 text-xl font-black">2. Проверить строки и создать proposal</h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              Найдено {preview.entries.length} строк и {preview.numeric_suggestion_count} числовых
              подсказок. Ни одна подсказка не выбрана автоматически. Невыбранные строки останутся
              обязательствами ручной проверки.
            </p>
            <p className="break-all font-mono text-xs text-slate-600">Preview SHA-256: {preview.preview_sha256}</p>
          </div>
          <label className="grid gap-1 text-sm font-bold">
            Проверенный объём proposal
            <textarea
              className="min-h-24 rounded-lg border border-slate-300 p-2 text-sm"
              defaultValue="Все строки выбранной таблицы технических характеристик"
              maxLength={4000}
              name="declared-scope"
              required
            />
          </label>
          <ol className="grid gap-3 p-0">
            {preview.entries.map((entry) => (
              <li className="list-none rounded-xl border border-slate-200 bg-slate-50 p-4" key={entry.ordinal}>
                <p className="m-0 text-xs font-black uppercase tracking-wide text-slate-500">Строка {entry.ordinal}</p>
                <h3 className="mb-0 mt-1 text-base font-black">{entry.raw_name}</h3>
                <p className="mb-0 mt-2 whitespace-pre-wrap text-sm"><strong>Значение:</strong> {entry.raw_value}</p>
                <p className="mb-0 mt-1 whitespace-pre-wrap text-sm text-slate-600"><strong>Инструкция:</strong> {entry.instruction ?? "не указана"}</p>
                <p className="mb-0 mt-2 break-all font-mono text-xs text-slate-500">{entry.provenance.locator}</p>
                {entry.numeric_suggestion ? (
                  <fieldset className="mt-3 grid gap-3 rounded-lg border border-blue-200 bg-blue-50 p-3">
                    <label className="flex items-start gap-2 text-sm font-bold">
                      <input name="selected-ordinal" type="checkbox" value={entry.ordinal} />
                      Сделать эту подсказку исполнимым требованием: {entry.numeric_suggestion.operator} {entry.numeric_suggestion.value} {entry.numeric_suggestion.unit ?? ""}
                    </label>
                    <div className="grid gap-3 md:grid-cols-2">
                      <label className="grid gap-1 text-xs font-bold">
                        Canonical property
                        <input className="rounded border border-slate-300 p-2 font-mono" name={`property-${entry.ordinal}`} pattern="[a-z][a-z0-9_]{1,99}" placeholder="cpu_cores_each" />
                      </label>
                      <label className="grid gap-1 text-xs font-bold">
                        Единица
                        <input className="rounded border border-slate-300 p-2" defaultValue={entry.numeric_suggestion.unit ?? ""} name={`unit-${entry.ordinal}`} />
                      </label>
                      <label className="grid gap-1 text-xs font-bold">
                        Обязательность
                        <select className="rounded border border-slate-300 p-2" defaultValue="" name={`mandatory-${entry.ordinal}`}>
                          <option disabled value="">Выберите явно</option>
                          <option value="true">Обязательное</option>
                          <option value="false">Желательное</option>
                        </select>
                      </label>
                      <label className="grid gap-1 text-xs font-bold">
                        Основание нормализации
                        <input className="rounded border border-slate-300 p-2" maxLength={2000} name={`review-note-${entry.ordinal}`} placeholder="Сверено с ячейками и единицей" />
                      </label>
                    </div>
                  </fieldset>
                ) : (
                  <p className="mb-0 mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
                    Машинной числовой подсказки нет: строка будет сохранена как MANUAL_REVIEW_REQUIRED.
                  </p>
                )}
              </li>
            ))}
          </ol>
          <button
            className="w-fit rounded-lg bg-blue-700 px-4 py-2 font-bold text-white disabled:opacity-50"
            disabled={commitPending}
            type="submit"
          >
            {commitPending ? "Сохраняем…" : "Создать immutable proposal"}
          </button>
          {commitState.error && <p className="text-sm font-bold text-red-800" role="alert">{commitState.error}</p>}
          {commitState.setId && (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm" role="status">
              <p className="m-0 font-black">Proposal сохранён</p>
              <p className="mt-2 break-all">Set ID: {commitState.setId}</p>
              <p className="mt-1 break-all font-mono text-xs">SHA-256: {commitState.proposalSha256}</p>
              <p className="mb-0 mt-2">Строк: {commitState.entryCount}; исполнимых: {commitState.executableCount}; остальные переданы независимому reviewer как manual.</p>
              <div className="mt-3 flex flex-wrap gap-4 font-bold">
                <a className="text-blue-700 hover:underline" href={`/requirement-set-review?set_id=${encodeURIComponent(commitState.setId)}`}>
                  Открыть exact reviewer screen →
                </a>
                <a className="text-blue-700 hover:underline" href={`/requirement-set-binding?set_id=${encodeURIComponent(commitState.setId)}`}>
                  Проверить готовность binding →
                </a>
              </div>
            </div>
          )}
        </form>
      )}
    </div>
  );
}
