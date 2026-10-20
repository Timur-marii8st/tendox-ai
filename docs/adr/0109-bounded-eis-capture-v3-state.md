# ADR-0109: Capture V3 с фрагментами обычных строк и отдельным состоянием

- **Статус:** ACCEPTED для контракта V3; реализация и actual capture не подтверждены.
- **Дата:** 2026-10-08.
- **Владелец:** root; независимый архитектурный review — Astra.
- **Контракт:** [capture V3](../eis/search/119-eis-capture-v3-contract.md).

## Контекст

Production query1 format V2 остановился с `ROW_EXCEEDS_SHARD_LIMIT` после
70 файлов/452345929 bytes; complete manifest отсутствует. Неуспешное evidence
и очистка приняты отдельно, происхождение полного corpus не установлено.
Поздняя READ ONLY REPEATABLE READ диагностика проверила до четырёх наиболее широких
raw rows каждого из 11 non-audit JSON relations: всего42кандидата, включая две
строки eis_223_lot_events. Для одной записи 223-ФЗ:
raw8204471B, exact canonical typed encoding10836001B. Это объясняет необходимость
деления обычных строк; диагностика не восстанавливает failed snapshot и не
доказывает глобальный encoded максимум.

Evidence: `nonaudit-encoded-width-v2.json`, SHA
`ba38663a8ad050a933dfb478ba29763a2c239b5cffc2e73bc19a55848e547507`,
DB T `2026-10-08T05:43:07.047852+00:00`, snapshot `113962:113962:`.
Все 11 relations измерены; выбранные raw bytes38085933. Private selected fields
передавались по SSH только для локального encoding; persisted отчёт содержит
scalars, typed PK и hashes. Это отдельная поздняя транзакция.

Verifier сохраняет полные audit bases и связи в SQLite. Его ambient `/tmp`
ограничен64MiB, а ранее наблюдённый aggregate linked audit basis уже71MB.
Actual query1 не достиг verifier: ENOSPC не наблюдался. Collector membership
SQLite и pending row — другие временные объекты, их нельзя считать покрытыми
квотой verifier или package payload.

## Решение

Ввести отдельный V3 с точным allowlist12relations и version-specific strict
discriminators. Audit raw32MiB, ordinary raw8MiB; fragmentable encoded row64MiB,
до восьми частей по8MiB. Small rows сохраняют canonical bytes; logical counts,
digest, tenant/PK/FK/audit semantics и exact file closure не ослабляются.
V1/V2 модели, планы, пути, результаты и значения limits сохраняются.

Явно разделить payload4GiB/512files, metadata16MiB, pending row64MiB,
collector membership main1GiB и verifier main8GiB. SQLite limits — fail-closed
candidate ceilings, не доказательство достаточности. JournalOFF/tempMEMORY и
проверенный внешний runtime pin обязательны для обоих SQLite пользователей.
Все ошибки завершают операцию без восстановления/повторного использования.

Verifier использует один заранее созданный RW bind file под RO parent/root,
операторский путь и runtime pin вне package. `/tmp64MiB`, RAM2GiB и прежние
timeouts сохраняются; compile options, effective PRAGMAs, полный mount set,
inode и swap policy проверяются. File bind/page limit не являются общей
квотой для произвольного кода. Controller сначала удаляет exact owned container
и подтверждает отсутствие, затем удаляет только проверенный host inode.

Disk admission учитывает отдельные transient ceilings и reserve по filesystem;
существующий package перед verifier уже отражён в free space. Это проверка
доступного места, а не резервирование против других host writers.

## Последствия и acceptance

До реализации обязательны независимое прочтение width evidence, actual isolated
file-bind sandbox и принятие точного [контракта](../eis/search/119-eis-capture-v3-contract.md).
Затем один ограниченный slice: два модуля, CLI, два новых V3 plans и unit/PG
tests. Controller adaptation и actual production capture — отдельные срезы.
Нужны golden V1/V2 parity, tamper/semantic controls, реальные большие ordinary
и audit rows, worst valid object graphs и фактические RAM/disk/tmp/cleanup
измерения в intended layout. Synthetic PASS не доказывает production fit.

Trusted corpus, origin, precision/recall/p95 остаются UNKNOWN до своих проверок.
Это решение не меняет поиск, ingestion, данные БД, grants или legal approvals.

## Уточнение реализации source6 — 2026-10-08

Addendum 2026-10-08, source6 candidate: production4 завершился INCOMPLETE с
generic OperationalError. Отдельный log window содержит FETCH timeout, но
не связывает его с backend снимка. Read-only EXPLAIN DECLARE для текущей
карточки44 показывает Sort над широким projection. Выбран ограниченный
V3-only SQL shape для `eis_notice_versions`: sorted PK subquery → correlated
LATERAL full payload lookup, оба с исходным tenant/selection, полный внешний
C-PK ORDER BY и OFFSET0 barriers. Наблюдавшийся план сортирует только ключи;
планировщик может выбрать другой план позднее, а больший estimated total cost
не является измеренным временем. Source review, same-snapshot old/new
cardinality/ordered-byte/RLS/Unicode/concurrency equivalence и intended-layout
PG check обязательны перед новым отдельно принятым capture.

Wire schemas,25relations,raw/encoded/physical limits, client prefetch и время
не меняются; V1/V2 и остальные24 V3 queries сохраняются. Отдельный client key
buffer не создаётся. Фиксированные V3 failure codes могут сообщать relation,
operation, sanitized driver SQLSTATE и заранее прочитанный backend ID без SQL,
params/DSN или post-fault diagnostic query. Причина прежнего отказа, actual
runtime, trusted corpus/origin и search metrics по-прежнему UNKNOWN.

## Альтернативы

Уточнение2026-10-08 для production6: после actual production5 global900s
timeout пользователь явно разрешил один полный snapshot при3600s capture,
RAM4GiB и ceilings16GiB/4096files. Это отдельный exact V3 ресурсный профиль,
описанный в [контракте](../eis/search/119-eis-capture-v3-contract.md#ресурсный-профиль-production6--2026-10-08).
V1/V2 и historical V3 не расширяются; rows/blocks/batches и scope неизменны.
Последовательные collector/verifier, fresh host-memory admission с1.5GiB
growth reserve, disk admission, согласованные deadline/controller/cleanup
budgets обязательны. Прежние actual evidence сохраняются с прежними budgets;
новые ceilings сами по себе не доказывают успешный рабочий снимок.

- Сохранить отказ V2 — допустимо до принятия и проверки V3.
- Расширить V2 задним числом — уничтожает его audit-only контракт.
- Обрезать строки/выбрать subset — нарушает полноту read closure.
- Поднять shard/RAM/tmp cap — не разделяет логические данные и служебное состояние.
- RW scratch directory без отдельного учёта — допускает неучтённые sidecars/spill.
