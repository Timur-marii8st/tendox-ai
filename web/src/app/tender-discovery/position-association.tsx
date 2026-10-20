"use client";
import { useEffect, useRef, useState, useTransition } from "react";
import type { SavedReviewPage } from "@/lib/eis-document-review";
import { reviewRequestKey } from "@/lib/eis-document-review";
import type { PositionEvidenceSet } from "@/lib/procurement-api";
import { sameProtocolRef } from "@/lib/eis-protocols";
import { associationMatches, validAssociationRequest, associationListMatches, associationDetailMatches, associationScopeKey,
  type AssociationReadScope, type AssociationCursor, type AssociationListResult,
  type AssociatedFragment, type AssociationRequest, type SavedAssociation } from "@/lib/eis-position-association";
import { supplierSearchRequestKey } from "@/lib/eis-supplier-search";
import { loadPositionAssociation, savePositionAssociation, listPositionAssociations, loadPositionAssociationDetail } from "./actions";
import { PositionAssociationReportView } from "./position-association-report";
import { PositionAssociationListView } from "./position-association-list";
import { SupplierSearch } from "./supplier-search";

export function PositionAssociation({ page, positions }: { page: SavedReviewPage; positions?: PositionEvidenceSet | null }) {
  const exact = positions?.law === "44" && sameProtocolRef(page.request.notice, {
    purchase_number: positions.purchase_number, version_number: positions.version_number,
    notice_xml_sha256: positions.notice_xml_sha256,
  }) ? positions : undefined;
  if (!exact) return <p className="mt-2">Чтобы связать фрагменты с позицией, откройте «Связать с карточкой и расчётом» для этой закупки.</p>;
  return <PositionAssociationSelection key={reviewRequestKey(page.request)} page={page} positions={exact} />;
}
function PositionAssociationSelection({ page, positions: exact }: { page: SavedReviewPage; positions: PositionEvidenceSet }) {
  const [index, setIndex] = useState<number>();
  const [selected, setSelected] = useState<AssociatedFragment[]>([]);
  const [result, setResult] = useState<SavedAssociation>();
  const [listing, setListing] = useState<AssociationListResult>();
  const [error, setError] = useState<string>();
  const [pending, start] = useTransition();
  const sequence = useRef(0);
  useEffect(() => () => { sequence.current++; }, []);
  const scope: AssociationReadScope | undefined = index === undefined ? undefined : {
    position: { selection: { notice: page.request.notice, source_index: index } },
    document: page.request, analyzer_version: "eis-native-review-v1",
  };
  const request: AssociationRequest | undefined = index === undefined ? undefined : {
    position: { selection: { notice: page.request.notice, source_index: index } }, document: page.request,
    analyzer_version: "eis-native-review-v1", fragments: selected.map(f => f.selection),
  };
  function clear() { sequence.current++; setResult(undefined); setError(undefined); }
  function list(cursor: AssociationCursor | null = null) {
    if (!scope) return;
    const captured = { scope, cursor, limit: 20 }, id = ++sequence.current;
    setListing(undefined); setResult(undefined); setError(undefined);
    start(async () => {
      try {
        const state = await listPositionAssociations(captured);
        if (id !== sequence.current) return;
        if (!state.result || !associationListMatches(state.result, captured)) { setError(state.error ?? "Список не соответствует выбранной позиции и документу."); return; }
        setListing(state.result);
      } catch { if (id === sequence.current) setError("Не удалось прочитать список связей. Повторите позже."); }
    });
  }
  function restore(association_id: string) {
    if (!scope || !listing || associationScopeKey(scope) !== associationScopeKey(listing.request.scope)) return;
    const metadata = listing.items.find(item => item.association_id === association_id);
    if (!metadata) return;
    const captured = { scope, association_id }, id = ++sequence.current;
    setResult(undefined); setSelected([]); setError(undefined);
    start(async () => {
      try {
        const state = await loadPositionAssociationDetail(captured);
        if (id !== sequence.current) return;
        if (!state.result || !associationDetailMatches(state.result, captured) ||
          state.result.report.created_at !== metadata.created_at || state.result.report.linked_by !== metadata.linked_by ||
          state.result.report.fragments.length !== metadata.fragment_count || state.result.report.selected_characters !== metadata.selected_characters) {
          setError(state.error ?? "Связь не соответствует выбранной записи. Обновите список."); return;
        }
        setSelected(state.result.report.fragments); setResult(state.result);
      } catch { if (id === sequence.current) setError("Не удалось восстановить связь. Повторите позже."); }
    });
  }
  function submit(save: boolean) {
    if (!request || !validAssociationRequest(request)) { setError("Выберите позицию и фрагменты: до 10, всего до 16000 символов."); return; }
    const captured = request, id = ++sequence.current; setResult(undefined); setError(undefined);
    start(async () => {
      try {
        const state = await (save ? savePositionAssociation(captured) : loadPositionAssociation(captured));
        if (id !== sequence.current) return;
        if (!state.result || !associationMatches(state.result, captured, save)) { setError(state.error ?? "Ответ не соответствует выбранной позиции и фрагментам."); return; }
        if (save) setListing(undefined);
        setResult(state.result);
      } catch { if (id === sequence.current) setError("Не удалось получить связь. Повторите позже."); }
    });
  }
  return <section className="mt-3 rounded border bg-blue-50 p-3" aria-label="Выбор фрагментов для позиции">
    <h5 className="font-bold">Связать фрагменты с позицией</h5>
    <p>Выберите показанные фрагменты. Выбор сохраняется при переходе между страницами; сервер проверит текст по исходному документу. Это операторская связь, требования и полнота ТЗ: UNKNOWN.</p>
    <label className="block mt-2">Позиция <select disabled={pending} value={index ?? ""} className="rounded border p-2" onChange={event => { clear(); setListing(undefined); setSelected([]); setIndex(event.target.value ? Number(event.target.value) : undefined); }}>
      <option value="">Выберите позицию</option>{exact.positions.map(p => <option key={p.source_index} value={p.source_index}>{p.source_index}. {p.name.value ?? "UNKNOWN"}</option>)}
    </select></label>
    <button type="button" disabled={pending || !scope} className="mt-2 rounded border bg-white p-2 disabled:opacity-50" onClick={() => list()}>Открыть список сохранённых связей</button>
    {listing && <PositionAssociationListView result={listing} pending={pending} onOpen={restore} onNext={() => { if (listing.next_cursor) list(listing.next_cursor); }} />}
    {page.page.blocks.map(b => {
      const checked = selected.some(f => f.selection.block_index === b.block_index && f.selection.character_start === b.character_start && f.selection.character_end === b.character_end);
      return <label key={`${b.block_index}:${b.character_start}`} className="mt-2 flex items-start gap-2 rounded bg-white p-2">
        <input type="checkbox" disabled={pending} checked={checked} onChange={() => {
          clear();
          setSelected(previous => {
            const next = checked ? previous.filter(f => !(f.selection.block_index === b.block_index && f.selection.character_start === b.character_start && f.selection.character_end === b.character_end))
              : [...previous, { selection: { block_index: b.block_index, character_start: b.character_start, character_end: b.character_end }, text: b.text, provenance: b.provenance, source_character_count: b.source_character_count }];
            return next.sort((a, c) => a.selection.block_index - c.selection.block_index || a.selection.character_start - c.selection.character_start);
          });
        }} /><span className="whitespace-pre-wrap">Блок {b.block_index + 1}, символы {b.character_start + 1}–{b.character_end}: {b.text}</span>
      </label>;
    })}
    <p className="mt-2">Выбрано: {selected.length} / 10 фрагментов; {selected.reduce((n, f) => n + [...f.text].length, 0)} / 16000 символов.</p>
    {selected.length > 0 && <button type="button" disabled={pending} className="underline" onClick={() => { clear(); setSelected([]); }}>Очистить выбор</button>}
    <div className="mt-2 flex flex-wrap gap-2">
      <button type="button" disabled={pending || !request || !validAssociationRequest(request)} className="rounded border bg-white p-2 disabled:opacity-50" onClick={() => submit(true)}>Подтверждаю связь выбранных фрагментов — сохранить</button>
      <button type="button" disabled={pending || !request || !validAssociationRequest(request)} className="rounded border bg-white p-2 disabled:opacity-50" onClick={() => submit(false)}>Открыть сохранённую связь этого выбора</button>
    </div>
    {pending && <p role="status">Проверяем источники и связь…</p>}
    {error && <p role="alert">{error}</p>}
    {result && <><PositionAssociationReportView result={result} /><SupplierSearch key={supplierSearchRequestKey(result.report.request.position)} request={result.report.request.position} publicName={result.report.position_name.value} /></>}
  </section>;
}
