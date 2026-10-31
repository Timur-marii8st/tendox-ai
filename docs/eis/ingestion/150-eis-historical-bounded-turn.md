# V62: ограниченный исторический source turn

Владелец root; локальная основа, source и production не изменялись. Контекст —
[V60](148-eis-national-census-v60.md), [V61](149-eis-corpus-initial-wait.md) и
[ADR0111](../../adr/0111-protected-eis-day-reconciliation.md). Постоянный
persisted READY блокирует историю даже при свободном lease; простое снятие
`mandatory-fresh-first` нарушило бы общий бюджет и приоритеты.

Целевой контракт обсуждаемого отдельного среза: не более одной исторической
атомарной попытки на tenant и UTC-час при полностью достоверном READY; общий
budget и резервы44/223 сохраняются. BLOCKED, deferred, ошибки и неизвестные
данные не выдают допуск. История не называется reconciliation. Попытка не
является SYNCED, NO_DATA не доказывает полноту. Это ещё не включённая policy.

Первый локальный milestone — отдельное состояние hourly claim под существующим
budget lock, без изменения строгой схемы старого budget JSON. Первое review
выявило два обхода и блокирующее чтение FIFO; рабочая инициализация удалена,
завершение привязано к UUID владельца, чтение FIFO неблокирующее. Внешний
activation ещё не реализован; после потери/порчи состояния worker должен
останавливаться. Claim не возвращается после restart; незавершённое окно на
границе часа остаётся неопределённым и блокирует повторный допуск. Тестируются
изолированный tenant, потеря файла, неверная идентичность, границы резервов,
fsync failure и перенос через час. Повторное независимое review основы —
PASS_FOUNDATION_BOUNDED, budget/reconciliation39 PASS. Проверка не защищает от
отката корректного sidecar к старой версии; lifecycle и доверенная граница
хранилища остаются обязательными до включения.

Основа не подключена к corpus, не создаёт source requests и не установлена.
Отдельно добавлен локальный классификатор переданных наблюдений: READY/IDLE/
BLOCKED. Он не читает БД, не доказывает происхождение входов и не разрешает
source. Второе независимое review классификатора — BLOCKED: временной диапазон,
часовой пояс и cutoff reconciliation не привязаны к evidence, поэтому даже
будущая или устаревшая координата может дать READY; CLEAR другого диапазона
также не доказывает отсутствие долга. Кроме того, принимается противоречие
`urgent_due < foreground_due`. Тесты классификатора этих условий не доказывают.

После двух неуспешных циклов review работа над классификатором приостановлена,
scope пересмотрен. Новый source-free milestone сверяет стандартные producer:
44 читает три предыдущих дня в UTC+03, исключая каждый день до 02:05 следующего
дня; 223 читает предыдущие три московских дня, причём 02:05 влияет на повторный
опрос, но не является фильтром периода. Точное время чтения, timezone и набор
дней включены в scope hash DUE и CLEAR; смена периода за время чтения блокирует
результат. Проверяется `urgent_due >= foreground_due`; в scope 223 включены
также отмены закупок и лотов. Это проверяет согласованность заявленных данных,
а не доказывает результат БД или происхождение evidence. Независимое review —
PASS_CLASSIFIER_BOUNDED, 44 теста и дополнительные границы PASS. Проверены SHA
классификатора `e4278af5906696eaaa2f866ee3afcbbc0cdab5d019d730e44639e3f48f25b959`
и тестов `32aacbe859a420c6c405eb0e9fcba715a243f03d102ba3e64c92c6f1d1060344`.
Интеграция и source admission не разрешены. Следующий срез — доверенное
tenant-scoped чтение обеих очередей и accepted catalog с доказательством полного
CLEAR, обработкой отсутствующей текущей волны и проверкой PostgreSQL; до этого
переданные классификатору данные остаются утверждениями вызывающей стороны.

Следующий milestone начат: локальный черновик reader собирает данные в одной
tenant-scoped READ ONLY REPEATABLE READ транзакции, не создаёт волну и не делает
source calls. CLEAR относится только к сохранённым планам. Это ещё не проверенный
reader: две попытки PostgreSQL acceptance остановились до выполнения тестов.
Текущая цепочка миграций ссылается на отсутствующую `20261023_01`; сохранённый
прошлый снимок миграций требует отсутствующий в текущем дереве `beta_access_schema`.
Изолированный временный PostgreSQL удалён. После двух ошибок того же подхода
подготовка приостановлена; следующий шаг — восстановить воспроизводимый единый
тестовый контур из согласованной версии схемы и приложения, затем заново провести
tenant/snapshot/timeout/queue acceptance и независимое review. Ни результаты
тестов, ни source admission для черновика не заявляются.
Независимое review черновика — BLOCKED: количество targets не подтверждает их
точный состав, каталог wave не проверяется на совпадение с принятым каталогом,
а возвращаемый evidence недостаточен для восстановления наблюдения. Тест
конкурентной записи также не различает изоляции snapshot и требует замены;
CLEAR/IDLE и реальный timeout ещё не проверены. Это вывод по чтению кода,
предложенные PG-сценарии ревьюер не запускал. Исправления и проверка после
восстановления согласованного тестового контура обязательны до любого допуска.
До любого включения нужны надёжный activation lifecycle, типизированная
проверка demand и обеих reconciliation очередей, проверка marker под lease,
append-only tenant audit, exact window/evidence, интеграционные crash/PG тесты,
полный gate, review и наблюдение обеих свежих полос. Ускорение и национальная
полнота UNKNOWN. План и результаты — `tmp/eis-history-turn-20261028-v62/`.

## Уточнение reader: состав и изолированный PG — 28 октября

Owner root; owned files `src/procurement/eis_history_reader.py`,
`tests/integration/test_eis_history_reader_pg.py`, этот контракт и live-план.
Reader теперь сравнивает текущую волну с точным составом плана всех семейств
принятого каталога и отвергает отличающийся каталог волны. Вместе с hash
возвращаются снимок, каталог, фактические ключи и вход классификатора для
пересчёта evidence. Это локальный read-only результат; он не выдаёт source
admission и не доказывает полноту непланированных дней.

Временный отдельный PostgreSQL16 был создан без доступа к production данным;
схема восстановлена миграциями установленного API image, тесты использовали
app role, отдельную БД и SSH-forward. Вариант fixture с явным
`HISTORY_READER_INSTALLED_SCHEMA_TEST=1` допускает только имя БД с маркером
`procurement_eis_test_` и не запускает миграции: схему подготавливает вызывающий.
В полном прогоне 7/9 PASS; два теста вернули READ_UNAVAILABLE, хотя эти же два
при отдельном запуске прошли. Причина нестабильности не установлена; это не
успешный gate. Подтверждены fail-closed при недостающем и подменённом target,
реальный PostgreSQL statement timeout и RLS adapter; отдельный прогон проверил
хэш evidence и snapshot с конкурентной записью, влияющей на refresh_due.
Тест CLEAR/IDLE и catalog mismatch остаются обязательными; independent review,
source admission, lifecycle учёта и installation не завершены. Disposable DB
и forward удалены. Логи: `tmp/eis-history-turn-20261028-v62/installed-schema/`.
Следующий шаг — локализовать READ_UNAVAILABLE при полном прогоне и получить
воспроизводимый PG gate без ослабления timeout, затем закончить недостающие
сценарии и проверить lifecycle допуска.

## Причина READ_UNAVAILABLE и повторная проверка — 28 октября

Owner root; owned files `src/procurement/storage/eis_223_regions.py`,
`tests/integration/test_eis_history_reader_pg.py`, этот контракт и live-план.
Диагностический перехват исключений в изолированном прогоне установил причину:
SQLAlchemy иногда выдавал `CompileError: Multiple, unrelated CTEs ... anon_1`
при построении `regional_due_windows`; прежняя гипотеза о нехватке времени не
подтвердилась. Обоим различным CTE присвоены собственные стабильные имена,
состав запроса и лимит statement timeout не изменены.

На отдельной PG16 БД со схемой установленного API image и app role:
reader10/10 PASS, включая несовпадение каталогов, изменённый состав, истинный
statement timeout и конкурентный snapshot. Существующие regional PG сценарии
порядка materialized history и recent reconciliation6/6 PASS. Более широкий
параметризованный прогон был прерван после восьми успешных случаев и не является
полным gate. Локальные unit94 PASS, Ruff и docs check PASS. Изолированная БД и
forward удалены. Evidence: `tmp/eis-history-turn-20261028-v62/diagnostic/`.

Это устранение локального SQL-дефекта, не разрешение source и не production
rollout. CLEAR/IDLE на реальных persisted данных, independent review,
адmission lifecycle, crash/audit и полный release gate остаются открытыми.
Следующий шаг — подтвердить CLEAR/IDLE и закрыть source admission lifecycle с
защитой резервов до подключения Gosplan recovery при READY.

## CLEAR/IDLE и отложенные ошибки — 28 октября

Owner root; owned files `src/procurement/eis_history_reader.py`,
`tests/integration/test_eis_history_reader_pg.py`, этот контракт и live-план.
Reader дополнительно проверяет последние попытки для двух недавних часов44,
защищённых completed-day координат44 и трёх последних completed-day дат223,
включая все семь семейств и обе отмены. Неуспешная или не имеющая response SHA
последняя попытка, а также отметка из будущего блокируют наблюдение: cooldown не
превращается в ложный CLEAR. Для 223 проверяются и попытки в указанном диапазоне,
даже если их ключ уже не входит в сохранённый план; это консервативный guard.
Отсутствующие попытки по-прежнему определяются штатными due producers.

В отдельной PG16 с app role и схемой установленного образа синтетически
созданы запланированные координаты и NO_DATA наблюдения с тестовыми SHA:
оба producer выдают CLEAR, общий reader — IDLE, coverage UNKNOWN. Отдельные
новые FAILED44 и FAILED223 внутри cooldown дают BLOCKED. Полный reader PG13/13,
unit83/83, Ruff и docs check PASS. Это тестовые SHA, не доказательство реальных
ответов ЕИС или национального охвата; CLEAR223 ограничен сохранёнными планами.
Evidence: `tmp/eis-history-turn-20261028-v62/idle-proof/`. Временная база и
forward удалены. Текущий reader не выдаёт допуск, не установлен, а полный
release gate и независимое review не проводились.

Остаются проверка границ и производительности дополнительных запросов при
реальном объёме, привязка evidence к durable tenant audit и безопасный lifecycle
hourly claim под source lease с сохранением budget/reserves и crash recovery.
Следующий срез — проверить эти зависимости на изолированных данных до
подключения Gosplan worker при READY.

## Production read-only: стоимость и реальные блокеры — 28 октября

Owner root; срез диагностики, code и production configuration не менялись.
Candidate reader загружен только в память отдельного Python процесса в API
контейнере; запросы в tenant-scoped READ ONLY REPEATABLE READ с ограничениями
statement5s/lock2s, source requests0/writes0. Для принятого каталога90 регионов
первая выборка guard заняла89–99ms, отдельная выборка223 —111–134ms, полный
reader остановился за179ms. Это отдельные замеры текущего состояния, не SLA и не
нагрузочный тест. При полном чтении обеих очередей общий latency не измерен:
текущий guard прекращает чтение после обнаружения 44 ошибки.

На момент наблюдения: одна последняя FAILED44 `DUPLICATE_NOTICE_VERSION` в
суточном окне region54/26Oct/EZK; immutable attempt и audit связаны, вариант
`PARTIAL/COMPLETE`, штатный reader подтвердил receipt и его prerequisites по
хэшу и связал receipt с тем же окном/response. Audit сообщает projected0/held1.
Projection audit и актуальное состояние HOLD этим отдельно не проверены. Это не
canonical checkpoint и не основание снимать блокировку или перезаписывать facts.
Также одна FAILED223 `SYNC_FAILED` в region77/27Oct/purchaseNotice; сохранённый
код общий и не выявляет исходную причину. Данные — снимок, новые попытки могут
сменить latest. Подробные attempt IDs и evidence в
`tmp/eis-history-turn-20261028-v62/performance/receipt.json`; сырые ответы и ключи
в evidence не выгружались.

Вывод: текущий reader правильно возвращает BLOCKED, и любое безусловное
ограничение «один history turn в час» практически может простаивать на постоянном
conflict-HOLD. Нужен отдельный контракт разграничения защищённого source debt,
подтверждённых quarantined conflict и cooldown; считать PARTIAL полным
reconciliation или ослаблять hard gates запрещено. Следующий срез — проверить
projection audit и актуальный HOLD для конкретного receipt в read-only snapshot,
затем спроектировать admission с неизменными долями и продемонстрировать его
на изолированных crash/retry данных. ГосПлан worker и расписание не установлены.

## Проверка конкретного conflict-HOLD — 28 октября

Owner root; ограниченный source0/write0 срез, production code/configuration не
изменены. В tenant-scoped READ ONLY REPEATABLE READ повторно сверена latest
попытка `60716ebf-d044-47a5-bad0-0ff6d6d67004` и тот же exact window. Для
проверки использована функция `verify_partial` из сохранённого S185 helper без
запуска его module-level кода и без его source/runtime paths. Сверены receipt и
prerequisite audits, идентичность окна и response, отсутствие legacy canonical
checkpoint, projection batch и audit payload/hash, список решений, количество
origins и фактическое состояние каждого HOLD через штатный read-only hold reader.
Результат: verified bounded, `PARTIAL/COMPLETE`, projected0, held1, текущий
`HOLD/UNKNOWN`. Это доказательство снимка, не закрытие source debt и не изменение
карточки/допуска. Source0/write0; stale latest, missing audit и ошибки блокируют.

Первая проверка превысила statement timeout5s (`57014`); вторая с диагностикой
завершилась за4.586s. Это два отдельных наблюдения под текущей нагрузкой, не
latency guarantee; 5s timeout не изменяли. При такой близости к пределу включать
этот verifier в каждый admission без проверки плана и производительности нельзя.
Обе пробы сохранены в `tmp/eis-history-turn-20261028-v62/hold-proof/`; reference
helper SHA256 `f201ed80ef7ddfa23fe5909c5138d5ac7db9df0dfe018b80d35fde0d53625e24`,
успешный результат `diagnostic.json` SHA256
`e5d419d4df89c2ce01c35ef978e5a4e30d0d017f8764e422d89e24dab94471b8`.

Следующий срез: измерить и ограничить стоимость exact HOLD/projection proof на
реалистичном объёме, затем описать различие unresolved source debt и доказанного
quarantine для scheduling без изменения HOLD или protected shares. Граница
`PARTIAL != canonical` сохраняется; automatic admission и Gosplan install ещё
BLOCKED, а другая ошибка223 остаётся отдельным условием.

## Локальное ускорение exact HOLD — 28 октября

Owner root; owned files `src/procurement/storage/eis_notice_hold.py`,
`tests/integration/test_eis_analog_resolution_scope_pg.py`, этот контракт и
live-план. Профиль read-only production proof показал: одна проверка HOLD заняла
4219ms из4531ms. В локальном single-notice reader использована существующая
scoped resolution для конкретного tenant/номера/версии и всех same-or-newer
variants/origins. Tenant-wide проверка неполных receipts и проверки audit,
canonical bytes и source bindings сохраняются; общие search predicates не меняли.

В отдельном Python процессе без установки, с runtime monkeypatch scoped predicate,
тот же exact production proof дал `HOLD/UNKNOWN`, source0/write0: полный проход
361ms, его наиболее дорогой HOLD запрос129ms. Базовый и candidate — по одной
пробе на общем сервере; сравнение не является SLA или нагрузочным испытанием.
Evidence `tmp/eis-history-turn-20261028-v62/hold-proof/profile*.json`.

Изолированная PG16 с установленной схемой и app role: 12 тестов эквивалентности
прежнего решения и scoped single-notice reader PASS, включая multiple-purchase
batch, новые origins, malformed audit, newer versions, global incomplete receipt
и tenant isolation. Unit65 PASS, Ruff/docs PASS. Временная база и forward
удалены. Код локальный, proof не означает production rollout. SHA изменённого
модуля `3fceb0f91eb4c9270ad5895b4c23b74715812fa88e293436164d80a49a397728`.

Дальше: спроектировать и протестировать bounded admission для подтверждённого
quarantine без признания PARTIAL canonical, с budget/reserves, tenant audit и
crash recovery. 223 FAILED, end-to-end gate, независимая проверка и rollout
остаются открыты; worker ГосПлана не включён.

## Проверяемое свидетельство карантина — 28 октября

Owner root; owned files `src/procurement/eis_quarantine_proof.py`,
`tests/integration/test_eis_variant_intake_pg.py`, этот контракт и live-план.
Добавлен локальный read-only verifier одного конкретного окна и latest attempt44.
Он требует tenant-bound REPEATABLE READ/READ ONLY, ограничивает statement5s и
lock2s, фиксирует snapshot/time и проверяет точную связь latest FAILED
`DUPLICATE_NOTICE_VERSION` с audit, PARTIAL/COMPLETE, audited receipt,
projection batch/payload/decisions и текущим HOLD каждой удержанной пары.
Отсутствие или расхождение доказательств даёт UNKNOWN. Возвращаемый VERIFIED
означает только проверенный карантин на этом снимке: coverage UNKNOWN,
`source_admission=NOT_GRANTED`, canonical checkpoint не создаётся.

На изолированной PG16 с synthetic transport и штатным ingestion проверены
положительный случай, tenant mismatch, неверный или устаревший attempt,
read-write transaction, несовпадение digest и отсутствие текущего HOLD;
все четыре существующих integration сценария variant intake PASS. Остальные
unit94 PASS; Ruff и docs check PASS. Дополнительный read-only production probe
загрузил candidate modules только в память: тот же latest conflict VERIFIED,
held1, source0/write0, elapsed276ms. Это один замер, не SLA; evidence —
`tmp/eis-history-turn-20261028-v62/quarantine/`. Изолированная база и forward
удалены.

Verifier пока не встроен в demand classifier или worker, не сохраняет audit и
не разрешает source. Нет доказательства безопасного повторного использования
старого snapshot, атомарной связи с hourly claim, runtime crash/lock tests,
независимого review и полного release gate. FAILED223 остаётся отдельным
блокером. Следующий срез — связать fresh tenant snapshot и verified quarantine
с admission/append-only audit под общим lease, сохраняя защищённые доли и
неизменный HOLD; затем проверить прерывание и восстановление до installation.

## Локальный READY admission и учёт — 28 октября

Owner root. В локальном кандидате reader проверяет актуальный tenant snapshot и
строго подтверждённый quarantine; независимый FAILED 223 продолжает блокировать
источник. Ledger записывает evidence и SHA в tenant audit под advisory lock,
допуская не больше одного claim в UTC-час и блокируя новый час при незавершённом
старом claim. UNKNOWN не закрывает claim. Runtime повторно проверяет возраст
снимка и границу дня, защищённые доли совместного бюджета и состояние очередей;
при потере подтверждения источник не вызывается. Эти механизмы не установлены.

Synthetic PG: 14 проверок reader и 5 ledger/runtime, включая конкуренцию,
изоляцию tenant и crash, PASS; evidence `tmp/eis-history-turn-20261028-v62/quarantine/`
`history-ready.log` и `ready-runtime.log`. Проверки host locks при гибели launcher
и промежуточной оболочки PASS, но не доказывают поведение при уничтожении всей
группы процессов. Независимый review, полный release gate, actual-source run и
reconciliation незавершённых claims остаются открытыми. Production cron
ГосПлана собирает только страницы, recovery запрещён выпускным guard.
