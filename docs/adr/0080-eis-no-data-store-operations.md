# ADR0080 — операторский контроль bounded evidence store

Дата/effective:2026-10-05. Статус: принято и установлено13:31:47UTC. Owner root.

## Контекст

S198 ограничивает store, но одной проверки последних20ответов недостаточно для
обнаружения исчерпания квоты и пропуска audit. Сохранённые ссылки immutable;
автоматическое удаление разрушает offline verification старых audit.

## Решение

Source-free operator report: global headroom/tenant-only age, bounded metadata
parity и PG audit failures/missing capture. Состояния PASS/FAIL/UNKNOWN не описывают
полноту ЕИС. Каждая metric принадлежит указанному tenant/snapshot; global только
ресурсные counters без чужих identities. SQLite RO и PG RR/RO независимы по времени.
<=128MiB/65536rows/2sSQLite;7дней/30sSQL/10failure samples/1MiBprivate proof.

Операционные пороги:80% любой квоты либо tenant record>=30дней требуют PLAN_ARCHIVE;
FAILED/missing audit — INVESTIGATE_FAILURES; неизвестный/повреждённый store —
RESTORE_VISIBILITY. Причины и headroom сохранены в typed proof. Это policy данного
ADR, не юридическое правило и не TTL. Никаких удаления/eviction/новых sourcecalls.
Для будущего удаления нужны проверенный архив и сохранение разрешения audit refs.

## Acceptance и последствия

48testsPASS Linux/isolatedPG, Ruff/mypyPASS. Host-only scripts, frozenS198runtime,
cron/schema/budget unchanged. Live report с фактическими counters обязателен.
Нет автомониторинга и автоматической оценки времени до заполнения. Оператор
получает воспроизводимые основания для дальнейшего управления хранением.
Scope/results: [docs82](../operations/82-eis-no-data-store-operations.md).

Real report:112records/278528DBbytes/FAILED0/missingcapture0; metadataPASS,
OBSERVE. Receipts и SHA — docs82. Runtime/source budget unchanged.
