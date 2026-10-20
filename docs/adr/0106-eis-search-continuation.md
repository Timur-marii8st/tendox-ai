# ADR0106 — продолжение поиска в сохранённой ЕИС

Дата: 2026-10-07. Статус: accepted; production INSTALLED.
Владелец root; реализация ограничена read-only search.

## Контекст

`eis-index` и `eis-223-index` считают все совпадения, но возвращают только
верхние 100. Переключение десяти строк в браузере не открывает остальные
совпадения. Между страницами импортируются версии, события и результаты
проверки источников; обычный offset может пропустить/повторить запись либо
скрыть новую отмену. Контракт корпуса: [план полного поиска](../eis/search/26-eis-full-corpus-plan.md).

## Решение

Опциональный `page_size=1..100` включает stateless continuation. Без него
старые вызовы сохраняют прежние верхние 100. Ответ содержит `next_cursor`,
`snapshot_at` и `page_snapshot_sha256`; последняя страница имеет null cursor.

Cursor связывает authenticated tenant, закон, точный query, search scope,
версию порядка, aware clock первого запроса, SHA полного потока совпадений
и последнюю позицию сортировки. Порядок существующий; Decimal сохраняется
строкой. Непагинированные внутренние вызовы остаются совместимыми.

Для continuation последние версии выбираются среди импортов до snapshot_at.
Последующие публикации/версии не дописываются в старую выдачу; нужен новый
поиск. При каждой странице заново читается live evidence отмен, holds и
schema quality. Изменение состава/evidence выдаёт `SEARCH_PAGE_CHANGED` (409),
истечение 15 минут — `SEARCH_PAGE_EXPIRED` (410), несоответствующий cursor —
422. Браузер не смешивает эти результаты и сохраняет уже видимые строки.
Устаревший async ответ от предыдущего поиска не попадает в новую выдачу.

Cursor не является approval или credential, не подписывается и не выдаёт
доступ: tenant берётся только из bearer authentication, контекст и SHA
пересчитываются, boundary обязан присутствовать в текущем matching stream.
Выбор другой допустимой границы внутри собственной выдачи не расширяет
права. Persisted cursor/session и новые таблицы не вводятся; чтение выполняется
в tenant-scoped REPEATABLE READ READ ONLY transaction.

## Последствия

В установленной версии каждая страница заново сравнивает полный matching
stream; transient память включает страницу и batch. Клиент хранит
загруженные страницы, отображает до десяти строк и явно отделяет локальную
страницу от загрузки следующих записей. Схемы/фильтры считают только полученные
записи. Полнота всей ЕИС и анализ документов не выводятся из исчерпания cursor.
Допуск, КП, экономика и exact-notice проверки действий сохраняют свои gates.

## Альтернативы

- Offset без согласованного evidence отвергнут из-за изменяемого порядка.
- Persisted snapshot/session и новый cleanup workflow избыточны для этого среза.
- Возврат всего корпуса одним ответом снимает ограничение памяти и payload.

Acceptance и PostgreSQL/production-read evidence:
[продолжение и сверка охвата](../eis/search/113-eis-search-continuation.md).

## Локальный срез повторного сравнения — 2026-10-09

Статус: проверка кандидата; **не установлен**. Существующий cursor и таблицы
не меняются. Process-local memo хранит только immutable JSON bytes результатов
сравнения: до 32 MiB retained payload, 128 batch entries, TTL 15 минут, LRU.
Ключ связывает tenant, закон, exact query, snapshot clock, полные текущие
notice bytes и применимые состояния/источники. Transient serialization, typed
objects, SQL buffers и Python overhead дополнительно расходуют память; 32 MiB
не является лимитом RSS. При expiry/eviction/oversize и в другом worker выполняется
полное сравнение; данные не урезаются.

Каждая страница продолжает читать все SQL batches и свежие holds/events/schema
checks, проверять provenance, порядок и fingerprint. Изменение evidence сохраняет
SEARCH_PAGE_CHANGED. Cached base comparisons 223 не кэшируют live events/schema.
Счётчики visited и newly compared/reused разделены. Конкурирующие miss могут
повторить вычисление; отдельный persisted cache/cleanup workflow не вводится.

Real-PG: 126 PASS/0 skip по четырём существующим группам; после добавления двух
late-223-event/schema-after-cache регрессий повторена затронутая группа:
93 PASS/0 skip (остальные 35 тестов не менялись). Unit 79 PASS. Это diagnostic
проверки, не receipt нового release и не production установка. На сохранённом
production6 корпусе 223: 216 совпадений; три страницы имеют прежние состав, порядок
и fingerprint, страницы 2–3 compared=0/reused=216. Измерение задержки не показало
заметного выигрыша; SQL, parsing и fingerprint всё ещё выполняются полностью.
Evidence: `tmp/improvement-program/m2/overnight-20261009-v1/03-pagination`
в основном checkout; результаты 44 и ресурсные ограничения фиксируются
в тематическом [отчёте](../eis/search/113-eis-search-continuation.md).
