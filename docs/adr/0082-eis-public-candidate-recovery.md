# ADR0082 — ограниченное восстановление public candidates по номеру

Дата:2026-10-05. Owner:root. Решение принято; bounded live acceptance завершён (docs84).

## Причина

S200 обнаружил23 публичных номера без tenant indexed versions. Национальная
публичная страница другого document/region scope не доказывает ошибку NO_DATA.
Нужна фактическая адресная загрузка и доказательство результата intake.

## Решение

Host-only операторный batch проверяет неизменённый report/DOM/SOAP binding и
делает<=3 exact-number запросов через прежний worker transport и global lease.
URL routes используются для выбора, XML admission полностью прежний. Транспортный
observer считает попытки и сохраняет полный связанный отвергнутый набор через
существующий retention contract, не подменяя функции intake.

Only usable latest exact version queues documents. Typed proof/audit отдельно
показывают canonical after state, удержание источника и ошибки очереди. Network
allowance180с не называется гарантией полного wall time; whole-response transport
не называется streaming byte limit. Публичный first-page scope сохраняется.

## Последствия

Можно восстановить пропущенные номера без повторного массового обхода. Нельзя
объявить полный охват, допуск поставщика, актуальность исторической закупки или
считать URL доказательством поддержанного XML. Auto recovery schedule, semantic
admission unsupported methods и полный reestr scan остаются отдельными этапами.
