# S203 — исторические факты протоколов

Owner root; независимый high-risk review Astra. Реализовано и установлено на VPS 2026-10-05.

## Контракт

`GET /v1/tender-discovery/eis-protocols` принимает `purchase_number`,
`version_number`, `notice_xml_sha256`. Tenant задаётся bearer principal.
Чтение read-only из canonical ZIP: нет обращений к ЕИС, изменения индекса,
заданий или регулярного расписания. Ответ `Cache-Control: no-store`.

Выбранное извещение проверяется по exact ref и source holds. Документы связаны
по номеру закупки: `linkage_scope=PURCHASE_NUMBER_ONLY`, `notice_version_link=UNKNOWN`.
Версия протокола не является версией извещения. Co-location в архиве не доказывает
содержательную применимость к этой версии. Исторический документ не подтверждает
текущий этап, свежесть или пригодность участия.

Поддержаны `epProtocolEOK2020Final`, `fcsPlacementResult`, `fcsProposalsResult`.
Каждый документ возвращается отдельно, без выбора «последнего» или объединения
заявок разных документов. Другие metadata families перечислены как неинтерпретированные.
Номер EOK читается из `commonInfo/docNumber`; foundationProtocolNumber/lotNumber
сохраняются отдельно, когда явно присутствуют. FCs createDate не становится published_at.

Факты имеют тип, `PASS|UNKNOWN` и XML SHA/member/indexed locator/namespace.
PASS здесь означает извлечённое поле, а не допуск поставщика. Нет поля — UNKNOWN.
Дубли singleton/чужой namespace/конфликт ветвей отклоняют разбор документа.
UTF-8 only; DTD/entities, NUL и иные declared encodings запрещены до XML parse.
Источник не меняет permissions/policy.

## Заявки и суммы

`observed_rows` — число явно представленных строк в этом документе;
`represented_applications` — число уникальных непустых идентификаторов заявок
при отсутствии повторов. Отсутствующий/пустой список и повторные ID дают UNKNOWN,
не 0 и не общее число участников процедуры. Идентификатор заявки не подтверждает
личность компании: `supplier_identity=UNKNOWN`. `fcsProposalsResult` описывает
распределение количества; его строки нельзя считать независимыми конкурентами.

Для FCs `price` — явное предложение участника. Для EOK single-app `finalPrice`
сохраняется вместе с `rightConcludeContractPrice`, включая отрицательную сумму.
У multi-app EOK нет прямого finalPrice: оценки стоимостных критериев не подменяют
цену. `appRating` читается только в предусмотренной ветви; rank1 не доказывает
подписанный контракт. `CC|RC` сохраняются как исходные коды без такого вывода.
Money — Decimal; currency/tax_basis UNKNOWN, прибыль/снижение/вероятность не считаются.

Официальный контракт: [ЕИС16.3/44404](https://zakupki.gov.ru/epz/main/public/download/downloadDocument.html?id=44404),
ZIP SHA `4313b235fcfbce1e32a610cdef1f68449d23de617c15fd7487bad8cb933d86d7`.
IntegrationEPTypes.xsd SHA `6de440e8ca71ea3b96122cab67638fd432c5c6e587529c150210d6eb0d6a4058`;
IntegrationTypes.xsd SHA `a60410248915b6fb5940473e4c08c9b6cf0120283b7cd96606b13cb371d32b60`.
Effective parser date 2026-10-05; новое юридическое правило не вводится.

## Ресурсы и проверка

SQL LIMIT+1: events40/docs12/archives4. Размер bytea проверяется до чтения:
ZIP total8MiB, declared expanded total32MiB, selected XML4MiB each/16MiB total,
rows200 per document/400 total, response1MiB; member name255 UTF-8 bytes.
Архив читается один раз; SHA/CRC/duplicate members/unsafe names проверяются.
Каждый документ учитывается в бюджете ответа до построения общего JSON.
SQL statement20s/lock2s. Это foreground анализ одного ref, не проход по всей базе.
Схема БД и существующие admission/cancellation/deadline gates не меняются.

Source0 операторская проверка: `python scripts/server-eis-protocol-check.py`;
`--api` проверяет установленный endpoint на loopback внутри API container.
В отчёт не выводятся bearer/source tokens. Полный private report0600 ограничен2MiB.
## Acceptance на VPS

158 Linux/isolated PostgreSQL tests PASS (gate16:26:12UTC, pytest10.86s).
Проверены exact refs/RLS/read-only, ограничения SQL/ZIP/rows/output,
защита SHA на уровне БД, duplicates/missing fields, UNKNOWN вместо ложных фактов,
negative right-to-contract price, UTF-16/32 DTD и branch-specific paths.
Ruff и mypy двух новых модулей PASS. Временная тестовая БД удалена.
Astra review закрыл пять замечаний: DTD encoding bypass, docNumber path,
admission branches, member/output memory bounds, family-specific foundation/lot refs.

Source0 direct preview16:27:17UTC: 9 документов трёх exact refs, DBwrites0,
read69/95/107ms (один прогон, без времени запуска контейнера). Private proof
`/var/lib/eis-browser/research/rejected/s203-protocol-facts-4c7af0a0-bdc3-4ac3-bc31-6b6dce75a8a0.json`;
SHA `ed598fd403a4ddcdb180d025034710d510cff037d0fe148b0fbfa38b596713ce`.
Исходные 9 XML входят в ранее полностью XSD-валидированные 16 members S202;
это не утверждение XSD validity для любого будущего набора.

| Номер | EOK Final: представленные заявки | Placement: строки | Proposals: строки / однозначное число заявок |
| --- | ---: | ---: | --- |
| 0373100075926000095 | 5 | 1 | 5 / 5 |
| 0373100075926000096 | 2 | 1 | 38 / UNKNOWN (повторные ID) |
| 0573500000526000095 | 1 | 1 | 1 / 1 |

Всего55 строк и48 явных amount observations в разных документах. Это **не**
55 поставщиков и **не** 48 независимых ставок: документы/повторы не агрегируются.
Все3 deadline expired, applicationFAIL/participationUNKNOWN. Current stage,
notice-version applicability, supplier identity/currency/tax/freshness UNKNOWN.

Deployment16:27:35UTC: pinned API/worker three-module overlay, atomic13files,
host68/API16/worker16 hashesPASS; HEAD20261005_01 без новой миграции.
Backup SHA `286fccb2571333b52c223bb0b5361d084c78ba42e66e8b8ef70e2fd00234f789`.
API image `sha256:c1be2597a0d10799f7f5107c4b69dfc916e50862f4bad9569f1b5fe2da9d09d6`;
worker `sha256:233e1f8d5173b459ebdc25ab661a10189920c19a3c35931b6ed6efc3f33c634d`.
Web/cron/resources/source budgets прежние.

Authenticated real HTTP API check16:28:17UTC:3 responses200/no-store,
source0/DBwrites0; 70/81/177ms per exact notice (один прогон, loopback на VPS,
включая HTTP/auth/разбор ответа). Это cached historical read, не поиск по всей ЕИС.
API proof `/var/lib/eis-browser/research/rejected/s203-protocol-facts-0c88cabd-0267-4884-8de6-bbb7e6742405.json`;
SHA `b0c3d227e4c83399b67fc621a44ffbe0e5bce0ffdeb3469c17f0dfca6491e1c8`.
API/direct reports содержат те же9 exact XML SHA, rows и UNKNOWN-граничные случаи.

Ops16:28:18UTC: health200, HEAD01, testDB0/markersfalse,
DB4682456087/free257977925632bytes. Proof
`/var/lib/eis-browser/research/rejected/s203-operations-proof.json`;
SHA `7717dc319edc3b76dd323fc6101bc3c95ec00ac6021ea7d241f0680ced920383`.
Documentation/hash/image seal16:30:35UTC: atomic6docs,
host68/API16/worker16 hashesPASS; API/web running/OOMfalse,
API1GiB/web768MiB; pinned images и cron hashPASS.
Backup `/home/syurai/vibe-seller-state/backups/s203-before-20261005T163034Z-seal.tar.gz`;
SHA `ae1045568efc4ee0c41849f81416cb207d1a8b38cc9c155791530d467d452adc`.

Следующий S204: показать эти документные факты в карточке discovery через existing
BFF и exact выбранный ref. Сохранить названия scope и все UNKNOWN/FAIL, отделить
строки документов от количества конкурентов. Массовая проекция/кеш и сравнение
сопоставимых исторических аналогов требуют отдельного bounded acceptance.
