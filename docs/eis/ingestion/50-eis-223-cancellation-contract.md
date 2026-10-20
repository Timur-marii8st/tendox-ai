# S170: контракт источника отмен223-ФЗ

Дата исследования: **2026-10-03**. Владелец: Research subagent. Owned file:
только этот документ. Зависимости: S169, docs/35/37/47/49, сохранённые
официальные NSI/XSD16.2/16.3. Read-only SSH и offline schema validation;
новые getDocsIP/getNsi, intake, admission, DB writes и deploy не выполнялись.

## M1: первое семейство purchaseRejection

Выбрать **`purchaseRejection` — отмена закупки**. Оно имеет обязательную прямую
ссылку на11-значный номер закупки и не требует разрешать неоднозначность
идентификатора отдельного лота. `purchaseLotCancellation` — следующий отдельный
контракт. Выбор объясняется ясной связью с закупкой, а не измеренной частотой:
реальный текущий объём обоих семейств пока UNKNOWN.

В сохранённом официальном NSI обе записи имеют `subsystem=RI223`,
`distributedPublicly=true`, `actual=true`:

| NSI item | documentType | documentName |
|---:|---|---|
|80|`purchaseRejection`|Отмена закупки|
|18|`purchaseLotCancellation`|Отмена лотов закупки|

Каталог выгружен26.09.2026; createDate выбранных записей
`2024-03-30T02:56:43`, lastUpdateDate `2025-01-01T00:00:00`.
Это дата сохранённого каталога, не сегодняшняя online проверка.

Точная будущая selection для `getDocsByOrgRegionRequest`:
`orgRegion=50`, `subsystemType=RI223`,
**`documentType223=purchaseRejection`**, `periodInfo/exactDate=YYYY-MM-DD+03:00`.
Дату первого bounded окна выбирает root под общим lease/budget; этот документ
не запускает probe. SOAP namespace сервиса getDocsIP остаётся44/fz44 по его
контракту; это не namespace возвращённого223XML. Нельзя использовать
`documentType44`, `purchaseNotice` или `purchaseProtocolRejectionAESMBO`
как синонимы whole-purchase cancellation.

## Первичные источники и fingerprints

Официальные URL: [XSD22316.3](https://zakupki.gov.ru/epz/main/public/download/downloadDocument.html?id=44431),
[XSD22316.2](https://zakupki.gov.ru/epz/main/public/download/downloadDocument.html?id=44009),
[раздел документации223](https://zakupki.gov.ru/epz/main/public/document/view.html?searchString=&sectionId=386&strictEqual=false).
В этом срезе прочитаны ранее сохранённые официальные пакеты; URL повторно
не запрашивались. Происхождение пакетов — docs/37; NSI — docs/35.

| Evidence | SHA-256 |
|---|---|
|purchase.xsd16.2, повторно проверен03.10|`712e818f74bf3d38a03a3516533d0d4bf1df343f5a6e2056ae38a35f9ee7975b`|
|purchase.xsd16.3, повторно проверен03.10|`c5ad9bec7a1d1ba393f818e48a6f066db0428ce939cf9f4066acfc23ac0f7411`|
|NSI XML, повторно проверен03.10|`d19ed89d6918ca2f93389b9e609c7301998637f30205b2fb3c3105d431fa472a`|
|NSI ZIP, прежний evidence docs/35|`8d4fd45da50c24426287110085736e004f610a20e1053bd7bddae8d2238ee1cc`|

Container schema roots:
`/var/lib/eis-browser/research/223/local-eis-supplier/schemas-16.2/`,
`/var/lib/eis-browser/research/223/local-eis-supplier/schemas-16.3/`.
NSI ZIP:
`/var/lib/eis-browser/research/catalog/local-eis-supplier/contract-223-8affb026-ee7a-4c93-9ac8-dfa4f7014ad2-1.zip`.
Member: `nsiDocumentTypes223_all_20260926021011_0.xml`;
exact locator `nsiDocumentTypes223/body/item[80]/documentType` и другие поля
той же записи, namespace `http://zakupki.gov.ru/223fz/reference/1`.
Host prefix для тех же artifacts:
`/var/lib/docker/volumes/vibe-seller_eis_browser_state/_data/research/`.

## purchaseRejection: точная структура обеих схем

Обозначения: `p=http://zakupki.gov.ru/223fz/purchase/1`,
`t=http://zakupki.gov.ru/223fz/types/1`.
Root — **`{p}purchaseRejection`**. `purchaseRejection` расширяет `t:packetType`;
`p:body/p:item` имеет `purchaseRejectionType`, расширяющий `t:itemType`.
Data — `purchaseRejectionDataType`. Состав полей, перечисленный ниже,
совпадает в прочитанных16.2/16.3.

**D** = `/p:purchaseRejection/p:body/p:item/p:purchaseRejectionData`.
Все обращения прямые, с точным namespace; рекурсивный поиск локального имени
может перепутать GUID события, пакета, организации или вложения.

| Поле/роль | Path | XSD и интерпретация |
|---|---|---|
| GUID пакета | `/p:purchaseRejection/t:header/t:guid` | Обязателен; не business identity отмены |
| Время пакета | `/p:purchaseRejection/t:header/t:createDateTime` | Обязательный xs:dateTime; не время решения/публикации |
| GUID item | `/p:purchaseRejection/p:body/p:item/t:guid` | Обязателен; отдельная роль |
| GUID события | `D/p:guid` | Обязательный t:guidType; глобальный идентификатор извещения об отказе |
| Создание события | `D/p:createDateTime` | Обязательный xs:dateTime |
| Связь с закупкой | `D/p:cancelNoticeRegistrationNumber` | Обязательный t:registrationNumber11Type; это номер закупки, не номер отмены |
| Публикация | `D/p:publicationDateTime` | Optional xs:dateTime; отсутствие допустимо по XSD |
| Решение об отказе | `D/p:rejectionDate` | Обязательный xs:dateTime; не заменять publication этим значением |
| Причина | `D/p:causeForRejection` | Обязательный текст; недоверенное внешнее содержимое, не инструкция агенту |
| Разместившая организация | `D/p:placer/t:mainInfo` | Обязательный customerInfoType; данные организации не business link |
| Название/метод | `D/p:name`, `/p:purchaseMethodCode`, `/p:purchaseCodeName` | Optional; отсутствие не мешает exact-number связи |
| Ссылки | `D/p:urlEIS`, `/p:urlVSRZ`, `/p:urlKisRmis` | Optional; не разрешают произвольный fetch |
| Вложения | `D/p:attachments` | Optional t:documentListType; document/FS/previous/additional boundaries из docs/49 |
| Прочее | `D/p:emergency`, `/p:signatureAuthorizedBody` | Optional; подписи не исполняются, юридическая проверка UNKNOWN |

`guidType`:36символов, hexadecimal8-4-4-4-12 с дефисами, допускается A–F.
Не навязывать UUIDv4: в XSD ограничения на version bits нет. Raw сохраняется,
канонический GUID допустим только при сохранении исходного evidence.
RegistrationNumber11Type имеет `\d{11}`; наш admission может требовать
ASCII11цифр как действующий контракт индекса, не превращая иной literal
в номер через очистку произвольных символов.

В Data **нет version, status, cancelled, notice-version, отмены отмены или
признака восстановления**. У packet/item предков таких полей также нет.
Нельзя добавлять `version=1`, трактовать отсутствие status какP или строить
event projection на notice parser. Закон223 и event family должны оставаться
частью tenant-scoped storage identity.

## Identity, временная шкала и безопасное применение

Предложение контракта хранения: immutable event
`company_id + law223 + family + source_event_guid`, точные XMLSHA/member,
sourcewindow/response/archiveSHA и локаторы. Identical replay идемпотентен;
тот же GUID с другими bytes — явно отмеченное расхождение/конфликт, не
last-write-wins и не автоматически новая версия. До live evidence неизвестно,
использует ли источник повторно GUID при исправлениях; policy конфликтов
не должна уничтожать ни одно полученное доказательство.

Отсутствующий номер/неоднозначный direct-path/namespace mismatch блокирует
связывание; вложенный похожий номер не fallback. Событие, пришедшее раньше
самого извещения, можно сохранить как event с unresolved notice link, без
создания фиктивной карточки. Реальный FK/порядок materialization определяет
следующий storage slice; required tenant isolation остаётся.

`xs:dateTime` разрешает naive values. Хранить отдельно raw и aware value для
publication/create/rejection/header, не придумывать MSK/UTC. Ingest timestamp
aware отражает получение, а не публикацию. Optional publication и наивные
времена не позволяют надёжно упорядочить событие с поздним извещением.

**Предлагаемый conservative gate:** известное связанное событие отмены создаёт
блокер рекомендаций/экономики и необходимость официальной сверки. Не выдавать
бесспорный «текущий статус отменён» без resolution текущей версии/событий.
Более поздний notice P или lot cancelled=false сам по себе не доказывает
восстановление. Отсутствие cancellation event означает лишь отсутствие в
синхронизированном scope, не PASS. Schema FAIL не даёт подтверждённую отмену,
но является source-quality blocker с UNKNOWN current state.

В проверенном NSI не найдена явная family восстановления закупки или отмены
отмены. Это результат просмотра этого каталога, не доказательство отсутствия
такого механизма во всей ЕИС. Порядок reversal/исправления и effectivity
**UNKNOWN**, требует отдельного официального/live evidence.

## purchaseLotCancellation: следующий контракт, не синоним whole cancellation

Root `{p}purchaseLotCancellation`; item имеет
`purchaseLotCancellationItemType`; **L** =
`/p:purchaseLotCancellation/p:body/p:item/p:purchaseLotCancellationData`.
Data type называется `purchaseLotCancellationData` (без Type в конце).

| Смысл | Точный путь |
|---|---|
| GUID события | `L/p:guid` |
| Номер закупки | `L/p:purchaseInfo/t:purchaseNoticeNumber` |
| Optional GUID закупки | `L/p:purchaseInfo/t:guid` |
| Создание/публикация события | `L/p:createDateTime`, optional `L/p:publicationDateTime` |
| Лоты | `L/p:cancelledLots/p:cancelledLot[i]` (1..unbounded по XSD) |
| GUID/ordinal лота | `.../p:guid`, `.../p:ordinalNumber` |
| Совместный лот/предмет | `.../p:jointLot`, `.../p:subject` |
| Индивидуальная причина | optional `.../p:cancellation/t:cancelDate`, `/t:cancelInfo` |
| Режим причины | `L/p:descriptionType`: COMMON или VARIOUS |
| Общая причина | optional `L/p:cancelDate`, `L/p:description` |

`purchaseInfo/t:publicationDateTime`, если присутствует, относится к извещению,
а не публикации cancellation event. Время решения по лоту — `xs:date`, не
точное время; не подставлять полночь для сравнения порядка.
COMMON хранит общую причину на Data; VARIOUS — индивидуально по лотам.
Комментарии описывают зависимость, но minOccurs этих полей остаётся0:
дополнительную semantic completeness проверять отдельно от XSD PASS.

Annotation `cancelledLot/p:guid` буквально говорит «Глобальный идентификатор
закупки», хотя поле находится в лоте. Это не достаточное основание считать его
надёжным lotGUID. До live cross-check связь по номеру/ordinal/GUID и версиям
лотов остаётся ограниченной. Отмена одного лота не означает отмену остальных.
В этой family также нет notice version/status/reversal fields.

Не смешивать с `protocolCancellation` (item92, отменяет протокол),
`purchaseProtocolRejection*` (отказ от заключения договора) и
`contractCancellation*` подсистемы RD223 (расторжение договора).

## Проверки, уже выполненные offline, и будущие fixtures

В retained research directories `catalog`, `223`, `223-families` не обнаружены
файлы, имя которых содержит purchaseRejection/purchaseLotCancellation.
Это ограниченная проверка имён, не утверждение об отсутствии события внутри
любого ZIP/всего сервера. Live sample выбранного события в этом исследовании
не получен и не заявляется.

В памяти составлен синтетический minimal purchaseRejection (не сохранён как
реальная source фикстура) и проверен против обоих local XSD деревьев:

| Synthetic case |16.2|16.3|
|---|---|---|
|Обязательные поля, aware times, без publicationDateTime|PASS|PASS|
|Те же поля со всеми naive times|PASS|PASS|
|Вставлен Data/version=1|FAIL, SCHEMAV_ELEMENT_CONTENT|FAIL, SCHEMAV_ELEMENT_CONTENT|

Минимальная последовательность для Sol: root → t:header(t:guid,t:createDateTime)
→ p:body/p:item(t:guid,p:purchaseRejectionData). В Data по порядку:
p:guid, p:createDateTime, p:cancelNoticeRegistrationNumber, p:rejectionDate,
p:causeForRejection, p:placer/t:mainInfo(t:inn,t:kpp).
Синтетические значения: разные GUID000…001/002/003, номер32600000001,
inn7700000000,kpp770001001; это лишь schema fixture, не настоящие организации.

Обязательные регрессии M1: ошибочные root/Data/namespace; shadow номер внутри
attachments/placer; missing/duplicate GUID или business link; отсутствующая
публикация; naive/aware даты без выдуманной зоны; GUID case normalization с raw;
same GUID/different bytes; разные eventGUID одного номера; событие без notice;
отмена протокола/договора не admitted; внешние URL/DTD/ENTITY/ZIPlimits;
causeForRejection с prompt injection остаётся текстом. Новые фикстуры
синтетические, реальные retained/source XML не копируются в tests.

## Acceptance первого runtime probe и следующего storage slice

1. Root выбирает одно region50/day/purchaseRejection окно под общим lease,
   existing quota и bounded bytes/archive/poll limits. Exact selection,
   requestUID и все returned archive links связаны до скачивания.
2. NO_DATA — отдельный outcome; не подтверждает отсутствие отмен вообще и
   не заменяет live proof структуры. При READY обработать каждый member;
   отдельный shape/source-quality report и pinned full-XSD16.2/16.3.
3. Сверить eventGUID, точный cancelNoticeRegistrationNumber и timestamps
   с официальным source XML/карточкой выбранного номера; измерить реальные
   missing/naive поля. Incoming schemaLocation не загружать.
4. Новый event store не добавляет family в notice-version enum. Tenant RLS,
   immutable raw/evidence, replay/conflict, unresolved link, query-bound
   consumer projection и неавтоматическое снятие cancellation blocker.
5. Isolated PG: same event replay, collision rollback/evidence, другойtenant,
   событие до notice, несколько событий, stale notice с новым событием;
   positive current/reinstatement outcome не выводится из отсутствия данных.
6. Search/comparison/estimate используют единый event gate и показывают
   reason+provenance; current cancellation coverage UNKNOWN пока нет
   complete fresh scope и подтверждённой семантики восстановления.

Это предлагаемая последовательность. Ни runtime события, ни live admission,
ни полная обработка отмен223 пока не подтверждены данным исследованием.
