# ADR0079 — bounded raw NO_DATA evidence

Дата: 2026-10-05. Статус: принято и установлено; real cron/offline binding PASS.
Owner root; самостоятельный review; зависимости S197/существующий audit schema.

## Контекст

Hash NO_DATA без исходных байтов не позволяет повторить parser. Повтор того же
источника не является независимой проверкой отсутствия данных. Нужен проверяемый
артефакт в пределах ресурсов VPS и tenant-scoped audit без хранения запроса/токена.

## Решение

Сохранять только валидный PROD IP BY_REGION NO_DATA: exact bytes + typed manifest
атомарно в отдельном SQLite store. Tenant/window/SHA образуют immutable identity;
replay возвращает первый manifest. Audit нового наблюдения append-only в PostgreSQL.
Ограничения:64KiB ответ/16KiB manifest/96MiB payload/65536records/128MiB DB/1s lock.
Journal DELETE, FULL synchronous, private permissions и отказ от symlink paths.

Лимит DB проверяется через [max_page_count](https://www.sqlite.org/pragma.html#pragma_max_page_count).
[Rollback journal](https://www.sqlite.org/tempfiles.html) занимает дополнительный
временный диск;128MiB не означает лимит общей файловой footprint. Нет eviction.
Quota/IO/unsafe failure получает typed FAILED и audit, источник остаётся NO_DATA /
UNKNOWN. Отдельный отказ audit обозначается FAILED в scalar sync result.

Offline report читает PG RR/RO и SQLite RO, reparse + hash/manifest binding + exact
journal tenant/window/actor/SHA/time; максимум20events/7дней. PASS только для
совпадения артефакта, coverage/source absence/independent corroboration UNKNOWN.
Новая запись не создаёт canonical receipt, index row или завершённое окно.

## Acceptance и последствия

222 Linux/PG теста PASS12:31:53UTC. Сохранена общая _parsed_post совместимость223,
source requests не добавляются. Для live acceptance требуется обычный cron и
ненулевые raw/audit/journal matches. Схема/cron/sourcebudget/UI без изменений.
Политика очистки и независимое подтверждение — последующие bounded slices.
Детали и deploy evidence: [docs81](../eis/ingestion/81-eis-no-data-raw-evidence.md).

Live acceptance:4/4raw reparse и4/4audit/journal binding12:46:11UTC;
bounded store28672bytes. Полные receipts/checksums — docs81.
