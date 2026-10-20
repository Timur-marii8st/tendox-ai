"use client";
import { useEffect, useRef, useState, useTransition } from "react";
import { sameProtocolRef } from "@/lib/eis-protocols";
import { reviewRequestKey, validReviewRequest, type ReviewRequest } from "@/lib/eis-document-review";
import { requirementPreviewMatches, type RequirementPreview, type RequirementPreviewRequest } from "@/lib/eis-requirement-preview";
import type { SavedSupplierProduct } from "@/lib/eis-supplier-product";
import { loadIndexedDocuments, loadRequirementPreview } from "./actions";
import { DocumentReview } from "./document-review";
import { RequirementPreviewReport } from "./requirement-preview-report";
import { RequirementReview } from "./requirement-review";
type Choice = { filename: string; request: ReviewRequest };
export function RequirementPreviewView({ product }: { product: SavedSupplierProduct }) {
  const [choices,setChoices] = useState<Choice[]>(), [selected,setSelected] = useState(""), [table,setTable] = useState(""), [result,setResult] = useState<RequirementPreview>(), [error,setError] = useState<string>(), [pending,start] = useTransition();
  const sequence = useRef(0), notice = product.report.position.selection.notice;
  const choice = choices?.find(c => reviewRequestKey(c.request) === selected);
  useEffect(() => () => { sequence.current++; }, []);
  function reset() { sequence.current++; setResult(undefined); setError(undefined); }
  function listDocuments() {
    const id = ++sequence.current; setResult(undefined); setError(undefined); setChoices(undefined); setSelected("");
    start(async () => { try {
      const state = await loadIndexedDocuments(notice); if (id !== sequence.current) return;
      const r = state.result;
      if (!r || !sameProtocolRef(r.notice,notice) || r.current_version_number !== notice.version_number || r.current_xml_sha256 !== notice.notice_xml_sha256 || r.version_status !== "CURRENT_KNOWN_VERSION" || r.read_gate?.blocked_reasons.length) { setError(state.error ?? "Версия документа изменилась или чтение требует проверки."); return; }
      const found = r.documents.flatMap(d => {
        const request = { notice, content_uid:d.content_uid, expected_document_sha256:d.sha256 };
        return d.fetch_status === "RECEIVED" && /\.docx$/i.test(d.filename) && d.received_byte_count !== null && d.received_byte_count > 0 && d.received_byte_count <= 4 * 1024**2 && validReviewRequest(request) ? [{filename:d.filename,request}] : [];
      });
      setChoices(found);
    } catch { if (id === sequence.current) setError("Не удалось прочитать список сохранённых документов."); } });
  }
  function preview() {
    if (!choice || !/^[1-9]\d{0,2}$/.test(table) || Number(table) > 100) { setError("Выберите полученный DOCX и номер таблицы от 1 до 100."); return; }
    const request: RequirementPreviewRequest = {product:product.report.request,document:choice.request,table_index:Number(table)};
    const id = ++sequence.current; setResult(undefined); setError(undefined);
    start(async () => { try {
      const state = await loadRequirementPreview(request); if (id !== sequence.current) return;
      if (!state.result || !requirementPreviewMatches(state.result,request,{run_id:product.report.run_id,source_url:product.report.details.source_url,html_sha256:product.report.details.html_sha256})) { setError(state.error ?? "Таблица не соответствует выбранным источникам."); return; }
      setResult(state.result);
    } catch { if (id === sequence.current) setError("Не удалось открыть таблицу документа."); } });
  }
  return <section className="mt-3 rounded border p-3">
    <h5 className="font-semibold">Характеристики из документа закупки</h5>
    <p>Выберите описание объекта закупки и откройте его сохранённый текст. Обоснование цены и проект контракта могут содержать другие сведения.</p>
    <button type="button" disabled={pending} className="mt-2 rounded border px-2 py-1" onClick={listDocuments}>Показать полученные DOCX</button>
    {choices && <><label className="mt-2 block">Документ<select className="ml-2 max-w-full rounded border p-1" value={selected} disabled={pending} onChange={e => { reset(); setSelected(e.target.value); }}><option value="">Выберите документ</option>{choices.map(c => <option key={reviewRequestKey(c.request)} value={reviewRequestKey(c.request)}>{c.filename}</option>)}</select></label>{!choices.length && <p>Подходящих полученных DOCX нет. Сначала получите документы выбранной закупки.</p>}</>}
    {choice && <><DocumentReview key={reviewRequestKey(choice.request)} request={choice.request} /><label className="mt-2 block">Номер таблицы в документе<input type="number" min={1} max={100} step={1} value={table} disabled={pending} className="ml-2 w-20 rounded border p-1" onChange={e => { reset(); setTable(e.target.value); }} /></label><button type="button" disabled={pending} className="mt-2 rounded border px-2 py-1" onClick={preview}>Показать таблицу рядом с товаром</button></>}
    {pending && <p role="status">Читаем сохранённые данные…</p>}{error && <p role="alert">{error}</p>}
    {result && <><RequirementPreviewReport result={result} /><RequirementReview key={result.preview_sha256} preview={result} /></>}
  </section>;
}
