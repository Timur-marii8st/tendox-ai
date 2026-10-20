export default function Loading() {
  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <div className="mx-auto w-[min(1100px,calc(100%-1rem))] py-10" role="status" aria-live="polite">
        <p className="text-xs font-black uppercase tracking-[.16em] text-blue-700">S4 · поиск по evidence</p>
        <h1 className="mt-2 text-3xl font-black sm:text-5xl">Ищу в документах…</h1>
        <div className="mt-8 h-24 animate-pulse rounded-2xl border border-slate-200 bg-white" />
        <span className="sr-only">Загружаются результаты поиска</span>
      </div>
    </main>
  );
}
