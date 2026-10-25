# ADR-0111 — защищённая обработка недавних суточных пропусков ЕИС

Дата: 2026-10-22. Статус: INSTALLED22Oct17:25МСК; R1b20:18МСК, bounded44/223 live PASS.

## Контекст

Постоянный fresh demand вытесняет RECONCILE_DAY и OUTAGE_RECOVERY.
Census22Oct16:12МСК показывает3canonical/492unattempted суточных окон44 за21Oct
в candidate-code scope99×5; это не процент национальной полноты.
Прежняя recovery admission доля60s/law/hour не обеспечивает приоритет суточных
пропусков, а снятие общего ограничения нарушило бы source/resource envelope.

## Решение

Opt-in EIS_RECONCILIATION_SHARE_ENABLED=1 выделяет360s/law/hour фактической
обработки последних3завершённых дней в существующем3240s joint start budget.
Current requests сохраняют remaining protected shares только при известном due
completed-day debt. Atomic180s tail, import lease, последовательный transport,
source pacing и resource gates сохраняются. После исчерпания доли возвращается
fresh priority; history получает остаток. Не начатое окно не подтверждается.

44 использует bounded exact-coordinate read, не весь ledger;223 фильтрует
accepted official catalog. Новые планы создаются только under lease перед
capture. Process crash консервативно списывает reservation; существующий формат
учёта и tenant binding сохраняются. Неверные/неполные данные не становятся PASS.

## Последствия

Это гарантия защищённого допуска при работающем scheduler и доступном источнике,
не SYNCED, SLA или полнота ЕИС. Временные ограничения источника и ошибки могут
сохранить пропуск. Fresh headroom уменьшается на занятую долю; net backlog,
source-to-search lag и каждое окно должны быть измерены после exact rollout.
NO_DATA остаётся наблюдением с provenance. Контрольные rechecks не отключаются.

Альтернативы: повысить cron frequency (не устраняет preemption), снять бюджеты
(нарушает envelope), считать NO_DATA завершённой полнотой (ложный PASS).
Откат — прежний worker image/config; schema/API/WEB и data не меняются.
