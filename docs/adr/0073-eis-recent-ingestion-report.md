# ADR0073 — снимок прохождения свежих окон в индекс

Статус: DEPLOYED / VERIFIED BOUNDED INGESTION OBSERVATION. Дата решения: 2026-10-05.
Владелец: root. Зависимости: S191, `EisCorpusScope`, tenant RLS и canonical receipts.

## Контекст

Полное планирование диапазона не показывает, получил ли загрузчик ответ ЕИС,
сохранены ли карточки и есть ли их версии в поисковом индексе. После S191
нужно измерить эти этапы до изменения source concurrency или расписания загрузки.
S190 показал риск вручную составленных ключей: DEFAULT EF имеет legacy key.

## Решение

Добавить операторский `server-eis-ingestion-report.sh` и Python helper.
Использовать существующий API runtime без пересборки и миграции. Каждый отчёт
выполняется в одном tenant-scoped repeatable-read/read-only transaction;
оба режима проверяются. Statement timeout 30 s. Внешние source clients
не создаются. Диапазон — не более трёх завершённых дат MSK, 99 кандидатных
кодов и пять семейств; точные ключи берутся только из domain factory.

Каждое окно имеет одно состояние: canonical receipt, отсутствующее планирование,
отсутствующая попытка или категория последней попытки из существующего gap policy.
Только `LEGACY_CANONICAL` подтверждает canonical. `NO_DATA`, транспорт и даже
`SYNCED` без receipt не считаются canonical. Ранее сохранённый canonical receipt
не исчезает при последней неудачной попытке обновления.

Метаданные включают attempt ID/UTC/source SHA, earliest canonical receipt UTC/SHA,
число сохранённых версий, число соответствующих lexical-v1 записей и событий.
Index join связан tenant + purchase number + version number. Два отчёта одного
scope сравниваются по exact keys: первые попытки, смена latest attempt,
переходы canonical, регрессии и приращение версий/индекса/событий. Это наблюдения
между снимками; из них нельзя выводить число source HTTP calls или национальную SLA.

Immutable proof создаётся с private mode 0600 под UUID на VPS. Stdout содержит
ограниченные итоги по дате/семейству и digest, без карточек/XML/ZIP/URL/секретов.
Неверный режим транзакции, scope, future timestamp или противоречивые счётчики
блокируют отчёт. Ошибка CLI содержит только фиксированный reason.

## Последствия и ограничения

Не требуется дополнительных source запросов или локального хранения архивов.
Read-only snapshot не меняет очередь, историю попыток, source policy и budgets.
Диагностический SQL использует bounded keys, но может читать таблицы для поиска
соответствующих записей; timeout является пределом отдельного statement.

Паритет lexical rows не доказывает качество токенов, eligibility latest version,
отсутствие source hold, актуальность deadline, полноту документов или выгодность.
События отмены хранятся отдельно и не должны создавать версии извещений.
Версия, первоначально сохранённая из другого окна, остаётся привязана к своему
immutable origin; счётчик выбранного окна не равен размеру ответа ЕИС.
99 кодов — candidate requests, реестр регионов и полнота остаются UNKNOWN.

## Проверка

27 синтетических regression tests PASS на Windows и Linux; Linux gate имеет
network none, 2 CPU / 2 GiB, без source credentials/volumes. Ruff/mypy PASS.
Live baseline: 06:49:46 UTC, exact 1485 keys, 374 canonical, 1046 NO_DATA,
65 unattempted; 6487 stored versions / 6487 lexical rows, 177 events.
Evidence и итоговая обычная cron observation — [docs75](../operations/75-eis-recent-ingestion-report.md).

Live final 07:05:40 UTC, same exact scope: 375 canonical/1069 NO_DATA/41 unattempted,
6488 versions/6488 lexical rows/177 events. За954s:24 first attempts,
23 UNATTEMPTED->NO_DATA/1->CANONICAL, regressions0, +1version/+1index.
Shared lease horizon includes23runs/21complete/2censored; incomplete capacity UNKNOWN.
Ручных source запросов нет; диагностика DBwrites0. Script-only atomic deploy9,
host23/API2 hashes PASS, source cron unchanged. Исходный interval включает
хвост прохода до baseline; attribution всего прироста одному run не утверждается.

## Альтернативы

Повторный общий census не различает этапы одного свежего cohort.
Дополнительный ручной source проход смешивает диагностику с изменением нагрузки.
Новый API/UI endpoint увеличивает release scope; сначала достаточно проверяемого
операторского отчёта, затем его контракт можно использовать в интерфейсе.
