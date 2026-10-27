# V48 — реальная выборка для регионального прогноза

Владелец root, 26 октября 2026. Численная приёмка отдельной EA/500 группы PASS:
5разных закупок, median18.5%/p7530.79%. Исходная159/EZK остаётся UNKNOWN.
Evidence `tmp/eis-regional-five-20261026-v48/`.
Зависимости — установленный [V47](135-eis-single-customer-history.md),
[контракт133](133-eis-regional-discount.md), [ADR0118](../../adr/0118-eis-regional-contract-history.md).

## Проверяемый результат

Цель0836600003326000287: Тверская область,159пачек/OKEI728, EZK,
KTRU17.12.14.110-00000005 и exactSPEC837021f8. Нужны≥5других независимых
закупок с теми же характеристиками/способом/единицей, объёмом79.5–318,
заключённые в последние365дней и проверенные≤24часов назад.
Собственная цель, несколько контрактов одного извещения и версии не увеличивают
выборку. Снижение, median/p75 считаются Decimal по неизменённой policyv2;
недобор оставляет UNKNOWN. Выборка не создаёт КП или допуск PARTICIPATE.

## Что уже проверено

Сохранённый inventory104контрактов не даёт ни одной предварительной группы
из5независимых извещений, даже без полной проверки характеристик/currentness.
Шесть сохранённых тверских пар не образуют нужную группу: единственная
подходящая пара — сама цель. Остальные отличаются характеристиками/объёмом/
способом либо имеют другие причины исключения. Стандартный source probe
вернул MANDATORY_FRESH_WORK_READY_OR_UNKNOWN,0source; это приоритет очередей,
а не доказательство отсутствия контрактов в ЕИС.

## Ограниченный discovery

Сначала фиксируются до8точных поисковых URL официального реестра контрактов:
Тверская область/города и период. Это обнаружение кандидатов, не admission.
Каждый URL — один immutable claim и одна попытка≤180s; общий source ceiling1440s.
Изменения только в request audit, общем учёте source budget и private raw.
Ledger наблюдений/КП, schema/images/cron не меняются.

Перед каждым turn отдельно проверяются urgent44 и jointmandatory. Разовое
исключение для известного READY фиксируется точным payload и audit;
UNKNOWN/BLOCKED не допускаются. Общие54мин/час, global/dispatch flock,
public60s cooldown, TLS/proxy, SQL5s, DB100GiB/disk40GiB и worker3GiB/3CPU
сохраняются. Lease освобождается между turns. Crash/timeout не разрешают retry.

Используются reviewed V45 claim и неизменённый owned-container lifecycle.
Новый bounded adaptor нужен потому, что прежний worker читает один RGK номер,
а прежний operator payload разрешал только два уже использованных адреса.
30synthetic policy/refusal tests PASS; источник до решения владельца не читался.
Discovery план637bb618: independent exact reviewPASS, preflightREADY/source0;
urgent44=READY/jointmandatory=READY. Пользователь26Oct поручил не запрашивать разрешений; owner принял решение
выполнить проверенный payload637bb618, standing-authorization.json. Discovery завершён: шесть сохранённых страниц и два UNKNOWN без пригодной
структурированной выдачи; восемь URL использованы по одному разу.

После discovery: sourceSHA→фиксированный список registry IDs→точный
refresh план/review/решение владельца по новому правилу без запроса разрешения. Каждый результат проходит штатный RGK0+PRIZ+актуальные
карточки, полное связывание scope и tenant ledger, затем native history/read.
Только после этого возможен PASS реального регионального прогноза.


## Зафиксированный refresh

Из шести raw/receipt с проверенными SHA детерминированно выбрана21закупка:
4EZK и17EA, один минимальный registry на закупку, без ранжирования по цене.
Исходной цели это не гарантирует5аналогов. Дополнение scope заранее разрешает
отдельную проверку реальной EA-группы с прежней policy, без подмены результата
исходной цели. `candidate-inventory.json`, `scope-evaluation-addendum.json`.

План136dbcad:21точный registry, по одной попытке≤180s, максимум3780s в разных
часах при прежних54мин/час. Установленный V47/worker не меняются. Observer
сохраняет только полностью возвращённые RGK/PRIZ bundles и карточки, возвращает
исходные объекты без изменения и не добавляет source calls; partial transport
failures полного raw не имеют.20policy/capture tests и independent review PASS.
Source0 preflight: urgent44/jointmandatory READY. `refresh-owner-decision.json`
связан с точным планом и review под standing instruction пользователя26Oct.

Сбор начат; первые исключения сохраняются UNKNOWN. После каждого turn остаются
request claim, результат и доступный raw; повтор consumed registry запрещён.
Чтение для прогноза и независимый Decimal расчёт ещё не приняты.


## Промежуточное evidence данных

21outcomes: один PASS (`0836300015126000030`, registry3694901242726000037),
остальные UNKNOWN. Это наблюдение относится к отдельной EA/SPECaa5cc339/500пачек;
исходной цели оно не является аналогом. Все20полных пар результатов повторно
разобраны штатной qualification из retained bytes; PASS воспроизведён.
`replay-first-batch.json`, `first-batch-replay-acceptance.json`, `batch-summary.json`. Сетевой WSDL timeout не повторяется;
у не вернувшего bundle запроса полный raw отсутствует, claim остаётся immutable.

Уже сохранённый официальный schema ZIP4313b235 (новых запросов0) подтверждает,
что `outValueRange` — внешний диапазон, отдельная ветвь от `valueRange`.
Он остаётся UNKNOWN; код и критерии admission не ослаблены.
`outside-range-source0-evidence.json`.

Native handlers на forced read-only production DB вернули для исходной цели
правильный context и UNKNOWN/sample0, для всех7проверенных cached целей NO_QUOTE;
AUDITOR save403. Это in-memory handler probe, не личная production HTTP сессия.
`native-progress.json`. Численный прогноз по реальной выборке ещё не принят.

Pagination page0/1 показывает8страниц; прочитаны1/2. Условный tail7794085d
фиксирует ранее непрочитанные страницы3–8:6URL×180s=1080s, прежние квоты/guards,
0ledger writes,28tests и independent reviewPASS. Все21outcomes и недобор min5
зафиксированы, source0 preflightREADY; owner-decision.json разрешил точный
payload7794085d по standing instruction. Все6страниц сохранены; selector дал74новые
независимые закупки (22EZK/52EA), исключив все21прежнюю закупку, не только registry.
Refreshf75a42e4: до74точных адресов×180s,13320s в разных часах/expiry8h, прежние54мин/час.
Owner останавливает новые turns после проверки реальной группы≥5/native/Decimal;
неиспользованные адреса остаются без claim.20tests и independent reviewPASS;
source0 preflightREADY, refresh-owner-decision.json связал exactplan/review/erratum.
Сбор начат: первый новый PASS0136300006826000027/SPECc13aa248/EZK/200пачек.
Это отдельная группа, не аналог исходной цели. Следующий registry до claim
остановлен часовым бюджетом и ожидает новое окно; source retry не создаётся.
Новые действия выполняются по bounded
плана/review/решения владельца под уже действующим указанием пользователя.


## Проверка незакэшированных реальных целей

До нового refresh native API смог прочитать8из97фиксированных source targets.
Для отсутствующей цели API требует canonical intake; выдуманный ref не подходит.
Bounded source0 diagnostic `scan-cohorts.py` использует полные retained PRIZ,
штатные `notice_market`/scope/region и свежие ledger observations, чтобы выбрать
реальный полный архив для дальнейшего intake. Он не пишет в БД и не заменяет
native acceptance. Первый scan:15реальных контекстов, ни одной группы≥5.
Старые V45наблюдения учитываются только в их исходном сроке24h, без обновления
checked_at; исходная цель не считается собственной историей.

## Продолжение после остановок до запроса

В первых11из74 три PASS, но разных cohorts: EZK/SPECc13/200,
EZK/SPEC0ee3/255 и EZK/SPECaa/779. С первым EA/SPECaa/500 они также
не образуют группу. Независимый source review подтвердил различие
fillingInstruction2/6; преобразовывать его в равенство оснований нет.
Совместные UNKNOWN содержат числовую толщину без OKEI в собственном item
выбранного заказчика; foreign-only blocker не доказан.

Дважды wrapper завершился до claim с пустыми логами; readonly audit доказал
отсутствие нового source request. После второго случая старый driver остановлен.
Continuation50e8cfd4 исключает все11consumed IDs и оставляет63непрочитанных;
вместо раздельного readiness wait используется непрерывное ожидание import
lease до600s внутри wrapper. Source180s и54мин/час прежние; expiry прежний.
20tests и независимый exact review PASS; source0 preflightREADY. Driver review
нашёл uncertainty gap, исправленный до запуска;12mock checks PASS. Owner decision
связал exact plan/reviews/preflight; сбор63адресов запущен без новых вопросов.
Старый f75driver не возобновляется. Evidence `tail/continuation/`.

## Снимок10:45UTC

Первый batch21/1PASS; tail26/9PASS, из них8EZK и1EA. Исходная цель
по-прежнему sample0. В отдельной c13/EZK/200 группе два разных извещения;
native forced-readonly production handler дал sample1UNKNOWN и self-exclusion.
Пять новых PASS (registry12/14/16/19/22) независимо сверены с raw/cards/ledger,
Decimal суммами; `continuation/source-prefix-review.json` ecd7a286.
Это internal AUDITOR probe, не personal HTTP. 29реальных контекстов, max1аналог;
median/p75=null. Сбор EA продолжается, min5 не принят.

В cached страницах source0найдены7других office/A4/printing/writing titles
с новыми EA procurement IDs: `tail/alternate-office-candidates.json`. Это discovery,
не admission; refresh этих дополнительных IDs ещё не начат. Цены не определяли
выбор/порядок, все95прежних кандидатов исключены.

## Блокер canonical intake отдельной EA-цели

Для0136300015126000029/300пачек найдено3аналога AA/EA (10:59UTC),
но цель отсутствует в canonical index. Полный PRIZ ZIP42dee682 содержит
EFSubmitOffers/EFFinal; прежний import завершился DOCUMENT_TYPE_UNSUPPORTED.
Ни один member не удалялся. Owner root, owned files/acceptance/зависимости —
`continuation/ea-intake/slice.json`. ExistingV47snapshot +5changed/1migration
20261026_02, без постороннего dirty-кода.

Добавляется только metadata family двух официальных EP types; факты award/price
из протоколов не объявляются. OfficialXSD4313b235 и source0 evidence подтверждают
namespace/identity. Actual preflight:1notice+4events. 33unitPASS/1PGskip;
independent code review899888cb PASS. Все4401прежних unit IDs сохранены, +10;
PG группы118→120 и159→169. Fullgate2:50PASS, unit4384+27skip, PG763/0skip,
web221, doctest9. AcceptedAPI0f2454b8, receipt4647da47; независимый reviewPASS.
Isolated actualPG/networknone/wheelSHA:1notice+4events, idempotence и полные
42dee ZIP bytes PASS; mainsearch FAIL/экономикаUNKNOWN (закрытая закупка).
Native300контекст тогда дал3аналога UNKNOWN; это не personal production HTTP.
После persistedEA events прежние API/worker несовместимы: consumer barrier
сохраняется, blind rollback запрещён. Collector работает на прежнем pinned image;
production images/schema/intake пока не менялись.

## Снимок12:44UTC

Tail73итога, последний фиксированный адрес ожидает lease. Новый
0336100009925000038/EA/290пачек поднял actualAA/EA cohort до4других закупок.
Source0 scan62реальных контекстов; исходная159цель sample0, max4UNKNOWN.
`continuation/cohort-scan-progress.json`, `native-four-others.json`.
Неизменённые критерии, без обновления старых checked_at.

EA executor:19fault cases PASS; code/executor/actualsource reviews PASS.
Exact deployment план fb2806e (schema26_02/3imagepins/full42dee archive),
без новых source calls; exact review/preflight/installed acceptance PENDING.
Подготовительный36d01073 superseded до apply: исправлен stale hash локальных
19tests в guardproof; executor/application/config bytes неизменны.

## Принятый native результат12:46UTC

Фиксированные21+74 адреса завершены:19PASS квалифицированных наблюдений,
76UNKNOWN. Все19новых PASS совпали с source0 повторным разбором raw/cards
и ledger; старый скопированный self-capture отдельно, timestamps не обновлялись.
Пять результатов относятся к трём заказчикам; независимость по policy — разные
procurement IDs, а не пять разных заказчиков.
Для cached0836300015126000030, Тверская область/EA/AA/500пачек, native
installed handlers дали PASS/sample5; собственная закупка исключена.
Это in-memory AUDITOR/forced-readonly productionDB, не personal HTTP-сессия.

| Независимая закупка | Пачек | НМЦК scope, ₽ | Контракт, ₽ | Снижение |
|---|---:|---:|---:|---:|
| [0136300000725000257](https://zakupki.gov.ru/epz/contract/contractCard/common-info.html?reestrNumber=3694901242725000034) | 1000 | 398000 | 275456.04 | 30.790000% |
| [0336100009925000038](https://zakupki.gov.ru/epz/contract/contractCard/common-info.html?reestrNumber=1690800221125000066) | 290 | 101500 | 82722.50 | 18.500000% |
| [0836300015126000005](https://zakupki.gov.ru/epz/contract/contractCard/common-info.html?reestrNumber=3694901242726000012) | 1000 | 352670 | 310349.60 | 12.000000% |
| [0336100009926000017](https://zakupki.gov.ru/epz/contract/contractCard/common-info.html?reestrNumber=1690800221126000031) | 300 | 98000 | 98000.00 | 0.000000% |
| [0136300000726000235](https://zakupki.gov.ru/epz/contract/contractCard/common-info.html?reestrNumber=3691100437826000007) | 500 | 220500 | 148837.50 | 32.500000% |

Decimal ceiling6: median18.5000%, p7530.7900% совпали с native.
Одинаковые deliveryregion/SPEC/EA/OKEI728, объёмы250–1000, разные
procurement IDs, signDate в365дней/currentcards≤24h подтверждены источниками.
НМЦК и цена относятся к whole notice либо полному контракту выбранного
заказчика; произвольной аллокации и предположений о НДС нет.
Coverage UNKNOWN; это сценарное снижение, не вероятность победы или
доказательство точности будущего прогноза. NO_QUOTE/PARTICIPATE UNKNOWN.
Исходная0836600003326000287 остаётся sample0UNKNOWN, отдельная300цель —4UNKNOWN.
`continuation/five-native-acceptance.json`, `replay-final.json`, `native-final-before-ea.json`.
Независимый финальный review2e48fb0c PASS: полные bytes/XML scope/SID/характеристики,
исключение self, ledger/native и независимый Decimal совпали.

## Установка и окончательная приёмка

Exactplanfb2806e6 установлен26Oct12:52UTC под standing instruction пользователя.
Source0 preflight сначала BUSY (штатный223), после наблюдаемого завершения
в12:50:43 дал READY; ограничения не менялись, process не прерывался.
Schema20261026_02, API/defaultworker/collector0f2454b8; DB/web/cron/hostscripts
неизменны. Старых producers при смене pins нет, compatibility barrier активен.
Full42dee PRIZ0136300015126000029: +1notice/+4metadataevents, ZIP без изменений;
обычный cached mainsearch HTTP200/exactba12. Закрытая закупка: applicationFAIL,
economicsUNKNOWN. Три exacttarget в actualmainHTTP200; personal session не создавалась.

После установки native500 sample5PASS/18.5%/30.79%, original159 sample0UNKNOWN,
новая300 sample4UNKNOWN; все прежние evaluated/числа неизменны. NO_QUOTE,
AUDITOR save403. Identity6wheelmodules/3pins/schema/health/audit4statuses PASS.
ИзолированныйPG/replay/migration producers удалены; readonly cleanup query
исправлен на actual имя, старое evidence сохранено отдельно.
Independent installed review6bbe822d PASS. `acceptance.json`,
`continuation/ea-intake/installed-independent-review.json`.

Сбор завершён:95unique refresh claims,19qualified/76UNKNOWN; дополнительных
семи/внешних candidates не запрашивали. Регулярный collector истории ещё не
реализован. Следующий срез — ограниченное регулярное обновление и срок
актуальности результатов, сохраняя exactSPEC/min5/self-exclusion/UNKNOWN.
Полный MVP, охват рынка, реальная прибыль и PARTICIPATE не приняты.
