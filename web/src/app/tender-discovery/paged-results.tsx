"use client";

import { useEffect, useRef, useState, useTransition, type ReactNode } from "react";

type Page = {
  query: string; matched_count: number; matched: unknown[];
  next_cursor?: string | null; page_snapshot_sha256?: string | null; snapshot_at?: string | null;
};

export function mergeSearchPage<R extends Page>(current: R, next: R, identity: (row: R["matched"][number]) => string): R {
  if (!current.page_snapshot_sha256 || next.page_snapshot_sha256 !== current.page_snapshot_sha256 ||
      !current.snapshot_at || next.snapshot_at !== current.snapshot_at || current.query !== next.query ||
      current.matched_count !== next.matched_count || (next.next_cursor && next.next_cursor === current.next_cursor) ||
      (next.matched.length === 0 && Boolean(current.next_cursor))) {
    throw new Error("SEARCH_PAGE_CHANGED");
  }
  const rows = [...current.matched, ...next.matched];
  const ids = rows.map(row => identity(row));
  if (new Set(ids).size !== ids.length || rows.length > current.matched_count) throw new Error("SEARCH_PAGE_CHANGED");
  return { ...current, matched: rows, next_cursor: next.next_cursor };
}

export function PagedResults<R extends Page>({ initial, loadPage, identity, children }: {
  initial: R; loadPage: (cursor: string) => Promise<{ result?: R; error?: string; restartRequired?: boolean }>;
  identity: (row: R["matched"][number]) => string; children: (result: R, canLoad: boolean) => ReactNode;
}) {
  const [result, setResult] = useState(initial);
  const [error, setError] = useState<string>();
  const [restart, setRestart] = useState(false);
  const [pending, start] = useTransition();
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const canLoad = Boolean(result.next_cursor) && !restart;
  return <>
    {children(result, canLoad)}
    {result.snapshot_at && <p className="mt-3 text-xs text-slate-600">Результаты на момент поиска:
      {" "}{new Date(result.snapshot_at).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" })} МСК.
      Продолжение доступно 15 минут. Новые публикации появятся после повторного поиска.</p>}
    {canLoad && <div className="mt-4 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm">
      <p>Получено {result.matched.length} из {result.matched_count}. Следующие совпадения можно загрузить из сохранённой базы.</p>
      <button type="button" disabled={pending} className="mt-2 rounded bg-blue-700 px-4 py-2 font-bold text-white disabled:opacity-50"
        onClick={() => start(async () => {
          setError(undefined);
          let next: Awaited<ReturnType<typeof loadPage>>;
          try { next = await loadPage(result.next_cursor!); }
          catch { if (alive.current) setError("Не удалось получить продолжение поиска. Попробуйте ещё раз."); return; }
          if (!alive.current) return;
          if (!next.result) { setError(next.error ?? "Не удалось получить продолжение поиска."); setRestart(Boolean(next.restartRequired)); return; }
          try { setResult(mergeSearchPage(result, next.result, identity)); }
          catch { setRestart(true); setError("Состав результатов изменился. Повторите поиск, чтобы получить согласованные страницы."); }
        })}>{pending ? "Загружаю…" : "Загрузить следующие совпадения"}</button>
    </div>}
    {error && <p role="alert" className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{error}</p>}
  </>;
}
