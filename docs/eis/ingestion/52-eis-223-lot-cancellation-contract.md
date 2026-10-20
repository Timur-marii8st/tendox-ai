# S171 M1: официальный контракт отмены лотов 223-ФЗ

Исследование **2026-10-03**, владелец Research subagent. Owned file — только
этот документ. Источники: сохранённые официальные NSI/XSD16.2/16.3,
docs/50 и текущие `eis_223_events.py` / `eis_223_archive.py`.
Новых запросов getDocsIP/getNsi, admission, изменения кода и deploy не было.
XML здесь — схема и синтетические проверки, не новый live proof отмены.

## Выбранное семейство и evidence

Точный код **`purchaseLotCancellation`**, NSI **item18**, subsystem `RI223`,
distributedPublicly=true, actual=true, название «Отмена лотов закупки».
NSI item80 — другая family `purchaseRejection`, отмена всей закупки.
Первый запрос следующего runtime slice должен использовать
`documentType223=purchaseLotCancellation`, `subsystemType=RI223`, выбранные
root region/day/offset. Политика public/actual подтверждена сохранённым
каталогом от26.09.2026; lastUpdateDate записи18 — `2025-01-01T00:00:00`.
Это не проверка свежести каталога на текущий момент.

Официальные первичные URL: [XSD16.2](https://zakupki.gov.ru/epz/main/public/download/downloadDocument.html?id=44009),
[XSD16.3](https://zakupki.gov.ru/epz/main/public/download/downloadDocument.html?id=44431),
[раздел223](https://zakupki.gov.ru/epz/main/public/document/view.html?searchString=&sectionId=386&strictEqual=false).
Повторное сетевое скачивание не требовалось: проверены сохранённые первичные
файлы и полные fingerprints через существующий `load_schema_tree`.

| Материал | SHA-256 |
|---|---|
|purchase.xsd16.2|`712e818f74bf3d38a03a3516533d0d4bf1df343f5a6e2056ae38a35f9ee7975b`|
|purchase.xsd16.3|`c5ad9bec7a1d1ba393f818e48a6f066db0428ce939cf9f4066acfc23ac0f7411`|
|Types.xsd, одинаковый файл обеих releases|`5737269f17857fc8dd646617e10d81f2de797b673f75812618ce1ae6c6442265`|
|Полное дерево16.2, policy fingerprint|`44cb86105da216b5f53071d5a1f652d09d83f877d611379d693c99a669a32520`|
|Полное дерево16.3, policy fingerprint|`2aa76beed7df0f8ea004bf67609da629c9f91ad9b887d50f04f1369af96baff0`|
|NSI XML, повторно проверен|`d19ed89d6918ca2f93389b9e609c7301998637f30205b2fb3c3105d431fa472a`|

Container roots:
`/var/lib/eis-browser/research/223/local-eis-supplier/schemas-16.2/`,
`schemas-16.3/`. NSI архив:
`/var/lib/eis-browser/research/catalog/local-eis-supplier/contract-223-8affb026-ee7a-4c93-9ac8-dfa4f7014ad2-1.zip`,
member `nsiDocumentTypes223_all_20260926021011_0.xml`.
Exact NSI locator: `nsiDocumentTypes223/body/item[18]/{documentType,subsystem,
distributedPublicly,actual}` в namespace `http://zakupki.gov.ru/223fz/reference/1`.
Host prefix для этих artifacts:
`/var/lib/docker/volumes/vibe-seller_eis_browser_state/_data/research/`.

Узлы `purchaseLotCancellation`, `purchaseLotCancellationItemType` и
`purchaseLotCancellationData` совпали между двумя releases при одинаковой
ElementTree сериализации. Это структурное сравнение проверенных узлов, не
утверждение равенства полных purchase.xsd (их SHA различаются).

## Exact paths и последовательность

`p=http://zakupki.gov.ru/223fz/purchase/1`,
`t=http://zakupki.gov.ru/223fz/types/1`; элементы qualified.
Root `{p}purchaseLotCancellation` расширяет `t:packetType`.
Data type называется **`purchaseLotCancellationData`**, без суффикса Type.

**D** = `/p:purchaseLotCancellation/p:body/p:item/p:purchaseLotCancellationData`.
**C** = `D/p:cancelledLots/p:cancelledLot[i]`.

| Роль | Exact path | Тип / обязательность |
|---|---|---|
|GUID пакета|`/p:purchaseLotCancellation/t:header/t:guid`|t:guidType, required|
|Время пакета|`.../t:header/t:createDateTime`|xs:dateTime, required|
|GUID item|`/p:purchaseLotCancellation/p:body/p:item/t:guid`|required, не GUID события|
|GUID события|`D/p:guid`|required, глобальный идентификатор сведений|
|Создание события|`D/p:createDateTime`|xs:dateTime, required|
|Публикация события|`D/p:publicationDateTime`|xs:dateTime, optional|
|Организация|`D/p:placer/t:mainInfo`|customerInfoType, required|
|Номер закупки|`D/p:purchaseInfo/t:purchaseNoticeNumber`|registrationNumber11Type, required|
|GUID закупки|`D/p:purchaseInfo/t:guid`|optional; не GUID события/лота|
|Публикация извещения|`D/p:purchaseInfo/t:publicationDateTime`|optional, не публикация отмены|
|Перечень лотов|`D/p:cancelledLots/p:cancelledLot`|1..unbounded, required|
|GUID в записи отменяемого лота|`C/p:guid`|t:guidType, required; семантика неоднозначна ниже|
|Номер лота|`C/p:ordinalNumber`|xs:int, required; не индекс массива|
|Предмет|`C/p:subject`|nonEmptyString≤2000, required; не ключ связывания|
|Совместный лот|`C/p:jointLot`|xs:boolean, required|
|Индивидуальное решение|`C/p:cancellation/t:cancelDate`, `/t:cancelInfo`, optional `/t:emergency`|cancellation optional; если есть, date+info required|
|Режим причины|`D/p:descriptionType`|required COMMON/VARIOUS|
|Общее решение|`D/p:cancelDate`, `D/p:description`|оба optional; date / nonEmptyString≤2000|

Полный порядок Data: guid; optional urlEIS/urlETP/urlVSRZ/urlKisRmis;
createDateTime; optional publicationDateTime; placer; purchaseInfo;
cancelledLots; optional attachments; descriptionType; optional emergency;
optional cancelDate; optional description; optional signatureAuthorizedBody.
У root после t:header и optional t:signature допускается optional
p:extendedType перед p:body. Ничего из signatures/XSLT не исполняется.

Порядок purchaseInfo: optional t:guid; t:purchaseNoticeNumber;
optional t:publicationDateTime; required t:name; choice t:purchaseMethod
**ИЛИ** sequence optional t:purchaseMethodCode + optional t:purchaseCodeName;
optional t:emergency. Для синтетического minimum использован purchaseMethodCode=1.

Порядок cancelledLot: p:guid; p:ordinalNumber; p:subject; p:jointLot;
optional p:cancellation. В cancellation дочерние элементы уже **t:**,
а GUID/ordinal в cancelledLot — **p:**. Перенос namespace из notice parser
без проверки создаст неправильный reader.

## Связь с извещением и лотом: что известно и что нельзя предполагать

В source notice лот имеет `.../p:lots/t:lot/t:guid` с annotation
«Глобальный идентификатор лота» и `t:ordinalNumber` — номер лота в извещении.
В событии `C/p:guid` имеет annotation **«Глобальный идентификатор закупки»**.
Имя узла и положение в cancelledLot не устраняют это противоречие.
XSD не задаёт keyref на notice lot, не проверяет GUID equality или ordinal
uniqueness и не ссылается на точную редакцию извещения.

Предлагаемая строгая последовательность association:

1. Exact company/law223/business number — обязательная граница. Проверить
   `purchaseInfo/guid`, если он и `notice.purchase_guid` доступны; конфликт
   не обходить совпадающим номером. GUID события/пакета не substitute.
2. Source ordinal ищется по `lot.ordinal.raw/value`, а не Python/SQL/JS array
   index. Один номер в source и position i — разные значения. Не переводить
   отсутствующий номер в1, не сопоставлять по названию предмета.
3. Нужна уникальность lot ordinal и GUID внутри конкретной версии. Duplicate,
   missing, nonpositive или несколько возможных связей → unresolved/UNKNOWN
   и review hold. Положительный ordinal — предлагаемая policy сверх XSD.
4. До отдельного live подтверждения значения cancelledLot/guid прямое
   равенство с notice lotGUID — наблюдаемое совпадение, не доказанный общий
   контракт. Расхождение GUID/ordinal и отсутствие GUID не дают PASS.
5. Показать событие на уровне закупки, но не маркировать все лоты отменёнными.
   Для ambiguous association допустима проверка/hold неопределённого scope,
   отдельно от подтверждённого FAIL конкретного лота. Неучтённые лоты не
   становятся разрешёнными только потому, что отсутствуют в данном событии.

Существующий `Eis223Lot.guid` nullable/defaultNone, `purchase_guid` также
nullable; часть legacy snapshots не несёт этих полей. Null не разрешает
fallback на ordinal/позицию с заявлением exact GUID match. Возможна отдельная
derived projection из сохранённого exact XML с parser version/provenance;
immutable source snapshots нельзя молча переписать.

Event identity хранится отдельно: tenant+law+family+eventGUID и XMLSHA/version
evidence, как в S170. **В схеме нет source version, notice version, status,
cancelled или reversal flag.** Новая версия notice с cancelled=false не
доказывает отмену события. Same eventGUID с иными bytes требует явного conflict
handling, а не last-wins; текущая стадия и восстановление UNKNOWN.

## COMMON, VARIOUS и даты

Комментарий `lotCancellationType` определяет COMMON: общая причина на Data;
VARIOUS: причина у каждого отменяемого лота. Но presence полей в XSD optional.
Следовательно, schema PASS не подтверждает наличие решения/причины по каждому
лоту. COMMON без общего cancelDate/description и VARIOUS без cancellation
нуждаются в отдельном semantic evidence статусе.

`cancelDate` — **xs:date**, допускающий timezone offset, но без времени суток.
Сохранять raw/calendar date и precision; не создавать datetime00:00 для
сортировки с publication timestamp. Naive source dateTime также допустим поXSD:
не назначать MSK/UTC по региону/ingest time. Event publication и purchaseInfo
publication принадлежат разным сущностям; не заменять одно другим.
Будущая date, невозможный порядок и недостаточная точность дают UNKNOWN/review.

## Offline доказательства и fixture guidance

03.10 `load_schema_tree` подтвердил pinned полные деревья16.2/16.3.
В памяти построен минимальный синтетический XML; schemaLocation не загружался,
DTD/entities/network отключены. Никакой реальный source XML не записывался вtests.

| Синтетический случай |16.2|16.3|Вывод для runtime|
|---|---|---|---|
|COMMON без date/cause/publication|PASS|PASS|Нужен отдельный completeness gate|
|VARIOUS без per-lot cancellation|PASS|PASS|Не считать отсутствующие решения полными|
|ordinalNumber=0|PASS|PASS|XSD не задаёт positive ordinal|
|ordinalNumber=-1|PASS|PASS|Нужна явная policy, не array indexing|
|Две одинаковые cancelledLot записи|PASS|PASS|Уникальность проверяет наш код|
|Все dateTime без timezone|PASS|PASS|Aware time не доказан|
|cancelledLot/t:guid вместо p:guid|FAIL|FAIL|Exact namespace обязателен|

Положительная базовая fixture: разные header/item/event/cancelledLot GUID,
synthetic number32600000001, placer inn7700000000/kpp770001001,
purchaseInfo/name и purchaseMethodCode1, ordinal7, subject, jointLot=false,
descriptionTypeCOMMON. Числа синтетические; schema PASS не подтверждает
юридическую валидность INN или реальное существование организации.

Дополнительные обязательные tests: ordinal7 у первого элемента массива;
один cancelled lot из двух; conflicting purchaseGUID; совпадающий ordinal и
разные GUID; один GUID при разных ordinals; duplicate event variants; отсутствующий
notice; naive publication; date-only decision; COMMON+индивидуальная причина;
VARIOUS+общая причина без индивидуальной; вложенный shadow purchase number;
oversized cancelledLots и attachments; no partial successful window при reject.

## Следующий proof и критерии завершения

Для live допуска нужен один явный purchaseLotCancellation region/day scope,
root lease и existing budgets, все returned archives и exact source selection.
NO_DATA не доказывает shape. До live pair cancellationXML ↔ exact noticeXML
приоритет — reader/source evidence с association UNKNOWN. Требуется сверить
несколько отменяемых лотов, GUID и source ordinal, whole/purchase GUID,
publication/decision precision и поведение новой версии notice.

Завершённый runtime slice должен раздельно показывать source schema quality,
association quality, historical event evidence, operation hold и текущую
стадию UNKNOWN. Проверяются tenant isolation, immutable/replay/conflict,
nonmatching lot unaffected-by-this-event и no false PASS при unknown coverage.
Ни факт события, ни XSD PASS не заменяют КП, ТЗ и три сценария экономики.
