# ADR0084 — исторические факты отдельных протоколов

Дата 2026-10-05. Owner root; review Astra. Решение принято и реализовано на VPS.

## Контекст

S202 сохранил 13 companion XML, но только их метаданные. Цель продукта — сравнивать
конкуренцию и выгоду с source evidence. Номер закупки сам по себе не связывает
протокол с конкретной версией извещения; распределительные строки не являются
независимыми поставщиками. В сохранённых наборах есть повторные application IDs.

## Решение

Первый bounded slice читает три семейства из immutable canonical ZIP по tenant
и exact выбранному извещению. Typed per-document факты, indexed locators и SHA.
Связь с версией извещения UNKNOWN; protocol/foundation/lot identifiers отдельны.
Не объединять документы и не выбирать latest по revision/createDate.

Считать только представленные строки и уникальные IDs при однозначности;
supplier identity/total submitted bidders UNKNOWN. Сохранять явные Decimal суммы,
right-to-contract flag, ранги и коды. Currency/tax, signed contract/current stage,
probability/profit/participation UNKNOWN. Existing hard gates не меняются.

Read-only authenticated API, без сети ЕИС/новой таблицы/cache/схемы/расписания.
Жёсткие SQL/ZIP/XML/row/name/output caps; no DTD/entities и UTF-8 only до parse.
Точные лимиты, XSD provenance и live acceptance: [docs86](../eis/search/86-eis-historical-protocol-facts.md).

## Последствия и альтернативы

Пользователь получает проверяемые исторические факты без выдуманного прогноза.
Повторный запрос разбирает ограниченный сохранённый набор; фоновой массовой
проекции и дешёвого history-summary cache пока нет. Не менять общий поиск ради
разбора XML всех кандидатов. Следующая агрегация требует явных критериев связи
и сопоставимости; XML revisions и НМЦК не заменяют эти критерии.

Альтернативы «считать все строки конкурентами», «rank1 означает контракт» и
«первый вложенный money — цена» отвергнуты: они дают ложные факты.

Acceptance:158 Linux/isolatedPG testsPASS, five review findings closed;
source0 direct/API9 real documents, repeated38 application rows remain UNKNOWN
for represented applications. HTTP70–177ms for3 cached refs in one loopback run;
expiredFAIL remains, no source calls/mutations/new schema. Proofs: docs86.
