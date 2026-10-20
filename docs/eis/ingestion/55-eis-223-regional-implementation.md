# S172 — parameterized regional loader и измеримый backlog

Статус: **DEPLOYED**,2026-10-03, HEAD `20261003_04`, api/worker/web.
Автоматический scope90codes PUBLIC_KLADR_SELECTOR включён, frozen plan900
на2026-10-02–03. Первый проход продолжается; actual всех записей, полная
обработка900targets и полнота export partitions UNKNOWN.
Owner этих docs:Astra, owned ADR0055/docs55 only. Runtime owners/files root
фиксирует в docs15. Dependencies: official research docs54, Sol region adapters,
root persisted scheduler/storage/coverage/API/worker.

## Контракт первого вертикального среза

Все official allowed region codes обслуживаются одним adapter. Никаких новых
parsers на77/78. Existing region50 windows/receipts сохраняют exact identity.
Реализован frozen finite wave с retained exact dates, catalog SHA и5families.
Root выбрал finite waves и три таблицы catalog/plan/targets с attempts из
существующих journals. Catalog membership подтверждён как PUBLIC_KLADR_SELECTOR,
не как NSI_ACTUAL_VERIFIED.

Исторический pilot2windows/30min даёт theoretical capacity96attempts/day.
Для примера99codes полный двухдневный проход990targets занимает минимум10.31days.
Daily freshness всей матрицы при текущем budget не заявляется. Нельзя ежедневно
создавать990newtargets и скрывать постоянно растущий deficit. Вариант two-day
scope — два фиксированных дня, не пересоздаваемый horizon на каждом cron.

Для S172 root выбрал после77/78 validation до32windows/600s sequential на cron11/41,
без fanout и без роста CPU/memory/DB budgets. Потолок1536attempts/day — только
арифметика; actual UNKNOWN до измерения latency/requests/lease contention.
Source10s polls сохраняются. Budget проверяется перед стартом каждого window;
atomic complete returned set не режется при пересечении deadline, bounded
in-flight overrun измеряется отдельно. Next wave: changed date pair и>=24h.

Реализовано разделение first sweep finished и source coverage complete:
permanent FAILED не блокирует навсегда новые waves, старые failed gaps
сохраняются под bounded retry reserve при новом wave. Если
старые gaps накапливаются быстрее обслуживания, coverage выводит lag/backlog
growth и pressure, не скрывает их и не заявляет своевременный полный охват.

## Последовательные milestones

1. M1 research: exact official catalog/version/status и orgRegion semantics;
   source proof hashes, explicit supported catalog scope. ADR decision до intake.
2. M2 adapters: keyword region с совместимым default50; exact requests/window
   key/preflight binding; unknown/invalid region failclosed. Бизнес identity
   notice/event не включает region и дедуплицируется между receipts.
3. M3 persisted plan: bounded seed, tenant unique targets, retained backlog,
   fair selection/retry/cooldown, duplicate dispatch protection. Read-only typed
   coverage отдельно от seeding/attempt mutation. Seed не принимает untrusted
   content за команды/permissions; only official catalog source contract.
4. M4 migration/consumers: explicit CHECKs, history-safe downgrade, existing
   cancellation/UNKNOWN gates не ослабляются. Region не фильтрует коммерческий
   поиск по месту поставки. Широкие metadata source receipts на VPS; documents
   по требованию после тех же operation gates.
5. M5 bounded controls77/78 и автоматический полный configured scope после
   gates; rollout/proof сохраняет actual attempts/lag/errors. Полный scope
   считается пройденным только по exact target receipts, не по успешному probe.

## Проверки, предотвращающие ложные выводы

- Полночь через несколько суток, restart и новый catalog version не теряют
  ранее запланированные targets; план не пересчитывается из today-only list.
- Repeated NO_DATA/FAILED одного региона не вытесняет первый проход остальных;
  cooldown учитывает aware time, future attempts не становятся due раньше срока.
- SYNCED с отсутствующим checkpoint отклоняется; PREPARING не completion;
  SOURCE_REJECTED оставляет gap. Explicit target states различают unvisited,
  deferred, failed, source no-data и positive import.
- Cross-region same business XML даёт одно notice/event evidence и несколько
  exact source receipts; conflicting bytes остаются immutable conflict evidence.
- Tenant isolation и replay/no extra mutation; coverage GET не создаёт задачи,
  не обращается к источнику и не превращает UNKNOWN в PASS.
- Fresh DB upgrade и upgrade from20261003_03; non50 history запрещает downgrade
  даже в другом tenant. Пустой downgrade восстанавливает literal50-only CHECKs.
- Budget/resource gates не растут пропорционально каталогу:32windows/600s,
  ограниченные returned sets/bytes, bounded DB selection, существующие locks.

## Выявленные архитектурные риски

Текущий `storage/eis_223_sync.py::due_windows` пересоздаёт today/previous-day
targets и сортирует по oldest observation; при regional expansion этот подход
забывает непройденные даты. Нужна persisted queue или явно иной доказанный
contract. `20261003_01` использует live model constraints при upgrade/downgrade;
новая region regex может незаметно попасть в историческую схему. Нужны frozen
historical CHECK definitions и target-version regression, не только upgradeHEAD.

На этапе M1 выполнено read-only чтение; tests/live source/deploy здесь не
запускались. Итоговые каталог, выбранная queue policy, performance и coverage
добавляются только по фактическому evidence.

## Промежуточное code review M2

Проверены source/storage region modules, models и migration04. Реализация
сохраняет frozen dates, catch-up не более2дней, old gaps остаются в global scope.
Новый wave после first sweep не ждёт бесконечно permanent failures. Tenant
catalog/plan/target FK, immutable/RLS и history-guard downgrade согласованы;
исторические01/02/03 attempt constraints теперь фиксируют literal region50.
Coverage отдельно показывает exact current scope и old gaps, оставляя
whole coverage/freshness UNKNOWN. GET не запускает source.

Открытое замечание: reserved retry помещался после31unseen. При600s partial batch
это не гарантирует выполнения retry. Нужен early retry slot; worker при этом
не должен завершать весь run на target-local failure этого retry. limit1 также
должен иметь определённую справедливость. Retry-first и limit2..32 теперь
проверены; worker продолжает target-local failure/PREPARING, прекращает
SERVICE_ERROR/global transport/reflection. Это замечание закрыто чтением кода.

Performance ограничение: _latest сортирует все tenant journals, _scope группирует
все historical targets; ограничение output32 не доказывает bounded SQL work.
Actual growth/EXPLAIN и throughput остаются UNKNOWN до измерения.

По сообщению root, official nsiSubjectRF/all и nsiKLADRShort/all дали NO_DATA.
Это не каталог и не основание генерировать01..99. Текущий strict parser explicit
two-digit kladr mapping — механизм проверки, не доказательство actual national
membership. Synthetic fixtures не разрешают production national seeding.

## Новый source evidence и delta review

Official selector22514bytes содержит90unique top-level11charIDs; body SHA
`b57a42d5ed113bc9460fc8b421ad00b4f6b5cd8ca3b2aae51ab61cd6a3b6f58d`.
Mapping exact two-digit prefix+9zeros — structural inference из observed source
и getDocs examples; HTML не имеет отдельного orgRegion. PUBLIC_KLADR_SELECTOR
планирует900targets, не заявляет actual=true90 или полный набор ЕИС. Single
public JSON lookup подтверждает actual50 только. Подробности в docs54.

Проверен regional worker: source POST/archive GET counters,32windows/600s start
budget и отдельный180s timeout started window; atomic full set не обрезается
только из-за batch deadline. Root сообщил PG89PASS/Linux482PASS до последних
review deltas. Итоговый deployment подтверждён ниже.

Последние deltas перед rollout:

- HTML parser первоначально выбирал li вне observed container chain и принимал
  EOF между fully closed rows. Нужен strict unique container/list closure, иначе
  truncated body может заменить catalog на partial список. Исправление прочитано:
  unique modal/select/list и закрытие контейнеров обязательны.
- Bounded scheduler возвращает<=32, поэтому worker len(due)/deferred=0 не равно
  total backlog. Исправлено: regional report показывает selected, backlog отдельно.
- DB/free-disk gates требуется повторять перед каждым новым regional window;
  32windows могут сохранить до1GiB compressed плюс metadata после initial check.
  Проверено: gates повторяются перед каждым региональным окном.

Последний parser edge исправлен: missing-id li допускается ровно один и только
с текстом «Не выбран». Прочитаны placeholder_count и exact normalized label
checks; регион с потерянным id теперь отклоняет каталог. Открытых blockers
после указанных исправлений в bounded review нет.

Новый порядок family→region→current/previous day даёт соседние даты региона,
не ожидая весь пустой current-day country sweep до предыдущего дня. Exact frozen
scope неизменен. API возвращает catalog_source_url/PUBLIC_KLADR_SELECTOR.
По root, live controls77AES2026-10-02 SYNCED23.381s/2ZIP9.7MB и78SYNCED17.316s/
1ZIP1.1MB; proof `/research/regions/s172-controls-20261003T173136Z.json`.
Это source-adapter controls, не deployment/полный региональный проход.

## Deployment и admission evidence

Root подтвердил HEAD20261003_04 api/worker/web. Итоговые gates:90PGPASS,
484LinuxPASS плюс latest16testsPASS, webbuildPASS. Proof:
`/research/regions/s172-admission-20261003T174923Z.json`.
Catalog90 PUBLIC_KLADR_SELECTOR, frozen plan900 наOct2–3. Retained control77
добавил108versions,78 —14versions, всего122new; index232current. Replay дал
0writes и не делал дополнительных source calls.

Cached samples: paper32.12ms, server-equipment124.16ms, coverage28.86ms;
DB2.82GB. Это отдельные измерения, не SLA и не sustained throughput.
Промежуточный UI snapshot первого national run:44/900terminal,
14SYNCED/30NO_DATA,0errors,19regions started/1complete. Это не финал batch;
последующие результаты root фиксирует в docs15. Whole coverage/freshness UNKNOWN.

Оставшиеся gaps: первый полный900sweep и actual throughput под shared lease;
automatic catalog refresh (пока bootstrap-only); bounded retention;44regional
parity; другие223families; реальная stable lot/revision association. Planned
regional scope не означает все закупкиЕИС или доказанную ежедневную свежесть.

## S173 — DEPLOYED

Api/worker/web HEAD `20261003_05`, backups/admission/cron/first-run подтверждены
root. Immutable observation journal закрывает bootstrap-only gap. Same SHA
recheck каждые24h, failure cooldown1h, removals review, additions
next wave; frozen wave membership не меняется. Exact wave SHA success time
отделён от latest accepted catalog и последней неудачи.

Прочитаны journal/source transport/models/migration05/runner/scheduler. Null
checks/FK/RLS/immutable/replay и last-accepted selection согласованы. Выявлена
accounting-edge: outer45s timeout после начала GET мог вернуть0source_requests.
Исправление прочитано: retained request_started перед page.goto и outer handler
сохраняют startup0/dispatch1; root сообщил15source tests/Ruff/mypyPASS.
Review PASS: открытых blockers в проверенном slice не осталось.

Cron10min и early fresh+retry reserve повышают доступную частоту, сохраняя
32windows/600s/2GiB/per-window resource gates и общий lease.24h creation guard
снят: new-day wave после first sweep, catch-up<=2days/old gaps retained.
192windows/h ceiling не SLA; freshness UNKNOWN и влияние на44 измеряется.

Root сообщил33PG/62focused/source13/runner6 и mypy/webbuild PASS. Live probe
`/research/regions/s173-public-probe-20261003T192813Z.json` дал19:28:12UTC
200/22514bytes/90codes/same bootstrapSHA; на момент probe production writes не было.
Подробный контракт: [ADR0056](../../adr/0056-eis-catalog-revalidation-and-refresh-lanes.md).
Retention,44parity/прочие223families/stable lot association остаются открытыми.

### S173 deployment proof

`/var/lib/eis-browser/research/regions/s173-admission-20261003T193743Z.json`:
1catalog с прежнимSHA,1newcheck+1audit,900targets/1waveunchanged;
replay0writes,0newsourcecalls. Один matching cron заменён на1/11/21/31/41/51;
backup/idempotence tests PASS. Итоговые gates33PG+69focused+ESLint/build/mypy/RuffPASS.

First manual32run217.6817s,41POST/9GET,9SYNCED+23NO_DATA,0errors,
69newversions; early fresh50lotcancel затем31unseen. К19:41:24UTC171/900terminal;
к19:42:02UTC176/900, поскольку automatic next cron уже начался. Index537.
Read-only API sample: coverage30.02ms,paper60.73ms,server140.33ms;DB2.91GB.
Proof `/research/regions/s173-final-api-20261003T194202Z.json`;
полный SHA здесь не приводится: root передал сокращённый digest.
Это отдельные samples, не sustained SLA. Whole coverage/freshness UNKNOWN.
Полный900sweep и measured sustained throughput ещё требуют завершения;
retention/44parity/другие223families/реальнаяstablelotassociation остаются gaps.
