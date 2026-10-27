# ЕИС: поиск, сравнение и история

Для поиска начать с 25/26 и актуального ограниченного workflow. Для исторических фактов — 86–92; для диапазонов — 93–99. Исторические наблюдения не дают допуск, прибыль или прогноз без подтверждения.

[Карта документации](../../README.md) · [Текущий статус](../../15-implementation-plan.md)

## Файлы

- [25-eis-tender-discovery.md](25-eis-tender-discovery.md) — Поиск и предварительное сравнение закупок заказчиков в ЕИС.
- [26-eis-full-corpus-plan.md](26-eis-full-corpus-plan.md) — План полного поиска и сравнения закупок ЕИС.
- [30-eis-fast-comparison.md](30-eis-fast-comparison.md) — Быстрый поиск и сравнение актуальных версий ЕИС.
- [34-eis-search-benchmark.md](34-eis-search-benchmark.md) — Бенчмарк поиска ЕИС — S134 / P1a.
- [36-eis-open-competition.md](36-eis-open-competition.md) — Электронный открытый конкурс 44-ФЗ.
- [40-eis-mixed-comparison.md](40-eis-mixed-comparison.md) — Общее сравнение выбранных закупок 44-ФЗ и 223-ФЗ.
- [69-eis-search-deadline-scope.md](69-eis-search-deadline-scope.md) — S186 — поиск по сроку в сохранённых карточках ЕИС.
- [70-eis-single-cursor-search.md](70-eis-single-cursor-search.md) — S187 — сравнение карточек одним потоком SQL.
- [86-eis-historical-protocol-facts.md](86-eis-historical-protocol-facts.md) — S203 — исторические факты протоколов.
- [87-eis-protocols-in-discovery-ui.md](87-eis-protocols-in-discovery-ui.md) — S204 — исторические протоколы в карточке закупки.
- [88-eis-historical-analog-selection.md](88-eis-historical-analog-selection.md) — S205 — исторические кандидаты в аналоги.
- [89-eis-analog-query-performance.md](89-eis-analog-query-performance.md) — S206 — ускорение SQL отбора исторических кандидатов.
- [90-eis-analog-candidates-ui.md](90-eis-analog-candidates-ui.md) — S207 — исторические кандидаты в аналоги в интерфейсе.
- [91-eis-analog-lexical-prefilter.md](91-eis-analog-lexical-prefilter.md) — S208 — измеренный лексический prefilter исторических кандидатов.
- [92-eis-scoped-resolution-checks.md](92-eis-scoped-resolution-checks.md) — S209 — точная область live resolution checks.
- [93-eis-characteristic-pair-observations.md](93-eis-characteristic-pair-observations.md) — S210 — записанные характеристики двух выбранных позиций.
- [94-eis-characteristic-pair-ui.md](94-eis-characteristic-pair-ui.md) — S211 — сравнение характеристик в исторической строке.
- [95-eis-selected-characteristic-recovery.md](95-eis-selected-characteristic-recovery.md) — S212 — восстановление характеристик выбранных карточек.
- [96-eis-recorded-range-comparison.md](96-eis-recorded-range-comparison.md) — S213 — сравнение записанных числовых диапазонов.
- [97-eis-range-external-id.md](97-eis-range-external-id.md) — S214 — диапазоны с externalSid.
- [98-eis-ambiguous-range-intake.md](98-eis-ambiguous-range-intake.md) — S215 — неподдерживаемый диапазон не отбрасывает архив.
- [99-eis-analog-payload-omissions.md](99-eis-analog-payload-omissions.md) — S216 — частичная выдача аналогов при ограничении размера.
- [112-eis-discovery-overview.md](112-eis-discovery-overview.md) — Обзор выдачи, компактные строки и отдельные границы полноты каталога.
- [113-eis-search-continuation.md](113-eis-search-continuation.md) — Продолжение после 100 совпадений и census трёх завершённых дней.
- [116-eis-search-quality-contract.md](116-eis-search-quality-contract.md) — M2a: строгий offline benchmark v2; frozen corpus и независимая разметка остаются условиями M2b.
- [117-eis-frozen-benchmark-capture.md](117-eis-frozen-benchmark-capture.md) — M2b: ограниченный неизменный снимок поисковых данных; trusted capture, replay и независимые labels принимаются отдельно.
- [118-eis-benchmark-instrument-evidence.md](118-eis-benchmark-instrument-evidence.md) — M2a/M2b1: приёмка инструмента, actual isolated PG evidence и незавершённые условия реального benchmark.
- [119-eis-capture-v3-contract.md](119-eis-capture-v3-contract.md) — Принятый контракт V3: fragments обычных строк и отдельное ограниченное SQLite состояние; actual fit не подтверждён.
- [121-eis-active-procurement-product-plan.md](121-eis-active-procurement-product-plan.md) — План активного procurement product search.
- [122-eis-active-census-m0.md](122-eis-active-census-m0.md) — Census M0 активных закупок.
- [exact-registration-number-integration.md](exact-registration-number-integration.md) — Интеграция поиска по точному регистрационному номеру.
- [exact-registration-number-search.md](exact-registration-number-search.md) — Контракт поиска по точному регистрационному номеру.
- [unified-search-workspace.md](unified-search-workspace.md) — Unified search workspace.

- [125-eis-search-recovery-review.md](125-eis-search-recovery-review.md) — Диагностика «бумага», throughput и пересмотр приоритета полезного поиска.
- [126-eis-paper-parity.md](126-eis-paper-parity.md) — Контрольные номера ЕИС по «бумага»: пропуски базы, регулярных типов и очереди, отдельное расхождение поиска.
- [127-eis-paper-recovery.md](127-eis-paper-recovery.md) — Офисная бумага на 3,23 млн: полный адресный intake и подтверждённое появление в HTTP поиске.

- [128-eis-hybrid-recovery.md](128-eis-hybrid-recovery.md) — Первый гибридный проход: обнаружение, durable queue и автоматическое восстановление.

- [129-eis-active-sweep.md](129-eis-active-sweep.md) — Расширение гибридного обхода на активные44 без товарного запроса.

- [133-eis-regional-discount.md](133-eis-regional-discount.md) — V45: официальные контрактные результаты, подбор истории и UI; установлен, +2результата контрактов; ≥5UNKNOWN; V46 восстановил контрольную закупку в поиске.
- [135-eis-single-customer-history.md](135-eis-single-customer-history.md) — V47: единственный source customer, полная проверка allocation и автоматический контекст истории.
- [136-eis-real-regional-five.md](136-eis-real-regional-five.md) — V48: пять реальных EA-аналогов/Decimal/native PASS; полный EA-архив и поиск установлены, исходная159цель UNKNOWN.

- [139-eis-freshness-handoff.md](139-eis-freshness-handoff.md) — V51: single freshwaiter установлен; native handoff/5UI PASS, national UNKNOWN.
