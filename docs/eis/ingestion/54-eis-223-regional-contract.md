# S172: контракт регионального охвата getDocsIP / RI223

Дата проверки: 2026-10-03. Владелец исследования: acquisition_research.
Read-only SSH, сохранённые официальные XSD и переданный root snapshot nsiAllList; без собственных token/getNsi/getDocsIP calls,
изменений runtime или production. **XML-каталог действующих регионов не получен;
полнота регионального набора UNKNOWN. Позднее получен официальный публичный
selector с90 записями — см. финальное дополнение PUBLIC_KLADR_SELECTOR.**

## Решение для M1

**Обновление после discovery root:** nsiAllList получен и разобран,249 записей.
`nsiKLADR`, `nsiKLADRShort`, `nsiSubjectRF`, `nsiCustomerRegions` имеют
`isAvailableForServices=false`. Это предупреждение об availability, но не
проверенный отказ текущего getNsi: его собственная XSD-аннотация разрешает
публичные записи nsiAllList и не задаёт явного фильтра по этому флагу.
Смысл флага относительно старых/новых сервисов не уточнён. Следующий bounded
probe: `nsiCode44=nsiSubjectRF`, `nsiKind=all`; источник имеет явный kladrCode.

Для автоматического списка использовать официальный КЛАДР ЕИС: в XSD имеется
`nsiKLADRList/nsiKLADR`, записи `objectType=R` и `isActual=true`.
Это подтверждённый формат справочника, но его текущая доступность через сервис,
содержимое и преобразование `code` в двухсимвольный `orgRegion` пока не проверены.
Нельзя объявлять 01–99 перечнем действующих регионов, подставлять названия из
памяти, считать 00 запросом всех регионов или использовать отсутствие данных
одного окна как доказательство отсутствия региона.

Можно реализовать загрузчик с явным проверенным списком partitions и provenance
каталога. Начальный список всех регионов должен поступить из отдельно
проверенного snapshot, а не генерироваться диапазоном. До этого допустим
явно ограниченный региональный scope; статус ALL_REGIONS не подтверждён.

## Официальные источники и retained evidence

Источник XSD — [официальный ZIP ЕИС 16.3, id44404](https://zakupki.gov.ru/epz/main/public/download/downloadDocument.html?id=44404),
ранее сохранённый и описанный в ADR0044. Дата публикации по ADR0044 — 19.09.2026.
Повторно прочитан 03.10.2026, без повторного скачивания.

VPS `syurai@192.144.13.82`:

| Артефакт | Путь / SHA-256 |
| --- | --- |
| Полный официальный ZIP | `/home/syurai/vibe-seller-state/s146-official-schemas.zip`; `4313b235fcfbce1e32a610cdef1f68449d23de617c15fd7487bad8cb933d86d7` |
| `GetDocsWS/GetDocsIndividualPerson/getDocsIP-ws-api.xsd` | `64b34c3af3b29daffb9ba10d48d23096830cf5e0a9c8bc969f0241e8ba6bd450` |
| `fcsExport.xsd` | `b0ff5149d8bdb7c64179600e391ddb3221a8540122f7cf937a0bf60db651f151` |
| `IntegrationTypes.xsd` | `a60410248915b6fb5940473e4c08c9b6cf0120283b7cd96606b13cb371d32b60` |
| `BaseTypes.xsd` | `87d1ff0f99e29bd49918104e108780cd37b3186efce8dc61528c5dab2d116937` |

В ZIP 65 members; указанные имена имеют общий верхний каталог
`æσÑ¼δ 16.3 ¿ΓÑαáµ¿∩ 3/` (сохранённая ZIP-декодировка имени).
Извлечённое дерево:
`/var/lib/docker/volumes/vibe-seller_eis_browser_state/_data/research/eok/local-eis-supplier/schemas-16.3/`.
Контейнерный корень research — `/var/lib/eis-browser/research/`.

В `/research/catalog/local-eis-supplier/` проверены имена members всех четырёх
сохранённых ZIP: только `nsiDocumentTypesList_all_20260926020517_0.xml`
и `nsiDocumentTypes223_all_20260926021011_0.xml`. Ни `nsiAllList`, ни фактического
`nsiKLADR` в этом наборе нет. Поиск имён retained research также не обнаружил
таких snapshots. Это предел проверенного набора, не утверждение об отсутствии
каталога в ЕИС.

## orgRegion: точный смысл и ограничения

XSD: `getDocsByOrgRegionRequest/selectionParams/orgRegion`, тип
`orgRegionKladrType`. Тип — `xs:string` с **единственным** ограничением
`xs:length=2`; нет enum, числового диапазона или pattern.

Аннотация запроса описывает отбор по региону заказчика; аннотация orgRegion —
регион организации по КЛАДР. Это организационная координата окна. Она не
подтверждает место доставки, географию исполнения или возможность участия
поставщика. Как конкретно сервис выбирает организацию при заказчике/организаторе/
совместной закупке, данный XSD не разъясняет: не приписывать orgRegion строго
`placer` без отдельного source proof.

Соседние обязательные поля: `subsystemType`, выбор
`documentType44|documentType223`, затем `periodInfo`.
Для нашего направления `RI223` присутствует в официальном описании подсистем.
`exactDate` имеет тип xs:date; указанное смещение учитывается при отборе.
Официальные примеры XSD: регион50 `2023-02-10+03:00`,63 `+04:00`,75 `+09:00`.
Это примеры, не полный каталог часовых поясов и не требование вычислять offset
из номера региона. Для универсальных окон выбрать явную временную политику,
хранить offset в ключе/доказательстве окна; не приписывать всем регионам местную
полночь Москвы. Поля oneHourInfo: date/fromHour/offsetTimeZone; lag более2ч.

## Машиночитаемый каталог: подтверждённая структура

Namespaces:

```text
e = http://zakupki.gov.ru/oos/export/1
t = http://zakupki.gov.ru/oos/types/1
```

Записи: `/e:export/e:nsiKLADRList/e:nsiKLADR`.
Элемент nsiKLADR имеет тип `t:zfcs_nsiKLADRType`.
Поля этой записи квалифицированы namespace `t`, в следующем порядке:

| Поле | Тип / семантика |
| --- | --- |
| `t:code` | base:kladrCodeType, строка1–20символов |
| `t:parentCode` | тот же тип, optional |
| `t:objectType` | строка длины1; аннотация R=регион,D=федеральный округ,A=район,C=город,S=населённый пункт,L=улица |
| `t:fullName` | zfcs_longTextMinType |
| `t:shortName` | строка1–300 |
| `t:OKATO` | optional |
| `t:postCode` | optional |
| `t:isManual` | optional xs:boolean fixed=true |
| `t:updateDate` | xs:dateTime |
| `t:isActual` | обязательный xs:boolean |

Алгоритм после получения полного XSD-valid snapshot: namespace-aware parse,
отобрать строго `objectType == 'R'` и boolean `isActual == true` (учесть XML
лексемы true/1), сохранить исходные code/name/updateDate, ordinal XPath,
member/XML SHA и каталог scope. Не включать D и не использовать parentCode
как код региона. Отсутствующие/неожиданные поля и конфликтующие одинаковые
коды останавливают принятие нового snapshot.

**Граница:** тип code1–20 не доказывает, что реальные R-коды имеют длину2.
Не делать `.zfill(2)`, `[:2]` или усечение до наблюдения фактического формата
и подтверждения преобразования. Число записей, список кодов, первая реальная
запись, freshness и полнота каталога сейчас UNKNOWN. Реальную XML-строку
региона в этом исследовании привести невозможно; примеры50/63/75 выше
взяты только из аннотации запроса.

## Следующий узкий source шаг (требует отдельного lease)

getNsiRequest официально допускает
`selectionParams/(nsiCode44|nsiCode223)` и `nsiKind=all|inc`.
Точный документированный bootstrap — **`nsiCode44=nsiAllList`, `nsiKind=all`**.
Далее брать код из реальной записи каталога, а не предполагать, что имя XML
автоматически равно request value. `nsiKLADR` — проверенное имя XML и кандидат
для discovery, но ещё не подтверждённый актуальный request value.

В `IntegrationTypes.xsd` тип `zfcs_nsiAllListType` содержит:
`code,name,isAvailableForServices?,dayOfWeek?,hourOfDay?,periodInHours?,
dsAllUnloading?,dsIncUnloading?,as2Unloading?,updateDate,isActual,isHidden?`.
`isHidden` при присутствии fixed=true. Проверить актуальность, публичность и
доступность сервиса перед запросом найденного KLADR-кода. Отсутствующий
isAvailableForServices не превращать в true. Наличие схемы не доказывает,
что каталог сейчас доступен для полной выгрузки.

Для сравнения, отдельный 223 reference.xsd имеет
`/r:nsiAllList223/r:body/r:item` (r=`http://zakupki.gov.ru/223fz/reference/1`)
с code/description/actual/hidden/exportTag и flags выгрузки. Его SHA
`5f8521081325820847103de9faed83abf38d3a22d9aa3077277b2afa34e9f10b`;
путь `/research/223/local-eis-supplier/schemas-16.3/reference.xsd`.
223 root называется nsiAllList223, тогда как bootstrap request в getDocs XSD
описан как nsiAllList; не смешивать XML-root и request-code.

Если полный КЛАДР слишком велик, нельзя молча скачивать его на ноутбук:
сначала проверить размеры archive set, выполнить bounded server-side extraction
региональных R-записей и сохранить происхождение полного snapshot. Маленькая
региональная проекция не означает, что полная загрузка справочника мала.

## Acceptance универсального списка

1. Сохранён официальный nsiAllList и подтверждена запись адресного каталога.
2. Известны полный archive set, schema validation, число всех/R/actual-R
   записей, дубликаты и exact mapping к orgRegion; ни один cutoff не замолчан.
3. Каталог публикуется атомарно с SHA/checked_at/source dates; при ошибке
   предыдущий snapshot остаётся с явным stale/UNKNOWN, не заменяется пустым.
4. Изменения кодов добавляют partitions, снятые коды сохраняют исторический
   audit. noData/error/unsupported различаются и не удаляют код автоматически.
5. Runtime proof отдельно подтверждает выбранные orgRegion/type/day окна;
   каталог не доказывает полноту или свежесть документов по каждому региону.

Официальный web-поиск не дал пригодного регионального snapshot; публичный
кандидат URL КЛАДР не открылся через web-инструмент. Сторонние списки и
исторические налоговые коды не использованы. Новые source calls не выполнялись.

## Фактический nsiAllList: результат отдельного root discovery

Root выполнил разрешённый discovery и передал READY snapshot для read-only
разбора. Здесь authenticated calls не выполнялись.

- Контейнерный путь:
  `/var/lib/eis-browser/research/regions/nsiAllList-a305e3418068f652729b8ba6b34e12b0ae9aafc2fb3e7e1e6ce2836d377c9545.zip`.
- Host prefix: `/var/lib/docker/volumes/vibe-seller_eis_browser_state/_data/`.
- ZIP12086bytes, SHA256 `a305e3418068f652729b8ba6b34e12b0ae9aafc2fb3e7e1e6ce2836d377c9545`.
- Один member `nsiAllList_all_20261003020034_0.xml`,155103bytes,
  SHA256 `48ec93b50287ada5b282b3cb441d554b2140e8ec86f2dc52e20cf9c954fe4eae`.
- SHA ответа, переданный root (не перечитан здесь):
  `f27126f27d5e72b5c619eb50c0fe65951e5063981b2b39dee2ae325f0f147e52`.

**Фактический XPath записей**:
`/e:export/e:nsiAllList/e:nsiAllList` — wrapper и item имеют одинаковое имя.
Прежний research parser, ожидавший другой тег списка, давал ложные0 записей;
namespace-aware чтение этого XPath даёт249. Значения дочерних полей — namespace t.
Не применять `.//nsiAllList` без проверки уровня: wrapper не является записью.

| Ordinal1-based | t:code | isActual | isAvailableForServices | dsAllUnloading / dsIncUnloading | isHidden |
| --- | --- | --- | --- | --- | --- |
|154|nsiSubjectRF|true|false|true / true|отсутствует|
|175|nsiCustomerRegions|true|false|false / false|отсутствует|
|191|nsiKLADRShort|true|false|true / true|отсутствует|
|221|nsiKLADR|true|false|false / false|отсутствует|

`nsiKLADRShort` name=`КЛАДР (сокращенная выгрузка)`, updateDate raw
`2026-06-02T18:55:38.963963`; nsiKLADR name=`Классификатор адресов Российской
Федерации (КЛАДР)`, updateDate raw `2026-06-02T18:55:38.965487`.
Оба timestamps без timezone: не превращать в aware watermark.
isHidden отсутствует согласно optional/fixed=true модели; явного true нет,
но это не отменяет явного запрета доступности через сервис.

Точные кандидаты payload:
`getNsiRequest/selectionParams/nsiCode44=nsiSubjectRF`, `nsiKind=all`
(приоритетный узкий каталог), затем при необходимости `nsiKLADRShort`/all.
Это исследование доступности, а не доказанная загрузка; root выполняет его
под source lease с ограничением архивов/байт. Ошибка сервиса остаётся ошибкой,
не подтверждением отсутствия регионов.

Повторная сверка по просьбе root: nsiDocumentTypes item132 имеет service=true,
dsAll=true; nsiAllList item225 тоже. Их успешные вызовы не опровергают false
для региональных каталогов. Но XSD getNsiRequest явно описывает допустимые
коды как значения nsiAllList; `isAvailableForServices` там не упомянут.
Аннотация самого флага говорит о возможности получения через сервисы отдачи
без уточнения поколения сервиса. Поэтому первоначальный вывод исследования
«следующий запрос не поддерживается» заменён на **UNKNOWN до bounded probe**.

### Более узкий nsiSubjectRF и явный mapping

Подтверждённый XSD XPath:
`/e:export/e:nsiSubjectRFList/e:nsiSubjectRF`, тип `t:zfcs_nsiSubjectRFType`
в тех же fcsExport/IntegrationTypes с SHA выше. Последовательность:
`t:code` (код субъекта,строка1–4), `t:kladrCode` (optional,КЛАДР,строка1–20),
`t:fullName`, `t:updateDate`, `t:isActual`.
Для orgRegion использовать **kladrCode**, не автоматически code. Реальные
длина/формат и наличие kladrCode требуют наблюдения snapshot. Отсутствие
не восполнять догадкой. Такой каталог по смыслу уже полного адресного КЛАДР;
малый размер является ожиданием, не измеренным фактом.

Другие найденные записи: nsiGAR (ordinal84) unavailable; nsiOKER (88)
unavailable и неактуален. nsiEMInfo (190), nsiOKTMO (201), nsiOKTMOPPO (207)
доступны, но это соответственно список информационных систем/муниципальные
классификаторы, а не доказанный каталог orgRegion КЛАДР. Подменять ими orgRegion
или выводить соответствие кодов без отдельного контракта нельзя.

Следующий исследовательский шаг — официальный публичный региональный
справочник/endpoint ЕИС либо проверенный актуальный источник КЛАДР с доказанным
mapping к orgRegion. Пока источник не найден, универсальный loader может
работать только с явно заданным reviewed scope и UNKNOWN полного охвата.

Root сообщил результат bounded `nsiSubjectRF/all`: **NO_DATA**, response SHA
`9a7d47ec614400ea18135c1cf5b57c80b6154000b66d0f3fee36f31a701592af`,
proof `/research/regions/s172-nsiSubjectRF-proof-...json` (точное имя в root run).
Архивов нет, БД не менялась. Это ответ конкретного запроса, не пустой список
регионов и не доказанный запрет метода.

Резервная проверка публичных источников: официальный
[ФНС: ФИАС](https://www.nalog.gov.ru/rn77/service/fias/) доступен, дата обновления
страницы07.10.2025; подтверждает использование ГАР и ссылается на fias.nalog.ru.
Сам fias.nalog.ru и публичный extendedsearch ЕИС через web-инструмент03.10
завершились timeout. Актуальные машиночитаемые региональные записи не получены;
налоговый список регионов сайта не принят за KLADR orgRegion без mapping proof.

Дополнение root: bounded `nsiKLADRShort/all` также вернул NO_DATA, response SHA
`ba3383c0ce9a14ad7d4d2962c825ce6cb2acb8b608c9d0efd107be0eda647ee2`.
Ни этот ответ, ни nsiSubjectRF NO_DATA не содержит фактического списка кодов.

### Публичный серверный транспорт

В ignored `tmp/s172-public-regions.py` и `.sh` создан bounded helper:
только HTTPS GET к zakupki.gov.ru,2MiB response cap, общий priority/import lease
и существующий host cooldown; marker cleanup через trap. Исходный публичный
URL: `https://zakupki.gov.ru/epz/order/extendedsearch/results.html`.
Playwright APIRequestContext с существующим SOCKS-прокси дважды завершился
ошибкой до HTTP-ответа; повтор с безопасной классификацией установил
certificate validation failure. Ответных байт и SHA нет. HTTPS-проверка
не отключалась. Промежуточные запуски возвращали COOLDOWN без HTTP-запроса.
Переход к существующему Chromium navigation transport (HTTPS verification
включён) пока не дал proof: wrapper завершился без helper output при активном
другом worker. Чужой worker/marker не удалялись. Исследование публичного
selector остаётся незавершённым, actual code list UNKNOWN.

## PUBLIC_KLADR_SELECTOR: полученный официальный список

После освобождения lease Chromium получил публичные ответы с обычной проверкой
HTTPS. CAPTCHA/access-control markers отсутствовали. Дочерние ресурсы страницы
блокировались, каждый следующий GET явно выбирался из уже прочитанного HTML/JS.
Все следующие артефакты лежат под `/var/lib/eis-browser/research/regions/`:
`public-<SHA>.bin` — точные response body bytes, `.json` — URL/status/bytes/
SHA/checked_at/final_url/transport. Это HTTP, не SOAP; response SHA равен body SHA.

| URL path на https://zakupki.gov.ru | UTC / HTTP / bytes | SHA256 |
| --- | --- | --- |
| `/epz/order/extendedsearch/results.html` | 2026-10-03T17:08:49.940995+00:00 /200/352504 | `8eee2ef4d0826f848da1303a54b5a59e1305bfa17a784c2625896256616cafbf` |
| `/epz/nsi/kladr/chooseRegion.html` | 2026-10-03T17:10:08.647275+00:00 /200/22514 | `b57a42d5ed113bc9460fc8b421ad00b4f6b5cd8ca3b2aae51ab61cd6a3b6f58d` |
| `/epz/static/js/openStreetMapCommonFunctions.js` | 2026-10-03T17:11:59.777073+00:00 /200/6464 | `2d8bb3ee6bc6e3abedeb51ac71857f2ab0e4efd68fa8f83c01d92024cecff0e7` |
| `/epz/api/nsi/subjectRf/regionIdByName.json?regionName=Московская` (UTF-8 percent-encoded query) | 2026-10-03T17:13:48.494410+00:00 /200/96 | `9d6439c140264bd9fc6ff75225289909ea111cda04c94d8078649104f9b5b5d8` |

URL каталога: [официальный selector КЛАДР ЕИС](https://zakupki.gov.ru/epz/nsi/kladr/chooseRegion.html).
Он обнаружен по фактическому href в extendedsearch HTML, затем fetched отдельно.
Структура: `div#modal-region`, внутри `div#region-select`,
`ul.select-vars.select-overflow > li.select-vars__item.select-text[id]`.
90 записей,90 уникальных id; все строго соответствуют `^([0-9]{2})0{9}$`.
Запись «Не выбран» не имеет id и исключается; **00 отсутствует**.

Примеры точных source rows:

```html
<li class="select-vars__item select-text" id="01000000000">Республика Адыгея (Адыгея)</li>
<li class="select-vars__item select-text" id="50000000000">Московская область</li>
<li class="select-vars__item select-text" id="63000000000">Самарская область</li>
<li class="select-vars__item select-text" id="75000000000">Забайкальский край</li>
<li class="select-vars__item select-text" id="99000000000">Иные территории, включая город и космодром Байконур</li>
```

Точный отсортированный список наблюдаемых префиксов:

```text
01,02,03,04,05,06,07,08,09,10,11,12,13,14,15,16,17,18,19,20,
21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,
41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,
61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,
83,86,87,89,90,91,92,93,94,95,99
```

Названия в HTML являются source labels ЕИС. Они сохраняются буквально; этот
технический каталог не используется как самостоятельное утверждение о
международном статусе территорий.

### Mapping и строгие границы

Предложенный parser принимает только закрытый URL/DOM-контракт, сохраняет
полный11-символьный id и source name, проверяет девять завершающих нулей,
после чего берёт двухсимвольный префикс как orgRegion. Это **контролируемое
структурное соответствие**, согласованное с root и официальными getDocs XSD
примерами50/63/75; в HTML нет отдельного поля orgRegion. Не обобщать усечение
на произвольный КЛАДР-объект. Не дополнять отсутствующие коды диапазоном.

Scope называется `PUBLIC_KLADR_SELECTOR`, не `NSI_ACTUAL_VERIFIED`.
HTML не содержит isActual/updateDate или признака полноты всех partitions
сервиса отдачи. Каталог задаёт проверенный **планируемый scope**, а source
availability/freshness/coverage каждой региональной partition подтверждаются
отдельными окнами. All-regions complete остаётся UNKNOWN.

JS `getRegionIdByName` делает GET к
`/epz/api/nsi/subjectRf/regionIdByName.json` с параметром regionName;
selector script использует `data.id` для выбора DOM элемента с тем же id.
В прочитанном JS нет явного преобразования id в двухсимвольный orgRegion.
Один bounded lookup по фактическому endpoint вернул точный JSON:

```json
{"id":"50000000000","name":"Московская область","actual":true,"kladrName":null}
```

Он подтверждает fullID selector и actual **одной** записи; не переносить actual
на остальные89 без evidence. kladrName=null не заменяет имя/код догадкой.
Для автоматического каталога lookup90имён не нужен: полные90 записей уже
сервером вложены в HTML. При изменении DOM/дубликатах/id shape/пустой выдаче
не публиковать пустой/частичный каталог, оставлять предыдущий с UNKNOWN.
