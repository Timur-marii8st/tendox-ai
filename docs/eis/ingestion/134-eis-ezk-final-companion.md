# V46 — извещение ЭЗК с итоговым протоколом

Владелец root, 26 октября 2026. Установлен после точного approval пользователя;
реальный импорт и основной HTTP поиск PASS в границах V46.
Evidence: `tmp/eis-ezk-final-20261026-v46/`.

## Проверяемый результат и контракт

Полный адресный архив `getDocsIP/PRIZ/by-number/<number>` допускает
`epProtocolEZK2020Final` как metadata-only companion. Сохраняются исходные ZIP,
XML, SOAP response SHA, source URL, tenant и audit. Неизвестный документ,
чужой номер, неверный namespace или дубликат блокируют весь набор.
Датированные окна не расширяются. Семантика протокола не становится
подтверждённой ценой, действующим этапом или разрешением участвовать.

Контракт расширяет [S202](85-eis-mixed-number-archives.md), используя те же
проверки direct-child `EPtypes/commonInfo/purchaseNumber` и `publishDTInEIS`.
Identity — SHA исходного XML; отсутствующая/неaware дата остаётся UNKNOWN.
Протокол не перекрывает отмену или истёкший deadline.

Основание — официальный пакет ЕИС16.3, id44404, SHA
`4313b235fcfbce1e32a610cdef1f68449d23de617c15fd7487bad8cb933d86d7`.
`fcsExport.xsd` объявляет family `epProtocolEZK2020Final` с типом
`ep:protocolEZK2020FinalType`, наследующим `protocol2020Type`.
Полный пакет получен из сохранённого server evidence; запросов к ЕИС0.
Все четыре XML контрольного архива прошли offline XSD validation без сети
и external entities; `official-xsd-proof.json`.

Миграция `20261026_01` после `20261025_01` расширяет два CHECK
`eis_procedure_events`. Tenant/RLS/immutable grants и parser identity прежние.
Downgrade при наличии новой family отказывает без удаления evidence;
rollback образа должен сохранять расширенную схему.

## Контрольный случай

Закупка `0836600003326000287`: исходный ZIP35294bytes, SHA
`b34aa4e5779209b9f35dd617ed459e7c2f5276ca0677008c637cb33d4cecae71`.
Внутри одно извещение EZK и три companion: EZKfinal, placement и proposals.
Предыдущее состояние — отсутствует в основном поиске, несмотря на историю
контракта; [V45](../search/133-eis-regional-discount.md).
Для проверки нужен весь исходный архив, без удаления протокола или переупаковки.
Истёкшая закупка должна находиться в ALL_CACHED с application FAIL;
исключение из NOT_EXPIRED_OR_UNKNOWN ожидаемо и не является ошибкой импорта.

## Приёмка и следующий шаг

Регрессия до исправления: `DOCUMENT_TYPE_UNSUPPORTED`; `red.txt`.
Локальные focused checks:129PASS/1PGSKIP. Полный gate
`release-20261025-213247-79a4b200f40f`:50/50PASS,4360PythonPASS/27прежних
разрешённыхSKIP,750PGPASS безSKIP,221webPASS,9doctests. Trusted verifier
проверил receipt и связанные reports; `gate-verification.json`.
Source archive `25122c96`, tree `ac8dd9ce`, API/worker image `5565a98a`.
Изолированная проверка финального образа без product-source mounts:
весь исходный ZIP→одно извещение+три companion→штатный API по номеру и
«бумага»200; SHA совпал. Replay0новых rows, tenant isolation и expiry PASS.
Тот же подготовленный retained-replay.py проверен с синтетическим activation
audit только в disposablePG; `real-source-result.json`. Production approval
и персональную production HTTP-сессию это не подтверждает.

## Подготовленная установка

Независимый review выявил несовместимость старых consumers: поздний EZKfinal
может маскировать отмену при старом COMPANION_TYPES. Поэтому перед первой
новой записью требуется единый совместимый API/worker/collector image и drain
старых worker-процессов под прежними leases. Web сохраняется.
После появления новой family откат на прежние images недопустим без отдельного
совместимого образа или изоляции consumers. Ошибки partial restore/start/audit
покрыты fault checks: прежний API изолируется до освобождения lease, если
совместимость не доказана. Mutation replay имеет отдельный owned/labelled
container lifecycle; lost client/timeout не освобождают lease с живым writer.
После его завершения выполняется read-only live HTTP search.19fault testsPASS.

План `ae99303df8ba196e87d76fb6d33c81e05489a4baa380226a8cddcc4526c69170`:
три config files, forward schema26, API/worker/collector image, source0 replay
ровно0836600003326000287 и live search. Cron/квоты/DB/web прежние.
Preflight/final independent plan review PASS; пользователь разрешил точный план.
Первая попытка отказала на занятом priority lease до mutation: schema/config/
containers прежние, PREPARED отсутствовал. После штатного завершения старого
worker повторён тот же утверждённый payload. Установка и source0 replay PASS:
schema26, API/worker/collector5565a98a, web/DB/cron прежние; +1notice/+3companion.
Реальный HTTP поиск ALL_CACHED по номеру200, exact XML SHA, applicationFAIL,
экономикаUNKNOWN; исходный ZIP сохранён побайтово. Owned replay container удалён.
Audit PREPARED→COMPATIBILITY_BARRIER→ACTIVATED→REPLAY_VERIFIED.
`activation-result.json`, `replay-output.json`, `live-search-result.json`,
`installed-identity.json`; independent installed review PASS.
Итоговые evidence и эти статусы записаны после seal; продуктовый код не менялся.

Последующий forced-read-only probe истории обнаружил CUSTOMER_IDENTITY_REQUIRED:
в XML один заказчик и полная customer allocation, но автоматический подбор
в V46 не выводил единственную identity из источника. Это исправлено
установленным [V47](../search/135-eis-single-customer-history.md): Тверская
область/159пачек, history200 с provenance. Неуспешный дополнительный probe
не использован как evidence установки V46.
Регулярный сбор истории и выборка≥5 остаются отдельными незавершёнными срезами;
реальное КП и региональный прогноз UNKNOWN.
