# ЕИС: получение и сохранение данных

Выбирать контракт семейства/версии или нужный runtime механизм. Начальный source contract — ADR-0044; правила variants/holds и свежести имеют отдельные ADR. Охват корпуса остаётся UNKNOWN без собственного evidence.

[Карта документации](../../README.md) · [Текущий статус](../../15-implementation-plan.md)

## Файлы


- [35-eis-document-catalog.md](35-eis-document-catalog.md) — Официальный каталог типов документов ЕИС.
- [37-eis-223-notices.md](37-eis-223-notices.md) — Отдельный reader извещений 223-ФЗ.
- [38-eis-223-families.md](38-eis-223-families.md) — Проверка дополнительных семейств 223-ФЗ.
- [43-eis-attachment-limit-review.md](43-eis-attachment-limit-review.md) — Review лимита метаданных вложений ЕИС.
- [44-eis-corpus-transport.md](44-eis-corpus-transport.md) — Transport lifecycle for a bounded EIS corpus pass.
- [45-eis-corpus-fairness.md](45-eis-corpus-fairness.md) — Fair retry lane for the EIS corpus queue.
- [46-eis-corpus-selection-performance.md](46-eis-corpus-selection-performance.md) — EIS corpus historical queue selection.
- [47-eis-223-general-notice-contract.md](47-eis-223-general-notice-contract.md) — Следующее общее семейство 223-ФЗ: purchaseNotice.
- [48-eis-general-223-implementation.md](48-eis-general-223-implementation.md) — S169: последовательный rollout purchaseNotice.
- [49-eis-general-223-retained-validation.md](49-eis-general-223-retained-validation.md) — S169: повторная проверка сохранённой выборки purchaseNotice.
- [50-eis-223-cancellation-contract.md](50-eis-223-cancellation-contract.md) — S170: контракт источника отмен223-ФЗ.
- [51-eis-223-cancellation-implementation.md](51-eis-223-cancellation-implementation.md) — S170: evidence whole-purchase cancellation 223-ФЗ.
- [52-eis-223-lot-cancellation-contract.md](52-eis-223-lot-cancellation-contract.md) — S171 M1: официальный контракт отмены лотов 223-ФЗ.
- [53-eis-223-lot-cancellation-implementation.md](53-eis-223-lot-cancellation-implementation.md) — S171: отдельные лоты — план реализации и high-risk review.
- [54-eis-223-regional-contract.md](54-eis-223-regional-contract.md) — S172: контракт регионального охвата getDocsIP / RI223.
- [55-eis-223-regional-implementation.md](55-eis-223-regional-implementation.md) — S172 — parameterized regional loader и измеримый backlog.
- [58-eis-duplicate-window-investigation.md](58-eis-duplicate-window-investigation.md) — S175: исследование незавершённых окон.
- [59-eis-223-wide-window.md](59-eis-223-wide-window.md) — S176 — полное окно из четырёх архивов 223-ФЗ.
- [60-eis-44-version-contract-research.md](60-eis-44-version-contract-research.md) — S177: идентичность и версия извещения44-ФЗ.
- [61-eis-44-conflict-diagnosis.md](61-eis-44-conflict-diagnosis.md) — S177: диагностика конфликтов 44-ФЗ.
- [62-eis-44-notice-variant-ledger.md](62-eis-44-notice-variant-ledger.md) — S178: реестр вариантов извещения 44-ФЗ, milestone 1.
- [63-eis-44-consumer-variant-hold.md](63-eis-44-consumer-variant-hold.md) — S179: общий hold evidence-only вариантов44.
- [64-eis-44-retained-projection.md](64-eis-44-retained-projection.md) — S180 M1 — полный транспорт44 и явная проекция карточек.
- [65-eis-44-automatic-partial-intake.md](65-eis-44-automatic-partial-intake.md) — S180 M2 — автоматическая обработка конфликтных окон44.
- [66-eis-gap-census-and-source-retry.md](66-eis-gap-census-and-source-retry.md) — S181 — сверка очереди ЕИС и повторы старых сбоев связи.
- [67-eis-attachment-recovery.md](67-eis-attachment-recovery.md) — S182 — восстановление старых отказов по количеству вложений.
- [68-eis-parser-gap-diagnostics.md](68-eis-parser-gap-diagnostics.md) — S184 — диагностика отказов parser и исходные названия документов.
- [72-eis-national-daily-scheduling.md](72-eis-national-daily-scheduling.md) — S189 — ежедневные пять типов процедур и защита старой очереди.
- [74-eis-durable-planning-retry.md](74-eis-durable-planning-retry.md) — S191 — повторяемое планирование завершённых дат.
- [76-eis-fresh-first-attempt-share.md](76-eis-fresh-first-attempt-share.md) — S193 — первая обработка свежих окон.
- [77-eis-corpus-bounded-continuation.md](77-eis-corpus-bounded-continuation.md) — S194 — продолжение corpus после приоритетного обновления.
- [78-eis-recent-no-data-rechecks.md](78-eis-recent-no-data-rechecks.md) — S195 — повторная проверка недавних пустых ответов ЕИС.
- [79-eis-no-data-aging-evidence.md](79-eis-no-data-aging-evidence.md) — S196 — возраст пустых окон и доказательства ответов ЕИС.
- [80-eis-older-no-data-reserve.md](80-eis-older-no-data-reserve.md) — S197 — старые пустые окна получают раннюю повторную проверку.
- [81-eis-no-data-raw-evidence.md](81-eis-no-data-raw-evidence.md) — S198 — исходные ответы NO_DATA и повторный разбор.
- [83-eis-no-data-public-cross-check.md](83-eis-no-data-public-cross-check.md) — S200 — сверка NO_DATA через публичную выдачу ЕИС.
- [84-eis-public-candidate-recovery.md](84-eis-public-candidate-recovery.md) — S201 — адресная загрузка кандидатов публичной выдачи.
- [85-eis-mixed-number-archives.md](85-eis-mixed-number-archives.md) — S202 — смешанные адресные архивы ЕИС.

- [120-eis-national-coverage.md](120-eis-national-coverage.md) — Национальный приоритет, production census и закрытие фактических пробелов.
- [134-eis-ezk-final-companion.md](134-eis-ezk-final-companion.md) — V46: полный адресный архив извещения ЭЗК с итоговым протоколом, сохранение source и проверка поиска.

- [137-eis-completeness-recovery.md](137-eis-completeness-recovery.md) — V49: свежий census44/223, официальная сверка и восстановление полноты; в работе.
- [138-eis-drug-positions.md](138-eis-drug-positions.md) — V50: 26 лекарственных позиций из retained XML; installed bounded PASS.

- [140-eis-223-regular-kesmbo.md](140-eis-223-regular-kesmbo.md) — V52: региональный KESMBO установлен; native312/UI/49штатных окон, bounded PASS.

- [141-eis-kes-five-live.md](141-eis-kes-five-live.md) — V53: пять разных штатных KES архивов, native/mainHTTP/actualUI5, bounded PASS.

- [142-eis-223-regular-zpesmbo.md](142-eis-223-regular-zpesmbo.md) — V54: подтверждённый unsupported ZP, source0 и контракт регулярного потока.

- [V55: позиции совместных закупок223](143-eis-223-joint-positions.md) — installed joint2/control1 и review PASS.

- [V56: сохранённый корпус ZP и joint backfill](144-eis-223-joint-backfill.md) —135native XML, source0 repair и fiveHTTP/UI приняты bounded.

- [V57: полный зафиксированный ZP corpus в поиске](145-eis-zp-corpus-search.md) —135mainAPI/287nativeitems, bounded review PASS.

- [V58: свежий census44/223](146-eis-completeness-census.md) — 6drug/14позиций восстановлены; HTTP/UI6 и review PASS,106joint далее.

- [V59: joint general/KES/AES](147-eis-223-joint-families.md) —106 позиций/6 карточек установлены, приёмка PASS_BOUNDED.

- [V60: текущий census и распределение очереди](148-eis-national-census-v60.md) — 44/223 и наблюдение одного часа, national UNKNOWN.
- [V61: первое ожидание corpus](149-eis-corpus-initial-wait.md) — host установлен без обхода fresh guards; cron evidence PENDING.
- [V62: ограниченный исторический turn](150-eis-historical-bounded-turn.md) — локальная основа учёта, source0; policy ещё не включена.

- [151-gosplan-discovery-slice.md](151-gosplan-discovery-slice.md) — Локальный адаптер ГосПлана, границы и оставшаяся интеграция.
