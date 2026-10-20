# Следующее общее семейство 223-ФЗ: purchaseNotice

Дата: **2026-10-03**. Владелец: Research subagent. Owned file: только этот
документ. Зависимости: docs/35/37/38, сохранённые официальные NSI/XSD и S166.
Acceptance исследования: выбрать один обоснованный общий тип, определить
точные XML paths, ограничения reader/DB, порядок реализации и проверки.
Исследование завершено; production admission семейства **не выполнен**.
Изучены локальные runtime files и сохранённые серверные artifacts read-only;
новых запросов к getDocsIP/getNsi, чтения secrets/env/DSN и deploy не было.

## Выбор: «Иной способ», а не исторический AE

Рекомендуется **`purchaseNotice`**, подсистема `RI223`. В официальном каталоге
`nsiDocumentTypes223` запись62 содержит название «Извещение о закупке “Иной
способ” (приглашение к проведению закупки)», `distributedPublicly=true`,
`actual=true`. Это конкретное семейство со своей схемой, не разрешение
универсального парсера любых223XML. Способ и ограничения участия берутся из
полей, а не из предположения, что любая такая закупка доступна любому поставщику.

**Почему не `purchaseNoticeAE`:** запись69 того же NSI и annotation
`purchaseNoticeAEDataType` называют его «Открытый аукцион в электронной форме
(до01.07.18)». Флаг `actual=true` разрешает присутствие в каталоге, но не
доказывает высокую полезность для новых процедур. У `purchaseNotice` уже есть
сохранённая публикационная выборка за01.10.2026; свежий объём AE неизвестен.
Выбор основан на полезном проверенном sample, а не доказанном лидерстве доли
рынка: national frequency/recall этого семейства остаётся UNKNOWN.

## Первичные источники и воспроизводимые fingerprints

Официальные ссылки: [каталог технических документов223](https://zakupki.gov.ru/epz/main/public/document/view.html?searchString=&sectionId=386&strictEqual=false),
[пакет XSD16.3](https://zakupki.gov.ru/epz/main/public/download/downloadDocument.html?id=44431),
[XSD16.2](https://zakupki.gov.ru/epz/main/public/download/downloadDocument.html?id=44009).
Пакет16.3 датирован28.09.2026 в предыдущем проверенном evidence docs/37.
Сегодня заново читались сохранённые файлы этих пакетов, а не новая публикация.

| Evidence | SHA-256 / locator |
|---|---|
| Официальный ZIP16.3, прежний S149 | `664facfa081008adb11a6df4373d1abe488927492ab8d618b9bc0b48cd1249ef` |
| purchase.xsd16.3, повторно сверено03.10 | `c5ad9bec7a1d1ba393f818e48a6f066db0428ce939cf9f4066acfc23ac0f7411` |
| Types.xsd16.3, прочитан03.10 | `5737269f17857fc8dd646617e10d81f2de797b673f75812618ce1ae6c6442265` |
| NSI XML, повторно сверено03.10 | `d19ed89d6918ca2f93389b9e609c7301998637f30205b2fb3c3105d431fa472a` |
| NSI выбранного типа | `nsiDocumentTypes223/body/item[62]/{documentType,subsystem,documentName,distributedPublicly,actual}`; namespace `http://zakupki.gov.ru/223fz/reference/1` |
| Каталог | `nsiDocumentTypes223_all_20260926021011_0.xml`, выгрузка26.09; lastUpdateDate выбранной записи `2025-01-01T00:00:00` |
| Сохранённый live ZIP purchaseNotice | `7dfacc0da896a1779b01430c4981096363394303c3582c6c0a8373c412eefb40`, 2778437bytes |

Artifacts внутри существующего volume:
`/var/lib/eis-browser/research/catalog/local-eis-supplier/` и
`/var/lib/eis-browser/research/223/local-eis-supplier/schemas-16.2/`,
`schemas-16.3/`; ZIP выборки:
`/var/lib/eis-browser/research/223-families/local-eis-supplier/purchaseNotice/17911292-48dd-4892-90ac-0caaa3b67013-1.zip`.
Это container paths, не файлы локального checkout.

## Точный XML контракт16.3

Префиксы: `p=http://zakupki.gov.ru/223fz/purchase/1`,
`t=http://zakupki.gov.ru/223fz/types/1`. `elementFormDefault=qualified`.
Ни локальное имя без namespace, ни рекурсивный `.//registrationNumber`
не подходят. Базовый путь **D**:
`/p:purchaseNotice/p:body/p:item/p:purchaseNoticeData`.

Корень `purchaseNotice` расширяет `t:packetType`; item имеет
`purchaseNoticeItemType`, расширяющий `t:itemType`; Data использует
`purchaseNoticeDataType → purchaseNoticeDataBaseType`.

| Смысл | Точный путь | Факт схемы и требование reader |
|---|---|---|
| Заголовок пакета | `/p:purchaseNotice/t:header/t:guid`, `/t:createDateTime` относительно header | `t:headerType`; не идентификатор закупки/её версии |
| GUID item | `/p:purchaseNotice/p:body/p:item/t:guid` | `t:itemType`; не заменяет business number |
| GUID закупки | `D/p:guid` | Обязателен по Data base; сохранить для последующего связывания |
| Номер / версия | `D/p:registrationNumber`, `D/p:version` | В XSD оба optional. Admission нашего индекса требует ровно11цифр и положительную версию; отсутствующее не выдумывается из имени файла/GUID |
| Название / метод | `D/p:name`, `D/p:purchaseMethodCode`, `D/p:purchaseCodeName` | Название обязательно, method fields optional; не выводить метод из слова purchaseNotice |
| Публикация / изменение | `D/p:publicationDateTime`, `D/p:modificationDate`, `D/p:createDateTime` | Разные значения; публикация optional, создание не подменяет публикацию |
| Статус | `D/p:status` | optional `purchaseNoticeStatusType`: F редактирование, P размещено, I недействительно, M изменение; P не означает открытую подачу |
| Общий deadline | `D/p:submissionCloseDateTime` | optional `xs:dateTime`; timezone не обязателен по этому типу |
| Режим сроков | `D/p:isLotOriented` | optional boolean, отдельные этапы по лотам; общий deadline нельзя без доказательства распространить на каждыйлот |
| Заказчик/timezone | `D/p:customer/t:mainInfo/t:timeZone/t:offset` и `/t:name` | offset описан как смещение относительно MSK, не самостоятельное доказательство зоны каждого dateTime |
| Публичность/МСП | `D/p:hidePurchase`, `D/p:hidePurchaseCustomerAccredited`, `D/p:forSmallOrMiddle` | Сохранять raw+provenance; отсутствие флага не означает разрешение участия; скрытые данные не включать в публичный discovery |
| Лоты | `D/p:lots/t:lot[i]` | `lotISListType → lotTypeIS → lotType`;0..unbounded по XSD, bounded по нашей policy |
| Идентичность лота | `.../t:guid`, `.../t:ordinalNumber` | GUID+source ordinal сохранять отдельно от позиции i в массиве; не считать ordinal=i |
| Детали лота | `.../t:lotData` | optional! Текущий `_one(lotData)` отвергнет schema-valid лот без деталей; результат не должен получить выдуманную цену/товар |
| Позиции | `.../t:lotData/t:lotItems/t:lotItem[j]` | `lotItemType`: guid, ordinalNumber, okpd2/code/name, okei/code/name, qty, additionalInfo; возможны legacy okdp/okved branches |
| Отмена лота | `.../t:cancelled`, `.../t:cancellation/t:cancelDate`, `/t:cancelInfo` | cancelled обязателен XSD; false в одном notice не доказывает отсутствие более позднего cancellation event |

### Цена: пять реальных лотов сейчас потеряли бы числовое значение

В `t:lotData` есть `xs:choice`, поэтому отсутствие `initialSum` не обязательно
означает отсутствие опубликованной цены. Точные прямые paths:

- `t:currency/t:letterCode`, `t:code`, `t:digitalCode`, `t:name`;
- `t:initialSum` (+optional `t:startingContractPriceRub`);
- альтернативный `t:maxContractPrice` (+optional `t:maxContractPriceRub`);
- альтернативный текстовый `t:initialSumInfo`;
- при initialSum могут быть `t:priceFormula` либо `t:commodityPrice`
  (+`t:commodityPriceRub`);
- позиционная цена, если дана: `t:lotItems/t:lotItem[j]/t:commodityItemPrice`
  (+`t:commodityItemPriceRub`).

Нужна отдельная типизированная семантика источника:
`INITIAL_SUM / MAX_CONTRACT_PRICE / TEXT_ONLY / UNKNOWN`, точный source locator,
Decimal и валюта. Не записывать maxContractPrice в поле initial_sum с ложным
locator и не считать commodityPrice ценой всего лота. Рублёвый эквивалент
источника сохраняется отдельно от исходной валюты; никаких самодельных FX.
letterCode/code disagreement → UNKNOWN; выбор одного молча недопустим.
Формула/максимум договора не становятся гарантированной выручкой.

Для bounded первого admission допустимо сохранить известный source amount
отдельно и оставить existing economics unavailable на новых неподдержанных
ветках. Лучше явный UNKNOWN, чем использовать maxContractPrice как прежнюю
НМЦК без обновлённого consumer contract. Нельзя обнулить эти5лотов и скрыть их
из discovery по признаку «нетцены».

### Deadline и вложения

Aware dateTime сохраняется с исходной зоной; naive/missing остаётся UNKNOWN.
Нельзя автоматически прибавлять3часа к customer offset: схема не устанавливает
такой mapping для каждого поля. При `isLotOriented=true` отдельный lot schedule
может находиться в `templateStructure/extendFields` и `lot/extendFields`;
их mapping в этом срезе **не установлен**. Общий deadline даёт только факт
извещения, не проверенный срок выбранного лота. Нужны отдельные доказательства
из exact XML/документа; положительная eligibility заблокирована.

`D/p:attachments` имеет тип `t:documentListType`:

- `t:totalDocumentsCount`, `t:additionalDocumentsCount`;
- `t:prevDocument[k]/t:guid` — retained links из прежних редакций;
- choice `t:document[k]` или `t:documentFS[k]`;
- document: `t:guid`, `t:fileName`, optional `t:description`, content/url branch,
  optional `t:contentUid`, `t:notPlacement`, cryptoSigns;
- documentFS: `t:guid`, optional createDateTime/description, `t:contentUid`.

Сегодня reader читает только document/fileName/contentUid/url. Для остальных
веток нужна явная полнота manifest UNKNOWN/unsupported references; нельзя
считать отсутствие document пустым полным комплектом, синтезировать URL изGUID
без контракта или скачивать скрытый notPlacement=true. Сохранить raw locators
для FS/previous/additional references. COUNT_CONSISTENT относится к перечисленным
элементам, не доказанной полноте ТЗ или полученным bytes. Прежняя безопасная
allowlist официального HTTPS223filestore и exact UID остаётся.

## Отмена и устаревшая версия: отдельные identities

Прежняя версия закупки определяется по `(company_id, law223, purchase_number,
version_number, xml_sha256)` и current projection; lower version не удаляется,
same number/version с иными bytes — конфликт. GUID пакета/время загрузки не
делают документ новой текущей редакцией. Status I означает source invalid,
а не обязательно юридическую отмену всей процедуры.

Официальный NSI содержит public/actual RI223 event families:

| Семейство | NSI | Точный идентификатор связи из XSD16.3 |
|---|---:|---|
| `purchaseRejection` | item80 | `/p:purchaseRejection/p:body/p:item/p:purchaseRejectionData/p:cancelNoticeRegistrationNumber`; событие — его собственный `p:guid`, publicationDateTime/rejectionDate |
| `purchaseLotCancellation` | item18 | `/p:purchaseLotCancellation/p:body/p:item/p:purchaseLotCancellationData/p:purchaseInfo/t:purchaseNoticeNumber`; event guid — Data/p:guid |
| Лоты отмены | внутри предыдущего | `Data/p:cancelledLots/p:cancelledLot[k]/p:guid`, `/p:ordinalNumber`, optional `/p:cancellation/t:cancelDate` и `/t:cancelInfo` |

У cancelledLot/guid annotation буквально «Глобальный идентификатор закупки»;
его семантику как lotGUID нельзя уверенно объявить по имени узла. В сочетании
с purchaseNoticeNumber и ordinal нужна live cross-check; неоднозначность даёт
UNKNOWN. Эти события не имеют контракта notice version и не должны входить
в `Eis223DocumentType` как будто это новые извещения. Нужен отдельный event
store/reader/precedence после их live evidence. Новых live отмен сегодня нет.
Возврат отмены/полный порядок событий UNKNOWN; отсутствие события не PASS.

## Что подтвердили сохранённые live bytes

Окно S152: region50, day2026-10-01,+03:00, UID
`17911292-48dd-4892-90ac-0caaa3b67013`. Повторное чтение03.10:
25XML-версий,25лотов,157элементов attachments/document. Это не25независимых
новых закупок: в архиве есть повторные номера с разными редакциями.

- Во всех25есть номер/версия/status=P, hidePurchase=false, lot cancelled=false.
- 20лотов имеют initialSum,5 — maxContractPrice; не подменять эти категории.
- У19извещений есть deadline, все19naive;6deadline отсутствуют.
- isLotOriented=false у24, true у1. Значение true уже встречается в sample.
- Сроки/версии описывают snapshot01.10, не действительность на03.10.
- Offline lxml validation обоих локальных полных XSD деревьев заново дала
  **24PASS/1FAIL на16.2 и16.3**. External schemaLocation не загружался.
- FAIL: `32616427936`,version1, XML SHA
  `f757773297c1e2aa1baa88b2f7ae6e7a0672f6ac23b69f77331f1aadae34a03c`;
  строка134: `placingProcedure` не содержит обязательный `summingupDateTime`.

Пример точного валидного source ref: `32616376238`,version3,
SHA `0a00bec55d734f8aa3ac464423f818161cf1811fe8fe164e237f27896a7ae062`,
member `purchaseNotice_32616376238_3_01A0F6367C7F73F1905923F5363CCF96.xml`.
Его deadline raw `2026-10-08T11:00:00` остаётся UNKNOWN_TZ.

S152 архив имеет terminal SOURCE_REJECTED. Исследование не меняет это состояние
и не вводит молчаливый partial import. Варианты следующего решения:
получить полностью валидное окно либо отдельным ADR/контрактом разрешить
безопасную metadata extraction при отдельном schema FAIL и явном PARTIAL
window/quarantine. Убирать ошибочный member или исправлять исходный XML нельзя.
Существующий S155 metadata/schema split — основание для review, не автоматическое
разрешение изменить admission generic family.

## Owned files будущего последовательного implementation slice

Это предложение ownership, не изменение этих файлов. Единственный будущий
владелец назначается root перед реализацией; shared consumer files не делить
между параллельными исполнителями.

| Область | Файлы / необходимые изменения |
|---|---|
| Reader/request | `src/procurement/sources/eis_223_archive.py`: explicit family admission, exact fields, lot identity/optional details, price-kind, scope safety; отдельный family reader допустим при ясном dispatch |
| Offline schema | `sources/eis_223_schema.py`, `tests/test_eis_223_schema.py`: pinned full trees и exact-family validation; snapshot change/versioning без false PASS |
| Intake/index | `storage/eis_223_index.py`: regex разрешённых family, model, current-version search; не менять law/number semantics |
| Refresh | `sources/eis_223_sync.py`, `storage/eis_223_sync.py`, `scripts/server-eis-223-refresh.py`: family whitelist и budget; регион50 остаётся явным bounded scope |
| DB | `storage/models.py` + новая Alembic migration: `ck_eis_223_window`, `ck_eis_223_snapshot_identity`, `ck_eis_223_attempt_scope` |
| DB history | Не редактировать применённые20261002_06/07. Downgrade новой migration обязан отказать, если новая family сохранена в windows/versions/attempts |
| Probe/import | Existing `scripts/server-eis-223-family-probe.py` уже знает purchaseNotice; cached validation отдельно от admission. `server-eis-223-import.py` принимает choices=SUPPORTED_DOCUMENT_TYPES, но отдельно проверяет retained proof: SOURCE_REJECTED не становится импортируемым из-за расширения whitelist |
| Consumers | `storage/eis_223_documents.py`, `eis_223_comparison.py`, mixed comparison/economics: optional details, max-price/lot deadlines/manifest unknown не должны расширять gates |
| UI/types | `web/src/lib/procurement-api.ts`; `web/src/app/tender-discovery/indexed-223-search.tsx` сейчас иначе показывает «Аукцион дляМСП» для любого не-ZKESMBO — нужен explicit family label; comparison price kind |
| Tests | `tests/test_eis_223_archive.py`, `test_eis_223_index.py`, `test_eis_223_sync.py`, `test_eis_223_family_probe.py`, профильные comparison tests, `tests/integration/test_eis_223_index_pg.py` |

Текущие regex/DB checks разрешают ровноAESMBO/ZKESMBO; одного расширения Literal
недостаточно. Snapshot identity связана с family из window_key; обязательны
сохранение composite FK, FORCE RLS, immutable journals и replay semantics.
Новые schema/shape статусы должны сохранять значение для прежних snapshots;
нельзя молча переинтерпретировать старую projection новым price mapping.

## Acceptance до production admission

1. Synthetic exact-family tests: root/Data mismatch, namespace shadowing,
   duplicate/missing business identity, nested false number, item/header GUID
   не подменяют identity; optional lotData, ordinal≠index, multi-lot, legacy
   classification и mixed currencies. ZIP/XML/DTD/ENTITY/bytes caps прежние.
2. Price tests: initialSum, maxContractPrice, initialSumInfo, source RUB
   equivalent, currency disagreement, negative/NaN/float rejection; каждое
   значение с exact XMLSHA+locator; ни суммирования лотов, ни unit price
   из division total, ни включения unsupported price в economics.
3. Deadline/flags: naive/missing UNKNOWN, aware сохраняется, isLotOriented
   не получает общий дедлайн без evidence, P не SUBMISSION_OPEN, I/hidden/cancel
   не получают PASS; freshness/cancellation coverage остаются отдельными.
4. Manifest: documentFS/prevDocument/additionalDocumentsCount и notPlacement
   явно отражаются; raw references не превращаются в разрешённую загрузку.
5. Cached real-source proof: те же25members,24/1XSD в каждой release;
   установленная admission policy не скрывает ни одного member/pricebranch.
   XML/ZIP hashes и exact source selection сохраняются;0source requests.
6. Isolated PG: обе старые family работают; новая разрешена только своей
   window; cross-family/cross-tenant rejected; latest/replay/conflict/immutable
   tests; RLS/compositeFK; migration upgrade и guarded downgrade с сохранённой
   новой историей; в failed/partial окно не записывается ложный COMPLETE.
7. Новый live intake только root под общим lease/rate budget: одно явное
   окно, все returned archives, source/quality counters; повтор без дублей.
   Проверка UI явного family/price kind и no mutations у read API. Объём
   current eligible opportunities не заявляется, пока timezone/events UNKNOWN.

Следующий event slice отдельно проверяет purchaseRejection/purchaseLotCancellation.
Ни schema PASS, ни найденная более широкая family не заменяют ТЗ, КП и
base/realistic/conservative; `PARTICIPATE` здесь не возникает.
