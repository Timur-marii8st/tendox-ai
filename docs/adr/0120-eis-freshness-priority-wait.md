# ADR 0120: один ожидающий запуск свежей загрузки ЕИС

Дата: 2026-10-26. Owner root. Статус: ACCEPTED_BOUNDED; host-only18:38UTC, ordinarycron/source/UI verified.
[Координация57](0057-eis-cooperative-source-lease.md),
[наблюдаемость71](0071-eis-shared-lease-observability.md),
[результат V51](../eis/search/139-eis-freshness-handoff.md).

## Контекст

В существующем часовом process-логе пять fresh44 BUSY совпали с ожиданием
`eis-import.lock` загрузчиком документов, уже владевшим `eis-priority.lock`.
Документы ждали 118–195 секунд. Fresh44 использовал неблокирующий priority lock
и терял cron tick. Ускорение source или изменение cadence этой причины не устраняет.
Это наблюдение процесса и подтверждённый порядок lock, не национальный benchmark.

Отказ от300s document wait отклонили: ADR57 ввёл его для сохранения прогресса
документов после полного atomic223window. Старый active24Oct sweep не продлевается,
пока свежие окна отстают; он также использует общий priority lock.

## Решение

Fresh44 сначала неблокирующе берёт свой `eis-freshness-dispatch.lock` на FD7.
Дубликат возвращает BUSY/75 без probe, marker и worker. Единственный владелец
затем ждёт priority FD8 до300s через background flock и interruptible shell wait.
INT/TERM handlers установлены до ожидания; exact child завершается и reaped
до освобождения dispatch. FD7 удерживается до завершения worker и owned cleanup.

Только после FD8 выполняются прежние актуальные readiness/proxy checks.
До владения FD8 `marker_owned=0`; timeout/interrupt/duplicate не меняют чужой hint.
Priority timeout возвращает `PRIORITY_LOCK_TIMEOUT`, без import phases/source.
Прежние import FD9 wait300, sourceworker, checkpoint/leases/budgets и source
validation сохраняются. Новых source retries, расписаний или scheduler нет.

Порядок fresh: dispatch7 → priority8 → import9. Documents и223 сохраняют свой
порядок. Два ожидания имеют суммарный timeout600s; это не полный wall-clock cap:
probe, startup, atomic tail и cleanup добавляют время. Flock не гарантирует FIFO.

## Последствия

Потерянный tick может дождаться handoff, а следующий tick coalesces. Worker
проверяет текущую работу под import lease; пропущенные ticks не становятся jobs
или подтверждёнными окнами. IDLE/BLOCKED/UNKNOWN не создают допуск.

54min/hour,180s source turn,223/reconciliation shares, pacing/TLS/robots,
SQL/resource/tenant guards и документы300s не ослабляются. Новый SOURCE/coverage
PASS из успешного процесса не выводится. Нужны actual source outcomes и
сопоставимые интервалы свежести, обе полосы и документы, cleanup без orphan.

## Альтернативы

Дополнительный cron без исправления lock сохраняет lost ticks. Неблокирующий
import у документов нарушает принятую защиту fairness. Неограниченная очередь
fresh waiters отклонена; отдельный private dispatch coalesces существующие ticks.
