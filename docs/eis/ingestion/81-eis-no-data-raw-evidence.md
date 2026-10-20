# S198 — исходные ответы NO_DATA и повторный разбор

Статус: завершён 2026-10-05; установлен на VPS и проверен обычным cron.
Владелец: root; самостоятельная реализация и review. Контракт: PRD, ADR0079,
инварианты AGENTS.md и S197. Это evidence slice для 44-ФЗ, не полный охват ЕИС.

## Что сохраняем

Только проверенный ответ PROD / IP / BY_REGION / NO_DATA. Сохраняются исходные
байты SOAP, SHA-256 и типизированный manifest: tenant, window key, actor, request
и response UUID, время наблюдения и исходное время ответа. Неоднозначная timezone
источника остаётся UNKNOWN_TZ. Тело запроса и токен не сохраняются. Отражение
токена проверяется в обычном, HTML/XML decoded и объединённом XML-тексте;
непустой SOAP Header, DTD, чужой request ID и неподходящий режим отклоняются.
Проверки не заменяют универсальный поиск любых возможных секретов.

Хранилище SQLite находится на VPS в persistent browser volume:
`/var/lib/eis-browser/no-data-evidence/no-data.sqlite3`. По умолчанию путь следует
за EIS_BROWSER_STATE_DIR; EIS_NO_DATA_EVIDENCE_DIR задаёт override, пустое значение
отключает retention. В окружении без этих настроек retention отключён.
Каталог0700 / файл0600, symlink path отклоняется. Тело и manifest записываются
одной транзакцией. Уникальность tenant/window/SHA возвращает первый immutable
manifest при повторе; новая попытка получает отдельный audit event.

## Ограничения ресурсов и состояния

- Ответ <=64KiB, manifest <=16KiB.
- Payload (тела + manifests) <=96MiB, <=65536 записей на весь store.
- SQLite DB <=128MiB; rollback journal — дополнительный временный файл.
- SQLite cache около1MiB, timeout блокировки1s, DELETE journal и FULL synchronous.
- Автоматического удаления или вытеснения нет. Новая запись при квоте получает
  FAILED/QUOTA_REACHED; валидный NO_DATA остаётся UNKNOWN и загрузчик продолжает.
- RETAINED и FAILED записываются tenant-scoped событием
  EIS_NO_DATA_RESPONSE_EVIDENCE. Отказ audit обозначается отдельно в результате
  sync, без ложного утверждения о записанном evidence.

Лимит страниц проверяется по фактически возвращённому значению PRAGMA;
[SQLite max_page_count](https://www.sqlite.org/pragma.html#pragma_max_page_count).
Rollback journal обеспечивает откат незавершённой транзакции и обычно удаляется
после commit/rollback: [официальное описание SQLite](https://www.sqlite.org/tempfiles.html).
128MiB — лимит DB, не суммарный пик диска с journal. Изменять старые записи
запрещают triggers; digest и повторный parser выявляют изменение содержимого.

## Проверка без запроса в ЕИС

Из каталога проекта на VPS:

```bash
bash scripts/server-eis-no-data-evidence-report.sh --since 2026-10-05T12:00:00+00:00 --limit 20
```

Начало периода timezone-aware, не старше7дней. Tenant фиксирован
local-eis-supplier. PostgreSQL snapshot REPEATABLE READ / READ ONLY, SQL30s,
SQLite открыт read-only. <=20 последних retained audit events. Для каждого:
manifest/raw SHA, повторный parser, request/response IDs и manifest проверяются;
затем ищется NO_DATA attempt с тем же tenant/window/actor/SHA после audit.
Отсутствующая запись — UNKNOWN; испорченный артефакт — FAIL. PASS означает только
совпадение сохранённого ответа с parser и manifest. Это не доказательство
отсутствия закупок и не независимое подтверждение источника.

Приватный UUID JSON <=1MiB сохраняется в research/rejected, stdout содержит только
агрегаты, путь и SHA, без raw XML. Diagnostic: source requests0 / DB writes0;
обычные фоновые загрузчики продолжают работу.

## Проверки и установка

222 теста PASS на Linux/VPS с isolated PostgreSQL, 2026-10-05T12:31:53Z.
Проверены tenant/RLS, exact bytes, reflection, размеры, quota, rollback, конкуренция,
busy, immutable/tamper, audit failures, serializable CLI, offline audit/journal
binding и совместимость _parsed_post с 223-ФЗ. Тестовые credentials и persistent
production paths отключены; тестовая БД удалена. Ruff/mypy PASS.

Runtime overlay содержит три проверенных модуля; зависимости, cron, source budget,
схема и UI не меняются. Установка под существующими source leases, с backup,
health/hash gates и rollback на S197. Обычный cron должен дать реальные артефакты;
до этого live acceptance не завершён.

Следующий slice: ограниченный lifecycle/операторский контроль evidence quota и
независимое подтверждение спорных NO_DATA. Исторический backlog, свежесть по всем
источникам и полный охват ЕИС остаются UNKNOWN.

S198 deployed2026-10-05T12:43:14Z:atomic13/host35/API5/worker5SHA PASS;
base images pinned S197, three-module network-none overlay. BackupSHA
 e8cb9394b2b9d9c5a83ee55e932ed82b6c781cca1a14887027aae05357ca9e90.
Cutover12:43:08.752311UTC:existingevidence0/storeabsent;
proofSHA2a53b1c26c738ea560673751122347c17d0daa4a9fb2db3ffd2bfd8a717bdcc3.
APIsha256:bc8e55852b9e9edc39881e7dedc62088255027226e246864653e5459cc3147d9;
workersha256:23987c6f3b8a0c074b35f6213862fad6f8d6504ee44df8ffd83e52943e59255b.
Ops12:43:30UTC:health200/HEAD03/testDBnone/DB4366883863/free258433990656bytes,
markersfalse, ordinary background cron intact. OpsSHA
4dc23fbe299e0a23aa32b1396f3b299e90cb37e1cd434b2df6ff09f63782e885.
Live raw/audit/journal verification remains pending. Source absence/fullEISUNKNOWN.

## Live acceptance — завершено

Обычный cron после cutover дал4 retained ответа, без FAILED retention на момент
2026-10-05T12:46:11.771737Z. Offline report проверил4/4 raw reparse и4/4 совпадения
с tenant audit/journal SHA/actor/window/time. Source requests0 / DB writes0 у
проверяющего инструмента; фоновые загрузчики продолжали обычную работу.
Proof: `/var/lib/eis-browser/research/rejected/s198-offline-replies-e1bc406a-4aea-4616-99aa-0663c656448b.json`.
SHA256: `2fdc6830f45cf18875bcd00055df761aa1d7a909e660bf8a2ffba9dd05a84650`.
Предыдущий snapshot12:44:42 имел0events; это последовательные snapshots, не сумма.

Store12:46:22UTC:4records, payload5169bytes, DB28672bytes; каждое исходное SOAP
тело623bytes, root0700/DB0600, journal отсутствовал на момент наблюдения.
SQLusage/count/sum паритет PASS, SQLite read-only. Metadata proof:
`/var/lib/eis-browser/research/rejected/s198-store-14010795-63da-4d1b-bcf7-6c287fb00b46.json`;
SHA256 `a126bbdd7bc8fe469c89fcf6e4108ccfa3ab20b29020c718d2ffc90349bc40f0`.
Значения4 не являются количеством всех пустых окон или исторической полнотой.

S198 завершён в описанных границах:222testsPASS + pinned deploy + real ordinary
cron + offline raw/audit/journal match. Runtime frozen после проверок; финальная
docs-only установка сохраняет35host/5API/5worker hashes и прежние cron/resources.
Независимое подтверждение отсутствия/полный охват ЕИС/общая freshness UNKNOWN.
Следующий S199: bounded operator quota/lifecycle для новых evidence, затем
отдельный контракт независимого подтверждения NO_DATA; не объявлять окна complete
по сохранённому пустому ответу.
