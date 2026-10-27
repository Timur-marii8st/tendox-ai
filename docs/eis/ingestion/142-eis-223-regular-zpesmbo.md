# V54: регулярная загрузка запросов предложений МСП

27 октября2026. Владелец root. Статус: PARTIAL; найденный joint дефект исправлен отдельным V55. Проверяемый результат: полный native ZP архив →
canonical/mainHTTP/actualUI и обычный аутентифицированный региональный поток.
[ADR0122](../../adr/0122-eis-223-regular-zpesmbo.md),
[принятый V52](140-eis-223-regular-kesmbo.md), [проверка V53](141-eis-kes-five-live.md).

Owner/файлы/acceptance: `tmp/eis-zpesmbo-regular-20261027-v54/slice.json`;
точный контракт и ограничения — `design-contract.json`.
Исходный baseline schema26_03/APIe1ac/WEB0052, source36249. Код старого
zpesmbo-reader-20261013-v1 рассматривается как справочный diff, не готовый release.

## Источник и воспроизведение

Retained UID b8e7735c-9762-4e6e-bcb0-4dfcca80e57e, BY_NUMBER №32616349722;
ZIP158928B SHA6f0438ebef9c2b2df2580336983607b0424073c95f0121bc149c2204f5196d1c.
Четыре native XML версии1–4. На точном установленном APIe1ac все четыре и
wholeZIP отвергнуты DOCUMENT_TYPE_UNSUPPORTED: `installed-source-before.json`.
Это подтверждённый пропуск; новые запросы к ЕИС0, business writes0.

Сохранены selection/initial/prepared/proof/ZIP с полными SHA в manifest.
Retained XSD PASS не считается новой официальной XSD-проверкой. Сроки rawnaive,
историческая закупка не объявляется действующей. BY_REGION координаты не
придумываются из этого BY_NUMBER: новый код обязан требовать factory binding.

## План текущего среза

Contract review PASS, 20 failure-first случаев исходно RED. Реализованы
parser/binding/7families/5CHECK/WEB; 25 новых unit случаев и четыре реальные
native редакции проходят локальный source0 replay. Проверки включают: новое семейство и два точных
addressing режима, no retag/partial UID set, old5/6 immutable history,
конкурентный одноразовый переход к7/1260 и пять downgrade guards всех tenants.
Затем код, inventory всех тестов, focusedPG и свежий полный release gate;
code/exactplan/installed reviews по прежнему процессу без нового permission question.
Потребители/WEB и barrier предшествуют первым planned ZP keys/импорту.

Бюджеты54min/hour/180turn/32/60, SQL5slock2s, source/resource/tenant guards и cron
прежние; expiredV38/consumedV49 не повторяются. Полнота ЕИС UNKNOWN.
BY_NUMBER сохраняется в windows/canonical/audit без записи регионального attempt.
Межоконный replay сохраняет исходный canonical source.
Первый focusedPG:92PASS4FAIL из-за тестовых ожиданий family counts/error codes;
После исправлений ZP+KES focusedPG25PASS, executor39PASS/nativechecker8PASS;
code/executor reviews PASS. Полный gate3 выявил procfs-race в старом test observer;
узкое исправление, deterministic RED→GREEN и57metricsPASS зафиксированы отдельно.
Fresh gate5:54/54PASS;4479unit/27предусмотренных skips,796PG,224WEB,9doctests.
Frozen source f4953bbf; API/worker/collector f28acac6, WEBc7a5409e.
Finalwheel/nativePG/mainHTTP:4редакции,100rawfacts/4missing, replay/RLS PASS.
Независимые code/native/executor/exactplan reviews PASS; executor42PASS.
План caf2e6df выполнялся по standing authority: один guarded apply, все preflight
под теми же четырьмя leases до PREPARED; очередь priority до480s, без прерывания
чужих workers или изменения cron/квот. Предыдущий план ef7ee4ad — BUSY без
PREPARED/изменений; reassessment и три наблюдения сохранены.
Этот release не установлен: migration scan timeout, recovery ниже.

## Исправление миграции на рабочем объёме

Планcaf2e6df дошёл до PREPARED; ADD snapshot CHECK превысил SQL5s на ~56тыс.
редакций. Транзакция откатилась до schema26_03; старые образы/config сохранены,
barrier/wave/intake не выполнялись. Точный readback — failure-reconciliation1.json.
Прежний prepared/failure не удаляется и не повторяется.
Новый контракт в ADR0122: exact validated BEFORE доказывает старые строки для
расширенного NOT VALID CHECK; PostgreSQL проверяет новые записи, convalidated=false
остаётся честным. Exact validated AFTER bootstrap сохраняется. Дрейф/неполная
валидность/наследование/занятые временные имена — отказ с откатом всей транзакции.
Владелец root; owned/acceptance — migration-recovery-slice.json. 15 новых PG
случаев, включая rollback и enforcement; нужен новый full54/image/native/review.
Gate5/sourcef495 остаются историей прежнего кода. После новой проверки — новый
forward plan в отдельном runtime state, без повторения старого PREPARED.

## Установленное продолжение

Планf6643c3183aeafd8765a2d4c4e7724c59f477f9d0c1f2ca26a713efc7a670e6f
установлен26Oct23:58UTC (27Oct02:58MSK), schema20261027_01.
Source8463ab96/API022f9918/WEB6e2e866f; свежий gate54/54:4479unit
(27предусмотренных skips),811PG,224WEB,9doctests. Executor54/native4/reviewsPASS.
Старый caf2 prepared/failure неизменён, новый state — siblingv54-continuation.
Все5installed CHECK выражений совпали с новым wheel/reference; convalidated=false,
validatedpredecessor доказательство и enforcement сохранены, физический VALIDATE не заявляется.
Source0 импортировал4редакции; mainHTTP/actualUI №32616349722 версия4/55Штука
с точными XML/ZIP/response/member/key PASS; deadline/profit/регион UNKNOWN.
Новая волнаd91976c7-db3f-483f-a155-5757ed132286:1260, прежние1080targets
неизменны, SHAbe8428b8. Первый readback:1080attempted/180unattempted, ZP0.
Обычный региональный source требуется отдельно; пока не принят. Source calls при
установке0, cron/budgets неизменны, nationalcoverage UNKNOWN.
Evidence — tmp/eis-zpesmbo-regular-20261027-v54/continuation/.

## Обычная региональная проверка 27 октября

V54 остаётся PARTIAL. Штатный запуск:24 попытки/33POST/9GET; cron и квоты прежние.
Контроль32616506760: native1=canonical1, mainHTTP PASS.
32616471357v2/XMLb9a65598: native2 в двух customer scopes, canonical0 — FAIL.
Evidence: `tmp/eis-zpesmbo-regular-20261027-v54/continuation/ordinary-native-main-result.json`.
Следующий срез — [V55](143-eis-223-joint-positions.md). Cached BY_NUMBER PASS
не закрывает этот дефект; national UNKNOWN.

## Завершение обычной волны

Read-only observation27Oct01:24:46UTC:1260/1260targets attempted, unattempted0.
НовыеZP180окон:33SYNCED/147NO_DATA/0FAILED; предыдущие1080target rows неизменны.
Evidence V55 `regular-complete-observation.json`, исходный V54 continuation
`installed-observation-20261027T012446Z.json`. Это завершение frozen2daywave,
национальное покрытие UNKNOWN. Найденный joint2→0 дефект остаётся причиной
статуса PARTIAL до отдельного принятияV55, уже загруженные XML не переписываются.
