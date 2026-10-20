# S169: повторная проверка сохранённой выборки purchaseNotice

Дата: **2026-10-03**. Владелец: Research subagent. Owned file: только этот
документ. Задача: проверить точные source shapes и передать граничные случаи
для reader/tests. Зависимости: [контракт семейства](47-eis-223-general-notice-contract.md),
S152 retained ZIP/XSD, M1 нового reader. Это read-only исследование;
admission, source API, getNsi/getDocsIP, DB writes, deploy не выполнялись.
Статус сохранённого полного sample остаётся **SOURCE_REJECTED**.
Текущая действительность закупок и полное покрытие UNKNOWN.

## Вход для cached parser proof

Scope из сохранённого selection sidecar:

| Поле | Значение |
|---|---|
| company_id | `local-eis-supplier` |
| family / subsystem | `purchaseNotice` / `RI223` |
| region / day / offset | `50` / `2026-10-01` / `+03:00` |
| request_id | `17911292-48dd-4892-90ac-0caaa3b67013` |
| ZIP bytes / SHA-256 | `2778437` / `7dfacc0da896a1779b01430c4981096363394303c3582c6c0a8373c412eefb40` |

Container artifact:
`/var/lib/eis-browser/research/223-families/local-eis-supplier/purchaseNotice/17911292-48dd-4892-90ac-0caaa3b67013-1.zip`.

Absolute host artifact:
`/var/lib/docker/volumes/vibe-seller_eis_browser_state/_data/research/223-families/local-eis-supplier/purchaseNotice/17911292-48dd-4892-90ac-0caaa3b67013-1.zip`.

Selection расположен рядом, basename
`17911292-48dd-4892-90ac-0caaa3b67013-selection.json`.
Старый reject proof рядом:
`17911292-48dd-4892-90ac-0caaa3b67013-replay-20261002T095250029410Z-proof.json`.
Читать exact bytes без изменения ZIP/member names/sidecar; новый cached proof
не должен переписывать старый или переименовывать окно в успешное.

Официальные схемы: [пакет16.3](https://zakupki.gov.ru/epz/main/public/download/downloadDocument.html?id=44431),
[пакет16.2](https://zakupki.gov.ru/epz/main/public/download/downloadDocument.html?id=44009).
Проверялись сохранённые локальные деревья
`/var/lib/eis-browser/research/223/local-eis-supplier/schemas-16.2/` и
`schemas-16.3/`; первичное получение и fingerprints — docs/37/47.
Новых сетевых обращений к этим URL не было.

## Точные размеры и shapes

Подсчёт включает **все25XML**, в том числе schema-invalid member; это inventory,
не25допущенных карточек. Внутри25XML находятся **23различных номера** и25лотов.

Префиксы: `p=http://zakupki.gov.ru/223fz/purchase/1`,
`t=http://zakupki.gov.ru/223fz/types/1`. База
`D=/p:purchaseNotice/p:body/p:item/p:purchaseNoticeData`;
`L=D/p:lots/t:lot[i]`, `A=D/p:attachments`.

| Path/признак | Количество | Семантика |
|---|---:|---|
| `L/t:lotData/t:initialSum` |20| Исходная initial sum |
| `L/t:lotData/t:maxContractPrice` |5| Другая семантика максимальной цены договора;4различных номера |
| `initialSumInfo`, `priceFormula`, `commodityPrice`, `commodityPriceRub` |0каждый| Схема допускает, sample не проверяет live |
| `startingContractPriceRub`, `maxContractPriceRub` |0каждый| Не подтверждены live sample |
| `L/t:lotData/t:currency/t:code=RUB` |25| Точный source currency code |
| `.../t:digitalCode=643`, `.../t:name=Российский рубль` |25каждый| Согласованный observed currency branch |
| `.../t:letterCode` |0| Только schema evidence |
| `A/t:totalDocumentsCount` |25| Во всех25равно числу прямых document этого XML |
| `A/t:document` |157| Сумма элементов по версиям; не число уникальных файлов |
| `A/t:documentFS`, `A/t:prevDocument`, `A/t:additionalDocumentsCount` |0каждый| Требуют synthetic fixtures, а не утверждения live coverage |
| `document/{t:guid,t:fileName,t:url,t:contentUid}` |157каждый| Все перечисленные поля присутствуют |
| `document/t:content` |0| Embedded binary branch не встречается |
| `document/t:notPlacement` |0| В157элементах отсутствует; не наблюдение157false |
| `D/p:submissionCloseDateTime` |19| Все19значений naive;6XML без поля |
| `D/p:isLotOriented` |24false,1true| True member не имеет notice-level deadline |
| `D/p:status` |25P| Размещено, не подтверждённая открытая подача |
| `D/p:hidePurchase` |25false| Флаг конкретного snapshot |
| `D/p:hidePurchaseCustomerAccredited`, `D/p:isUploadComplete`, `D/p:forSmallOrMiddle` |0каждый| Missing сохраняется UNKNOWN |
| `L/t:lotData/t:forSmallOrMiddle` |3true,22false| Ограничение МСП существует на уровне лота |
| `L/t:cancelled` |25false| Не доказывает отсутствие более позднего event |

Важно: общий тип `purchaseNotice` **не означает отсутствие ограничений МСП**.
Три observed лота с true: `32616427233v1`, `32616429672v1`,
`32616430345v1`; source ordinal у каждого1. Проверка только top-level
forSmallOrMiddle потеряет уже встречающееся ограничение.

## Public source cases для M1

Все суммы — исходные decimal strings, валютаRUB, lot ordinal1.
Они не supplier quotes, не unit price и не доказательство прибыли.

| Номер / версия | maxContractPrice | XML SHA-256 |
|---|---:|---|
|32616427233 /1|688484.7|`a3fd3f4a7aac1ede309e2206c91a0e74afc026361f34aef590a610b2ac34ed5b`|
|32616379346 /2|369076162.77|`38ad362bacac720cb4994b4b77a8f62b278175b43efd72a89cd5bfceffd1dc67`|
|32616428604 /1|7000000|`60a61beb3aa9c32d43b211d27a904b14fc2f7e2c685e740d59e675c428ae56c6`|
|32616430135 /1|20647471.13|`cc75e5f28cf4e4825b0277843c41006935f44235c970a976259119f61a4e6f44`|
|32616379346 /3|369076162.77|`b8c7bfee6d39287ddc1be3699d3c1e9297e22edf4d16fcea9e21899a0f5af860`|

Lot-oriented case: `32616430345v1`, XMLSHA
`d6e099c566944bb9106c8b24eb0b9ed3e481a7951305c8bcfbcb8e0bde92f60c`.
`D/p:isLotOriented=true`; `D/p:submissionCloseDateTime` отсутствует.
Не выводить срок из publication/createDateTime или произвольного dateTime
в template. Таймзона/дедлайн выбранного лота UNKNOWN.

## Header и внешние rendering references

Во всех25XML:

- `/p:purchaseNotice/t:header/{t:guid,t:createDateTime}`;
- `/p:purchaseNotice/p:body/p:item/t:guid` и один `p:purchaseNoticeData`;
- `/p:purchaseNotice/p:extendedType` с `t:contentUid`, `t:cryptoSigns`,
  `t:xsltFileDsUid`.

В observed header нет business status/visibility flags. Пакет GUID,
item GUID и Data GUID — разные роли; registrationNumber/version берутся
только из прямого Data. Флаги выше находятся в Data/lotData.

ExtendedType — расширенная печатная форма по XSD. Её ссылки находятся вне
attachments.157document не означает157всех XML content references. Не выполнять
XSLT/подписи, не скачивать expanded rendering references в обход существующего
exact-manifest/source contract; если они не поддержаны, границу явно указать.

Все25root содержат `xsi:schemaLocation` со значениями TFF-16.2. Оно не загружалось
и не использовалось как разрешение сетевого доступа. Sample валидировался
против локальных retained16.2 и16.3 независимо от строки source.

## Граничные случаи для синтетических fixtures

**Currency choice:** XSD currencyType допускает `letterCode` **ИЛИ** sequence
`code? + digitalCode`, затем optional name. `letterCode=RUB` без digitalCode
может быть schema-valid. `letterCode + code` одновременно нарушает choice;
не принимать конфликт как fallback. `code` optional при наличии digitalCode:
голый643не должен автоматически становиться валютой без отдельного явного
нормализующего контракта. Все raw fields сохраняют свои locators.

**Manifest choice:** documentListType содержит optional total, additional,
повторяемый prevDocument/guid, затем choice повторяемых document **ИЛИ**
documentFS. FS имеет guid/contentUid, но не содержит fileName/url по этому
типу. Не придумывать эти поля, URL или equivalence с document. previous/additional
не считаются скачанными без resolved exact refs. Mixed document+documentFS
fixture полезен как invalid choice; валидный FS-only — отдельный случай.

**Flags:** missing, false, true и invalid literal различать. Source
notPlacement=true не разрешает скачать скрытое вложение; наличие безопасного
URL не отменяет этот флаг. Header shadow flag не должен заменять Data flag.
Lot MSP true с отсутствующим top-level — уже observed, обязательная регрессия.

**Deadlines/цены:** aware/naive/missing, lot-oriented true с общим deadline
и без него, max-price безinitialSum, text-only/formula branches,
cross-currency conflict. Source ceiling(kind) остаётся отдельным фактом;
economics не получает цену через переименование maxContractPrice вinitialSum.

## XSD результат и границы proof

В этом запуске повторная offline lxml validation полного25member набора:

| Schema | PASS | FAIL |
|---|---:|---:|
|16.2|24|1|
|16.3|24|1|

Одинаковый FAIL: `32616427936v1`, XMLSHA
`f757773297c1e2aa1baa88b2f7ae6e7a0672f6ac23b69f77331f1aadae34a03c`.
`D/p:placingProcedure` не содержит обязательный `p:summingupDateTime`.
Исходник не исправлялся, member не исключался, retained proof не менялся.

Новый cached parser proof после M1 должен отдельно показать25processed members,
23номера,25лотов,20initial/5maximum prices,19naive/6missing deadlines,
157listed document entries и24/1quality per release. Если выбран строгий
all-or-nothing admission, весь архив остаётся rejected. Если root отдельно
утвердит metadata/schema split, FAIL остаётся привязан к точномуXML и не
становится eligibility PASS; исходное evidence сохраняется.

Это inventory и source-quality evidence, не current-source refresh. Нет
новой live проверки закупок/отмен, прав участия, полногоТЗ, действительногоКП
или сценариев экономики. Реальные source bytes не копировались в test fixtures;
unit fixtures должны оставаться синтетическими.
