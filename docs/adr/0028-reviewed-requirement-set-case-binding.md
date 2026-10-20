# ADR-0028: reviewed requirement set и exact case binding

Дата: 2026-09-20  
Статус: Accepted for the local pilot

## Контекст

Документ приложения содержит 87 строк, но текущий deterministic mapper безопасно
нормализует только часть из них. AI review намеренно не создаёт исполнимые
`Requirement`, а sourcing без требований может искать лишь названия карточек.
Материализовать все строки как машинные условия означало бы скрыть неоднозначность
и превратить неполный разбор в допуск.

## Решение

Хранить source table как immutable proposal с полным непрерывным рядом entries.
Каждая entry содержит exact provenance и либо typed `Requirement`, либо состояние
`MANUAL_REVIEW_REQUIRED`. Независимый reviewer принимает одно решение по exact
proposal digest. `PASS` подтверждает полноту покрытия строк и проверку
нормализации, но не закрывает manual entries и не утверждает соответствие товара.

Только terminal `PASS` можно отдельной operator-операцией связать с существующей
версией кейса. Binding фиксирует proposal, decision и собственный SHA-256; reviewer
не может быть preparer или binder. Для `case_id + version` допускается один
append-only binding, автоматического выбора latest нет.

Sourcing использует только typed requirements связанного набора. Доказанный
mandatory `FAIL` исключает карточку, остальные условия и все manual entries
остаются открытыми. Общий technical status результата всегда `UNKNOWN` до exact
BOM и полного compliance review.

## Последствия

В пилоте решение принимает существующая изолированная роль
`COMPLETENESS_REVIEWER`; отдельная technical reviewer role может быть добавлена
после появления production RBAC/session boundary. Внешняя отправка RFQ, создание
КП, покупка и рекомендация `PARTICIPATE` этим решением не разрешаются.
