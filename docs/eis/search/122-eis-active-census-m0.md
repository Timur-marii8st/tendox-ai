# M0: официальный active census — проверенный ограниченный срез

12.10.2026. Owner root. **M0 INCOMPLETE**: национальное исходное множество,
полнота текущих редакций/состояний и стоимость полного bootstrap не доказаны.
Завершён обход двух конечных официальных выборок и проведены actual source probes.
Первый census выполнен при mandatory-admission v2 / source v8. Сейчас production
KESMBO cached intake v1 установлен по exact approval; схема20261013_01.
Worker3GiB/3CPU, SQL5s, scheduler/cron/частота прежние; загрузчики продолжаются.
Ниже отдельно разделены census, локальные проверки, выпуски и фактические записи.

## Исходное множество и границы

Официальная [выдача 44](https://zakupki.gov.ru/epz/order/extendedsearch/results.html?searchString=&pageNumber=1&recordsPerPage=_50&sortBy=PUBLISH_DATE&sortDirection=false&fz44=on&af=on&ca=on&publishDateFrom=08.10.2026&publishDateTo=08.10.2026&priceFromGeneral=100000000&priceToGeneral=200000000&currencyIdGeneral=-1)
и [выдача 223](https://zakupki.gov.ru/epz/order/extendedsearch/results.html?searchString=&pageNumber=1&recordsPerPage=_50&sortBy=PUBLISH_DATE&sortDirection=false&fz223=on&af=on&ca=on&publishDateFrom=08.10.2026&publishDateTo=08.10.2026&priceFromGeneral=100000000&priceToGeneral=200000000&currencyIdGeneral=-1).
Нет товарного слова или фильтра региона. Дата размещения 08.10.2026, цена
100–200 млн, af/ca; currencyIdGeneral=-1, все 87 увиденных цен в рублях.
Это специально узкая ценовая выборка для проверки завершения обхода,
не национальная репрезентативная выборка и не первая база продукта.

| Закон | Источник объявил | Страницы | Уникальные номера | Пересечение страниц | У нас есть | Нет |
|---|---:|---|---:|---:|---:|---:|
| 44 | 70 | 1:50, 2:20; далее ссылки нет | 70 | 0 | 70 | 0 |
| 223 | 17 | 1:17; пагинации нет | 17 | — | 14 | 3 |

Каждый номер, закон, фактическая дата и цена карточки проверены; echo controls,
HTTP200, DOM SHA и declared count проверены offline. Все карточки — «Подача заявок».
Обойдена вся объявленная выдача именно этих фильтров за интервал наблюдения.
Это не immutable snapshot на один момент: upstream продолжает меняться.
Индексы сверены PostgreSQL RR/read-only, procurement_app/RLS on, company
local-eis-supplier; writes0/sourcecalls0. Из 84 существующих номеров 11 generic223
совпадают по GUID с редакцией, связанной публичной карточкой. У трёх AESMBO в snapshot
нет сравнимого GUID: UNKNOWN, а не расхождение. Для 70 номеров44 источник страницы
не дал номера редакции: UNKNOWN. Полная редакция документов и актуальное состояние
каждого лота не подтверждены для всех84; совпадение GUID не закрывает их.

Расширение без даты, цены, региона или ключевого слова: 44 страницы1/20/21 —
147 уникальных номеров, у нас123, отсутствуют24; 223 страница1 — 50 номеров,
у нас20, отсутствуют30. Вместе с конечными выборками: **284 номера, 227 существуют,
57 отсутствуют**. Это явное неполное подмножество, не процент национального охвата.
Свежие отсутствующие номера не объявлены потерянными или unsupported без причины:
часть может ждать eligibility/обработки. Private списки и все DOM сохранены.

## Официальный способ и ограничения

- Публичные страницы доступны без входа; используемый proxy/browser/TLS не менялись.
- Пагинатор сначала показывает последнюю страницу20, но direct page21 принят
  сервером, echo21, 50 карточек. Это **не доказанный hard cap20**. Страница21 дала
  47 других номеров и три пересечения со страницей20, снятой раньше. Embedded count
  вырос1603535→1603538. Причина пересечения точно не локализована; такой проход
  по offset не доказан как полный снимок. Нельзя объявить 20 страниц полным перечнем.
- Объявленные embedded counts:44 1603535,223 323514. Это количество результатов
  двух стадий af/ca, а не доказанное число всех бизнес-действующих закупок и лотов.
- Штатное окно [CSV](https://zakupki.gov.ru/epz/order/orderCsvSettings/loadSettings.html?totalCount=1603535)
  явно ограничивает **5000 записей на запрос**, десять файлов по500. HTTP200,
  DOM13691bytes, SHA `9e8b8c60b313b8871b09c6e5fb9a349ce7f034381a746280144988ca7941b2f5`.
  Сами CSV не скачаны: колонки, фактическая полнота файлов и граница5000 ещё UNKNOWN.
  Первый guessed URL дал404; корректный controllerPath прочитан из JS страницы.
  Это ошибка диагностического адреса, не отказ ЕИС.
- showLotsInfoHidden=true вернулся в echo223, но лотовых строк не появилось.
  14 сохранённых223 XML содержат по одному лоту. Независимое перечисление всех лотов,
  их текущие состояния, отмены/приостановки и полнота многолотовой выдачи UNKNOWN.
  status=P XML означает размещённость, не закрывает текущую стадию/все лоты.

Прямой полный национальный export не подтверждён. Следующий существующий путь —
**официальные CSV-партиции по региону/периоду/стадии**, каждая ≤5000, с проверкой
всех chunks/ID/count/редакций/лотов и последующей сверкой поздних изменений.
Конечные HTML-партиции уже доказаны, национальная разбиенная CSV-процедура ещё нет.
getDocsIP остаётся загрузчиком XML; не является проверенным active roster.
getDocsLE/новый доступ не подключались. Реализация вокруг предположения о полном
доступном списке не начата.

## Реально найденные необходимые типы

Три отсутствующих223: **32616448999** (работы на Уфимской ТЭЦ3), **32616447331**
(поставка фундаментных блоков), **32616446704** (охрана Тюменских электрических сетей).
Все — конкурс МСП и actual XML `purchaseNoticeKESMBO`. Официальный запрос
**getDocsByReestrNumberRequest / RI223** проверен для каждого номера: complete READY
archive sets, UUID/compound bindings, safety/reflection/ZIP checks и XSD16.2/16.3 PASS.
Получены четыре редакции:1,1+2,1. GUID каждой текущей связанной публичной редакции
совпал с XML; v2 второго номера отличается сроком20:00→16:00 от v1.

Установленный parser допускает только purchaseNotice/AESMBO/ZKESMBO и отклоняет
все четыре с **DOCUMENT_TYPE_UNSUPPORTED**. Local/production normalized file SHA
`ba23ae91ae45e7405926a74534ce4dea6b221fa3be130bfa70a7619cee86508a` совпал.
XML сохранены приватно; они **не загружены в production индекс**.
Отдельный02/day08/KESMBO дал другую закупку32616448012, тоже valid XML и отсутствует
в индексе. Нельзя выводить экспортный регион/дату целевой закупки лишь из INN
и календарной даты публичной карточки: соответствие этих координат UNKNOWN.

В национальной неполной44 выдаче 15 отсутствующих карточек ч.12 ст.93.
Официальный сохранённый NSI называет соответствующий тип epNotificationEZT2020;
это подтверждённый методический пробел. Их raw XML в этом срезе не получены:
последняя попытка диагностики44 не получила lease за120s, sourcecalls0.
Остальные9 отсутствующих44 —6 аукционов и3 котировки, причина отсутствия UNKNOWN.
В национальной223 части среди30 отсутствующих:14 ZK-МСП,8 AES-МСП,5 «иной способ»
и3 с названием способа «единственный поставщик (до01.07.18)». Последнее не доказывает
legacy XML root: он UNKNOWN. Не приравниваем labels и209 типов к доле потерянных закупок.

## Измеренная стоимость

| Страта | Карточек | XML bytes на карточку | Разбор, ms |
|---|---:|---:|---:|
| EF, кредит | 2 | 78491–89201 | 1.68–2.22 |
| EF, другое | 2 | 106952–133315 | 1.91–29.02 |
| EOK | 2 | 258556–841959 | 3.35–7.63 |
| EZK | 1 | 75133 | 1.05 |
| generic223 | 2 | 113435–396452 | 1.78–4.91 |
| AES-МСП223 | 2 | 278339–380290 | 3.68–5.86 |

Это повторный component parse **существующих XML**, не production-интеграция и не
full intake. SQL retrieval + проверка hashes/decompression/разбор 11 карточек —
0.310252s, peak RSS136524KiB/133.32MiB; writes0/sourcecalls0. Источник/индексирование
этого component-замера не включены. Стратификация family + credit/other, по2 при
наличии, не репрезентативность всей страны.

Actual получение найденной недостающей части: три номера / четыре редакции KESMBO,
53.915165s, ZIP165504B, XML561017B; по номеру17.870/17.997/18.048s.
Это диагностический cold browser/by-number путь, не лучший batch throughput.
9 paced POST/GET дают18s обязательных пауз; три initial prepared waits —30s;
остальные5.915s — browser/network/schema/другое без фазовой детализации.
WSDL navigation не считается одним из9 paced data calls. Полная цена intake/index
**UNKNOWN** из-за unsupported parser; память source browser UNKNOWN, sampler не создавался.
14 целевых карточек стоимости (11 existing +3 missing) и одна дополнительная
координатная проба не доказывают национальную полноту.

По223 publicationDateTime у v1/v2 номера32616447331 —14:49:20 и14:59:56 08.10:
в этом реальном примере поле меняется с редакцией, не является неизменным временем
первой публикации закупки. Это наблюдение, не универсальный контракт всех типов.
Значения без offset; timezone по-прежнему UNKNOWN. Server/caller stamps отличаются
примерно248s; доверенный UTC здесь не перепроверялся, публикация→индекс не считается.

## Пересчитанный прогноз и решение

Календарный срок полной первой базы **UNKNOWN**. Старые6–12раб.дней — инженерная
оценка, не ETA продукта. При raw counts выше идеальный HTML100 и минутном cooldown
потребовали бы минимум13.38суток только метаданных; CSV500 — условно2.68суток.
Эти числа **не ETA**: в исходном срезе CSV ещё не были проверены, пределы/партиции/лоты/действующее множество
не закрыты, source counts не бизнес-active denominator, lease waits и повторная сверка
не включены. Частота запросов не увеличивалась.

Положительный гарантированный bootstrap budget при fresh потоке не доказан.
Принятый сопоставимый heavy cohort450новых44+161due223 стоил3919.076s/65.318min
против3240s/54min выделения: дефицит679.076s/11.318min ещё без controller/daily/newtypes.
Это burst, не средняя обязательная скорость каждого часа. Ранее наблюдались долги
обоих законов; свободные минуты lease нельзя раздать начальной базе как устойчивый запас.
M0 не исправлял scheduler и не выдаёт новый capacity PASS. Оценки update3–6раб.дней+48h
источника и search2–5дней+benchmark остаются условными после полной базы/доказанного бюджета.

Следующий конкретный замер — **одна полная официальная CSV-партиция≤5000 со всеми
500-row файлами**, полями редакции/стадии/лотов, границами и measured source/leasecost
при работающем fresh потоке. Затем разбиение всего национального scope должно дать
реальный N_missing по стратам; только после него и положительного бюджета можно
оценить срок полного bootstrap. Прототип перекрытия ожиданий остаётся частью этой
задачи, не основанием объявить продукт готовым. Production пакета M0 нет.

## Evidence

Private `C:\Users\elkgo\vibe-seller\tmp\improvement-program\m2\active-census-m0-20261012-v1`:
`result-v1.json`, `validation-bounded-traversal.json`, все page JSON/DOM/SHA,
`national-44-partial-ids.json`, `national-223-partial-ids.json`, четыре PG comparisons,
`223-existing-current-guid-comparison.json`, `missing3-xml-profile.json`, source proof
TARs/received XML/ZIP, `cost-existing-xml.json`, `canonical-parser-production-identity.json`,
`artifact-index-v1.json`. Source scope и причина private adaptations в scope-v1/кесmbo-scope.
Использованы stock strategy/family/by-number primitives; исходные runtime helpers не менялись.
30s lease refusals и cooldown выполняли sourcecalls0. Две конечные диагностические
операции ожидали lease≤120s без marker; cron/production guards прежние. Незавершённая44
проба не считается отказом ЕИС. Offline validation проверяет traversal/evidence,
не является подтверждением полного продукта. Связанный [план](121-eis-active-procurement-product-plan.md).


## Продолжение 13.10: CSV и подтверждённый KESMBO gap

Private evidence: `active-census-csv-20261012-v1`. Два официальных CSV GET
с теми же конечными фильтрами дали44=70/223=17 уникальных номеров, точное
совпадение с завершёнными HTML-партициями. 223 —17 уникальных(number,lotordinal).
Files36109/12858B, cp1251/25columns; SHA44 dbeb3e4d…/223 b10ef590….
Собственно download0.322/0.326s; общий вызов включает ожидание importlease
и запуск browser, поэтому download не является полной стоимостью обхода.
Экспорт70 строк при recordsPerPage50 подтверждает, что размер CSV не ограничен
одной HTML-страницей. Все строки stage«Подача заявок». Полей revisionGUID
и полного состояния каждого лота нет; latest/currentstate CSV не закрывает.

Отдельный AF-only national источник заявил53447944/42415223. Обход44
по возрастанию публикации нашёл07.01.2014, deadline14.01.2014, всё ещё
label«Подача заявок». **AF filter/source count не является действующим
множеством.** Deadline-ограничение по официальным полям при неограниченной
первой публикации подготовлено; получение отложено из-за importlease:
120.926s, затем2.908s/sourcecalls0. Это не сетевой отказ или запрет ЕИС.
Истёкшие и неизвестные сроки/прочие незавершённые стадии учитываются отдельно;
неизвестная timezone223 и будущийdeadline не заменяют currentstate evidence.
Полное национальное множество, его стабильность между обходами и N_missing UNKNOWN.

`kesmbo-targeted-intake-20261013-v1`: прежний отказ parser воспроизведён,
минимальный KESMBO reader и честный BY_NUMBER binding реализованы локально
от exact installed sourcev8. Initial/PREPARED/archiveUID/fullset, family
и номер всех records проверяются; region/day не выдумываются. Existing
scheduler family set, pacing/resources/guards прежние, ни одного sourcecall
или production indexwrite для replay. 7 isolatedPG18 scenarios PASS;
три actual preservedwindows/4версии приняты, replay idempotent, foreigntenant0.
Search возвращает последнюю v2 для32616447331, GUID/XML/window/archive/response
совпадают. У всех4версий один лот/cancelled=false, statusP; это sourcefacts,
не доказанная актуальная открытая стадия или полная отменная история.

| Номер / запрос | Intake с cached proof, s | Обычный поиск isolatedPG18, s | Replay-start→visible, s |
|---|---:|---:|---:|
| 32616448999 / Уфимской ТЭЦ | 0.317615 | 0.166885 | 0.484500 |
| 32616447331 / блоков фундаментных | 0.226175 | 0.024351 | 0.250526 |
| 32616446704 / Тюменские | 0.261543 | 0.023541 | 0.285084 |

Всего actual replay1.660494s; это не production freshness/p95, не источник→поиск
и не throughput всей нагрузки. Память этого локального replay не измерена.
Full PG16 receipt pending. Независимый bounded source review PASS, принято
разделение выпуска: совместимый reader/schema/UI без intake, затем offline
importer от реально установленной совместимой базы. Старые APIimages strict
Literal не читают KESMBO после записи; их post-intake rollback недопустим.
Первый compatibility archive d8715d3b…:1086files,9ownedpaths, importer прежний,
migration20261013_01; никаких pending pager/paper/scheduler changes.
Stock sealing/wholepolicy-map PASS,48stages/14PGgroups/oldIDs retained;
draft unit3216→3224 и PGgeneral2→6 с exact collectiondigests. Activeproduction
policy/guards не менялись. Новые runtimebytes требуют exact approval.

Первая полная база и обновление остаются INCOMPLETE. Календарный ETA UNKNOWN:
сначала получить и замкнуть deadline/state partitions без publicationlookback,
затем сопоставить реальный nationalN_missing и доказанный bootstrapreserve.
Один следующий release-шаг — private fullgate compatibilityslice и stock
install/rollback rehearsal до exact-request; получение3новыхномеров
на production будет отдельным завершённым срезом после compatiblebaseline.

## Утреннее продолжение 13.10: изменяемая национальная выборка

Все регионы, без начального publication lookback/цен/методов; официальный
AF и deadlineFrom=To13.10.2026. Первая страница показывала **«более2000»**,
а не точный2068; planned2068 не считается доказанным числом. Ночные CSV1/2
дали500+500номеров и506+504лотовых строк. После перерыва CSV3 дал500номеров/503строки,
CSV4 только113номеров, HTML уже«более1600». Их объединение **не является
завершённым единым снимком**: источник менялся, ограничения обнаружены.
Сохранены первоначальные файлы/SHA, моменты получения и progress; повторная
сверка тех же фильтров выполняется без изменения частоты или обхода lease.
Уход из выдачи не называется отменой. Exact lotGUID/currentrevision/stage
не заменяются CSV ordinal/date/AF.

Повтор первой части500номеров изменил четыре номера относительно ночной части;
read-only production app/RLS/on/SQL5s нашёл226, отсутствует274 (0.281383s SQL).
Это **не доля национального пробела**. Среди отсутствующих лотовых строк:
иной способ144; электронный конкурс МСП64; запрос предложений МСП23;
аукцион МСП22; котировки МСП20; старый открытый электронный аукцион2.
Название метода само по себе не доказывает XMLroot. Начальная публикация
доходит до2025года; текущая редакция/стадия этих500 остаётся UNKNOWN.
Evidence: active-census-csv-20261012-v1/first500-gap-profile.json и
compare-deadline13-first500.json.

Full compatibility gate v1 FAIL/no receipt: единственный inherited idle fixture
использовал UTCday вместо неизменённого runtime MSKday после21UTC. Детерминированно
при22UTC 1FAIL/7PASS, после исправления aware fixture8PASS; все assertions/IDs
сохранены. Cleanup четырёх ресурсов complete. V2 archive abefc07d…/1086files/10paths:
добавлен только этот testfile плюс примечание contract. Whole map48stages/14groups
и независимый narrow amendment READY; corrected private gate выполняется.
Activeproduction guards/policy/schema/code прежние, runtime scheduler не менялся.

Второй проход сохранил1609уникальныхномеров/1622lotrows без пересечения chunks,
но terminalCSV сократился113→109 ещё во время чтений. Оба прохода не atomic;
третий неизменённый полный обход не запускается. Пересмотр: использовать более
малые официальные partition filters и сверку добавленных/ушедших IDs, сохраняя
известные неизвестные состояния; отсутствие в новом списке не является отменой.
Конечная HTMLpage33 и CSVafter2000 отложены importlease30.799/120.641s, source0;
это не source/network failure. Production loaders не останавливались.

Read-only canonical comparison именно сохранённого1609set:1215known/394missing,
SQL0.975813s/200numberbatches/consistent snapshot/runtime app/RLS/on. Отсутствует
127конкурсовМСП,63запросапредложенийМСП,20котировокМСП,22аукционаМСП,
160«инойспособ»,2старыхэлектронныхаукциона. Все эти394 впервые опубликованы2026;
количество методов не становится долей закупок, XMLroots ещё требуют proof.
Currenteditions1215 и currentlotstates1609 UNKNOWN: CSV не содержит GUID редакции.

Проверка ordinary production API с query«ИП2616С» нашла32515100333/v34,
firstpublication05.08.2025;HTTP200/0.148740s/XML-window parity PASS. Raw archive
1775031B/hash/member/provenance PASS, sourcecalls0/read-only. Официальный CSV
lastchange05.10.2026/deadline13.10.2026 11:00/AF; это не независимая проверка
всех cancellation/lotstates. Один запрос не p95/p99 и не freshness SLA.
Evidence: partition223-deadline13-pass2-union.json, compare-deadline13-pass2.json,
partition223-deadline13-gap-profile.json, old2025-user-search.json,
old2025-user-provenance.json в active-census-csv-20261012-v1.


## Завершённый compatibility и проверенный адресный importer 13.10

Compatibilityv2 installed13Oct05:46:33UTC по human exactapproval115482f8…;
schema20261013_01, runtime/352hostbindings/health/cleanup PASS. Worker3GiB/3CPU,
SQL5s/cron/scheduler unchanged. Targetedwindows/KESMBOversions0: установка reader
сама по себе не добавила три отсутствовавших закупки. Ordinaryproductionsearch
«Темозоломид»5.647012s, «Камышлов»0.071461s, old2025«ИП2616С»0.050017s;
HTTP200/XMLwindow parity PASS, не p95 и не source→index freshness.

Cached importer от exact installedabefc07d…: три delta paths, один runtime
scripts/server-eis-223-import.py, семь specific negative/success cases.
Полный privategate48/48,3204unitPASS+27explicit skips,607PG16/0skips,
127Node/9doctests/builds/cleanupPASS719.014s; receipt05bacf1198… verified.
Sourcearchive80089518…/1087files; package7d9c01aa…установлен по exact approval.
Trustedcontroller/verifier unchanged, adapter только exact pins, privatepolicy
unit3224→3231 с bound collectiondigest; oldIDs/PGinventory preserved.

Изолированная installedCompose2.40.3 репетиция44.800917s PASS: stockinstall,
три реальных cached sourcewindows/four editions, latest2/1/1 обычным APIsearch,
rollback на совместимые installedf11/97ab images сохраняет schema13/four versions
и поиск. Sourcecalls0/prodmutations0/cleanupPASS. Первый отказ — команда искала
hostscript внутри image; corrected existing read-only scripts mount. Candidate
bytes/receipt не менялись, fullgate не повторялся; failedproof сохранён.

Согласованный exact offload только olderdaily dump10,161,849,725B выполнен;
локальная копия SHA25ddf115…/pg_restore-listPASS сохранена, другие dumps прежние.
До нового backup reserve после offload DB12,247,686,167B/free59,590,057,984B,
margin4,392,698,857B над DB+40GiB; guard/retention не ослаблены.
Установка13.10 server07:54:44–08:09:30UTC/885,550526s INSTALLED; новый mandatory
backup выполнен. Runtime352bindings/images/schema13/3GiB3CPU/cleanup PASS.
После free48,458,285,056B/MemAvailable6,603,505,664B. Worker peak не измерен.
Exactrequest/evidence: kesmbo-targeted-intake-20261013-v1/
exact-approval-kesmbo-intake-v1.md, production-installation-intake-v1.json,
production-runtime-postchecks-intake-v1.json, approved-single-backup-offload-v1.json.

Запись данных пока не началась: три bare30s и два priority30s admission отказа
до importer, read-only procurement_app/RLSon/KESversions0/targetedwindows0.
lslocks PATHabsence не доказывает свободный lock: FD остаётся в parentbash после
завершения flockchild; fuser подтвердил реальные44priority holders.
Неизменённые попытки не продолжаются. Data-only v2 был подготовлен, но review
DA2-R1 заблокировал освобождение coordination без confirmed Docker termination.
v3 исправляет только operational lifecycle, использует stock address-replay
300s waits; finalplan06d75655…/executor09551683… review READY,
пользователь подтвердил exact data-only v3, исходный v2 не исполнялся.
На isolated Compose2.40.3 six lifecycle cases PASS45,089654s; отдельный настоящий
flock/UNKNOWNbranch/OSError diagnostic-write PASS. Приложение/receipt прежние,
gate не повторён. Реальная операция:4newversions/3numberwindows/latest2/1/1,
leasewait120,571841s/work8,545068s/total129,354924s/core0,123066s.
Все15 cachedsourcefiles verified до записи. Все4XML/source-member/archive/
response/prepared/window bindings PASS; procurement_app/read-only/RLSon,
foreigncompany видит0. Idempotent replay3cases0new/все4идентичности иingestedtimes
прежние, work8,861729s. Owncontainers/markers absent, cleanup PASS.
OrdinaryproductionAPI:32616447331/v2 «блоков фундаментных» page1/1,250500s;
32616446704/v1 «Тюменские» page3, pages0,226314/0,292185/0,218828s;
32616448999/v1 «Уфимской ТЭЦ» page1/0,622789s. AllHTTP200/XMLwindowparity PASS.
AfterMemAvailable6,877,577,216B/free48,437,280,768B; workerpeak UNKNOWN.
Sourcecalls0; cachedsnapshot не доказываетlatest-source-state/currentlotstage/
publicationtimezone/freshness/p95p99. National productINCOMPLETE.
Evidence production-intake-final-result-v3.json, production-search-postchecks-intake-v3.json,
production-targeted-provenance-intake-v3.json, production-approved-three-intakes-v3-replay.json.

Семантика223 уточнена по сохранённому officialXSD16.3 SHAc5ad9bec…:
purchaseNoticeDataBaseType/publicationDateTime, line1711 — «Фактическая дата
размещения», xs:dateTime. РеальныеZP v2/v3/v4 имеют разные даты этого поля:
оно не заменяет initialpublication. Naiveзначения не задают timezone; перевод
вUTC/publication→index UNKNOWN. Другие XSDтипы содержат собственные определения.
Evidence publication223-schema-evidence-v1.json, sourcecalls0.

## Подтверждённый необходимый тип ZPESMBO

Из сохранённого missingset выбран32616349722, initialpublication03Sep2026,
CSV AF/deadline13Oct12:00. Official BY_NUMBER без datefilter дал UID
b8e7735c-9762-4e6e-bcb0-4dfcca80e57e, полныйZIP158928B/four XMLversions1–4,
XML515678B; XSD16.2/16.3 PASS. Вызов18.698537s, source2POST+1GET, indexwrites0.
Installedcompat parser отверг все четыре DOCUMENT_TYPE_UNSUPPORTED, source0.
Название метода теперь подтверждено реальным root, не только CSV inference.
V2publication14Sep11:23:54/deadline23Sep12:00;v3publication23Sep11:16:16/deadline
30Sep12:00;v4publication30Sep11:24:49/deadline13Oct12:00. Все statusP/naive:
timezone/currentlotstage UNKNOWN, revisionpublication не равноfirstpublication.
Не включён в KESintake package. Одна карточка не устанавливает долю пропуска
или полную стоимость63CSV способов. Evidence active-census-csv-20261012-v1:
by-number-zp-actual-evidence.tar.gz SHA53ba3a06…, missing-zpesmbo-actual-profile.json,
zpesmbo-installed-parser-rejection.json. Использовать сохранённые XML, source
повторно не скачивать для parserfix.


## Независимый local ZP intake/search срез после запроса KES approval

Private zpesmbo-reader-20261013-v1: explicit parser/index/models/migration02,
cached importer/UI реализованы локально от sealedintake80089518…, не production.
82unit/Ruff/TypeScript/focusedESLint PASS. Actual4XML readerPASS0.045129s;
isolatedPG18:4версии/1numberwindow, ordinary«заземлений»latestv4/foreign0/replay/
provenance PASS. Intake0.332816s/search0.121696s/replay-start→visible0.454513s,
total0.643609s. Memory/availability→index/publication→index UNKNOWN; не SLA.
Два localPGотказа(environment collection, staleheadfixture01 при installed02)
разобраны полностью, после reassessment повтор сокращён9→4 affected/mandatory;
4PASS, прочие8 прежних успешных сохранены. Не заявляется единый full9PASSrun.
No sourcecalls/prodchanges/gate/package; root owns privateexplicit paths/docs/handoff.
До ZPwrite нужен совместимый rollback: сначала reader/schema/UI без intake,
затем importer от реально установленной compatiblebaseline. KESpackage unchanged.

## M0: старые публикации и изменяемые границы CSV — 13 октября

Официальная ограниченная партиция223: AF/подача заявок, deadline>=14Oct,
publishDateTo31Dec2025, без нижней даты, региона, цены или метода. HTML50/CSV/
повторный HTML дали одинаковые31 номера/31 номер-лот, terminal boundary PASS.
Первая публикация16Mar2016–30Dec2025; SQL known8/missing23. Это явно неполная
часть целевой базы: не включает deadline13Oct, неизвестные сроки, другие стадии
и44. Номер32515592903 опубликован30Dec2025, изменён05Oct2026: наблюдаемая
семантика фильтра — первая публикация, не последняя редакция. Не распространять
этот единичный факт на все поля/форматы. Edition/state/lot completeness UNKNOWN.
Evidence partition223-old-open-final-v1.json/compare-old-publication-partition31.json.

Дополнение>=01Jan2026 объявляет «более13000», Jan–Sep — «более1800», не точные
counts. Три разрешённых CSV ranges1–500/501–1000/1001–1500 дали1496 уникальных
номеров, пересечения3 и1 внутри дат22/29Sep. Причина изменения/нестабильного
порядка ещё UNKNOWN; offset union не объявляется полным. Продолжение offset
остановлено; следующий ограниченный листJan1–Sep21 отделяет целые даты,
остальные даты и Oct-onward сохранены как незавершённые дополнения. Scope не
сужается произвольным lookback. Evidence partition223-new-jansep-offset-diagnosis-v1.json,
partition223-jansep-date-strata-v1.json; повтор/terminal сверка обязательны.

## Адресный bootstrap существующих типов и ZP — local, не production

Actual missing32515359393 «поставка древесного топлива»,31Oct2025: BY_NUMBER
19.218235s,2POST+1GET,oneZIP/oneXML purchaseNotice/v1, XSD16.2/16.3 PASS.
Installed parser PASS, но bind BY_NUMBER WINDOW_INVALID до БД. Это наш admission
пробел, а не отказ источника. Реальный XML сохранён: повторного скачивания для
fix не было. GEN method «Иной способ» не равен отдельному unsupportedXMLtype.

Минимальный local candidate от точного sealedinstalled80089518: addressing для
трёх уже читаемых notice roots, ZP reader/model/UI,13_02 additive CHECK. Regional
scheduled3 остаётся прежним. GEN snapshot deep-equal установленному parser.
Actual isolatedPG18: GEN1+ZP4versions/latest/search/RLSforeign0/replay0new PASS;
GEN intake0.148564s/search0.015038s/start→visible0.163602s, ZP0.422179s,
оба total0.978883s.7affected/mandatory PG18 PASS; cleanup PASS. Это local proof,
не production SLA/текущая редакция/полнота. ZP staticcache root отдельно исправлен
после FileNotFound beforeDB; KES/ZP/GEN source roots не смешиваются.

Первый compatibility candidate14ownedpaths/1092files сохраняет установленный
KES-only importera630 без изменений; новые адресные записи в этом выпуске0.
Сначала compatibleimages/schema/UI, затем отдельный importer/data exactrelease
от реально установленной compatiblebaseline. Активная policy/guards прежние.
Whole-map preflight выявил Windows encoding12старыхUnicode IDs и WindowsPath
manifest order; исправлены только сборUTF8/упаковка, fullgate до этого0.
Stock sealing/полный inventory и sole review READY. Source17efdf74…,
privatepolicy5837e223…, units3240,52stages/16PGgroups; controllerf9e053 прежний.
Privategate после исправления порядка52stages завершён PASS/cleanup; receipt сохранён, выпуск/appplan не готовится по новому приоритету M0; production changes0.
Evidence 223-active-address-compat-20261013-v1, actual-pg-addressing-replay-v3.json.

## Национальный AF-only CSV-перечень — текущий основной срез

13.10 выбран толькоофициальныйAF/allRussia обоихзаконов, безdeadline/initialdate/
price/method/regionbounds. Meta44:«более530000»,223:«более42000» записей; exactuniqueN
UNKNOWN. Completefinite454 из предыдущего среза имеетextra deadline>=14Oct и
не заменяет полныйAF-range. Все прежниеfiles сохраняются/повторноневыгружаются.

ПервыйrootCSV каждого закона дал500 rawlabels.44pub7–17Jan2014;223pub30Dec2012–
22Mar2013 и670lotrows. Сравнение root500 каждого:RLS/app/read-only/source0,
canonicalexactpresence0;130 ранних44 rawlabels имеют нестандартную длину,
canonicalmappingUNKNOWN. Они же в сохранённомHTML, не CSV decode defect.

Терминальные первые leafcapture:44 unboundedleft–15Jan2014=338;223 unboundedleft–
15Mar2013=427/593lotpairs. Подтверждение изменения границ/reconciliation PENDING.
44rootprefix потерял одинID при попытке классифицировать поCSVdisplaydate:
0318300384414000001/date15Jan реальновернулся From16Jan. Соседний previewнайден,
leaf/previewoverlap0; это не evidence пропуска или доказанныйtimezone. Query-date
и отображаемую date не отождествлять. Других запросовHTML-pagination не было:
доказан повтор толькоDOCUMENT_ONLY с заблокированнымиdynamicrequests.

Reuse19CSV withbodySHA/AFrowlabels:44observed570 (70present;370usualnumberabsent;
130canonicalidentityUNKNOWN),223observed3610 (1921present/1689absent).
Это union разныхsourceasof12–13Oct/subfilters/preview; не closednationalsnapshot.
Ordinary indexedpresence не означаетlatest/current/searchvisible. RLS/app/
consistentread/sql5s/source0/dbwrites0 PASS,0.101382s. После следующих диапазонов
таблицы пересчитываются, исходныйsnapshot сравнения сохраняется.

Официальный CSVmodal primarysavedHTML сообщает<=5000результатов, десять links
по500. Wholeleaf долженпоместитьсяв500, lotrowsдедуппоnumber; cap не повышен.
При cap500 cursor не движется, календарный interval делится. Single-daycap
сохраняется как конкретный boundedblocker, не бесконечный offset-loop.
Для>=530k/42k native records нужны как минимум порядка1060/84файлов при500/file;
exactuniqueN неизвестен, это порядок workvolume, не доля missing. Минимальный
cooldown alone около17.7/1.4часа без lease/недополныхleaf/rechecks. Действительные
sourcecalls c lease/startup≈125–189s, download≈0.4–1s; ETA пересчитать по
завершённымleaf density/actualmonotonic walltime после boundedpass. Средние и
ранние2014/2013 payloads не гарантируют стоимость более новых/большихlotsets.

Private national-af-csv-resume.py продолжает существующийcaptureworkflow:
воспроизводимый blocker — singleURL probe не сохранял cursor после interruption,
а ручной offset-union и DISPLAY_DATE классификация не закрыли range. Никакой
новой productionплатформы; sameprobe/oneHTTP/importlease300/stock60s/TLS8MiB.
Oneproducerlock/atomiccheckpoint/durable raw+SHA; max12requests, nofail-autoretry,
необычныеliteral IDs сохраняются отдельно отcanonical. Offline4savedCSV checks
source0 PASS. Latest continuation.json содержитPID/tasks/ranges иследующийcursor.
Snapshot/restore/gate/install/observers не повторялись. Offload-copy завершился
connectionclosed, partialunverified/notusable; удалений0, новыйcopyне запускается.

Текущаясводкапосле12readpass/day24proof:44observed2513/present70/
absentusual2313/identityUNKNOWN130;223observed4859/present1941/absent2918.
Prefix querycaptures44through24Jan2014=2443rawlabels,223through07Jul2013=1749;
cross-rangeoverlaps0. Day24declared520/2CSVchunks/twoequalfullpasses/unique520
полностьюзакрыт, не источник лимит500;metadata+rechecks preserved. NativeuniqueN
национальногоисточникаещёUNKNOWN, labels>530k/>42k не точныйdenominator.
12reads1471.221s including modeled732scooldown/newcomplete2907/~7113hour,
не устойчивыйSLA;conditional firstpass≈4–7days44/12–18h223 совместно, затем
globalreconciliationUNKNOWN. Срез national-af-report-v1.md/privateJSON.
Одинследующийboundedproducer81248/PIDcontinuation; standardthreadm0-csv heartbeat
30min возобновляеттолькоэтуM0задачуизcheckpoint, не запускаетduplicateobserver.
RecoveryheartbeatPAUSED. No app/guard/sourcefrequency/resource changes.

## Уточнение scope: только открытая подача — 13.10, 22:57 МСК

По указанию пользователя исторический AF-обход прекращён. Сохранены raw/header/hash
и continuation перед25Jan2014; один прежний25Jan request ещё до уточнения не получил
importlease за300s, exit1/sourcecalls0, checkpoint не продвинут. Активного producer нет;
heartbeat m0-csv PAUSED, production loaders не останавливались.

Новый официальный фильтр: вся Россия, только один закон44/223, AF и
applSubmissionCloseDateFrom=13.10.2026. Нет publication range/price/method/region cutoffs.
В обоих ответах checked checkbox AF/solelaw, hidden deadline13Oct, пустые publication
и price; HTML labels «более46000»/«более15000», CSV-trigger46069/15009. Source stamps
19:54:57/19:57:21UTC (22:54:57/22:57:21МСК), caller времени отдельно в execution.
Это PRELIMINARY native records, не unique/current-open proof. Календарный today
фильтр включает истёкшие часы: точное время/timezone и known cancelled/suspended
исключения обязательны, unknown отдельно. Дата публикации не ограничивается.

Existing private resume получил deadline-only mode: разделение будущих deadline
диапазонов, metadata exactcount≤5000, штатные CSV chunks≤500, две одинаковые полные
последовательности плюс meta recheck. Нет новых sourcechannels/framework/production
изменений; stock importlease300/cooldown60/oneHTTP/TLS/8MiB остаются. Source0 proof
переиспользует31 realCSV, проверяет оба applied filters и отклонение неверной deadline
границы; исторический mode failclosed при наличии frozen checkpoint.
Evidence: active-census-csv-20261012-v1/open-applications-20261013-v1: scope.json,
historical-checkpoint-frozen.json, 44/223-counter.json/html/execution.json,
preliminary-counters.json, deadline-wrapper-offline-proof.json, continuation.json.
Enumeration/current-production comparison пока INCOMPLETE; неподтверждённое число
не заменяется прежними историческими AF aggregate или source-счётчиком.

## Возобновление 14.10: актуальный неполный результат

На 09:17 МСК read-only production comparison: CSV44 4509/present4461/missing48;
CSV223 6921/present5365/missing1556. Прирост с утра: +4500/+4921 номеров.
По последним сохранённым CSV полям deadline>=14Oct: 44 4500/4452/48,
223 6848/5343/1505; оставшиеся9/73 — прежние calendar seeds. Сегодняшние часы,
timezone, latest revision/cancel/suspended/lotstate ещё не сверены: exact eligible N
UNKNOWN. Наличие canonical version не подтверждает актуальность или поиск.
Старые seeds сохранены, включая3 XML extensions за прежней13Oct границей.

Два bounded прохода завершены; один новый producer PID37252 возобновил12reads.
Последние CSV:44 06:16:14UTC,223 06:15:10UTC. Прежний ночной STOPPED был
актуален; причина старого NO_OUTPUT не была доказанным отказом ЕИС. Теперь stock
flock-E75/entrymarker различают lease timeout и выполнение; источник HTTP200.
Mutex300s, cooldown60s(wait61), oneHTTP/TLS/500file/5000filter/8MiB/SQL5s прежние.
Исторический default запрещён, production loaders и cron продолжают работу.

22315–16Oct: начальный native4921, полный первый проход4923unique, пересечений
chunks0. Последний запрос4501–4921 вернул423 номера вместо421; причина между
изменением живой выдачи и семантикой end offset не различена. Parent INCOMPLETE,
raw сохранён; выбран меньший официальный partition15Oct/16Oct. Это не EOF/PASS.
44day14 прежний lease-specific block снят после фактических успешных запросов
через тот же mutex. Сегодня meta1385 и первыйCSV500 получены; старый7823 не
считается текущим extent. Причина изменения count не доказана.
Неизвестные цены/precision не считаются закрытыми без parent/disjoint union.

Национальные native46069/15009 относятся к13Oct, не к сегодняшнему atomic списку.
Точный остаток страны UNKNOWN. Для уже начатого44day15<=500k первого прохода
осталось28 записей, затем9CSV повторной сверки иmetadata. Последние24reads:
команды1766.374s, ещё61s cooldown/read; min2.578/max185s, median7.438s.
Command включает lease, раздельные wait timestamps UNKNOWN. Это не SLA:
условные10reads текущейветки займут около22min при среднем этого набора,
внешнее ожидание/изменения выдачи могут увеличить срок. National ETA UNKNOWN.

Heartbeat m0-csv ACTIVE только для новой выборки и comparison, один владелец root.
Новые релизы/gates/snapshot/restore не запускаются. Source clock примерно67s
позади desktop; trusted clock relation UNKNOWN, настройки не менялись.
Evidence open-applications-20261013-v1: continuation.json,
compare-new-filter-partial-v7.json, partial-calendar-candidates-20261014-v2.json,
223-15-16-cardinality-diagnosis-v1.json и raw/parsed/execution00016…00043.
Следующее действие: закончить существующий bounded pass, обновить прирост,
пройти оставшиеся deadline/price ветки и выполнить global reconciliation.

## Региональный приоритет 14 октября

Humanchoice: **адрес заказчика OR место поставки/работ**, отдельные отметки.
Порядок16+02/12/18/21/43/56/63/73 →77 →78 →national remainder. По law+number
объединяем источники, признаки не AND. Unknowngeography и nationalqueue сохранены.
Это privatecensus/order иегоmetadata, не production scheduler/intake/UI.

Форма Все параметры search.html и choose-okpd.js различают customerPlace/Codes,
delKladrIds/Codes для44/223 и deliveryPlaceGAR для44. APIkladr/loadChildren
OKER33/30/31 подтвердил11key/code bindings. Все5фильтровTatприменены реально:
44customer571,223customer949,44legacydelivery0,223delivery440,44GAR574 на07:35–45UTC.
Nativecounters неunique/currenteligible; суммы пересечённыхфильтров не складываем.
К началуdata pass44customer584/223customer968: живыеinputconditionsизменились,
поэтомуmetadataобновлён, source0proof повторно не запускался.

Privatehelper сохраняетgeoприdate/price split/midnight rebase ивыбираетминимальный
prioritytier. Source0guards/restart/8actualCSV PASS. После5livefilterchecks55tasks
добавлены перед12сохранённымиnationaltasks; одинcollector запущен07:56UTC.
Первыйbounded12pass COMPLETE/59calls: поTat44customer585observed/present454/missing131;
223customer973/delivery475/union997/intersection451,present744/missing253 на08:20:30UTC.
СамиCSVобрабатываются; новыеимпорты в production этойзадачей не выполнялись.
ОбщиеCSV5896/7554,present5717/5817,missing179/1737 — PARTIAL; actualstate/searchUNKNOWN.

223customer973≠declared968,delivery475≠472;44twofull584passes отличаются1ID:
added0311300111726000070,removed0211100000226000325. Мутациявыдачи/согласованность
endpoints не полностьюразделены, не transportfailure. Широкиеparents INCOMPLETE.
После2неудачширокогоподхода4Tatпредиката заменены на непересекающиесяdeadline
14/15/16/17–19/20–infinity; всеfutureдаты, публикации и raw/старыеIDs сохранены.
В refined pass закрыты customer-ветки Татарстана со сроком14.10 обоих законов:
44 —5номеров, все5есть в production;223 —5, есть3, отсутствуют2 (snapshot08:20:30UTC).
Два одинаковых CSV-набора и итоговый nativecount5 подтверждены для каждой ветки.
Refined bounded pass COMPLETE:12reads/0errors/28m20s (monotonic commands+cooldowns),
прирост0/0. Следующийpass RUNNING:15.10 customer тоже закрыт двумяCSV+recheck,
44=114/223=181. Union проверенных14–15.10:44=119/present117/missing2;
223=186/present143/missing43 (тотже snapshot08:20:30UTC, не повторён безnewIDs).
Осталось78веток, collector перешёл16.10. На границе71 минимум114HTTP/1h55m пауз;
при прежнемmix около4h29m
только для минимальныхreads. Неизвестныеcounts/extra pages/drift не включены; полный ETA UNKNOWN.
Следующий один bounded collector продолжаетcheckpoint. Exact eligibility UNKNOWN.
Отдельно переучтены сохранённые CSV по календарному сроку>=14.10:44=5887,
present5708/missing179;223=7481,present5795/missing1686. Это PARTIAL,
не точное число доступных заявок: сегодняшних сроков1385/1926, timezone/time UNKNOWN.

CSVимеет official_geography_filter иpointer/SHA метаданных; actualXMLlocationUNKNOWN.
Отсутствиенаблюденияпризнака неFAIL: другаяветка могла ещёнепройти. GARtextpredicate
неexhaustiveregionproof; исходныйnationaltarget не уменьшается. Source0repro
обнаружилколлизиюимён двухfailedregionalreads: исправленоучётомfailedattempts+
region/basis, обаdiagnosticfiles сохранены, checkpoint0advanced. Другиеproofsunchanged.
OneHTTP/stocklease300/cooldown60/TLS/500CSV/5000filter/8MiB/SQL5s/3GiB3CPU сохраняются.
Productionloaders продолжают работу; sourceclock~67s behinddesktop/trustedrelationUNKNOWN.
Evidence open-applications-20261013-v1: regional-priority-{official-geo-bindings,
offline-proof,live-filter-proof,activation-audit,live-census-drift,deadline-refinement}-v1.json,
regional-priority-memberships-partial-v2.json, regional-failure-name-before/after-v1.json,
compare-new-filter-partial-v10.json, partial-calendar-candidates-20261014-v3.json,
regional-priority-refined-pass-progress-v1.json, regional-priority-closed-ranges-v1.json,
continuation.json и raw/parsed/execution.
Следующий шаг обновлён ниже: first traversal предшествует change reconciliation; одинаковые passes не доказывают completeness.
## Первый обход отдельно от сверки — 14 октября

Последнее указание человека: первый проход всех доступных веток не ждёт вторых CSV
и recheck уже перечисленных веток. Private helper сохраняет тот же checkpoint,
региональный приоритет внутри каждого этапа и stock ограничения; new framework0.
Первый новый bounded pass:12 FIRST requests,0 CHANGE requests;5 запросов дали
новые уникальные IDs:44+30,223+83. Elapsed39m57.72s: lease26m25.17s,
прочая command work1m20.55s, cooldown12m12s. Старые24:12first/12repeat,
новыхIDs0, точный leaseUNKNOWN (старое elapsed не разбивается задним числом).
Теперь /proc/uptime отдельно фиксирует import wait, без изменения timeout300.
Осталось70first/6recheck задач; known minimum75HTTP. По18requests/hour
условный первый обход4h10–7h46, если unknown ветки empty/≤500 и contention прежний;
дополнительные страницы/5000 splits/null-price/drift не учтены, upperETA UNKNOWN.

Одинаковые проходы не national completeness. Added/disappeared IDs и source stamps
сохраняются, pagination/cause UNKNOWN; исчезновение не отмена. Новая функция
record_change_comparison и legacy-unexplained-change-comparisons-v1.json сохраняют
это явно. observed-expired-to-future-deadline-differences-v1.json подтверждает
различия наблюдённых полей CSV, но причина/редакция и глобальное отсутствие пропусков UNKNOWN.

Raw CSV5926/7637; на DB10:54:23UTC present5768/5954,missing158/1683 (v11).
Calendar>=14Oct latest observations5917/7566,present5759/5932,missing158/1634,
точное число доступных заявок UNKNOWN; сегодня1385/1926 сроков без общей TZ-проверки.
Tatquery union615/1082,present505/879,missing110/203; customer615/1075,
delivery5/475,intersection5/468. Query match не actualXMLgeo/eligibility.

Подготовка загрузки подтверждённых приоритетных пропусков не ждёт полного census.
32616445250: card AF,15Oct10MSK(+03),revision1/currentGUID совпадает с XML,
единственный lot cancelled=false; отсутствует, actual getDocsIP/XSD/stock preflight PASS.
ОдинZIP124667B,5retainedfiles130512B; stock importer/receipt/schema13/3GiB3CPU
совместимы. Canonical XMLdeadline остаётсяUNKNOWN: HTMLfact не подменяет модель.
32616445747: card AF+deadlineMSK подтверждены, lotstate/actualXML ещёUNKNOWN.
Data-only план одной45250/UID9dd0d9b4… и pin-only executor с expiry до14:50МСК
подготовлены для NEWexact data approval; canonical writes0. Новых app releases0.
Diff/proof/lifecycleAST unchanged, expiry before marker/callback tested; old3UIDapproval
не покрывает этот payload. После approval — stock leases/ownedworker/cleanup,
provenance/RLS/replay/ordinary production search; current source/card limitations отдельно.

Evidence: first-vs-recheck-local-proof-v1.json, first-traversal-cost-report-v1.json,
first-only-pass-result-v1.json, regional-priority-memberships-partial-v3.json,
compare-new-filter-partial-v11.json, partial-calendar-candidates-20261014-v4.json,
priority-confirmed-open-missing-v1.json, priority-cached-preflight-v2.json,
priority-stock-runtime-readonly-v1.json, exact-approval-priority-cached-intake-v1.md.
Следующее действие: существующий следующий first-only --max-requests12 pass,
без дубликата, затем actualgrowth/knowncounts/lease-forecast; data operation толькопоapproval.

### Приоритетный data-only импорт — выполнен 14 октября

Human exact approval539c64…/executor831e6b… исполнен до expiry14:50МСК.
32616445250, purchaseNoticeKESMBO, редакция1 добавлена в production: new_versions1,
source calls0; без выпуска/миграции/backup, существующие3GiB/3CPU/SQL5s/guards.
Импорт233.474с: ожиданиеpriority224.635с/import5.753с, worker2.709с.
Replay330.322с: new_versions0/replayed=true, ожидания135.328с/191.869с.
Provenance XML/window/response/prepared/archive PASS; foreigntenant0; собственные
workers отсутствуют, markers очищены, leases освобождены. Receipt переиспользован.

Обычный production поиск «кранов шаровых»: нужная версия на первой странице,
HTTP200/1.275с и совпадающий provenance. По номеру32616445250: HTTP200/0.088с,
пустая выдача — отдельный FAIL поисковой доступности; новый release не начат.
Canonical deadline UNKNOWN (XML безTZ); официальныйHTML независимо показывает
15Oct10:00МСК. API время не visibility lag; freshness/p95/fullnational UNKNOWN.

Evidence в open-applications-20261013-v1: priority-production-final-result-v1.json,
priority-production-import-v1.json, priority-production-replay-v1.json,
priority-production-provenance-after-replay-v1.json, priority-production-search-v1.json.
Census продолжается одним producer с сохранённым региональным порядком;
first-only pass96–107 завершён:12requests/recheck0,4reads дали44+10/223+1,
lease1196.69с/total2007.67с. Raw CSV5936/7638, present5779/5990, missing157/1648
на snapshot11:52:47UTC. Набор неполный, raw seeds включают старые сроки; это не
точное число открытых закупок. Осталось66first/10recheck задач,min71HTTP.
По текущему mix условный остаток3h18–6h02 (unknownempty/<=500), верхняя границаUNKNOWN.
Один следующий producer74064 сохраняет региональный порядок. Evidence:
first-only-pass-result-v2.json и compare-new-filter-partial-v12.json.
Следующее действие — завершить существующий first-only pass, сравнить новый набор
с production и обновить остаток/темп. Одобренный импорт не повторять.

### Первый обход108–119 — прирост и SSH-отказ, 14 октября

CSV дали44+30/223+294 уникальных номеров;12first attempts=9sourceHTTP+3 SSH
connect failures до команды на нашем сервере. Повторных сверок/source-card/API-prep0.
Raw NO_OUTPUT/source_requestsUNKNOWN сохранены; stderr отдельно доказывает
client→ourhost port22 failure, не отказ ЕИС. После отказов successful118/119 и
read-onlySSH; под свободным exclusiveownerlock сняты только3 SSHblocks.
Настройки/source pacing/production не менялись, tasks/raw/checkpoints сохранены.
Known lease512.59с на9 requests; failed SSH lease timestamps UNKNOWN.
Commands615.03с + cooldown732с =22m27 reconstructed;4requests дали новыеIDs.
RawCSV5966/7932,present5789/6194,missing177/1738 на DB12:32:59UTC;
это retained наблюдения, включая прежние сроки, не exact openN/currentrevision.
Metadata223CUSTOMER02:335 в08:15UTC, CSV375 в12:05UTC;223DELIVERY16:338
в11:58UTC, CSV341 в12:00UTC. Причина/полнота обоих расхождений UNKNOWN.
Осталось64first=60ready+4blocked,12change; ready minimum67HTTP,unknownMETA54.
Ready-onlyconditional ETA2h47–5h02 при9HTTP/12attempt mix и unknownempty/≤500;
extra pages/splits/дрейф/blocked leaves/lease не дают полного upperETA.
Один nextfirst-onlyproducer72480; helper unchanged, unvisited перед changes,
региональный порядок прежний; широкие blockedparents не повторяются автоматически.
Evidence: first-only-pass-result-v3.json, third-pass-ssh-failure-diagnosis-v1.json,
continuation-after-third-pass-before-ssh-recovery-v1.json, compare-new-filter-partial-v14.json.
Следующее действие — завершить существующий boundedpass, записать рост/остаток,
затем readyfirst ranges; полнота и текущая открытость остаются INCOMPLETE/UNKNOWN.

### Подготовка региональных пропусков без выпуска — 14 октября, ongoing pass

Source0/DBwrites0: regional-priority-memberships-partial-v4.json разделяет CUSTOMER
и DELIVERY, union/intersection и missing по существующему RLS snapshotv16.
Observedpartial: Татарстан44union655/present526/missing129,2231135/905/230;
Башкортостан44union767/present617/missing143/NOT_COMPARED7,223382/280/102;
МарийЭл223union21/present15/missing6. Семь не входивших в DB input номеров
оставлены UNKNOWN, не отсутствующими. Union регионов не добавляется к nationalN
повторно; queryгеография не фактическая XMLгеография/исчерпывающий охват.

priority-missing-candidates-partial-v2.json сохраняет608unique(law,number) кандидатов,
исключительно пересечение региональныхCSV с подтверждённым missing-set comparisonv16.
Для каждого сохранены исходные AF/deadline/title, CSV URL/file/hash/source stamp,
CUSTOMER/DELIVERY flags. Currentrevision/cancel/suspend/lotstate/XMLtype/deadlineTZ
UNKNOWN — это НЕ список подтверждённо открытых/готовых импортов. Существующий
stock cached/by-number путь принят на реальном45250; для нового номера нужны
card/XML/XSD/bind/lot/provenance и exactapproval, не новый release. Истёкший
539c64 payload и исполненный45250 не повторяются.

Snapshotcomparisonv16: rawCSV6648/7947,present6330/6203,missing318/1744,
DB12:58:52UTC. Это не exact openN; сохраняются истёкшие source observations.
Livepass partial9firstHTTP/recheck0 дал44+682/223+15, measuredlease940.56с;
producer72480/ownerlock жив, activecheckpoint не изменяется. Финальный темп/остаток
считать по завершению pass, предыдущую условную оценку не выдавать за гарантию.
Следующий шаг — finishexistingpass, затем readyunvisited по прежнему региональному
приоритету; источниковые проверки новых карточек координировать одним владельцем.

### Первый обход120–131 завершён — 14 октября

12HTTP первого обхода, повторных0, новых44+689/223+15;7requests дали новыеIDs.
Knownlease940.56с (12/12),commands990.282с+cooldown732с=28m42 reconstructed.
RawCSV6655/7947,present6337/6203,missing318/1744 на DB13:06:43UTC;
это неполный observedset с retained сроками, не exact openN/currentrevision.
Metadata/nativecount/filter/asof и все6blocked ranges сохранены в
first-only-pass-result-v4.json; countdrift не EOF/PASS и не исчезновение закупки.
Осталось60first=54ready+6blocked,16changes,min59readyHTTP,unknownMETA49.
Ready-onlyconditional2h21–4h18 при текущем mix/unknownempty-or<=500;
blocked/drift/extra pages/leases не дают полного upperETA.
Collector72480 штатно завершён. Перед следующим pass root выполняет один
ограниченный source-read45747 card/lot preflight через existingdeadline_document
под тем жеcollector-owner.lock, stockimportlease300/TLS/8MiB/61cooldown.
Это независимая подготовка отсутствующей карточки, без canonical writes/release,
не второй producer; actualPID/status в priority-open-preflight-status-v1.json.
Следующее действие — завершитьpreflight/cleanup, затем один existingfirst-only
--max-requests12 collector. Productionloaderscontinue; expiry539 не продлевается.
Evidence: first-only-pass-result-v4.json, compare-new-filter-partial-v17.json,
priority-card-lot-preparation-45747-v2.json после завершения preflight.

### Одобренный45747 data-only исполнен, census132–143 завершён — 14 октября

Exact e133634…/executor3f6ff… подтверждён человеком и выполнен.32616445747/revision1,
XML0e276121… добавлен вproduction:1version,sourcecalls0;runtime/schema/worker3GiB3CPU
и guards unchanged. Import111.501с,worker2.816с,priority106.807с/import1.502с.
Replay175.220с,new_versions0;priority160.088с/import12.007с. Provenance/RLSforeign0,
rawXML/archive/window/response/prepared bindings и ownedworker/markercleanup PASS.
Existingapplicationreceipt VALID reused; no gate/install/migration/backup.
Titlequery «комплексным испытаниям диагностике» — identity visible onfirstpage,
HTTP200/5.296с;number32616445747 — HTTP200/0.077с EMPTY/FAIL. Одинtitle sample
выше2с/5с целей, p95/p99 UNKNOWN; separateperformance defect,no fixinscope.
Canonicaldeadline/publication/suspension UNKNOWN; HTMLAF/revision1/15Oct10MSK и
XMLlotcancelled=false/GUIDparity сохранены как отдельныеsourceobservations.
XML→visibility/availability→index p95 UNKNOWN; approval/preparation были ручными,
source/client clock relationtrusted UNKNOWN. No globalfreshness/completenessclaim.
Evidence:priority-production-final-result-45747-v1.json и указанные в нёмpostchecks.

CSVpass132–143:12firstHTTP/recheck0,44+675/223+189;lease921.43с,
commands978.282с+cooldown732с=28m30. Sourcecard/lot/by-number preparation отдельно.
first-only-pass-result-v5.json сохраняет12immutableexecutions и latestremaining
на14:01UTC(nextpassужеactive):57first=46ready+11blocked,19changes,min51readyHTTP,
unknownMETA42;readyconditional2h01–3h41,wholeETAUNKNOWN(drift/extra pages/lease).
Сводка сначала не записалась из-за локальнойsyntaxerror; raw/checkpoint не потеряны,
no productionchange. Сводка исправлена; activecheckpoint не редактировался,
readonlysnapshot continuation-observed-for-v5-metrics-v1.json сохранён отдельно.
Comparisonv18:raw7443/8152; это retained observedset, не exactopenN. Одно наличие
версии не currentstate/searchvisibility. Следующий producer89056 один, first-stage
региональный порядок16+neighbors->77->78->rest/customerORdelivery сохраняется.
Следующее действие — закончитьexisting144–155 boundedpass, обновитьgrowth/remaining/
RLScomparison; не повторятьисполненные539/e133 dataoperations и не начинатьapprelease.

### Первый обход144–155 — 14 октября

12firstHTTP/recheck0,44+121/223+63;5requests дали новыеIDs. Lease634.49с,
reconstructedtotal1419.592с=23m40. Raw7451/8199;presence asof comparisonv19,
это не exactopenN/currentrevision и включает retained expiredobservations.
Осталось53first=42ready+11countdriftblocked,23changes,min47readyHTTP,METAunknown37;
ready-onlyconditional1h33–2h46 atlastmix/unknownempty-or<=500,no fullupperETA.
Metadata/filter/asof/blockedbounds в first-only-pass-result-v6.json; unchanged
blockedparents не повторяются. Одинnextfirst-stageproducer, actualPID в handoffv116,
sharedownerlock/stocksource/3GiB3CPU/SQL5s/TLS/pacing прежние.
Обаexactdata539/e133 исполнены/cleanupPASS, не повторяются; новыхapprovals pending0.
Следующее действие — finishesexisting156–167pass, updategrowth/RLScompare/remaining,
thenreadyunvisited priorityranges. Productionloaderscontinue; apprelease не начат.

### Два контрольных импорта и причина lease — 14 октября

Root; owned: private evidence/передача и документы; runtime не менялся.
Оба контрольных KESMBO 32616445250/32616445747 завершены: import1/replay0,
provenance/RLSforeign0/ownedcleanupPASS. Title-query1.275/5.296с; number-query
HTTP200 EMPTY/FAIL у обоих. Canonicaldeadline/publicationtimezone/suspension
UNKNOWN; sourcecard15Oct10MSK отдельно. Нет p95/p99 или freshnessPASS.

Installed importer автоматически связывает tenant/номер/UID/initial/prepared/
archive/proof/record hashes, выполняет bounded parse, transactional index/replay.
XSD проверяет source probe; importer проверяет сохранённый XSD proof. Accepted
executor автоматически проверяет exact hashes/receipt/resources/expiry/leases/
workertermination/owncleanup. Card/revision/GUID/lot/deadline reconciliation,
provenance/RLS/replay и search используют отдельные существующие процедуры:
это пока не автоматический end-to-end batch. Два примера доказывают KESMBO,
не смешанный набор608(270law44/338law223). Prepared ambiguous2, ready complete0;
607старых кандидатов не подготовлены и не объявлены всё ещё missing.

На100сопоставимых single-revision/one-archiveKESMBO: XML30.7–38.0мин;
две publicстраницы/номер при61с дают минимум202.3мин интервалов; консервативная
последовательная подготовка3.88–4.01ч без lease/retry/approval/postchecks.
Cached worker100операций4.52–4.69мин без lease; это отдельная стоимость импорта.
Для608 ETAUNKNOWN до распределения типов/редакций/объёмов, не экстраполяция.

36CSV120–155 ждали2496.48с:44priority2204.36с(88.3%),223292.08с,
неатрибутировано0.04с. Stock monotonic metrics сопоставлены с /proc/uptime,
не с расходящимися wallclocks. Два прохода120–143:54.25% ожидания;144–155:44.7%.
Installed44 wrapper удерживает hostfd9 на весь60windows/180s worker; median184.6с.
В44наблюдениях1094NO_DATA/492SYNCED,7083.60с суммарно; минимум5140с приходится
на обязательный2s pacing2570HTTP. CPU/DB/network/poll отдельноUNKNOWN. Удалять
lock/паузы или снижать maxwindows без расчёта нельзя. Зависание не подтверждено.

Минимальный вариант для последующей локальной проверки: обслужить один pending
CSV между завершёнными атомарными окнами существующим владельцем/transport,
с тем же cooldown/oneHTTP/pacing и бюджетом fresh44. Простое unlock вcontainer
не освобождает hostfd wrapper; никакого второго loader/framework. Выигрыш ещё
не измерен; всё2496с не объявляется устранимым. Сейчас реализации/релиза нет.
Evidence в open-applications-20261013-v1:two-control-automation-and-lease-result-v1.json,
priority-preparation-buckets-v1.json,lease-wait-holder-attribution-v1.json,
lease-owner-fd-readonly-v1.json и installed snapshots. Следующее действие —
закончить existing156–167 CSVpass и продолжить непосещённые priorityranges,
не ручную подготовку остальных608. Production loaders продолжают работать.

### Первый обход156–167 завершён после контрольных примеров

12firstHTTP/recheck0,44+793/223+752;7requests дали новые IDs. Lease977.8с
из1763.14с(55.46%), включая732сcooldown; это основной измеренный тормоз.
RO/RLScomparisonv20 DB15:02:14UTC: raw8244/8951,present7713/6986,missing531/1965.
Raw retainedexpired, NOTexactopenN; anyversionpresence не актуальная карточка.
47first=36ready+11blocked,29changes,min41readyHTTP,unknownMETA32. Readyonly
conditional1h40–2h59 приsamelease/mix иempty-or<=500META; fullupperETAUNKNOWN.
Одинexistingcollector168–179 подтверждён actualPID/commandline; details вhandoffv118.
Firstbeforechanges/региональный порядок сохранены;608вручную не подготавливаются.
Evidence:first-only-pass-result-v7.json,compare-new-filter-partial-v20.json,
actual-collector-after-controls-v1.json. Следующий шаг — finish existingboundedpass.

### Первый обход168–179 — 14 октября

12firstHTTP/recheck0,new44+193/223+28;6requests дали новыеIDs. Lease716.76с
из1499.297с(47.8%), включая732сcooldown. Comparisonv21 DB15:36:31UTC:
raw8437/8979,present7902/7108,missing535/1871; retainedexpired/anyversion,
NOTexactopenN/currentstate. Changes DBpresence не приписываются privateintake.
41first=30ready+11blocked,35changes,min35readyHTTP,METAunknown26; readyconditional
1h13–2h07 приsamelease/mix иempty-or<=500META. Forecast не включает idleмежду
boundedpasses; wholeupperUNKNOWN. Одинexistingproducer180–191 actualPID/commandline
verified; no duplicate/activecheckpointedit. Firstregionalpriority сохраняется;
11driftblocked не повторяются широкими parents, новые releases/cardprep608 не начаты.
Evidence:first-only-pass-result-v8.json/compare-new-filter-partial-v21.json,
continuation-after-pass168-179-v1.json/actual-collector-after-pass168-179-v1.json.
Следующее действие — finish oneexisting180–191 pass, thenremaining readyfirst.

### Первый обход180–191 — 14 октября

12firstHTTP/recheck0,new44+1091/223+0;6requests дали новыеIDs. Нулевой223growth
не отсутствиепубликаций/неполнотаPASS. Lease905.81с из1700.67с(53.3%),
732сcooldown. Между finalcheckpointwrite и nextlaunchpreflight88.243с idle,
localclockmtime proxy, не measuredprocessexit. Comparisonv22 DB16:06:29UTC:
raw9528/8979,present8812/7108,missing716/1871; retainedexpired/anyversion,
NOTexactopenN/currentstate. 35first=24ready+11blocked,41changes,min29readyHTTP,
unknownMETA20. Readytiers:16+neighbors3/77Moscow5/78SPb5/rest11. Это не региональная
полнота:11driftblocked сохранены отдельно. Readyconditional1h09–1h56samecontention,
METAempty-or<=500/exclidle,wholeupperUNKNOWN. Одинproducer192–203 actualverified;
productionloaderscontinue, ресурсы/pacing/guards прежние. Новыхrelease/cardprep608нет.
Evidence:first-only-pass-result-v9.json/compare-new-filter-partial-v22.json,
continuation-after-pass180-191-v1.json/actual-collector-after-pass180-191-v1.json.
Следующее действие — finish192–203 и оставшиесяreadyfirst в согласованном порядке.

### Первый обход192–203 — 14 октября

12firstHTTP/recheck0,new44+1532/223+683;8requests дали новыеIDs. Lease1635.63с
из2419.296с(67.6%),732сcooldown. Idle послеfinalcheckpointwrite1173.642с
(19m34) доnextlaunchpreflight; localmtimeproxy, не measuredworkerexit.
Existingm0-csv readinessheartbeat30→10min устраняет часть продолженияpollinggap;
приживомcollector толькоreadonlystate. Sourcecooldown61/oneHTTP/max12/TLS/lease300,
SQL5s/3GiB3CPU/productioncron прежние. Измеренныйэффект измененияmonitor покаUNKNOWN.
Comparisonv23 DB17:06:12UTC:raw11060/9662,present10290/7679,missing770/1983;
retainedexpired/anyversion, NOTexactopenN. 32first=21ready+11blocked,44changes,
min33readyHTTP/unknownMETA16. Moscowcustomer44native4183/223native2581 asofsavedMETA;
ещё идут offsets, не exhaustedextent/полнота. Readytiers77=5/78=5/rest11,
region16+neighborsfirstready закончены, blocked11 сохраненыUNKNOWN.
Readyconditional1h51–2h45samecontention/empty-or<=500META/exclidle,wholeupperUNKNOWN.
Одинproducer204–215 actualverified;productionloaderscontinue/no release/manual608.
Evidence:first-only-pass-result-v10.json/compare-new-filter-partial-v23.json,
actual-collector-after-pass192-203-v1.json/continuation-monitor-idle-adjustment-v1.json.
Следующее действие — finish204–215 и оставшиесяreadyfirst по приоритету.

### Первый обход204–215 — 14 октября

12firstHTTP/recheck0,new44+2660/223+1007;10requests дали новыеIDs. Все12HTTP
учтены:2countdrift executions содержалиbasefields, metadata/growth joined по
exactfile+URL изfrozencheckpoint; raw не изменялись. Lease689.04с из1461.78с
(47.1%),732сcooldown. Idle51.164с послеfinalcheckpointwrite доnextlaunch;
agentactive atcompletion, не доказательство эффекта только10minmonitor.
RO/RLScomparisonv24 DB17:32:57UTC:raw13720/10669,present12941/8463,missing779/2206.
Inputs=frozenv23 unionCSV204–215, live216+excluded; приростinputs=passgrowth проверен.
Retainedexpired/anyversionpresence, NOTexactopenN/currentstate/searchvisibility.
MoscowCUSTOMER44:4185unique vs4183META;223:2584 vs2581. ПричинаUNKNOWN:
sourcechange/pagination не исключены; всёraw/IDs сохранено, completeness неPASS,
не immediatewide retry. 30first=17ready+13blocked,46changes,min22readyHTTP,
unknownMETA14;readytiers77=1/78=5/rest11. Readyconditional45–73minsamecontention/
METAempty-or<=500/exclidle;fullupperUNKNOWN. Одинexisting216–227 actualverified.
Evidence:first-only-pass-result-v11.json/compare-new-filter-partial-v24.json,
moscow-customer-first-extent-drift-v1.json/actual-collector-after-pass204-215-v1.json.
Следующее действие — finish216–227, remainingreadyfirst beforechanges;
13blocked позже smallerallcoveringpartition, безnewrelease/manual608/productionchange.

### Первый обход216–227 — 14 октября

12firstHTTP/recheck0,new44+449/223+0;9requests дали новыеIDs. Lease521.4с
из1298.438с(40.2%),732сcooldown. Idle396.332с послеfinalcheckpointwrite,
localmtimeproxy доnextlaunch; отдельная цена продолжения, sourcepacing прежний.
RO/RLScomparisonv25 DB18:00:01UTC:raw14169/10669,present13381/8514,missing788/2155.
Inputs=frozenv24 unionCSV216–227, live228+excluded; inputgrowth=passgrowth проверен.
Retainedexpired/anyversionpresence, NOTexactopenN/currentstate/searchvisibility.
Moscow44DELIVERY_GAR3906uniquevs3905META, newblocked; previousCUSTOMERdifferences
сохранены. ПричинаUNKNOWNsourcechangeORpagination; не repeatwideparent/неPASS.
30first=16ready+14blocked,46changes,min26readyHTTP,unknownMETA11;
readytiers78=5/rest11. Приоритетные16+neighbors/77readyfirst exhausted,
но14blocked отдельно и региональнаяполнотаUNKNOWN. НачатыSPbCUSTOMER44CSV/223META.
Readyconditional47–67minsamecontention/METAempty-or<=500/exclidle;fullupperUNKNOWN.
Одинproducer228–239actualverified, productionloaderscontinue/no runtimechanges.
Evidence:first-only-pass-result-v12.json/compare-new-filter-partial-v25.json,
actual-collector-after-pass216-227-v1.json/continuation-after-pass216-227-v1.json.
Следующее действие — finish228–239, remainingreadyfirst beforechange reconciliation.

### Первый обход228–239 и остановка перед reconciliation — 14 октября

12firstHTTP/recheck0,new44+2084/223+449;9requests дали новыеIDs. Lease1202.72с
из1979.172с(60.8%),732сcooldown; continuationidle398.256с localmtimeproxy.
RO/RLScomparisonv26 DB18:39:52UTC:raw16253/11118,present15384/8899,missing869/2219.
Inputs=frozenv25 unionCSV228–239, live240+excluded; inputgrowth=passgrowth проверен.
Retainedexpired/anyversion, NOTexactopenN/state/searchvisibility. Offlinecalendarv1
отдельно: today1385law44/1860law223 TIME/TZUNKNOWN; дата не даёт eligiblePASS.
SPbCUSTOMER44 unique2643vs2648META;223681vs680,DELIVERY223377vs376:
причинаUNKNOWNsourcechangeORpagination,3newblocked. 29first=12ready+17blocked,
47changes,min21readyHTTP,METAunknown8;readytiers78=1/rest11. Conditional58–80min
samecontention/METAempty-or<=500/exclidle;fullupperUNKNOWN. Одинoldcode240–251 работает.

Bounded privatehelper fix: actualdeadline_census с fixtureROOT/source0 воспроизвёл
RECHECK при blockedfirst+readychanges. После двух проблем настройки fixture метод
упрощён: BaseExceptionintercept доHTTP, без фабрикации executionevidence.
Добавлен только phase-stop: FIRST_ENUMERATION_BLOCKED_NEEDS_REFINEMENT, если
readyfirstнет иblockedfirstостались. Следующий запуск требует smallerofficialpartition,
не endlessrechecks/unchangedrestart. Actualfunction4source0casesPASS: stop/restart
с durableblockedIDs; readyfirstbeforechange; regionaltier; changesallowedпосленулевогоfirst.
FixtureSTOPPED_FAILURE после intentionalintercept ожидаем и не source/productionFAIL.
HelperSHA421ea21dffda2d852401a37af66510cf61fa171c589a1666b8ebd7422904b3fe,
prior dffa2b31…; текущийloadedproducerне менялся/activecheckpointнеedited.
Production/scheduler/guards/HTTP/pacing/лимиты прежние; нетrelease/gate/receipt/newhelper.
Evidence:first-only-pass-result-v13.json/compare-new-filter-partial-v26.json,
first-stage-blocked-before-recheck-{repro,proof}-v1.json/first-stage-blocked-stop-helper-v1.diff.
Следующее действие — finish240–251; nextfirstpass421ea21d; приnewstop splitblocked
подсвободнымownerlock, сохраняя исходныеraw/IDs и UNKNOWN причины расхождений.

### Первый обход240–251 — 14 октября

12firstHTTP/recheck0,new44+802/223+29;8requests дали новыеIDs. Lease636.07с
из1408.922с(45.1%),732сcooldown; continuationidle438.532с localmtimeproxy.
RO/RLScomparisonv27 DB19:10:37UTC:raw17055/11147,present16181/8941,missing874/2206.
Inputs=frozenv26 unionCSV240–251, live252+excluded; growthassertPASS.
Retainedexpired/anyversion, NOTexactopenN/currentstate. National15Oct44priceleaf
4009uniquevs4028META,2232377vs2442;2newblocked, causeUNKNOWNsourcechangeORpagination.
Parentraw/IDs/metadataasof сохранены, не retrywide/no completecredit. 28first=
9ready+19blocked,48changes,min18readyHTTP,unknownMETA6. Priorityreadyregions16/neighbors/
77/78 exhausted butblocked remainUNKNOWN; идут allRussia deadlinebranches.
Readyconditional35–47minsamecontention/METAempty-or<=500/exclidle;fullupperUNKNOWN.
Один252–263 запущенпослеactualPID/ownerlock/helperSHA preflight:421ea21d verified.
Новыйphase-stop действует при no readyfirst + blockedfirst; без endlesschanges.
Evidence:first-only-pass-result-v14.json/compare-new-filter-partial-v27.json,
actual-collector-after-pass240-251-v1.json/first-pass252-launch-preflight-v1.json.
Следующее действие — finish252–263; приFIRST_ENUMERATION_BLOCKED_NEEDS_REFINEMENT
подfreeownerlock smallerallcoveringpartition, сохраняя географию/UNKNOWN/parentIDs.
Production/scheduler/guards/pacing прежние, нетnewrelease/manual608.


### 2026-10-14 22:51 МСК — первый CSV-проход252–263

Root; evidence `first-only-pass-result-v15.json`, `compare-new-filter-partial-v28.json`, frozencheckpoint252–263. 12 first HTTP,0recheck; new44+1485/223+875,11requests yielded newIDs. Lease1307.06s/2075.376s=63%; nextlaunchidle272.706s finalcheckpoint-localmtime proxy, not measured process-exit. DB22:49:43MSK:44 observed18540/present17628/missing912;223 observed12022/present9582/missing2440. Partial retained observations include expired; anyversion presence does not establish actualopen/state/searchvisibility. Server clock~67s behinddesktop, trustedrelationUNKNOWN.

At263:7readyfirst/20blockedfirst/49changes,min8readyHTTP,5unknownMETA; conditionalready23–38min samelease/mix/METAempty-or<=500/excludingidle; fullupperUNKNOWN. New223deadline16Oct offset1001 overlaps previousCSV: parent/raw/parsedIDs preserved, causeUNKNOWN; requires smaller official exhaustivepartition, no unchangedwide retry. Oneexistingcollector PID123412/session26696 runs264–275 under421ea21d helper; afterpass savegrowth/RLS thennextreadyfirst. On blocked-first stop refine underfreeownerlock beforechanges. Productionloaders continue; no release/scheduler change.


### 2026-10-14 23:21 МСК — первый CSV-проход264–275

Root; evidence `first-only-pass-result-v16.json`, `compare-new-filter-partial-v29.json`, frozencheckpoint264–275. 12firstHTTP/0recheck,5requests yielded newIDs;44+1137/223+682. Lease869.27s/1664.671s=52.2%; idle116.242s checkpoint-localmtime→nextlaunch proxy, not worker-exit. DB23:19:32MSK:44observed19677/present18754/missing923;223observed12704/present10237/missing2467. Retainedpartial/raw includesexpired; anyversion presence notactualopen/currentrevision/searchvisibility. Server~67sbehinddesktop/trustedrelationUNKNOWN.

NativeMETA44deadline16Oct8063 and223deadline20Oct∞8374 require more date/pricepartitions, no added globalprice/publication restriction; null/cents/exhaustiveunion remain separate acceptance. At27510readyfirst/21blockedfirst/50changes,min24readyHTTP/8unknownMETA; conditionalready55–74min samelease/mix/METAempty-or<=500/exclidle, wholeupperUNKNOWN. New22317–19Oct unique2500vsMETA2463 causeUNKNOWN, raw/IDs retained and nofullnesscredit/unchangedwide retry. Oneexistingcollector140536/session82162 first276–287; afterpass result/RLS/nextfirst. Refineblockedfirst underfreeownerlock whenreadyexhausted; changeslater. Productionloaderscontinue/no release/scheduler.


### 2026-10-14 — ночные этапы и подготовка первой партии

Root; human разрешил продолжать после доступной очереди: разбор blockedfirst без ожидания, midnightpreserve/rebase, statebuckets national/Tat и автоматизированную подготовку до20 кандидатов существующими средствами. Production-записи запрещены до одного exactbatchapproval; приложение/scheduler/resources/guards/access/frequency и профиль компании не менять. Старый запрет на ручную последовательную подготовку608 не мешает новой boundedавтоматизации. Оба контрольных импорта завершены, не повторять.

`overnight-stages-v1.json` и handoffv128 задают продолжение. Existingm0-csv ACTIVE с сохранённым10minритмом, prompt заменён согласованными этапами; второй automation нет. `priority-batch20-manifest-v1.json`:20SELECTED_NOT_PREPARED,10по44/10по223 с разными CSVmethods; отсутствовали в comparisonv29, savedAF+futurecalendar только кандидаты. Ready0, currentrevision/state/TZ/XML/readiness ещёUNKNOWN; sourcecalls0/productionwrites0. После ownerboundary — reuseXML/existingprep, manifest ready/ambiguous/unsupported/unprepared, actualwalltime/lease/network/pacing, затем одна точная операция.

`blocked-first-range-review-v1.json` по frozen275 сохраняет21блокированную ветку, pages/hash/offset/sourceobservations:17допускают соседние deadlinechildren,4single-day требуют другого официального фильтра либо extentvalidation.10имеют один CSV нижеcap,1имеет pageoverlap; эти наблюдения сами не доказывают полноту/изменениеисточника. Активныйcheckpoint не редактировался, дети не активированы; существующийPID140536 продолжает276–287. При свободномownerlock применять проверенныеchildren с сохранениемprice/geo/company/parentraw; неизвестные причины отдельно, независимые части продолжать.


### 2026-10-14 — сохранение блокировок при смене суток

Privatehelper854eb727 заменяет421ea21d для следующих запусков. Actualoldloop source0 воспроизводит сбросblocked_reason/phase приmidnight и незапрошенный wideparentretry. Новый rebase_census_calendar сохраняетblockedparent IDs/reason/lane с calendar_rebase_pending, архивирует его раз вдату; истёкшие querybranches сохраняет отдельно, unblockedrebase сохраняетcompany/geo/prices.7actualfunction source0cases PASS; proof `midnight-block-preservation-source0-proof-v1.json`, diff `midnight-block-preservation-v1.diff`. Никакого вывода о текущем состоянии закупок или полноте из этого proof. RunningPID140536 загружен421, не прерывался; activecheckpoint/production/pacing/leases не менялись. Послеfreeownerboundary verify854 передзапуском; refinement lower=max(parentfrom,today), parentraw retained.


### 2026-10-14 23:45 МСК — первый проход276–287 и применение refinement

Root; `first-only-pass-result-v17.json`, `compare-new-filter-partial-v30.json`:12firstHTTP/0repeat,11requests yieldednewIDs,44+2273/223+1257; lease547.81s/1317.453s=41.6%, idle87.894s checkpointmtime→nextlaunch включаяlocalrefinement, неprocess-exit. DB23:43:15MSK retainedpartial44=21950/present20249/missing1701,223=13961/present11287/missing2674; expiredobservations retained/anyversion only, notactualopenN/latest/searchvisibility; clocksrelationUNKNOWN.

`blocked-first-deadline-refinement-activation-v1.json`: подсвободнымownerlock17неполныхродителей→34смежныхдочернихdeadlineграницы, geo/price/company сохранены; source0URL/adjacentunion checksPASS, sourceполнотаUNKNOWN. Родители/raw/IDs сохранены вsuperseded_incomplete_tasks; не считать ихcomplete и неактивировать повторно. Послеactivation43readyfirst/5blockedfirst/50changes,min45readyHTTP/41unknownMETA; conditional82–157min samelease/mix/METAempty-or<=500/exclidle, wholeupperUNKNOWN. ОдинPID162932/session62125 runs288–299 с854helper; Tatrefinedfirstpriority восстановлен. Наmidnight сохранятьblockedreason/lane/raw, refinementlower=max(parentfrom,today). Batch20prep pending/no prodwrites, productionloaderscontinue.


### 2026-10-15 00:08 МСК — lease-stop и начало первой реальной партии

Root; first-pass288-290-lease-stop-result-v1.json:3attempts/2firstHTTP/0repeat/0newIDs; thirdexit75/noentry/importwait300s/source0. Totalwait347.15s/485.016s=71.6%; cooldown122s только после2successfulMETA, timeoutbranch exits immediately. Boundedreadonly pass288-shared-lease-diagnostic-v1.json then provedmutexFREE; only290leaseblock cleared underowner, rangeblocks retained. Midnight effective_from15Oct, rawIDsets notreset; expiredquerybranches archived, not confirmedcurrentclosedprocurements.

Independentfirst2prep (fiveobjectiveblockedleaves) now localPID170428/session65664 holdscollector-owner.lock, no activeCSVproducer. Read-plan selects0211200000126000030law44 and32616417744law223; existingworker/stockimportlease300/3GiB3CPU, no prioritymarker/appwrites. AcceptedOwnedWorker+cleanup ASTidentical; localowner retaineduntilremoteprocess+ownedcontainers terminal. Actualresults pending/prepared0. Fullclientwall includesstaging/lease/network/mandatorypauses/cleanup; actualHTTPcountUNKNOWN, no invented0. Terminal→cacheproof/stockpreflight/XSD/currentstate thenrest≤20/CSVresume291+; no repeatfirst2 ifresult/cacheexists. Productionloaderscontinue.


### 2026-10-15 00:17 МСК — второй lease-refusal и изменение private-допуска

PrepV1 штатно завершён: importwait300.007s, fullclient304.297s, no acquiredlease/no worker/no callback => diagnosticHTTP0; rawsource_callsUNKNOWN сохранён. Cleanupconfirmed, results[]. После двухsharedadmissionfailures одинаковый polling не повторён: privateV2 usesstockblocking GNUflock-E75-w300 throughinheritedparentFD; Linuxsource0 proveslockretainedafterchildexit/releasedonparentclose/75nocallback. No pollingstarvationcausalclaim. AcceptedOwnedWorker+cleanup unchanged, no production/sourcefrequency/resources/prioritymarker changes. PID125768/session19255 nowownscollectorlock, sourcepreparation2callbacks pending; noCSVproducer. V2failure не означаетrun20sameattempts.

`current-state-buckets-partial-20261015-v1.json` usesv30 DB14Oct23:43:15MSK withoutnewsource/DBqueries: nationalretained21950/13961,present20249/11287,missing1701/2674; Tatunion655/1135,present550/992,missing105/143. No acceptedfullcurrentopen/closedproofs => actualNUNKNOWN, notactual0; allretainedstatesunconfirmed/currentrevision/TZ/cancel/suspend/lotstate. UnfinishedTatqueries7perlaw afterrefinement/midnight, allgeoflags separate. Reportgeneration notupdatedDBsnapshot. Actualsource2captureruntime/readybatch remainspending; no canonicalwrites.


### 2026-10-15 00:34 МСК — реальные XML первой пары и оставшаяся партия

Root; first2 captureV2 completed/cleanup confirmed: fullclient312.672s, lease144.794s, outerpauses122.000s; HTTPcount UNKNOWN_NOT_INSTRUMENTED. Cachedstock44 preflight found official cancellation0211200000126000030, event14Oct14:39:22MSK after last savedAF12:28:23MSK; exclude fromopenbatch, preserveCSV/raw/provenance. 22332616417744 purchaseNotice contentparser+XSD16.2/16.3 PASS, but installedBY_NUMBER admission onlyKESMBO: WINDOW_INVALID; awaredeadline/currentstateUNKNOWN, no bypass/unsupportedtypeclaim. Manifest ready0/excludedclosed1/ambiguous1/unprepared18. First2 neverrefetch.

Statebucketsv2 retainv30 DB14Oct23:43:15MSK: national44 listed21950=cancelled1missing+unknown21949(20249present/1700missing);22313961unknown(11287/2674). Tat44union655=cancelled1missing+unknown654(550/104);223union1135unknown(992/143). ConfirmedopenN UNKNOWN, noatomicnow/latest/searchvisibilityclaim; Tat7unfinishedqueries/law. One remaining18coordinator PID166196/session78077 holdsowner, actualcommandline verified, sourcecaptureonly/no prodwrites. Readresult+cleanup→cachedchecks/manifest→CSV291+ underfreeowner; no secondcaller. Full20preparation/loadETA UNKNOWN until actualmixedbatch and readyoperation. Handoffv132; evidence first2-event-admission-result-v1/current-state-buckets-partial-20261015-v2/remaining18-read-plan-v1 in existing evidence root.


### 2026-10-15 01:04 МСК — восемь наборов XML, новый допуск после lease-stop

Root; remaining18 operation captured6law44 then stopped7th atstocklease300.001s/exit75/no callback/HTTP0. Fullclient1206.360s, acceptedownedcleanup/remoteprocess/containerabsence confirmed. Cachedchecks source0:4stocknoticeparsersPASS/currentstateUNKNOWN;2archives contain supportedEOK2020 plus unsupportedfcsPurchaseApproval, wholepreflight blocked; no droppingadjuncts/fabricatedpartialarchive. Total8captured/checked:ready0/closed1/unsupported2/ambiguous5/unprepared12. SourceHTTPtotalUNKNOWN; measuredpartial8 capturewall1519.032s includeslasttimeout, full20/loadETAUNKNOWN.

Mutexheld diagnostics preserved, originalflockPIDnotvisible andFDholdernotidentified; noorphanclaim. LaterfreshprobeFREE provedchangedreadiness, then one remaining12coordinator PID173368/session77524 launched;8successfulcacheexcluded, bothlaws early, samekerneladmission/acceptedcleanup/pacing/resources. NoCSVproducer/prodwrites. Onterminal→cachechecks/currentcard/lots/oneexactmanifest; noapprovaluntilrealreadybatch. Newblocked22320–21Oct parent refinedto2adjacentsingle-daychildren underfreeowner;1000IDs/raw retained/UNKNOWN. Actualmidnightqueue80readyfirst/4blockedfirst/11changes; prior14Octlane counts obsolete. Statebucketsv3 regeneratesdenormalizedtable afterv2staleallunknown row; DBv30 unchanged23:43:15MSK14Oct, no source/DBrefresh. ProductINCOMPLETE.


### 2026-10-15 01:43 МСК — все20 XML проверены, текущие карточки отдельно

Root; final12capture completed/ownedcleanup/locksreleased PASS, fullclient1809.000s. All20(10law44+10law223) hashboundcachedmetadata/installedstockchecks complete: ready0/closed1/unsupported7/ambiguous12/unprepared0. Unsupported44:3wholearchives contain fcsPurchaseApproval alongside supportedEOK2020;223:2purchaseNoticeOK+2purchaseNoticeZPESMBO absentinstalledparser support. No silentexclusionfromnational/partialarchivefabrication.4other223 generic/AEScontent+XSDPASS buttargetedBY_NUMBERadmissionblocked.8remainingstockadmissiblecases requirecurrentcard/stateproof, not automaticreadiness.

Measured20capture activeclient3328.032s(55m28) includinglast300timeout; allattempts inclpriorfailedadmission/localdecode3632.470s(60m32). SourceHTTPUNKNOWN; lease/network/internalpoll-pacing andouterpauses savedseparately; fullprep includesnowrunningcardstage, loadETAUNKNOWN/ready0. Conditionalnextsame10+10 XMLcapture~60.54min excludescurrentcards/gaps, oneactualmixedbatch notstatistics. Onecurrentcardcoordinator PID175760/session53489 ownslock,8cards+observed223lotlinks/max12reads viaexistingdeadline_document/stocklease/61spacing. Privateprobe onlyadds8exactnativecardURLs; ASToutsideassignment unchanged, sameTLS/single-documentroute/bytes/timeouts, no productionguard/proxy/routeschange. Terminal→GUID/revision/deadline/lot/state review→exactreadyoperation/no writes→CSV291+. All20XMLneverrefetch. National/Tatcounts remainv3/v30 pendingacceptedcurrentproof. ProductINCOMPLETE.


### 2026-10-15 02:06 МСК — текущие карточки частично, национальный обход продолжен

Root; currentcard reader stopped4thattempt stocklease75/300s/noentry/source0;3savedcards explicitlyAF andfutureMSKdeadline matchesXML. CurrentGUID/revision/suspension/lotstate/XSD44 notfullybound, fullopenNUNKNOWN/ready0; no keywordabsence-as-PASS.3HTTP/lease384.17s/fullclient647.578s including244souterpauses. All20XML and3cardbodies reused;5primarycards(inclfailed0311100029326000080) pending, unsupported7/cancel1 retained. No emptybatchapproval/newwrites.

CSV291 succeeded375unique223/413lotpairs/newglobal41, lease0/command2.234s. It stoppedafterpersist becauseWindowscp1252 cannotprintregionalCyrillicJSON; onlyconsoleensure_ascii changedtoTrue, actualsavedcallcp1252roundtripPASS. Helper32cc79b8630ca49922f9548e689e332098b22a33f1186448f70407a728714a0f, no HTTP/mutex/queue/pacingchanges; savedCSV/checkpointnotrefetched. Last61scooldownloop didnotrun dueexception; actualexecutionmtime→nextlaunchgap>61s separatelyconfirmed. OneexistingCSVproducer PID172220/session59522 now292–303 viaunchangedstockE75w300; localstdoutfailure doesnotrequireidleproductionmutex. Iflease75again, stop+changedreadinessrule remains.

Comparisonv31 DB15Oct02:01:40MSK/frozenv30+CSV291only excludeslive292+, appRLS/read-only/200batch/SQL5s unchanged. Retainedcounts below are not atomiccurrentopenN; zero fullopenproofs is notactualzero.3cardAF/awaredeadlineobservations remainpartial.

| Scope/law | Listed unique | Full open N | Known cancelled | Unknown fullstate | Present anyversion / missing |
| --- | ---: | --- | ---: | ---: | ---: |
| Russia44 | 21950 | UNKNOWN | 1 | 21949 | 20249 / 1701 |
| Russia223 | 14002 | UNKNOWN | 0acceptedclosedproofs | 14002 | 11325 / 2677 |
| Tat44 CUSTOMERorDELIVERY | 655 | UNKNOWN | 1 | 654 | 550 / 105 |
| Tat223 CUSTOMERorDELIVERY | 1185 | UNKNOWN | 0acceptedclosedproofs | 1185 | 1035 / 150 |

Knowncancelled44/Tat:present0/missing1; unknown44national20249/1700 andTat550/104;223allunknown asabove. Tat44 customer615/delivery630/intersection590;223customer1075/delivery647/intersection537. NewTatunion+50 contains41newglobal+9alreadyglobalnewregionflags, not50additionalnationalIDs. Tat7unfinishedqueries/law, nationalbefore29279readyfirst/4blocked/12changes; regionaltransition/offsettraversal notfullness. ProductINCOMPLETE; afterpass freeze/metrics/RLS/nextfirst, card/GUIDproof independentatfutureboundary.


### 2026-10-15 02:53 МСК — завершён 292–303, продолжен первый обход

12 attempts/12firstHTTP/0repeat/0errors; CSV growth44+68/223+11. Lease1567.58s; command1624.091s + mandatory pauses732s =2356.091s, lease66.53% of this measured sum. Full process wall UNKNOWN (not measured by one monotonic timer). Checkpointmtime→nextlaunch495.199s includes comparison/agent work and heartbeat gap, not pure idle/process exit. HTML observed separately: {"44": 439, "223": 370}; never added to CSV union.

RLS consistent readonly v32 snapshot 2026-10-15T02:50:18.447051+03:00; frozen v31 plus only completed CSV292–303, growth assertions PASS. SQL5s/lock1s/200batch/RLS unchanged; live304+ excluded. Retained observations, anyversion presence, full current open N UNKNOWN. Closed proof is one official44cancel; zero accepted open proofs does not mean actual zero.

| Scope/law | Listed unique | Known cancelled | Unknown full current state | Present / missing | Unfinished queries |
| --- | ---: | ---: | ---: | ---: | ---: |
| Россия / 44 | 22018 | 1 | 22017 | 20317 / 1701 | 52 |
| Россия / 223 | 14013 | 0 | 14013 | 11343 / 2670 | 43 |
| Татарстан / 44 | 723 | 1 | 722 | 618 / 105 | 7 |
| Татарстан / 223 | 1189 | 0 | 1189 | 1041 / 148 | 7 |

Tat44 customer709/delivery630/intersection616/union723; Tat223 customer1075/delivery651/intersection537/union1189. Regional flags not actual XML geography; no duplicate national addition. Queue after303:73readyfirst/4blockedfirst/18changes, minimum75HTTP/70unknownMETA; same-mix conditional245–474min excludes idle, META may expand/full upperUNKNOWN. All18parent refinements already activated, preserve them; four single-day blocks remain independent refinement work, no unchanged wide retry.

One producer PID148636/session11329 runs304–315 with existing helper32cc/privateprobe573/stockE75w300/cooldown61, owner confirmed held. No second source caller. All20XML/3successfulcards reused; ready0/closed1/unsupported7/ambiguous12;5primarycards/currentGUID/revision/suspend/lot/XSD44 proofs pending. Full preparation/loadETA UNKNOWN. Product INCOMPLETE; production writes0. Next freeze/metrics/changed-ID comparison/nextfirst; coordinated residual prep and blocked refinement at free owner boundary.


### 2026-10-15 03:10 МСК — 304–315 завершён; остаток текущих карточек

12attempts/12firstHTTP/0repeat/0errors;6CSV/6META, CSV growth44+6/223+1. Lease118.54s, commands171.501s plus732s mandatory pauses=903.501s (lease13.12% ofsum). FullprocesswallUNKNOWN, measuredsum not substituted for one monotonic client timer. Frozen continuation-after-pass304-315-v1.json; every execution exactfile+URL accounted. HTML observed44=400/223=168 separately, not CSV union.

Same appRLS consistentreadonly snapshot v33 2026-10-15T03:07:36.179131+03:00, frozenv32+completedCSV304–315 only. SQL5s/lock1s/200batch unchanged; no source or DB writes. FullcurrentopenN UNKNOWN; retained observations/anyversionpresence not latest/searchvisibility/atomicnow.

| Scope/law | Listed | Known cancelled | Unknown fullstate | Present / missing | Unfinished queries |
| --- | ---: | ---: | ---: | ---: | ---: |
| Россия / 44 | 22024 | 1 | 22023 | 20323 / 1701 | 52 |
| Россия / 223 | 14014 | 0 | 14014 | 11348 / 2666 | 43 |
| Татарстан / 44 | 723 | 1 | 722 | 618 / 105 | 7 |
| Татарстан / 223 | 1189 | 0 | 1189 | 1041 / 148 | 7 |

Queue66readyfirst/4blockedfirst/25changes,min68HTTP/64unknownMETA; same-mix conditional85–166min excludesidle/METAexpansion, wholeupperUNKNOWN. Tatqueryunion723/1189 unchanged (7unfinished/law); source geography and exact currentstate unresolved. All18refinements alreadyactivated; four single-day blocks still require official all-covering refinement or extent-vs-temporal validation.

Residual5 currentcard coordinator PID174876/session40281 owns local lock; no CSV producer. Five uncached primarycards (0311100029326000080/0411000004426000001/0111100001126000053/32616424684/32616446729),223 first, plus exact observedlotlinks only/max12. Prior3successfulcards/all20XML excluded. Old failed031card proved source0; subsequent12successfulCSV admissions are changedconditions, not guarantee nextlease. Stockreader/terminalquery AST/cleanup/quarantine/61s pauses/TLS/limits unchanged; helper32cc/probe573. No actions/PARTICIPATE/productionwrites. Manifest ready0/closed1/unsupported7/ambiguous12; fullprep/loadETAUNKNOWN. Next terminal/cleanup/allmetrics/cachedstateproof, then CSV316+; unknownnotready, no pernumberprepapproval.


### 2026-10-15 03:31 МСК — все8первичных карточек сохранены; два списка лотов

Residual5 coordinator174876 завершён, remote_terminal_confirmed/ownerfree.5successfulHTTP/0errors/fullclient1062.562s incllease729.2s and305smandatorypauses. Combined primarycardphase8HTTP/1previoussource0leasefailure,client1710.140s/lease1113.37s/pauses549s. All8officialcards have explicitAF and awarefutureMSKdeadline matching XML walltime.2KESMBO currentpurchaseGUID+revision1 match hashboundXML; canonicalparsed223deadline stillUNKNOWN, not silently rewritten from HTML.44currentGUID/revision/XSD andcurrentlot/suspension remainUNKNOWN, fullopenNUNKNOWN/ready0. SameDBv33 15Oct03:07:36MSK; statebucketsv7 only adds sourcefacts, no DBrefresh/countchange. National22024/14014,present20323/11348,missing1701/2666;Tat723/1189,present618/1041,missing105/148.

Commonprivateadapterdefect reproduced on2savedHTML: html.unescape decodes native unescaped &noticeGuid as legacy &not entity (¬iceGuid), hiding valid native lotlinks. Localfix decodes only semicolon-terminatedentities; querydelimiters retained, strict exacthost/path/number/GUID checks. Plain/encoded/numericentity/foreignhost and2actualsavedcards PASS/source0. No primarycardrefetch/URLfabrication/proxy/productionchanges.2nativeobservedURLs bind currentpurchaseGUID and sourceHTMLhash.

One existingstockreader derivative PID180472/session52460 reads only2observedlot-list documents/max2. Terminal_query AST/cleanup/quarantine/TLS/limits/61souterpause unchanged; helper32cc/privateprobe573 unchanged. NoCSVproducer whileownerheld. Onterminal parse currentlotGUID/status vs savedXML, preserveUNKNOWN, thenCSV316+; do not wait all full current proofs to continueFIRST. All20XML/8cards reused; ready0/closed1/unsupported7/ambiguous12. Captureallattempts3632.470+primarycards1710.140=5342.610knownclientphase sum excludesgaps/agentwork/reviews/currentlots; fullprep/loadETA UNKNOWN, not89min readybatch forecast. Productionwrites0.


### 2026-10-15 07:39 МСК — два списка лотов проверены; CSV316+ возобновлён

Lotreader180472 завершён/remote_terminal_confirmed/ownerfree.2HTTP/0errors/lease279.35s;2currentpurchaseGUID pages contain all cachedXMLlotGUIDs,identitypresencePASS. Current cancellation/suspension notexplicitlyproven, canonical223deadlineUNKNOWN/44GUIDrevisionXSD unresolved; fullopenNUNKNOWN/ready0. All20XML/8primarycards/2lotpages reused; no newwrites. Same DBv33 15Oct03:07:36MSK, statev8 adds only sourcefacts, groups/table unchanged.

Full lotphase14219.000s; requiredpauses122s, actual13928.610s, localpauseovershoot13806.610s. HTTP2 already persisted by03:36:12MSK, coordinatorfinished07:27:19MSK while lasttime.sleep(61) returned13867.61s. KernelPower42/107 boundedread shows battery sleep/resume events; exact time relation/causeUNKNOWN, no clock/power/settings changes. Do not attribute localovershoot toEIS/transport/lease. Actualcapture+primary+lotclientphase sum19561.610s includesovershoot; phaseattributionwithoutit5755s excludesagentwork/reviews/gaps andisnotfullprep/loadforecast.

One actualCSVproducer PID8912/session99882 runs316–327, helper32cc/privateprobe573/stockE75w300/cooldown61 unchanged, ownerheld/no prep caller. Last315checkpoint→launch16256.733s includes entire prep/localpause/agentwork, not pureidle; prepterminal→launch642.549s includes nextheartbeat/analysis/review. Frozen before316 queue66readyfirst/4blocked/25changes, fullupperUNKNOWN; firsttraversal continues while currentstate proof remains incomplete. Next frozenmetrics/RLSchangedIDs/nextfirst; blocked officialrefinement and cachedcontractwork atfreeboundary.
