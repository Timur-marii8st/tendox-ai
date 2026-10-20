# ADR0085 — ограниченный отбор исторических аналогов

Статус: принято, backend установлен и проверен. Effective2026-10-05.

## Контекст

S203/S204 дают факты отдельных протоколов. Для оценки конкуренции PRD требует
сопоставимость по предмету, региону, периоду и объёму, прозрачную выборку и
калибровку вероятностей. Обычный lexical search ограничивает только вывод,
обрабатывает все кандидаты и предпочитает active перед expired.

## Решение

Выделить bounded read-only SQL отбор latest сохранённых карточек одной семьи,
с истёкшим deadline и публикацией в explicit target-relative периоде до LIMIT21.
20карточек/25позиций; существующие immutable lot_items как source0 projection.
Exact target/ref/position, tenant RLS/holds, проверка payload до гидратации,
SQL/foreground/output budgets. [Контракт](../eis/search/88-eis-historical-analog-selection.md).

Коды и целые названия сравниваются строго; конфликт двух KTRU блокирует fallback.
Decimal quantity[0.5..2] и normalized unit label — retrieval predicates.
Region delivery/specification equivalence UNKNOWN. Любой FAIL исключает строку,
остальные только для проверки; никакого score/competitor count/price merging.
Missing publication не заменяется now. SQL LIMIT не трактуется как bounded scan.
Внешнее содержимое не меняет внутреннюю retrieval policy или permissions.

## Последствия

Быстрая ограниченная гидратация без повторного чтения архива и нового cache/table.
SQL scan/latency, lexical recall, sample completeness и общая полнота UNKNOWN;
они не подменяются числом показанных карточек. Требуются измерения реальных запросов.
Только выдача source candidates через API; UI ещё не реализован.
Полноценная статистика/прогнозы отложены.193isolatedPGtests PASS; installed
three paper reads3.2–4.1s with exact-time direct equality, sample truncated.
Реальные измерения выявили40повторных SQLкоманд; следующая bounded итерация
проверит их удаление без изменения результатов/hold semantics.

S2062026-10-05: duplicate reads removed in the same read-only RR snapshot;
SET LOCAL jit=off avoids measured1150ms compilation overhead for this selector.
Policy/filter/limits/evidence contract unchanged.208isolatedPGtests PASS,
including exact S205 report equality and transaction setting restoration.
Six installed first/repeat reads1.98–2.17s HTTP; paired body median3.303→1.942s,
standalone52→13SQL. Measurements/remaining scan limit: [S206](../eis/search/89-eis-analog-query-performance.md).
No full-coverage/analogy/competition/profit inference or new source requests.

S2082026-10-05: materialized disjoint lexical identity branches before complete
source filters/final LIMIT; exact S206 report identity on216PGgates and6installed
same-time/snapshot reads. Paired median2122→1624ms, actual GIN use not observed;
no new index/schema/source calls or policy change. [Evidence](../eis/search/91-eis-analog-lexical-prefilter.md).
S207 UI already exposes criteria/locators/truncation/UNKNOWN; scope remains bounded.

S2092026-10-05: optional pre-limit eligible resolution scope includes every
same/newer retained pair and its full audited batch. All source/hold/receipt
checks remain; default consumers unscoped.228PGtests/frozen BOTH-module oracle
and6installed full-report identities PASS, direct median1618→723.5ms in saved
warmed sample. Spill remains, no full coverage/SLA claim. [Evidence](../eis/search/92-eis-scoped-resolution-checks.md).

## Альтернативы

Full source reparse/cache всех архивов дороже и преждевременен; reuse обычного
поиска не ограничивает вычисления и исключает полезную историю из первых лидеров.
Технический/географический PASS без evidence и прогноз без калибровки недопустимы.
