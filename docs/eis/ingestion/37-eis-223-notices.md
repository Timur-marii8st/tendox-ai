# Отдельный reader извещений 223-ФЗ

S149 завершён в описанной границе: одно проверенное семейство `purchaseNoticeAESMBO`, RI223.
S150 подключил данные к отдельному tenant индексу и отдельной секции поиска223-ФЗ.
Полнота ЕИС, право участия, экономика и review лота остаются UNKNOWN.

## Официальный контракт и live образец

[Раздел ЕИС 223-ФЗ](https://zakupki.gov.ru/epz/main/public/document/view.html?searchString=&sectionId=386&strictEqual=false)
показывает схемы16.3 от28.09.2026 и16.2 от16.06.2026. Пакеты получены
через официальный UI без отключения TLS/защиты:

| Пакет | Размер | SHA256 |
|---|---:|---|
| [16.3/id44431](https://zakupki.gov.ru/epz/main/public/download/downloadDocument.html?id=44431) | 174509 | 664facfa081008adb11a6df4373d1abe488927492ab8d618b9bc0b48cd1249ef |
| [16.2/id44009](https://zakupki.gov.ru/epz/main/public/download/downloadDocument.html?id=44009) | 173113 | b7fc0e8ab81fde9e05e43fc8a83d675f7c49514c4548294cafc7d50cc0b74ae0 |

SOAP getDocsIP16.3 явно содержит choice documentType44/documentType223;
выбран RI223/documentType223 AESMBO на основании official public/actual
nsiDocumentTypes223 из S145. Оболочка SOAP по-прежнему namespace fz44/get-docs-ip,
это не означает44-ФЗ внутри возвращённого XML. Архив содержит прямой root
purchaseNoticeAESMBO namespace `http://zakupki.gov.ru/223fz/purchase/1`,
header namespace `http://zakupki.gov.ru/223fz/types/1`, body/item/...Data.
Номер11цифр и version извлекаются только из прямого Data, не из вложенных блоков.

Окно region50/day2026-10-01/+03:00, requestUID2784d834-8c3f-498e-9df0-d29f18c99f81.
15 XML-версий/один ZIP2230186bytes, SHA
2607be9f8863613ba8712db7040266f487d46d75860c52b144934c5e8a387a46.
Все15/15valid по обоим официальным purchase.xsd16.2/16.3; schemaLocation
реальных XML указывает16.2. Incoming schemaLocation никогда не загружается.
XMLSchema использует только известный локальный пакет, no_network/entities=False.
XSD proof SHA699d8a75ea9fa1cb383789adf2f9600ab618af555fdad2a61bd914d426bec012.
Raw/proofs: `/var/lib/eis-browser/research/223/local-eis-supplier/` на VPS.
Исходный shape.json служит диагностикой; facts reader/XSD direct-path являются
отдельной проверкой, подписи не исполняются и их юридическая валидность UNKNOWN.

## Семантика reader

Каждый исходный title/method/status/time/lot/item/attachment имеет exact XML SHA
и locator с p:/t: namespace prefixes. Decimal для цены/количества; float,
NaN/Inf/отрицательные/неоднозначные литералы не становятся деньгами.
Цены остаются на уровне каждого лота; разные валюты/несогласованный numeric code
не становятся RUB, лоты не суммируются в ложную единую НМЦК. Classification
name OKPD2 отделено от description позиции; название классификатора не считается
полной спецификацией. cancelled/status/MSP flags не дают самостоятельный допуск.

Сроки без timezone сохраняются raw/UNKNOWN. Types.xsd описывает offset как
смещение относительно MSK, но это ещё не доказательство применения зоны заказчика
к каждому полю времени. Нулевой customer offset не преобразует naive deadline
в действующий срок. Прямой aware deadline сохраняется с исходной зоной.

Manifest COUNT_CONSISTENT означает совпадение количества перечисленных ссылок с
исходным счётчиком, а не полноту документации/получение байтов. Download URL
допускается только HTTPS официального223filestore и exact uid32hex; внешние/
неоднозначные ссылки сохраняются raw, safe value=None. XML/ZIP limits:
16MiB ZIP,200members,4MiB/XML,32MiB expanded; пути/дубликаты/symlinks/encryption/
unknown compression/DTD/ENTITY/UTF16/32 отвергаются. Partial parse не публикуется
как полное окно; unknown/duplicates не скрываются last-wins.

Operator script `scripts/server-eis-223-probe.py` запускается на VPS под общим
eis-import.lock: одно окно, max2archives/max4polls с10s интервалом, existing
rate pauses. Token только из env; исходящие SOAP не сохраняются. Reflection
проверяется также после bounded decompression. Replay требует exact selection
sidecar с company/UID/region/day/zone/family и одинаковых immutable bytes.

## S150 — поиск и сохранение

Отдельная tenant storage/index/law/lot-aware search проекция реализована;
API/UI с явным223 scope, версии/replay/conflicts/RLS и UNKNOWN timezone/admission. Cancellation,
прочие223семейства, полный historical scope и legal/economic comparison требуют
отдельных contracts. Существующие44-ФЗ identifiers/paths не расширяются вслепую.


## S149 проверки и replay

95 bounded local tests(36new223), 36Linux223tests, Ruff3files/mypy2 прошли.
API/worker rebuilt/deployed, миграций не требовалось. Cached operator replay
0.168086s, parsed15versions/16lots/30items/127refs, invalid URLs0.
Все15naive/missing deadlines UNKNOWN, никаких inferred active time windows.
parsed JSON 2784d834-8c3f-498e-9df0-d29f18c99f81-1-parsed.json SHA
53ae86be53667b46a1e0d84fa76271a36129a5f36b3f2290e4b2d8787c5d535d.
Proof proof-2784d834-8c3f-498e-9df0-d29f18c99f81-20261002T081336768310Z.json
SHA49281ea99505c6d44fb5509b56c547b266c6ce20ed3e34bb64d4477f5ae34e3b.
Initial SOAP SHA0dfc0cc91d42717969d7e600f98bab7d4a2d7c0403dcc48d6719aa06bb9016ee,
prepared SHAd1847807ac7d7f1e9a56a802fd20c140a50b4f2d84a7a5f734b7378940d9d178.
Observed selection sidecar восстановлен по exact собственному S149 вызову и
UID/digests: он операторский provenance, не подписанное доказательство ЕИС о
полноте окна. Новый probe сохраняет selection до запроса; cached инойscope
отклоняется. После усиления source/ready/archive-set binding результат byte-identical.

Миграция20261002_04:4 immutable FORCE RLS таблицы с tenant FK, SQL SHA(content)
и JSON identity guards. Raw ZIP dedup по company/SHA. Version conflict откатывает
весь window/audit. Read endpoint GET `/v1/tender-discovery/eis-223-index` берёт
company из principal, no-store, latest-only repeatable read. Слова разных
items/lots не объединяются; economics/eligibility/coverage/freshness UNKNOWN.
До100результатов из known corpus; matched_count полный в этом корпусе.
Контракт [ADR-0050](../../adr/0050-eis-223-metadata-index.md).

На VPS импортировано15версий/11текущих карточек,1архив. Intake0.246493s,
replay0.134307s/no new rows/audit. Live поиск«спецобувь»0.181946s,2карточки:
32616403675v3/2лота с неизвестной initialSum и32616427291v2/1лот/2156464.04RUB.
Отсутствующие initialSum/description не выдумываются; другие price branches
не проверены. Proof s150-index-proof-20261002T085108548383Z.json,
SHA88cea4203639ae3ebc9853dfb80efd91de512c61127b0e238562b2b897e4d53f.
GET не изменил counts223/audit/44jobs/blobs/analyses. CUA через реальный BFF
подтвердил результаты, отдельные лоты, UNKNOWN deadline и exact title evidence.
92 local и41 isolated PG tests, Ruff/mypy, webbuild/ESLint прошли.
Следующий срез: ограниченный refresh только проверенного223семейства вregion50.

## S151 — регулярное обновление проверенного scope

`scripts/server-eis-223-refresh.sh` запускается на VPS в11/41минуты каждого часа;
Python due-check допускает today/yesterday+03:00/region50/AESMBO раз в6h.
NO_DATA — наблюдение, не checkpoint полноты. Errors/PREPARING повторяются через1h;
ошибка прекращает текущий проход. При одинаковом checked_at ошибка имеет приоритет
для более короткого backoff. Другие регионы/семейства/история не включаются.

Migration20261002_05: immutable FORCE RLS attempt journal, tenant composite FK
для SYNCED к реальному source window, SQL evidence/status guards, audit.
Source сначала проверяет prepared UID/full archive set, затем скачивает max2ZIP,
проверяет bounds/typed reader/token reflection, атомарно импортирует окно.
Raw ZIP dedup сохраняется. Исходящие SOAP/credentials не попадают в logs.

Общий source lock с ожиданием45s, max2windows/180s source budget,
100GiB DB/40GiB free reserve; worker2CPU/2GiB. Cron wrapper может пропустить
занятый проход, следующий due-check повторит его.180s ограничивает source await;
завершение bounded atomic ingestion/cleanup может добавить время. Никакого
обещания глобальной свежести или active deadline из naive поля.

Live pass36.016568s: today4новые версии, yesterday0;2SYNCED. Немедленный повтор
NOT_DUE/0source requests.19версий/15текущих карточек,3source windows,2raw ZIP,
2journal entries;19/19XMLвалидны по16.2и16.3. Proof
`s151-refresh-proof-20261002T093556828190Z.json`, SHA
ae8a8d139a1c1c121f428d9701a24b9de280b1803d3c52d1410e34c66935c6f8.
73 focused local tests,16Linuxsync/runner и42isolatedPGtests прошли;
Ruff/mypy/shell syntax/deploy подтверждены. Следующие задачи: остальные223
семейства, документы отобранных кандидатов, timezone semantics и статусы.

## S153 — электронные котировки в индексе

Reader/intake/search допускают только AESMBO и ZKESMBO. Root/Data, provenance
и SQL snapshot family связаны с точным source window. Migration20261002_06
сохраняет AES history; downgrade с котировками запрещён. Refresh пока AES.
35версионный ZKESMBO sample импортирован0.351389s; replay0.201899s без мутаций.
Всего54версии/50текущих карточек/4окна/3ZIP. Search«центрифуга»0.166236s,
32616427422v1; BFF/UI подтвердил метод,339994.15RUB,4ссылки, source locator/SHA.
Без timezone срок UNKNOWN, descriptions UNKNOWN; profit/eligibility/coverage
UNKNOWN.76local/43PGtests,Ruff/mypy/webbuild/ESLint прошли. Proof
s153-index-proof-20261002T100735671307Z.json, SHA
b6ce16975db2560b7dec6c978906b2e24426abf6dc65831053eb24cf8056faa3.

## S154 — refresh двух223семейств

Region50/today+yesterday+03:00 дляAESMBO/ZKESMBO. Due targets4, oldest checked_at
first; max2за проход/180s,6h success/1h error, cron11,41 иобщийlock/budgets
сохранены. Migration20261002_07 расширяет immutable journal, history сохраняется.
83local/23Linuxsync/44PGtests, Ruff/mypy/shellsyntax/deploy прошли.
Live37.372801s:8new/2SYNCED; repeatNOT_DUE/0requests.
62версии/56current/6windows/4ZIP/4attempts. Proof
s154-refresh-proof-20261002T105057620924Z.json,
SHA66a090a3195a76ee1dbfde11179d4dab4b82f66e754c63742e0280c85497d246.
Full-XSD61/62validbothreleases;1XMLsubstantiationNationalRegimeValue104>100.
Typed metadata projection иfull-XSD — разные проверки; SYNCED неXSD PASS.
Raw history сохранена, eligibility/economics/coverage/freshness UNKNOWN.

## S155 — полная XSD проверка отдельным evidence

Точный номер/версия/XMLSHA связан compositeFK с immutable FORCE RLS quality
journal. Official schema package/root/tree SHA и parser version сохранены;
отсутствие полного evidence двух releases — UNKNOWN, любая schema ошибка — FAIL.
Schema PASS не даёт допуск/полное ТЗ/прибыль. Диагностика видна в API/UI.
Offline audit bounded200versions/32MiB compressed, без HTTP; pinned trees
проверяются целиком, external schemaLocation запрещён. [ADR0051](../../adr/0051-eis-223-schema-quality.md).

Deployment2026-10-02:79версий/72current/10windows;158checks,156PASS/2FAIL
дляXML32616432455v1, SHA d95f415b79ee37f87d8a64e602a2ad62f2ed1cd5276d4ba56a709e4fb11fdc97.
Replay0new/source0; API0.324525s/GETне меняетaudit/jobs; CUA подтвердил
FAIL обеихXSD иисходнуюцену1615916.67RUB.97local/45PG/37Linuxtests,
Ruff/mypy/webbuild/ESLint прошли. Production schema20261002_08; testDBудалена.
Proofs s155-schema-proof-20261002T172747460572Z.json,
SHA1d46cb2a7ec7a42f4f0acebda883e06564bdbd889df04d2a366b4ca9ee5b5254;
APIproofs155-ui-api-proof-20261002T172855560054Z.json,
SHAbbfdf0bbc3084e0a45416a22215521cf6c9ae3232e97755659fa9ca15bdc39ec.

## S156 — автоматическая bounded очередь качества

Штатный223refresh выполняет offlinequality после source outcome или NOT_DUE.
Только latest tenant versions с отсутствующей проверкой текущих pinned16.2/.3
и текущего lxml validator. Записанный FAIL не вызывает бесконечный retry.
2XML/32MiB compressed/30s soft между целыми версиями, ZIP открывается один раз
наSHA. DB100GiB/free40GiB guard и существующий import lock сохраняются.
QUALITY_UNAVAILABLE отдельный safe reason; source SYNCED не переписывается.
API GET не запускает validation. Никакого supplierPASS из schema PASS.
104local/46isolatedPG/48Linux, Ruff/mypy/deploy прошли. Production livequeue0
(79versions уже158checks), repeat0new/source0, audit неизменен. Positive latest,
missing release/old validator/FAIL-done/tenant проверены isolated syntheticPG.
Proof s156-quality-proof-20261002T174256101204Z.json,
SHA f2e9e574bc2c1cd205f936226ddf9f4a00eeb4635cd43f6b19ab47ce9b9f161c.

## S165 — ограниченная память поиска при росте индекса

SQL-prefilter остаётся тем же: текущая версия каждого номера в tenant и
пересечение сохранённых поисковых ключей. Все кандидаты проверяются в одном
consistent read snapshot, порциями до200 с keyset по purchase_number,
без OFFSET и загрузки всего результата SQL в память. После каждой порции
сохраняются только100 глобальных лидеров. Порядок прежний: известный блокер
срока, полнота текстового совпадения, число совпавших терминов, номер;
цена, XSD PASS и прибыль не участвуют в ранжировании.

evaluated_candidates/matched_count считают весь известный подходящий индекс,
а не только возвращаемую сотню. Поздний более релевантный кандидат может
вытеснить раннего. XSD evidence читается для≤100 возвращаемых точных refs
в том же snapshot; источник/tenant/identity и смысл FAIL/UNKNOWN сохраняются.
При новом импорте следующий запрос получает новый snapshot. Никакого нового
HTTP, XML/документного разбора или writes/audit. API contract и миграции не
меняются. Снижение потребления памяти не доказывает полноту всей ЕИС или SLA.

Gate:47local/61isolatedPG/242Linux passed, Ruff/mypy passed. Synthetic451 и
PG450current проверили late leaders, latest versions, tenant и отсутствие
мутаций. Production до/после вернул полностью одинаковые результаты трёх
запросов на одном saved-source snapshot;3–30мс на небольшом223sample.
Proof s165-bounded-search-proof-20261003T060949728800Z.json,
SHAa04ab702ad309e0acbd111b8c576d1ce51ca52f2be65adae78dfb9f3362e92aa;
данные только на VPS, HEAD20261002_11, isolated testDB удалена.

## S169 — общий формат purchaseNotice

Подключён явный формат `purchaseNotice` помимо AESMBO/ZKESMBO. Цена хранится по
исходной ветке: INITIAL_SUM / MAX_CONTRACT_PRICE / TEXT_ONLY / UNKNOWN.
Maximum, formula, commodity и неоднозначная валюта не превращаются в начальную
рублёвую сумму. МСП-признаки извещения и лота, hide/accredited/notPlacement,
ссылки documentFS/prev и additional count сохраняют точные XML locators.
Неразрешённый manifest UNKNOWN; скрытые файлы не скачиваются.

Общий срок применяется только при явном isLotOriented=false. Наивная дата не
получает угаданный часовой пояс. Все безопасно разобранные members набора
сохраняются атомарно; полная XSD quality проверяется отдельно. XSD FAIL не
исправляет XML и не означает supplier hard gate. Предварительный расчёт
показывает quality status и предупреждения. Подтверждённые hidden/accredited-only/
invalidated records и отменённый выбранный лот блокируют соответствующий расчёт.

Боевой запуск 3 октября: окно регион 50 / 2026-10-02, один ZIP / 40 версий /
38 номеров, две максимальные цены. XSD 16.2 и 16.3: 38 PASS / 2 FAIL.
Refresh содержит шесть целей, прежний batch 2 и бюджеты. Gates 66 PG / 397 Linux,
Ruff/mypy, web build и review прошли. Реальная MAX-карточка на 6 млн RUB проверена
в API/браузере; экономика UNKNOWN. Один ТЗ DOCX скачан: 32 фрагмента, 1/8 файлов,
комплект INCOMPLETE, требования UNKNOWN.

Общий формат не означает отсутствие ограничений МСП. Полный охват ЕИС,
действительное КП и допуск не подтверждены. Hashes и границы проверки — в
[плане](../../15-implementation-plan.md) и [контракте S169](48-eis-general-223-implementation.md).


## S170: независимые события отмены

purchaseRejection не является извещением и не имеет notice version/status.
[Контракт50](50-eis-223-cancellation-contract.md), [реализация51](51-eis-223-cancellation-implementation.md),
[ADR0053](../../adr/0053-eis-223-cancellation-evidence.md). Событие связано с точным
номером закупки; оно может поступить раньше notice. Более поздний notice не
снимает hold. В поиске проверка batched и идёт до итоговой сортировки;
comparison/documents/source estimate читают одну tenant snapshot.
Подтверждённый source cancellation блокирует кандидата; ambiguous chronology,
missing timezone/schema или GUID variants дают UNKNOWN и operation hold.
Текущая стадия/восстановление и полный охват UNKNOWN. Отмена лотов и расширение
регионов — следующие самостоятельные контракты.


S170 deployed03.10: live event32616425280/region50/01.10 поступил доnotice,
обаXSD PASS, timezone UNKNOWN и operation hold. Real archive18,753bytes,
raw/quality/replay fingerprints — docs15. Scope событий не означает fullEIS.


## S171: отдельный source family отмены лотов

[Контракт52](52-eis-223-lot-cancellation-contract.md),
[реализация53](53-eis-223-lot-cancellation-implementation.md),
[ADR0054](../../adr/0054-eis-223-lot-cancellation-evidence.md).
Политика UNKNOWN-only: eventGUID, purchase number, source lotGUID/ordinal и
array selection сохраняются отдельно. Связь со стабильным лотом/версией ещё
не доказана. Событие создаёт review hold, не whole-purchase mandatory FAIL.
Schema PASS, более поздний notice и совпадающие identifiers не снимают hold.
Document hold имеет notice scope; source estimate даёт отдельный selected
lot state и сохраняет все прочие blockers. Batched search проверяет до ranking.

Развёрнуто03.10 HEAD20261003_03;84PG/454Linux, UI/health PASS. Регион50,
оба live окна01/02.10 NO_DATA. Synthetic full schemas PASS, real lot-event
intake и stable association UNKNOWN. Следующий этап — единый parameterized loader + автоматическая очередь по
официальному каталогу регионов, baseline/reconciliation.77/78 — контрольная
выборка rollout, не отдельные адаптеры и не конечный scope. Полный ЕИС не заявлен.

## S172: единый региональный загрузчик

[Контракт54](54-eis-223-regional-contract.md), [реализация55](55-eis-223-regional-implementation.md),
[ADR0055](../../adr/0055-eis-223-regional-coverage.md). Один параметризованный loader
обслуживает все90codes фактического публичного КЛАДР-selector ЕИС.77/78 — лишь
контрольные выгрузки; регион не является отдельным адаптером или фильтром доставки.
Immutablewaves/targets сохраняют старые окна и retrygaps при смене суток. Business
number/version дедуплицируется across regions, exactsource receipts сохраняются.
Typed `/v1/tender-discovery/eis-223-coverage`+UI показывает900plannedwindows,
progress/noData/failures/oldgaps/watermark. WholeEIS/freshness UNKNOWN; runtime
deployment и actual counters фиксируются отдельно вdocs15.

S172 deployed03.10 HEAD20261003_04. Первый общий пакет32окон за331.323s:
8SYNCED/24NO_DATA/0errors,102newversions. С учётом controls77/78 индекс330current,
wave44/900terminal и856unattempted. Cached API поиск «бумага»28.83ms,
«серверное оборудование»154.48ms на этом индексе; это не SLA полного ЕИС.
Общий cron11/41 продолжает очередь автоматически; fullscope/freshness UNKNOWN.
