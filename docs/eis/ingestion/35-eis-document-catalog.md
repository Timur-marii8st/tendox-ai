# Официальный каталог типов документов ЕИС

Статус: S145 / P5a1 завершён 2026-10-02. Это discovery capabilities источника.
Наличие типа в каталоге не означает, что его adapter реализован или весь корпус
этого типа уже получен. Глобальный охват и полнота актуальных карточек UNKNOWN.

## Проверенный контракт

Первичные источники: [официальные схемы 16.3, пакет 44404](https://zakupki.gov.ru/epz/main/public/download/downloadDocument.html?id=44404),
[альбом ТФФ 44403](https://zakupki.gov.ru/epz/main/public/download/downloadDocument.html?id=44403)
и разрешённые live ответы `getNsi` на VPS. SHA пакета схем:
`4313b235fcfbce1e32a610cdef1f68449d23de617c15fd7487bad8cb933d86d7`.
Контракт SOAP: `GetDocsWS/GetDocsIndividualPerson/getDocsIP-ws-api.xsd`;
44-ФЗ list/entry: `fcsExport.xsd`, `IntegrationTypes.xsd`
(`zfcs_nsiDocumentTypesType`). Это проверенная версия, без утверждения, что она
является самой новой опубликованной версией ЕИС.

Два фиксированных запроса `getNsiRequest` с `mode=PROD`, `nsiKind=all`:

| Закон | Поле выбора | Код |
|---|---|---|
| 44-ФЗ | `nsiCode44` | `nsiDocumentTypes` |
| 223-ФЗ | `nsiCode223` | `nsiDocumentTypes223` |

`getNsiResponse` возвращает `nsiArchiveInfo/archiveUrl/archiveName` напрямую:
`getPreparedPart` для этого метода не применяется. Ответ привязан к exact
request UUID, response UUID и PROD; SOAP/namespace/порядок/ветки проверяются.
Ошибки и `noData=true` сохраняют UNKNOWN. Готовые ссылки в двух live ответах
оказались HTTPS `int.zakupki.gov.ru/dstore/common/download/compound` с
`docRequestUid`/`compoundUid`; используется существующая строгая проверка URL
и соответствия UUID. Произвольные адреса не загружаются.

Форматы архивов различаются:

- 44: namespace `oos/export/1`, `export/nsiDocumentTypesList/nsiDocumentTypes`;
  поля namespace `oos/types/1`: `documentType`, `documentName`, `subsystemType`,
  `isDistributedPublicly`, `updateDate`, `isActual`.
- 223: namespace `223fz/reference/1`, `nsiDocumentTypes223/body/item`;
  `documentType`, `subsystem`, `documentName`, `distributedPublicly`, `actual`,
  `createDate`, `lastUpdateDate`. Header — namespace `223fz/types/1`.
  Basis этого reader — `OBSERVED_LIVE_223`: форма подтверждена полученным
  официальным каталогом; полная валидация по отдельному пакету XSD 223 ещё
  не заявляется. `xsi:schemaLocation` из XML не загружается и не исполняется.

Каждое исходное поле имеет raw value, XML SHA, member и locator. Статусы
публичности/актуальности PASS/FAIL означают только значения этих флагов:
`true|1`, `false|0`. Пропуск, дубликат, иной literal или вложенная структура
дают UNKNOWN. Наивная дата не получает придуманный timezone; исходное значение
сохраняется, `updated_at=null`. PASS флага не является допуском поставщика,
подтверждением всей процедуры или разрешением автоматического подключения.

## Live результат

Повторный полный probe через штатный browser transport и глобальный rate lock
занял **10.497184 s**, включая один браузер, 2 SOAP POST и 2 archive GET.
Оба ответа HTTP200/READY. Каталоги источника датированы **2026-09-26**:
это дата возвращённой полной выгрузки, без подмены её текущей датой.

| Метрика | 44-ФЗ | 223-ФЗ |
|---|---:|---:|
| Всего записей типов | 220 | 110 |
| Public=true и actual=true | 126 | 93 |
| Public/actual UNKNOWN | 0 | 0 |
| Public+actual целевая подсистема | PRIZ: 27 | RI223: 67 |
| Сжатые bytes | 8 107 | 4 479 |
| XML bytes | 119 164 | 63 976 |

Остальные записи относятся к другим подсистемам или имеют иной признак
публичности/актуальности; их наличие не даёт разрешения читать непубличные данные.
Следующий bounded adapter — `epNotificationEOK2020` (44-ФЗ, PRIZ, электронный
открытый конкурс). Каталог также показывает `epNotificationEZT2020`; структура
и ограничения его метода требуют отдельной проверки. 223 требует своего law/
namespace/идентификаторов/версий/лотов, а протоколы — event/history parsing.
Список кодов не добавляется в `SUPPORTED_NOTICE_TYPES` автоматически.

## Evidence на сервере

Корень tenant: `/var/lib/eis-browser/research/catalog/local-eis-supplier/`.
Исходящие SOAP с token не сохраняются; responses/ZIP/proofs остаются на VPS.
Tenant directory 0700, файлы штатного probe 0600. Append-only snapshots имеют
company_id, checked_at, request/response IDs, source digest, entries/provenance
и `adapter_policy_changed=false`. Это исследовательские artifacts, не новая
DB policy или production catalog admission.

| Artifact | Filename / SHA-256 |
|---|---|
| Live 44 response | `contract-44-1b4c958e-5b80-43bf-aa8c-e4f3e595277f.xml`; `a6e61fdf652dc849f361875329f8ab043e0cfea063cfe120e67144f07ad67809` |
| Live 223 response | `contract-223-8affb026-ee7a-4c93-9ac8-dfa4f7014ad2.xml`; `0c355d889ad7a23336b6b453b13acfe7d9bbc364321748129b6598a9731cbb27` |
| 44 archive | `contract-44-1b4c958e-5b80-43bf-aa8c-e4f3e595277f-1.zip`; `7ab2ff0b4941a887a9bcce93f617581ece3482382020f58d6fa3fb3a0acab906` |
| 223 archive | `contract-223-8affb026-ee7a-4c93-9ac8-dfa4f7014ad2-1.zip`; `8d4fd45da50c24426287110085736e004f610a20e1053bd7bddae8d2238ee1cc` |
| 44 XML | `nsiDocumentTypesList_all_20260926020517_0.xml`; `f53fed4befb36e66db38b75c29e3912f767be162ee7654c78c21ce4274283f02` |
| 223 XML | `nsiDocumentTypes223_all_20260926021011_0.xml`; `d19ed89d6918ca2f93389b9e609c7301998637f30205b2fb3c3105d431fa472a` |
| 44 snapshot | `snapshot-44-1b4c958e-5b80-43bf-aa8c-e4f3e595277f-20261002T062352853395Z.json`; `4e7ead95930891632c5baf1526049260edb6af9af7f4b381a0aa4942d63ab4d6` |
| 223 snapshot | `snapshot-223-8affb026-ee7a-4c93-9ac8-dfa4f7014ad2-20261002T062352853395Z.json`; `665dd63ffc1e4aae4c1ca0a90c5e9bd18628690a1e19a79d515fe1b1691e5e31` |

Для EOK exact code field: 44 XML
`nsiDocumentTypesList/nsiDocumentTypes[123]/documentType[source-field-1]`.
Каждое из остальных полей той же записи имеет собственный locator в snapshot.
Оба live archive SHA совпали с первым получением: transport replay подтверждён.

## Ограничения и проверки

Ответ ≤2 MiB; ≤4 archives; каждый ZIP ≤8 MiB, ≤20 XML members, expanded set
≤16 MiB, ≤2000 entries на archive. Нет extraction на filesystem; path traversal,
symlink, encryption, иной compression, не-XML/duplicate members, duplicate type,
DTD/entity/UTF-16/32 и неизвестные namespace отвергаются. Полное содержимое XML
проверяется на reflection token перед сохранением ZIP, включая сжатый payload.
SOAP POST/GET последовательны, со штатной паузой; CAPTCHA/блокировки/quota не
обходятся. Корпус закупок при probe не загружается.

76 профильных unit tests (33 catalog + existing feed/archive/sync), Ruff и mypy
двух production files прошли на Windows. Linux worker image прошёл 73 теста:
все 33 новых catalog tests и 40 existing feed/archive/sync tests серверного
набора. Эти наборы existing tests отличаются; число не объявляется одинаковым.
Негативный Windows тест нашёл нормализацию ZIP backslash: проверяется исходный
`orig_filename`, поэтому опасное имя не теряется при платформенном преобразовании.
API/worker images пересобраны, API health ok. Миграция не нужна: reader не меняет
production tables. UI в этом slice не изменяется.

Runtime/host/local SHA reader совпал:
`aa200b298a5966c863598b09bf2e60dca53c765c46828f065c3cde75408ab0ef`.

## Операторский запуск

Со штатным worker image и scripts mount, на сервере:

```bash
cd /home/syurai/vibe-seller
flock -w 300 /home/syurai/vibe-seller-state/eis-import.lock \
  sudo -n docker compose -p vibe-seller -f docker-compose.server.yml \
  run --rm -T --no-deps \
  -v /home/syurai/vibe-seller/scripts:/app/scripts:ro worker \
  python /app/scripts/server-eis-catalog-probe.py --company-id local-eis-supplier
```

Optional `--cached-request-44 UUID --cached-request-223 UUID` повторяет проверку
двух сохранённых contracts/ZIP без source I/O. Новый proof не переписывает старый.
Повторение probe не выполняет ingestion карточек и не включает новые адаптеры.
