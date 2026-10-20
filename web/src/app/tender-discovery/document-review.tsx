"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { firstReviewCursor, reviewPageMatches, reviewRequestKey, type ReviewCursor, type ReviewRequest, type SavedReviewPage } from "@/lib/eis-document-review";
import { loadDocumentReview, prepareDocumentReview } from "./actions";
import { DocumentReviewReport } from "./document-review-report";
import { PositionAssociation } from "./position-association";
import type { PositionEvidenceSet } from "@/lib/procurement-api";

export function DocumentReview({ request, positions }: { request: ReviewRequest; positions?: PositionEvidenceSet | null }) {
  // The parent mounts this component with the complete immutable request as key.
  const [report, setReport] = useState<SavedReviewPage>();
  const [previous, setPrevious] = useState<ReviewCursor[]>([]);
  const [error, setError] = useState<string>();
  const [pending, start] = useTransition();
  const sequence = useRef(0);
  useEffect(() => () => { sequence.current++; }, []);
  const key = reviewRequestKey(request);
  function load(kind: "prepare" | "first" | "next" | "previous", cursor: ReviewCursor) {
    const id = ++sequence.current;
    start(async () => {
      let result;
      try { result = await (kind === "prepare" ? prepareDocumentReview(request) : loadDocumentReview(request, cursor)); }
      catch {
        if (id === sequence.current) setError("Не удалось получить текст. Проверьте соединение и повторите запрос.");
        return;
      }
      if (id !== sequence.current) return;
      if (!result.result || !reviewPageMatches(result.result, request, cursor, kind === "prepare")) {
        setError(result.error ?? "Полученный текст не соответствует выбранному документу и странице.");
        return;
      }
      setError(undefined);
      if (kind === "next" && report) setPrevious(v => [...v, { offset: report.page.offset, character_offset: report.page.character_offset, limit: report.page.limit }]);
      else if (kind === "previous") setPrevious(v => v.slice(0, -1));
      else setPrevious([]);
      setReport(result.result);
    });
  }
  return <section className="mt-2" data-document-review={key}>
    <div className="flex flex-wrap gap-2">
      <button type="button" disabled={pending} onClick={() => load("prepare", firstReviewCursor)}
        className="rounded border border-blue-300 px-3 py-2 disabled:opacity-50">Подготовить текст DOCX для проверки</button>
      <button type="button" disabled={pending} onClick={() => load("first", firstReviewCursor)}
        className="rounded border border-slate-300 px-3 py-2 disabled:opacity-50">Открыть подготовленный текст</button>
    </div>
    {pending && <p role="status">Читаем выбранный документ…</p>}
    {error && <p role="alert" className="mt-2 text-red-800">{error}</p>}
    {report && <><DocumentReviewReport report={report} /><PositionAssociation page={report} positions={positions} /><nav aria-label="Страницы сохранённого текста" className="mt-2 flex gap-2">
      <button type="button" disabled={pending || !previous.length} onClick={() => load("previous", previous[previous.length - 1])}
        className="rounded border px-3 py-2 disabled:opacity-50">Предыдущая</button>
      <button type="button" disabled={pending || report.page.next_offset === null} onClick={() => {
        if (report.page.next_offset !== null && report.page.next_character_offset !== null) load("next", {
          offset: report.page.next_offset, character_offset: report.page.next_character_offset, limit: report.page.limit });
      }} className="rounded border px-3 py-2 disabled:opacity-50">Следующая</button>
    </nav></>}
  </section>;
}
