"use client";
import { useEffect, useRef, useState, useTransition } from "react";
import type { RequirementPreview } from "@/lib/eis-requirement-preview";
import { comparisonMatches, formatSupplierIndex, savedProposalMatches, savedDecisionMatches, sameReviewValue, type RowChoice, type RequirementProposal, type RequirementComparison, type ProposalRequest } from "@/lib/eis-requirement-review";
import { prepareRequirementProposal, loadRequirementProposal, reviewRequirementProposal, loadRequirementComparison } from "./actions";
import { RequirementReviewReport } from "./requirement-review-report";
export function RequirementReview({ preview }: { preview: RequirementPreview }) {
  const [rows,setRows] = useState<RowChoice[]>(() => preview.table.rows.map(r => ({source_row:r.source_row,mode:"MANUAL",supplier_index:null,mandatory:null})));
  const [note,setNote] = useState(""), [id,setId] = useState(""), [proposal,setProposal] = useState<RequirementProposal>(), [comparison,setComparison] = useState<RequirementComparison>();
  const [normative,setNormative] = useState(false), [association,setAssociation] = useState(false), [confirmed,setConfirmed] = useState<number[]>([]), [reviewNote,setReviewNote] = useState("");
  const [error,setError] = useState<string>(), [pending,start] = useTransition(), sequence = useRef(0);
  useEffect(() => () => { sequence.current++; }, []);
  function clear() { sequence.current++; setError(undefined); setProposal(undefined); setComparison(undefined); setConfirmed([]); setNormative(false); setAssociation(false); }
  function change(index: number, values: Partial<RowChoice>) { clear(); setRows(a => a.map((r,i) => i === index ? {...r,...values} : r)); }
  function save() {
    if (rows.some(r => r.mode === "PAPER_FORMAT" && r.mandatory === null)) { setError("Укажите обязательность формата перед сохранением предложения."); return; }
    const request: ProposalRequest = {preview:preview.request,expected_preview_sha256:preview.preview_sha256,rows,note};
    const current = ++sequence.current; setError(undefined); setProposal(undefined); setComparison(undefined);
    start(async () => { const state = await prepareRequirementProposal(request); if (current !== sequence.current) return;
      if (!state.result || !savedProposalMatches(state.result,request,preview)) { setError(state.error ?? "Источники предложения не совпадают."); return; }
      setProposal(state.result.proposal); setId(state.result.proposal.proposal_id);
    });
  }
  function restore() {
    const current = ++sequence.current; setError(undefined); setProposal(undefined); setComparison(undefined); setConfirmed([]); setNormative(false); setAssociation(false);
    start(async () => { const state = await loadRequirementProposal(id.trim()); if (current !== sequence.current) return;
      if (!state.result || !savedProposalMatches(state.result,undefined,preview) || state.result.proposal.proposal_id !== id.trim()) { setError(state.error ?? "Предложение относится к другой таблице или товару."); return; }
      setProposal(state.result.proposal); setRows(state.result.proposal.request.rows); setNote(state.result.proposal.request.note);
    });
  }
  function compare() {
    if (!proposal) return; const current = ++sequence.current; setError(undefined); setComparison(undefined);
    start(async () => { const state = await loadRequirementComparison(proposal); if (current !== sequence.current) return;
      if (!state.result || !comparisonMatches(state.result,proposal)) { setError(state.error ?? "Решение не соответствует предложению."); return; } setComparison(state.result);
    });
  }
  function decide() {
    if (!proposal) return;
    const request = {proposal_id:proposal.proposal_id,expected_proposal_sha256:proposal.proposal_sha256,normative_document:normative,position_association:association,confirmed_rows:[...confirmed].sort((a,b) => a-b),note:reviewNote};
    const current = ++sequence.current; setError(undefined); setComparison(undefined);
    start(async () => { const state = await reviewRequirementProposal(request,proposal); if (current !== sequence.current) return;
      if (!state.result || !savedDecisionMatches(state.result,proposal) || !sameReviewValue(state.result.decision.request,request)) { setError(state.error ?? "Решение не соответствует выбранному предложению."); return; }
      const checked = await loadRequirementComparison(proposal); if (current !== sequence.current) return;
      if (!checked.result || !comparisonMatches(checked.result,proposal)) { setError(checked.error ?? "Сохранённое решение недоступно."); return; } setComparison(checked.result);
    });
  }
  return <section className="mt-3 rounded border p-3"><h5 className="font-semibold">Подготовить проверку требований</h5>
    <p>Для каждой строки выберите интерпретацию. Количество листов, плотность с допуском и класс бумаги требуют дальнейшего разбора. Отдельный проверяющий подтвердит роль документа, связь с позицией и нормализацию.</p>
    {preview.table.rows.map((r,i) => { const index = formatSupplierIndex(r,preview); return <fieldset key={r.source_row} className="mt-2 rounded border p-2" disabled={pending}><legend>Строка {r.source_row}: {r.cells.find(c => c.column === 1)?.text}</legend><label>Интерпретация <select value={rows[i].mode} onChange={e => change(i,{mode:e.target.value as RowChoice["mode"],supplier_index:e.target.value === "PAPER_FORMAT" ? index : null,mandatory:null})}><option value="MANUAL">Требует ручной проверки — UNKNOWN</option>{index !== null && <option value="PAPER_FORMAT">Точный формат бумаги A/B0–10</option>}</select></label>{rows[i].mode === "PAPER_FORMAT" && <><p>ТЗ: {r.cells.find(c => c.column === 3)?.text}; товар: {preview.product.details.characteristics[index!-1].value_raw}. Кириллическая А/В нормализуется только после независимого подтверждения.</p><label>Обязательное требование <select value={rows[i].mandatory === null ? "" : String(rows[i].mandatory)} onChange={e => change(i,{mandatory:e.target.value === "" ? null : e.target.value === "true"})}><option value="">Не определено</option><option value="true">Да</option><option value="false">Нет</option></select></label></>}</fieldset>; })}
    <label className="mt-2 block">Пояснение к предложению<textarea maxLength={1000} disabled={pending} value={note} onChange={e => {clear();setNote(e.target.value);}} className="block w-full rounded border" /></label>
    <button type="button" disabled={pending} onClick={save} className="mt-2 rounded border px-2 py-1">Сохранить предложение проверки</button>
    <label className="mt-2 block">Открыть предложение по ID<input value={id} disabled={pending} onChange={e => {clear();setId(e.target.value);}} className="ml-2 rounded border" /></label><button type="button" disabled={pending} onClick={restore} className="rounded border px-2 py-1">Открыть сохранённое предложение</button>
    {proposal && <><RequirementReviewReport proposal={proposal} comparison={comparison} /><button type="button" disabled={pending} onClick={compare} className="mt-2 rounded border px-2 py-1">Прочитать независимое решение и сравнение</button><details className="mt-3"><summary>Независимая проверка предложения</summary><p>Требуется другая учётная запись с ролью проверяющего. Подтверждение окончательное и относится к показанному Proposal SHA256. В текущем пилоте роль настроенного подключения проверяет сервер.</p><fieldset disabled={pending || !!comparison}><label className="block"><input type="checkbox" checked={normative} onChange={e => setNormative(e.target.checked)} /> Документ содержит нормативные требования для выбранного предмета поставки.</label><label className="block"><input type="checkbox" checked={association} onChange={e => setAssociation(e.target.checked)} /> Таблица относится к точной выбранной позиции закупки.</label>{proposal.request.rows.filter(r => r.mode === "PAPER_FORMAT").map(r => <label key={r.source_row} className="block"><input type="checkbox" checked={confirmed.includes(r.source_row)} onChange={e => setConfirmed(a => e.target.checked ? [...a,r.source_row] : a.filter(n => n !== r.source_row))} /> Строка {r.source_row}: подтверждаю точный формат, сопоставленное поле товара, обязательность и преобразование кириллической А/В.</label>)}<label className="block">Основание решения<textarea maxLength={1000} value={reviewNote} onChange={e => setReviewNote(e.target.value)} className="block w-full rounded border" /></label><button type="button" onClick={decide} className="mt-2 rounded border px-2 py-1">Сохранить независимое решение по показанному SHA256</button></fieldset></details></>}
    {pending && <p role="status">Проверяем сохранённые источники…</p>}{error && <p role="alert">{error}</p>}
  </section>;
}
