# V61: начальное ожидание import lease для исторической очереди

Владелец root; host script установлен, runtime acceptance PENDING. Доказательство причины и
границы измерения — [V60](148-eis-national-census-v60.md); исходный source contract
и приоритеты — [ADR0057](../../adr/0057-eis-cooperative-source-lease.md).
Проверяемый результат: один scheduled corpus owner, встретив занятый import lock,
ограниченно ждёт прежние priority/223 owners и затем повторно получает import;
неиспользованный cron tick не теряется только из-за занятости lock.

Изменён `scripts/server-eis-corpus-run.py` и связанные тесты. Первоначально
свободный lock работает как прежде; при занятости используется существующее
interruptible ожидание continuation в рамках общего horizon840s и одного
corpus-dispatch owner. После acquisition остаётся прежний worker с обязательным
`--mandatory-fresh-first`, поэтому READY/UNKNOWN/истощённые квоты не обходятся.
Отдельный `INITIAL_WAIT_HORIZON_REACHED` отражает отсутствие начального запуска.
Если health check исчерпал horizon, worker не стартует. Уже начатое atomic
window не прерывается; owner/foreign locks и source pacing не меняются.

Первичный regression до исправления воспроизвёл2 ошибки: tick исчезал и timeout
был классифицирован как immediate SERVER_IMPORT_BUSY. Focused тесты проверяют
реальные flock, оба higher-priority lock, coalescing, INT/TERM, horizon, отсутствие
worker до acquisition и сохранение mandatory-fresh guard; результат хранится в
`tmp/eis-corpus-initial-wait-20261027-v61/focused-correction.txt`:137 PASS, включая
метрики. Отдельный черновой
host-only installer сохраняет bytes/mode и берёт corpus-dispatch lock до общего
deployment lease, чтобы старый ожидающий parent не пережил замену;16 fault/lock
tests PASS. Первый полный gate для `b6f8fb7f…` выявил устаревшее ожидание
немедленного отказа в тесте метрик. Тест исправлен с проверкой короткого horizon;
скорректированный пакет `071f21e6…` основан на exact V55 source `ba622978…`,
изменены script и два файла тестов. Повторный gate:56/56 PASS с проверенной
квитанцией `8b27db54…`,4503 Python tests (27 разрешённых skips),831 PostgreSQL
tests,228 web tests; очистка проверена. Независимое review затем обнаружило гонку:
блокирующая метрика перед worker могла пережить horizon или сигнал. Для двух
случаев добавлены regression и повторная проверка после метрики; профильные139
тестов PASS. Исправленный пакет `dcbb49f4…` прошёл независимое code/installer
review и полный gate56/56 с квитанцией `13740597…` (4505 Python,27 разрешённых
skips;831 PostgreSQL;228 web). Точный план `5e7c3181…` прошёл независимое review
и preflight, затем установлен script `4b1826ae…`; tenant audit содержит PREPARED
и ACTIVATED, source requests установщика0, images/schema/cron не менялись.
Обычный cron27Oct21:45–21:55 МСК: после уступки223 продолжил под import lease,
затем16attempted/0synced/0new versions и остановка MANDATORY_FRESH_WORK_READY;
stdout сверён с SHA segment receipts. Первый import в этом запуске был свободен,
поэтому именно initial-busy wait в production ещё не наблюдался. Evidence:
`tmp/eis-corpus-initial-wait-20261027-v61/ordinary-cron-evidence.json`.
Само ожидание не
обещает progress, если mandatory fresh постоянно READY; национальный охват и
устойчивое ускорение остаются UNKNOWN.

Следующая диагностика: persisted READY блокирует историю даже при свободном
lease, а `_corpus_pass` не использует `JointStartBudget`. Возможный отдельный
срез — строго ограниченный durable historical turn при достоверном READY с
общим бюджетом и сохранением обеих reconciliation reserves. Его лимит, admission,
crash accounting и evidence ещё не утверждены и не реализованы. UNKNOWN,
deferred и ошибки probe нельзя трактовать как безопасный READY. Это направление
требует отдельного контракта, тестов и наблюдения обеих свежих полос.
