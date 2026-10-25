# Поиск действующих закупок 44/223: единый продуктовый план

Актуальный план от 13.10.2026. Владелец — root. Продукт остаётся **INCOMPLETE**.
Production: KESMBO cached intake v1 установлен; три адресных номера/четыре редакции импортированы и найдены поиском. Схема20261013_01, worker3GiB/3CPU, SQL5s.
Этот документ задаёт результат, зависимости и приёмку. Он не разрешает менять
production. Exact approvals и guards сохраняются; принятые snapshot/restore,
установки и проверки не повторяются без изменения значимых условий.

## Текущий приоритет M0 — открытая подача, 13 октября

По уточнению пользователя нужны закупки всей России, на которые **сейчас можно
подать заявку**: официальный AF («Подача заявок») **и** окончание подачи не раньше
сегодняшней даты; дата публикации не ограничивается. Исторический AF-обход остановлен,
checkpoint сохранён перед25Jan2014; исторический producer отсутствует.
14Oct heartbeat m0-csv заменён только deadline-only продолжением (ACTIVE);
default historical mode отказывает при наличии frozen checkpoint.
Его несостоявшееся чтение25Jan до остановки дало importlease300s/exit1/sourcecalls0;
raw CSV этого дня не получен. Повтор и переход к нему запрещены. Production loaders продолжают.

Предварительные новые source counters13.10:44 —46069 записей в CSV-trigger
(HTML «более46000»,22:54:57МСК),223 —15009 («более15000»,22:57:21МСК).
В обоих ответах проверены AF, единственный закон, deadlineFrom13Oct, пустой
publication/price и отсутствие регионального ограничения. Это объявленные записи,
не доказанное число уникальных актуальных закупок. Сроки сегодняшнего дня проверяются
по точному времени с timezone; истёкшие исключаются, неизвестный timezone/state
отдельно. Известные отмены/приостановки исключаются. Deadline не заменяет state.

Root; owned: private CSV/progress/evidence, этот план/M0/live/handoff. Acceptance:
полный уникальный перечень нового official filter и сравнение с production;
версии/лоты не увеличивают N, актуальность редакции/карточки отдельна.
Existing private resume адаптирован для непересекающихся deadline-ranges, без
publication cutoff: официальный CSV500/file,5000/filter, exact exportcount,
два одинаковых множества номеров и повторная metadata сверка; изменение
содержимого карточки сохраняется отдельно и не означает её актуальности. Переполнение/повтор IDs/
изменение выдачи/отказ сохраняются и не превращаются в EOF/PASS.
Stock server-document-probe/importlease300/cooldown60s/TLS8MiB прежние;
один producer/HTTP, local wait61s. Ресурсы/cron/guards/sourcefrequency прежние.
Новые compatibility/intake/release/scheduler отложены до перечисления/сравнения.
Evidence: private active-census-csv-20261012-v1/open-applications-20261013-v1;
[результаты M0](122-eis-active-census-m0.md). Национальная полнота INCOMPLETE.

## Результат M0 12.10

[Фактический срез M0](122-eis-active-census-m0.md): полный обход объявленных
конечных фильтров70/17; национальное неполное множество284/known227/absent57.
CSV≤5000/500-row; 13.10 оба ограниченных CSV70/17 exactIDs PASS. National
AF-only534479/42415 не active denominator: источник сохраняет stageAF
даже у44 со сроком14.01.2014. Deadline/state census ещё не замкнут, полная
национальная актуальная база UNKNOWN. Три missing223/4KESMBOversions получены
официально по номеру; минимальный reader/BY_NUMBER intake/search проверен
на isolatedPG18 без productionwrites. Для безопасного stockrollback выпуск
разделён: compatibilityreader/schema/UI без intake → importer от установленной
compatiblebaseline. Compatv2 abefc07d…/10paths установлен по exactapproval, runtime/health/schema/postchecks PASS.
От установленной базы подготовлен cached importer: receipt05bacf11…/607PG16,
трёхномерный intake и совместимый post-data rollback на Compose PASS44.801s.
Второй пакет7d9c01aa… установлен13.10 за885,551s; runtime/postchecks PASS.
Согласованный single offload выполнен, проверенная локальная копия сохранена.
Первые30s attempts не получили lease. Data-only v3 после review/exact approval
импортировал3номера/4редакции: leasewait120,572s/work8,545s; обычный поиск,
source provenance, RLSforeign0 и replay0new PASS. Это закрытие конкретных
cached пропусков, не current-source-state/fullactive completeness. Приложение/
receipt и automatic schedulerfamilyset прежние. Дополнительный конечный M0
partition старых публикаций:31номеров/31лотов, HTML/CSV/recheck exactIDs,
known8/missing23. Первоначальная дата до2025 включает update2026; не lookback.
Bootstrap ETA и гарантированный freshreserve UNKNOWN. Scope не урезан lookback.

## Что должен получить пользователь

Поиск всех **публичных действующих закупок 44/223** в национальной границе ЕИС,
независимо от даты первой публикации. По умолчанию — подтверждённая подача заявок;
отдельно доступны другие ещё не завершённые процедуры: комиссия, приостановка,
возобновление. По 223 состояние определяется по лотам: отмена одного лота
не скрывает остальные. Неизвестное состояние видно отдельно и не называется
открытой подачей. Эти режимы не означают допуск к участию.

Карточка показывает актуальную редакцию, номер, название, закон, способ,
заказчика, его регион и отдельно место исполнения, доказанные сроки и цену,
актуальный перечень документов, изменения, отмены и восстановления, ссылку
на ЕИС и время последней сверки. Поиск работает по номеру, поисковым полям
карточки и явным фильтрам. Полнотекстовая обработка каждого ТЗ и OCR всех
вложений не являются условием начальной базы карточек и не обещаются как готовые.

В scope входят все регионы официального каталога, а не 50/77/78 или выбранные
товары. Непубличные сведения недоступны getDocsIP: это явная граница доступа.
Она не позволяет заявлять охват всей ЕИС. Версия каталога и его изменения
должны быть учтены перед итоговой приёмкой.

## Что пользователь может найти сейчас

На www.syurai.su/tender-discovery доступно загруженное подмножество пяти
семейств каждого закона. 44: EF2020, EZK2020, EOK2020, отмена и отмена отмены.
223: purchaseNotice, AESMBO, ZKESMBO, отказ от закупки и отмена лота.
Reader/UI KESMBO установлены и3номера/4редакции доступны; автоматического
потока этого семейства нет. ZPESMBO32616349722/v1–v4 XSD-valid, installed parser
DOCUMENT_TYPE_UNSUPPORTED; локальное исправление actualPG18 PASS, не установлено.
Национальный загрузчик уже использует 90 регионов. Полнота и общая свежесть
этой сетки не подтверждены. Режим 44 `NOT_EXPIRED_OR_UNKNOWN` допускает
неизвестный срок; будущий срок тоже не доказывает актуальную стадию.
По 223 `application_status` остаётся UNKNOWN.

Проверенные 12.10 примеры: «Темозоломид», 44 / 0175200000426001937 v1 —
4,341 s; «Камышлов», 223 / 32616455097 v1 — 0,100 s. Сохранены связи
window/response/archive/XML. Это отдельные проверки, а не общий SLA.
Замеры 10.10: перевозки — 21,017 s, бумага — 6,736 s; «услуги по печати
документов» — 61,152 s в режиме ALL_CACHED. Последнее — время поиска,
не печать PDF; оно превышает бюджет веб-клиента 60 s.
Повторное сравнение на каждой странице и STRONG «бумага/ценные бумаги» открыты.

## Подтверждённые пробелы

| Область | Что известно | Что ещё не установлено |
|---|---|---|
| Регионы | Поддерживаемая сетка — 90 кодов; целиком исключённого региона для пяти имеющихся семейств не установлено | Для отсутствующих методов во всех 90 регионах нет подтверждённого национального обслуживания |
| Конкретные окна 44 | 48/EZK2020 и 77/EOK2020 за 08.10; 42/EZK2020 за 12.10, часы 10/12, имеют отказы | Какие действующие номера потеряны из-за каждого отказа — пересечение с официальным active census |
| Периоды | В census 08.10 данные 44 начинались с 12.08.2026, EOK — с 29.09; 223 — с 01–02.10 | Диапазон не доказывает непрерывного охвата; более ранние действующие закупки независимо не перечислены |
| Пропуски загрузки | В принятой outage-карте 21 600 координат: 6406 direct + 148 daily credit, 15 046 unresolved | Число отсутствующих закупок и действующая часть этого долга |
| Отсутствующие задания | 870 hourly keys за 09.10, 14/15 МСК, отсутствуют по 87 регионам — всем кодам прежнего каталога кроме 50/77/78 | Их покрытие данными не доказано; это отдельный набор, не пересечение с outage-картой |
| Суточная 223 recovery | 09.10 вне rolling-пары: 0/450 после final cutoff; 10.10 ранее закрыто 450/450 | Поздние изменения старых действующих извещений за пределами rolling-пары |
| Состояния | Отмена/отмена отмены и отмена лота частично поддержаны | Полный текущий этап, приостановка, восстановление и состояние всех лотов не сверены |

Числа выше относятся к принятым срезам 08–12.10, а не новому live census.
115 координат начального свежего долга не были обслужены в принятом наблюдении.
Количество planned windows, сохранённых карточек или типов не является полнотой.

## Какие из 209 типов нужны

Основа — сохранённый официальный NSI export от 26.09, полученный 02.10,
и XSD 16.3. Текущий drift каталога UNKNOWN. Полная построчная карта 209 типов,
официальных названий, SHA, локаторов и продуктовых ролей сохранена в private
`active-procurement-product-plan-20261012-v1/type-gap-inventory-v1.json`.

**Непосредственно нужны 10 типов:**

- Новые извещения 44: `epNotificationEZT2020`, `fcsNotification111`.
- Новые извещения 223: `purchaseNoticeKESMBO`, `purchaseNoticeZPESMBO`.
- Содержание и документы: `epClarificationDoc`, `fcsPurchaseDocument`,
  `explanation`, `changeRequirements`. Последний ранее был в категории протоколов.
- Отмены FCS: `fcsNotificationCancel`, `fcsNotificationCancelFailure`.

Изменённые редакции обычно приходят в том же семействе извещения: отдельный
NSI-тип не нужен для каждой версии. Нужно правильно применять latest edition,
сохраняя version/variant identity, conflicts и holds.

**Ещё 16 типов требуют проверки как источники текущего состояния:**

- 44: четыре `epProtocol*2020Final` (EF/EOK/EZK/EZT), `epProtocolCancel`,
  `epProtocolEvDevCancel`, `epNoticeApplicationsAbsence`, `tenderSuspension`,
  `unplannedCheckTenderSusp`.
- 223: четыре `purchaseProtocolSummingup*` (AESMBO/KESMBO/ZKESMBO/ZPESMBO),
  `purchaseProtocol`, `protocolCancellation`, `protocolLotAllocation`.

Достоверное состояние обязательно, но безусловный импорт всех 68 протокольных
типов — не обязательно. Сначала выбирается авторитетный официальный источник
current stage и доказываются переходы по закупке/лоту. Если статус предоставлен
проверяемым реестром, часть этих потоков не нужна для первого результата.
Наличие parser не означает наличие update flow. Suspension-типы нельзя
отложить автоматически вместе с остальными отчётами и контролем.

Шесть legacy-типов 223 до 01.07.2018 нужны, если их номера ещё присутствуют
в действующем реестре. Возраст сам по себе их не исключает. 18 типов ПП РФ 615
относятся к отдельному режиму; граница проверяется по официальным фильтрам.
Остальные 159 типов по умолчанию вторичны: планы, исполнение, отчёты,
промежуточные события. Их подключаем при доказанной зависимости активного
состояния или актуального содержания. Количество типов не даёт процент
пропущенных закупок. Непубличные типы не входят в эти 209 public/actual. Флаг `isActual` каталога
относится к типу, а не стадии закупки: M0 также проверяет старые/снятые с
актуальности типы, если их номера ещё действуют. Эти 209 не являются закрытым
списком всех потенциально нужных readers.

## M0: один замер для срока начальной базы

**Официальный active census + стратифицированная пробная загрузка.**
Получить действующие номера 44/223 и лоты по всей географии без фильтра товара
или даты первой публикации. Сохранить стадии, методы, регионы, даты,
source URL/редакцию и raw evidence. Перед масштабным обходом подтвердить
разрешённый официальный способ перечисления, его лимиты и версию каталога.

Существующий public-check ограничен 44, первой страницей из 50 и одним днём
всех стадий. Это конкретный блокер полноценного census. Нужна ограниченная
доработка того же reader: оба закона, активные partitions, полная пагинация,
контроль повторов/последней страницы и сохраняемый прогресс. `_200` уже повторял
страницы; удачные `_50/_100` не доказывают полного обхода. Capped выдача дробится
по официальным регионам/способам. Новый queue framework не нужен.

Если полный разрешённый обход недоступен, сохранить точный blocker и запросить
полный active export у владельца официального канала. Сторонний список может
ускорять discovery, но не доказывает полноту относительно ЕИС.

В том же эксперименте выбрать до 100 недостающих/изменённых действующих карточек:
оба закона, необходимые roots, старые публикации, малые/большие архивы,
проблемные состояния. Измерить полный source/intake/index cost, число запросов,
объём ZIP/XML, CPU/SQL/сеть, ошибки и остаток мощности при работающем свежем потоке.
Для неподдержанного root сохраняется raw и UNKNOWN; цену его полного parser
нужно измерить после adapter, а не заменить синтетическим PASS.

Выход: число активных, отсутствующих, неверных редакций и неизвестных состояний;
число нужных date groups W, реальная смесь/квантили стоимости и доступный остаток B.
ETA рассчитывается по сумме стоимости нужных групп / B с запасом на повторы
и сверку. До этого срок полной базы UNKNOWN. Темп 90 старых окон/час и прежние
58 дней исторической очереди к этой задаче неприменимы.

## Этап 1: полная база действующих закупок

1. Добавить четыре missing notice roots, нужные отмены, изменения документов
   и минимальную проекцию стадии/лотов. Остальные readers определяет M0.
2. Сверить active roster с сохранёнными latest/index/holds. Использовать
   принятый корпус и raw; неизменённые пакеты повторно не загружать. Официальные
   карточки отсутствующих номеров можно сделать доступными для discovery до
   полного XML-обогащения, с отдельным origin/provenance и явным UNKNOWN редакции/
   документов. Это не canonical XML, не допуск и не завершение этапа полной базы.
   Такой ранний пользовательский срез входит в этап 1 и требует своего exact release.
3. Загрузить отсутствующие номера и редакции. 44 by-number уже есть, но имеет
   ограниченные passes и может отвергать mixed/unsupported full sets.
   223 by-number в production не реализован; M0 проверил диагностический RI223
   по трём номерам/четырём редакциям. Нужен canonical reader необходимых типов;
   fallback — проверенные region/family/date groups из официального списка.
   Дата определяется источником, а не произвольным lookback 30/90 дней.
   Полный архив не урезается ради PASS.
4. Включить старые действующие закупки. Догрузка всей истории не является
   условием: active-относящиеся outage gaps входят в bootstrap, другие остаются
   отдельной recovery, а завершённая старая история — вторичной.
5. Повторный официальный census и catch-up закрывают изменения за время импорта.
   Исчезновение из списка требует подтверждения terminal state, а не автоотмены.

Приёмка относительно зафиксированной актуальной reference-границы:
число indexed active равно source active; необъяснённых номеров, обязательных
неподдержанных типов/стадий нет; latest edition, отмены и лоты совпадают;
поисковые ключи привязаны к правильным версиям. Все partitions/страницы и
расхождения имеют evidence. Count floor вместо полного множества означает UNKNOWN.

Метрики отдельно: покрытие номеров, редакций, состояний/лотов, документов и
поисковых полей; разбивка по закону, региону, методу, стадии и возрасту.
Это не precision/recall поиска: для них нужен независимый размеченный эталон.
После этапа пользователь найдёт ранее отсутствовавшие старые действующие закупки
и новые методы, с честными состояниями и актуальными ссылками на документы.

## Этап 2: устойчивое обновление этой полной базы

Обязанности учитываются отдельно: новые документы, обязательные сверки,
bootstrap/outage recovery и старая история. Один владелец и HTTP-stream;
durable coordinates, bounded retry/backoff, atomic full set и tenant guards.
История получает остаток; outage не должна навечно ждать нулевой свежей очереди.
Daily credit допускается только по доказанному покрытию нужных hourly keys.

Обновления должны находиться и для ранее опубликованных действующих закупок.
Для 223 нужен один paired-revision probe: две реальные редакции одного номера,
официальное время редакции с timezone и фактические date-window bindings.
M0 уже получил v1/v2 одного номера: `publicationDateTime` изменилось между
редакциями. Timezone и привязка изменений к date-window остаются UNKNOWN;
нужен замер именно этих частей контракта. Создание/сохранение/упаковка не заменяют публикацию.
Если источник группирует по initial date, rolling two days недостаточно:
нужны active-date groups или подтверждённый change feed. Нагрузка пересчитывается.

Бюджет — по полной M0-матрице. Existing heavy cohort требует 3919 s до overlap.
Только четыре новых notice roots при прежней cadence добавляют empty-floor
480 s/ч. Даже идеальные 990 s overlap, controller и existing daily floor дают
3573,101 s/ч: дефицит **333,101 s к 54 минутам** до новых filled windows/recovery.
Наивное опрашивание всех десяти direct roots даёт дефицит **1218,101 s/ч**.
Это measured peak + amortized MODEL, не полная future capacity. Такая сетка
не предлагается: задача — работа по active roster и измеренной цене.

Решения выбираются по стоимости, а не новым квотам scheduler:

- Переиспользование immutable XML и exact identities; active-aware группы.
  Отсутствие новой версии у нас не является основанием отменить source recheck.
- Overlap продолжать только в полной матрице: прототип использовал
  1505,51/1670 s, но durable phase accounting, полный daily/rollover/TTL не доказаны.
- Проверяемый вариант — сокращение нашей паузы с 2 s до 1 s в общем транспорте.
  Один global HTTP даёт максимум 60/min и 3600/h против официальных 90/4000.
  Нужны аудит всех клиентов токена, quota/error/Retry-After, server reserve и
  сохранение per-UID prepared 10 s. Это не реализовано и не одобрено;
  изменение runtime/guard pins требует нового exact approval.
- Если мощности всё равно недостаточно — конкретный дефицит и изменение
  официальной source capacity/канала. getDocsLE документирован, но его доступ
  с mTLS не получен и подключение не начато. Больше CPU/RAM сами по себе
  не обоснованы: sampled CPU 221,9 s за 3 h, throttling 0; phase profile ещё нужен.

Приёмка: минимум 48 h при работающем источнике, два day rollovers, полные 6 h/24 h
обязанности и три полных последовательных совместных часа. Новые/повторные окна,
очереди, возраст, lease, ошибки, квоты, затраты и p95/p99 запаса по обоим законам.
Долг после catch-up не растёт; recovery устойчиво продвигается. Outage/restart
отдельны от steady режима. Сохранены все пропуски, включая 870 и 223 за 09.10.
Новые версии/отмены найдены пользовательским поиском с provenance.

Пользователь видит свежесть, последний успех, ошибки и пробелы по partitions.
Пустая выдача не называется доказательством отсутствия закупок в ЕИС.

## Предлагаемая свежесть: цели проверки, не действующий SLA

Сейчас известен отдельный 44 publication→ingest **123,179 минуты**:
65m32,514 до eligibility, 57m31,059 до начала окна, 7,176 s обработки.
Detection и index commit не отделены. По 223 publication timezone и правило
редакции UNKNOWN. Национальный срок появления версии сегодня не подтверждён.

Первый проверяемый бюджет: полученный валидный XML→поисковая видимость p95≤60 s;
готовая для опроса координата 44→видимость p95≤60 min. При нынешнем eligibility
44 это предварительный publication budget до 180 min: scheduler не устраняет
задержку до допуска окна. Для 223 текущая шестичасовая cadence даёт только
условный budget до 7 h для текущей даты; previous/старые изменения в него не входят.
Это нельзя объявить общим SLA 223.

Продуктовая цель обоих законов — **source available→search p95≤60 min**,
после получения XML — ≤60 s. Её достижимость подтверждает full-matrix trial,
включая более частый 223 discovery и late changes. Если расчёт не сходится,
меняется цена/доступная source capacity, а не скрыто разрешённая задержка.
Численный publication→search SLA 223 устанавливается после paired-revision/timezone
probe. Сокращение eligibility 44 требует проверки более ранней доступности окон
и отдельного exact approval. Source availability, discovery, receipt, commit,
index visibility и API latency записываются отдельно с clock uncertainty. Первое
наблюдаемое READY/discovery не подменяет независимый момент доступности: если
его нет, source-available lag остаётся UNKNOWN; отдельно измеряется опоздание
запланированной сверки и receipt→search, без скрытия интервала до обнаружения.

## Этап 3: подтверждённая скорость поиска

Предлагаемая приёмка на полной active базе: **первая страница p95≤2 s, p99≤5 s;
continuation p95≤1 s**, при четырёх одновременных пользователях и работающем импорте.
Cold/warm отдельно. Это критерии разработки, не обещание из примера 223 за 0,1 s.
ALL_CACHED — отдельный benchmark; его 61 s нельзя выдавать за baseline active scope.

Работа: минимальная indexed projection, SQL prefilter/ranking без разбора тысяч
полных карточек; existing continuation/session сохраняет одно сравнение вместо
повторного полного stream на каждой странице. Version/XML, tenant/query/scope/time
binding, invalidation, holds и порядок сохраняются. UI различает стадии, UNKNOWN,
as-of и ошибки. Исправляется «бумага/ценные бумаги» с независимыми положительными
и отрицательными примерами, без подмены этим общей оценки качества.

Один benchmark: ≥40 заранее заданных запросов обоих законов, разные методы/регионы,
широкие/обычные/многословные/номер/нет совпадений, несколько страниц, cold/warm,
1/4 users с импортом; ≥1000 responses для p99. Content/order parity, ошибки,
CPU/SQL/serialization и resource peaks. Принятый restore используется для
before/after; финальная приёмка — production после exact release, на полной базе.
Precision/recall без независимого эталона остаются UNKNOWN.

## Сроки: что и когда изменится

Это плановые инженерные оценки одного владельца, не ETA из старого throughput.
Source/approval ожидание учитывается отдельно. Готовность receipt не закрывает этап.

| Этап | Осталось | Зависимости | Диапазон и недостающий замер |
|---|---|---|---|
| M0 | Официальный active список, missing map, до 100 cost cases | Полный разрешённый обход/export, доступ, каталог | 1–2 рабочих дня на bounded extension/probe; время полного обхода неизвестно до source counts. Capped/access failure — конкретный внешний blocker |
| Полная база действующих | Direct inputs, состояния/лоты, условные readers, initial load и сверка | M0, реальные payloads, исправление 44 rejects, exact approval | 6–12 рабочих дней инженерии + UNKNOWN время импорта/сверки. Один M0 эксперимент даёт N/W/cost/B и диапазон срока |
| Устойчивое обновление | Full budget/cost, старые active changes, recovery, timestamps и restart | M0/M1 costs, контракт 223 времени/редакций, одобренный вариант source cost/capacity | 3–6 рабочих дней + минимум 48 h рабочего источника. Если scope не помещается — один full-matrix load trial определяет дефицит и нужный канал |
| Подтверждённая скорость | Projection, pager reuse, match bug, UI и full benchmark | Окончательный active индекс/стадии, exact release | 2–5 рабочих дней + 0,5–1 день проверки. Если цель 2 s не достигнута — один 40-query phase profile на полном корпусе задаёт добавочную работу |

Улучшения обновления/поиска можно начинать на принятом корпусе, пока идёт штатный
импорт. Порядок продуктовой приёмки: **полная база → устойчивое обновление →
подтверждённая скорость на этой базе**. Production fresh loaders не останавливаются.
Суммарная инженерная оценка после M0 — 11–23 рабочих дня, но это НЕ конечный ETA:
bootstrap/source/approval время UNKNOWN. Обещать полный продукт через 11 дней
сейчас необоснованно; диапазоны пересчитываются после M0.

Следующее одно действие — **M0 AF AND deadline>=today национальный CSV-перечень
и сравнение production**, без historical-only обхода и новых релизов. На14Oct09:17МСК
CSV observed44=4509/223=6921, calendar>=14Oct4500/6848; national/eligible N UNKNOWN.
Cardinality failure22315–16 сохранён, меньшие official single-day partitions идут;
актуальные числа и evidence — в [M0](122-eis-active-census-m0.md).

## Evidence

[Официальный source contract](../../adr/0044-eis-source-contract.md),
[каталог типов](../ingestion/35-eis-document-catalog.md),
[региональная граница](../ingestion/54-eis-223-regional-contract.md),
[deadline не равен стадии](69-eis-search-deadline-scope.md),
[public pagination](../../research/32-eis-data-strategy-review.md),
[public reader](../ingestion/83-eis-no-data-public-cross-check.md),
[by-number](../ingestion/84-eis-public-candidate-recovery.md),
[production измерения](../ingestion/120-eis-national-coverage.md).
Private evidence: `tmp/improvement-program/m2/active-procurement-product-plan-20261012-v1`:
209-map, capacity floors и source index. План — не новый census и не реализация продукта.

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

### Текущий приоритет после двух контрольных примеров — 14 октября

45250/45747 импорт/replay/provenance/RLS/cleanup завершены; title виден,
number-search FAIL, canonicaldeadline/suspension UNKNOWN. Серийной ручной
подготовки608 не будет. Автоматические проверки, неоднозначные buckets,
условная стоимость сопоставимыхKESMBO и причина lease — [разбор M0](122-eis-active-census-m0.md#два-контрольных-импорта-и-причина-lease--14-октября).
88.3% измеренногоCSVwait120–155 перекрывается с44fresh worker, whole-cycle
hostlock, обязательный pacing сохранён. Minimal cooperative window-boundary
service только предложение для boundedlocalcheck; production не менялся.
Следующее действие — первыйCSVобход в согласованном региональном порядке.

14Oct15:38UTC:168–179firstpass завершён,new44+193/223+28,repeat0.
30readyfirst/11blocked;conditionalready1h13–2h07 exclboundedpassidle,wholeUNKNOWN.
ПоследнийpartialRLSsnapshot8437/8979 observed,535/1871 missing; не actualopenN.
Одинproducer180–191 продолжает; details/evidence в [M0](122-eis-active-census-m0.md#первый-обход168179--14-октября).

14Oct16:08UTC:180–191first COMPLETE,new44+1091/223+0,repeat0.
24readyfirst/11blocked;tiers16+neighbors3/77=5/78=5/rest11. НациональнаяполнотаUNKNOWN.
RO/RLScomparisonv22 raw9528/8979,present8812/7108,missing716/1871, не actualopenN.
Одинexisting192–203 продолжает; [M0 evidence](122-eis-active-census-m0.md#первый-обход180191--14-октября).

14Oct17:08UTC:192–203first COMPLETE,new44+1532/223+683,repeat0.
21readyfirst/11blocked;Москваcustomer offsets продолжаются. Source/productionпрежние.
Measured continuationidle19m34: readinessmonitor30→10min; gain покаUNKNOWN.
Одинexisting204–215 продолжает; [M0 evidence](122-eis-active-census-m0.md#первый-обход192203--14-октября).

14Oct17:35UTC:204–215first COMPLETE,new44+2660/223+1007,repeat0.
17readyfirst/13blocked;MoscowCUSTOMER counts4185vs4183/2584vs2581 UNKNOWN,
не исчерпывающий extent. ROcomparisonv24 raw13720/10669,missing779/2206, неopenN.
Один216–227 продолжает; [M0 evidence](122-eis-active-census-m0.md#первый-обход204215--14-октября).

14Oct18:02UTC:216–227first COMPLETE,new44+449/223+0,repeat0.
16readyfirst/14blocked;SPb начат, MoscowGAR3906vs3905UNKNOWN сохранён.
ROcomparisonv25 raw14169/10669,missing788/2155; не actualopenN/currentstate.
Один228–239 продолжает; [M0 evidence](122-eis-active-census-m0.md#первый-обход216227--14-октября).

14Oct18:46UTC:228–239first COMPLETE,new44+2084/223+449,repeat0.
12readyfirst/17blocked; SPb counts UNKNOWN. ROv26 raw16253/11118,missing869/2219.
Privatehelper421ea21d останавливается доrechecks при unresolvedblockedfirst;
4source0 actualfunctionchecks, liveoldproducer240–251 продолжается/productionнеизменён.
[M0 evidence](122-eis-active-census-m0.md#первый-обход228239-и-остановка-перед-reconciliation--14-октября).

14Oct19:13UTC:240–251first COMPLETE,new44+802/223+29,repeat0.
9readyfirst/19blocked; allRussia deadlines, 15Octcounts UNKNOWN сохранены.
ROv27 raw17055/11147,missing874/2206; не actualopenN/currentstate.
Один252–263 сprivatephase421ea21d продолжает; [M0 evidence](122-eis-active-census-m0.md#первый-обход240251--14-октября).


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
