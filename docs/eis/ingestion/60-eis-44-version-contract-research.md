# S177: идентичность и версия извещения44-ФЗ

Дата исследования:2026-10-04. Владелец: acquisition_research.
Только официальные retained XSD ЕИС и чтение текущего parser; без getDocs POST,
токенов, SQL mutations или изменений runtime. Root отдельно исследует пару
XML закупки0373100047426001450/version1/epNotificationEF2020.

## Вывод для решения

**Официального основания выбирать поздний XML по publishDTInEIS не найдено.**
versionNumber описывает номер версии документа, а id — идентификатор документа
ЕИС. Реестровый purchaseNumber идентифицирует закупку. Схема не утверждает,
что тройка purchaseNumber/type/versionNumber однозначно определяет все байты
выгрузки; одновременно не даёт разрешения игнорировать конфликт времён.

startDT является бизнес-датой: схема требует заполнять его фактическим временем
публикации **первой версии** по местному времени размещающей организации.
Поэтому парное изменение publishDTInEIS/startDT на87секунд нельзя объявить
служебным processing artifact только из-за малой величины изменения.
Повторная публикация, исправление экспортера, разная обработка или другой
документ — возможные гипотезы, ни одна здесь не подтверждена.

## Источники и воспроизводимость

Официальный [раздел технической документации ЕИС](https://zakupki.gov.ru/epz/main/public/document/view.html?searchString=&sectionId=432&strictEqual=false),
[интеграционные схемы16.3,ZIP id44404](https://zakupki.gov.ru/epz/main/public/download/downloadDocument.html?id=44404).
Публикация19.09.2026 по retained acquisition evidence ADR0044.
04.10повторно прочитан тот же официальный архив на VPS:
`/home/syurai/vibe-seller-state/s146-official-schemas.zip`.
SHA256 `4313b235fcfbce1e32a610cdef1f68449d23de617c15fd7487bad8cb933d86d7`.

Имена ниже относительно общего верхнего каталога ZIP
`æσÑ¼δ 16.3 ¿ΓÑαáµ¿∩ 3/` (retained decoding имени).

| Schema | SHA256 | Нужные определения |
| --- | --- | --- |
| IntegrationEPTypes.xsd | `6de440e8ca71ea3b96122cab67638fd432c5c6e587529c150210d6eb0d6a4058` | notificationEF2020Type,notification2020Type,notification2020CommonInfoType,procedureCollecting2020Type |
| BaseTypes.xsd | `87d1ff0f99e29bd49918104e108780cd37b3186efce8dc61528c5dab2d116937` | versionNumberType |
| CommonTypes.xsd | `2bbf918c2d1063c9e7adafe6f03d94a32ad14e1ab28c3caaa8638471238a06e0` | printFormType |
| fcsExport.xsd | `b0ff5149d8bdb7c64179600e391ddb3221a8540122f7cf937a0bf60db651f151` | export/epNotificationEF2020 |

Точный locator аннотации: `xs:schema/xs:complexType[@name=TYPE]` и дочерний
`xs:element[@name=FIELD]/xs:annotation/xs:documentation` внутри sequence.
Для наследуемых полей следует пройти extension base, а не искать только
непосредственных детей notificationEF2020Type.

Поисковые запросы по официальному zakupki.gov.ru не дали дополнительного
официального объяснения same-version republish variants. Сторонние выдачи,
примерыXML и агрегаторы в выводы не включены. Отсутствие найденного описания
не доказывает, что механизм повторной выгрузки отсутствует в ЕИС.

## XML paths и точный смысл

Namespaces: `e=http://zakupki.gov.ru/oos/export/1`,
`ep=http://zakupki.gov.ru/oos/EPtypes/1`,
`c=http://zakupki.gov.ru/oos/common/1`.
`N=/e:export/e:epNotificationEF2020`.
fcsExport задаёт тип ep:notificationEF2020Type, расширяющий
ep:notification2020Type. Тот содержит commonInfo с extension
notification2020CommonInfoType.

| Путь от N | XSD / semantics по официальной аннотации |
| --- | --- |
| `ep:id` | optional xs:long; идентификатор документа ЕИС; при приёме изменения проекта обязателен |
| `ep:externalId` | optional base:externalIdType; внешний ID документа, уникальность проверяется в пределах размещающей организации |
| `ep:versionNumber` | optional base:versionNumberType; отсутствие/1 трактуется как первоначальная версия, иное значение как изменение; при приёме изменений контролируется последовательность |
| `ep:commonInfo/ep:purchaseNumber` | optional base:purchaseNumberType; номер закупки присваивается после размещения; нужен при приёме изменения |
| `ep:commonInfo/ep:docNumber` | optional base:documentNumberType; номер документа, присвоенный ЕИС, заполняется при передаче |
| `ep:commonInfo/ep:directDT` | optional xs:dateTime; автоматически заполняется датой направления текущей версии на размещение |
| `ep:commonInfo/ep:plannedPublishDate` | xs:date; планируемая дата публикации |
| `ep:commonInfo/ep:publishDTInEIS` | optional xs:dateTime; дата публикации документа ЕИС, игнорируется при приёме и заполняется при передаче |
| `ep:commonInfo/ep:href` | optional base:hrefType; ссылка на карточку размещённого документа |
| `ep:notificationInfo/ep:procedureInfo/ep:collectingInfo/ep:startDT` | optional xs:dateTime; игнорируется при приёме; фактическое время размещения первой версии в местном времени организации |
| `ep:notificationInfo/ep:procedureInfo/ep:collectingInfo/ep:endDT` | xs:dateTime; окончание подачи заявок |
| `ep:modificationInfo` | optional notification2020ModificationType; основание изменения,info/addInfo?/reasonInfo |

BaseTypes/versionNumberType = xs:int,minInclusive0. Это структурная XSD-граница;
parser сейчас принимает только>=1. Не превращать XSD-допустимый0 в подтверждённую
версию без отдельного контракта. Аннотация приёма не является гарантией
неизменности каждого XML, выгруженного сервисом отдачи.

## Непарсимые identity/evidence поля для сравнения root

Текущий notice parser сохраняет purchaseNumber,type,versionNumber,published_at,
deadline,цену,title,XML SHA,member,attachments иlot data. В отличие от event
ветки, notice snapshot не сохраняет отдельный source document id.
Перед любым изменением identity следует сравнить в обоих raw XML:

1. `N/ep:id` — наиболее прямой официальный ID документа. Разный id может
   различать source documents; одинаковый id не доказывает byte-equivalence.
2. `N/ep:externalId` вместе с `purchaseResponsibleInfo/responsibleOrgInfo`
   — локальная область уникальности, не глобальный GUID-допуск.
3. `commonInfo/docNumber`, `directDT`, `plannedPublishDate`, `href` и
   `modificationInfo` — контекст версии/направления/публикации.
4. `ep:printFormInfo`: CommonTypes/printFormType содержит ссылку/содержимое
   печатной формы, `c:dsUid` как ID документа ХД, `c:signature` и
   `c:signatureInfo/{c:url,c:dsUid}` для подписи ХД. Это ссылки на связанные
   артефакты, а не автоматически иной identity notice XML. Не скачивать их
   в рамках этого исследования.
5. Root/schemaVersion,attachment UIDs и служебные признаки можно сохранить
   как дополнительное raw evidence. Версия схемы не является версией закупки.

Если root уже подтвердил, что **все** поля кроме двух дат равны, изменение
парсинга id само по себе пару не разрешит. Тогда сохранять обе XML SHA и
member provenance как расходящиеся source observations одного semantic key;
текущий победитель/актуальная публикация остаются UNKNOWN.

### Подтверждение root по фактической паре

Root передал проверенные одинаковые значения: `id=44105096`,
`versionNumber=1`, `schemeVersion=16.2`, `docNumber=№0373100047426001450`.
Отличаются два времени выше иUUIDв имени XML. Retained identity proof:
`/var/lib/eis-browser/research/rejected/s177-identity-proof.json`,
SHA256 `7647d77c04981e7f7a45c4db388772d817e12e33104abf6012933a10dc0734dc`.
Это evidence root, не повторная независимая проверка XML данным агентом.
Добавлениеid не разрешает именно этот конфликт. Исследованный pinned пакет
16.3 описывает контракт; schemeVersion16.2самих XML не переименовывается в16.3
и не означает подтверждённую в этом исследовании валидацию по16.2.

### UUID имени файла и transport identity

В том же официальном getDocsIP-ws-api.xsd (SHA
`64b34c3af3b29daffb9ba10d48d23096830cf5e0a9c8bc969f0241e8ba6bd450`)
раздельно описаны: `docRequestUid` как ID ранее направленного запроса;
index `id/refId` как IDs запроса/ответа; `dsUid` в информации о prepared parts
как ID **архива** ХД. Ни одна проверенная аннотация не связывает UUID имени
вложенного XML с versionNumber/idnotice или приоритетом публикации.
Нельзя отождествить разныеUUIDmembers с этими полями только по форматуGUID.
Правило генерации/смены имени XML при повторной отдаче в исследованном XSD
не найдено. Имя остаётся source_member provenance, а не доказанным business
version или основанием выбрать одну из двух дат.

## Чего официальный источник не установил

- Нет найденного правила, что более поздний publishDTInEIS заменяет ранний
  при одинаковом id/versionNumber.
- Нет найденного разрешения исключить startDT/publishDTInEIS из сравнения
  исходных документов или считать их экспортным шумом.
- Нет подтверждённой связи87секунд с повторным подписанием/контролем/репликацией.
- XSD не задаёт приоритет ZIP-member order, archive filename или fetch time.
- Наличие xs:dateTime само по себе не требует timezone; сохранение raw и
  UNKNOWN для naive дат остаётся отдельным runtime-инвариантом.

Практический bounded контракт: отличать exact byte duplicate от semantic-key
collision; не выбирать earliest/latest без нового официального evidence.
Возможная изоляция одной конфликтной записи с сохранением обеих наблюдений
требует отдельного решения root о полноте окна и hard gates. Это исследование
не разрешает молчаливый пропуск конфликта или перевод всего окна в COMPLETE.
