# Запуск, пилот и эксплуатация

Локальный case — 16; PostgreSQL/API — 17; экран — 18; пилот — 20/21; сервер ЕИС — 28. Датированные measurements/rollout читать по нужному разделу, не считать старые counters текущими.

[Карта документации](../README.md) · [Текущий статус](../15-implementation-plan.md)

## Файлы

- [16-local-case-workflow.md](16-local-case-workflow.md) — Локальный расчёт кейса — S1.
- [17-storage-api.md](17-storage-api.md) — Хранение и API — S2.
- [18-first-screen.md](18-first-screen.md) — Первый экран внутреннего пилота — S3.
- [20-stabilization-pilot.md](20-stabilization-pilot.md) — Протокол пилотной проверки полного пользовательского сценария.
- [21-pilot-runbook.md](21-pilot-runbook.md) — Runbook пилотного прогона по серверному пути.
- [27-eis-index-operations.md](27-eis-index-operations.md) — Операционный запуск ограниченного индекса ЕИС.
- [28-eis-server-operations.md](28-eis-server-operations.md) — Сервер ограниченного индекса ЕИС.
- [29-eis-corpus-queue.md](29-eis-corpus-queue.md) — Большая очередь публичных данных ЕИС.
- [56-eis-refresh-measurements.md](56-eis-refresh-measurements.md) — S173: измерение регионального refresh 223-ФЗ.
- [57-eis-regional-runtime-reconciliation.md](57-eis-regional-runtime-reconciliation.md) — S174: сверка регионального runtime.
- [71-eis-fresh-gap-and-lag-census.md](71-eis-fresh-gap-and-lag-census.md) — S188 — фактические пропуски загрузки и свежесть 44-ФЗ.
- [73-eis-shared-lease-observability.md](73-eis-shared-lease-observability.md) — S190 — измерения общего доступа загрузчиков к ЕИС.
- [75-eis-recent-ingestion-report.md](75-eis-recent-ingestion-report.md) — S192 — прохождение свежих окон ЕИС в поисковый индекс.
- [82-eis-no-data-store-operations.md](82-eis-no-data-store-operations.md) — S199 — квота и lifecycle исходных ответов ЕИС.
- [114-reproducible-quality-gates.md](114-reproducible-quality-gates.md) — M1: воспроизводимый снимок, полная инвентаризация checks и изолированные PostgreSQL gates.
- [115-candidate-quality-workflow.md](115-candidate-quality-workflow.md) — M1: подготовительный runbook candidate-triggered quality gate, receipts и граница активации.
- [121-eis-production-readiness.md](121-eis-production-readiness.md) — диагностика NO_DATA 19 октября, исправление отчёта и условия готовности API.
- [122-eis-no-data-overflow.md](122-eis-no-data-overflow.md) — восстановление записи NO_DATA через второй ограниченный сегмент.

- [123-beta-shortlist.md](123-beta-shortlist.md) — acceptance и подготовка сквозной беты подбора закупок.

- [124-beta-invitations.md](124-beta-invitations.md) — B11: вход по приглашению, профиль/КП и изоляция компаний.
- [125-spec-remediation.md](125-spec-remediation.md) — сверка исходников с R4, точная маржа, owner confirmation и оптимизация чтения архивов.

- [126-backup-rotation.md](126-backup-rotation.md) — ежедневный проверенный дамп и безопасная ротация двух последних копий с сохранением исходной.
- [127-eis-223-selector.md](127-eis-223-selector.md) — Устранение SQL timeout выбора очередной партии 223-ФЗ.
- [130-eis-throughput-diagnosis.md](130-eis-throughput-diagnosis.md) — Транспортные сбои, стоимость пустых проверок и блокировка исторической загрузки.
- [131-eis-source-errors.md](131-eis-source-errors.md) — Доступ во время регламентных работ и сохранение безопасных кодов отказов.
- [132-eis-timeout-recovery.md](132-eis-timeout-recovery.md) — Проверка восстановления доступа, шесть новых закупок и HTTP search.
